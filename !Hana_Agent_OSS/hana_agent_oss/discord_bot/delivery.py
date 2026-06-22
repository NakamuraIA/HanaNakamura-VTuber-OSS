from __future__ import annotations

# Entrega de texto no Discord respeitando o limite de 2000 chars por mensagem.
# A Hana costuma responder longo; aqui o próprio código quebra em várias mensagens
# (em fronteiras boas: parágrafo > linha > espaço) e manda um bloco de código grande
# como arquivo anexo em vez de poluir o chat. Espelha o responseDelivery da Nyra.

import io
import re

SAFE_DISCORD_LIMIT = 1900  # margem sob o limite real de 2000

_CODE_BLOCK_RE = re.compile(r"```([a-z0-9+#]*)\n([\s\S]*?)```", re.IGNORECASE)

_EXT_BY_LANG = {
    "js": "js", "javascript": "js", "ts": "ts", "typescript": "ts",
    "py": "py", "python": "py", "html": "html", "css": "css",
    "json": "json", "md": "md", "markdown": "md", "yaml": "yml", "yml": "yml",
    "sh": "sh", "bash": "sh", "tsx": "tsx", "jsx": "jsx", "sql": "sql",
}


def split_text_safely(text: str, limit: int = SAFE_DISCORD_LIMIT) -> list[str]:
    """Quebra o texto em pedaços <= limit, preferindo parágrafo > linha > espaço."""
    remaining = str(text or "")
    chunks: list[str] = []
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit * 0.5:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit * 0.5:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit * 0.5:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


def extract_big_code_file(text: str) -> tuple[str, bytes, str] | None:
    """Se houver um bloco de código grande, retorna (nome_arquivo, bytes, linguagem).

    Só dispara para blocos realmente grandes (>1500 chars), para não transformar
    todo trecho curto de código em anexo. Retorna None quando não vale a pena.
    """
    biggest = ""
    lang = "txt"
    for match in _CODE_BLOCK_RE.finditer(str(text or "")):
        code = match.group(2)
        if len(code) > len(biggest):
            biggest = code
            lang = (match.group(1) or "txt").lower()
    if len(biggest) < 1500:
        return None
    ext = _EXT_BY_LANG.get(lang, "txt")
    return (f"hana_code.{ext}", biggest.strip().encode("utf-8"), lang)


_DUPLICATE_RE = re.compile(r"^(.{30,}?)\s*\1$", re.DOTALL)


def collapse_exact_duplicate(text: str) -> str:
    """Colapsa uma resposta exatamente dobrada (X + X) de volta para X.

    Rede de segurança contra soluço de repetição de modelos baratos, que às vezes
    emitem a mesma resposta duas vezes coladas. Exige X >= 30 chars para não mexer
    em repetições curtas legítimas (ex.: "pão, pão, pão").
    """
    s = str(text or "").strip()
    match = _DUPLICATE_RE.fullmatch(s)
    if match:
        return match.group(1).strip()
    return s


def build_payloads(text: str) -> tuple[list[str], tuple[str, bytes, str] | None]:
    """Prepara o que enviar: lista de mensagens de texto + arquivo de código opcional.

    Quando um bloco de código grande é extraído como arquivo, ele é removido do
    texto inline (vira referência curta) para o chat não ficar gigante.
    """
    text = collapse_exact_duplicate(str(text or "")) or "(sem resposta)"
    code_file = extract_big_code_file(text)
    if code_file:
        filename = code_file[0]
        # Substitui o bloco grande por uma nota curta apontando o anexo.
        def _replace(match: re.Match) -> str:
            return f"📎 (código completo no anexo `{filename}`)" if len(match.group(2)) >= 1500 else match.group(0)

        text = _CODE_BLOCK_RE.sub(_replace, text).strip() or f"📎 código no anexo `{filename}`"
    return split_text_safely(text), code_file


def code_file_to_discord(code_file: tuple[str, bytes, str]):
    """Converte o tuple de arquivo num discord.File (import tardio do discord)."""
    import discord

    filename, data, _lang = code_file
    return discord.File(io.BytesIO(data), filename=filename)
