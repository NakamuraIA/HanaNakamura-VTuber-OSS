"""Skills: os manuais que a Hana le e escreve sobre como fazer as coisas.

Skill = o MANUAL (quando/como fazer, pegadinhas). Script = o CODIGO que executa.
A skill aponta pro script; nunca duplique codigo dentro do manual.

Antes eram arquivos .md numa pasta, com validacao de caminho pra impedir que ela
escrevesse fora dali. Agora moram na tabela `skills` do mesmo banco da memoria:
nao existe caminho pra escapar, a Nakamura edita pela tela, e o backup continua
sendo UMA pasta.

Script continua sendo arquivo de verdade — `terminal.run` precisa executar.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.core.protocol import ToolResult
from backend.core.registry import RegisteredTool, ToolRegistry
from backend.memory.core import HanaMemory
from backend.paths import MEMORY_DB

logger = logging.getLogger(__name__)

# Nota curta demais nao ensina nada; so polui a skill.
MIN_NOTE_CHARS = 8

_SKILL_TAG = r"anotar[_\s-]*skill"
SKILL_XML_EXTRACT_RE = re.compile(
    rf"<\s*{_SKILL_TAG}(?P<attrs>[^>]*)>(?P<body>.*?)<\s*/\s*{_SKILL_TAG}\s*>",
    re.IGNORECASE | re.DOTALL,
)
SKILL_XML_BLOCK_RE = re.compile(
    rf"<\s*{_SKILL_TAG}[^>]*>.*?<\s*/\s*{_SKILL_TAG}\s*>",
    re.IGNORECASE | re.DOTALL,
)

_mem: HanaMemory | None = None


def _store() -> HanaMemory:
    """Uma instancia por processo — abrir o banco a cada chamada e desperdicio."""
    global _mem
    if _mem is None:
        _mem = HanaMemory(str(MEMORY_DB))
    return _mem


# --- operacoes ------------------------------------------------------------ #

def list_skills() -> list[dict[str, Any]]:
    """Indice: nome + titulo. O corpo sai so no read_skill."""
    return _store().list_skills()


def read_skill(name: str) -> dict[str, Any]:
    """Skill completa, ja com as notas que ela mesma anotou coladas no fim."""
    item = _store().read_skill(str(name or ""))
    if item is None:
        return {"ok": False, "error": "skill_not_found", "name": name}
    return {"ok": True, "skill": item["name"], "title": item["title"], "content": item["content"]}


def create_skill(name: str, content: str, *, title: str = "", overwrite: bool = False) -> dict[str, Any]:
    """Cria ou atualiza uma skill.

    `overwrite=False` protege contra sobrescrever sem querer um manual que ja
    existe — o erro pede confirmacao em vez de apagar calado.
    """
    try:
        mem = _store()
        existente = mem.read_skill(name)
        if existente and not overwrite:
            return {"ok": False, "error": "skill_already_exists", "name": existente["name"]}
        chave = mem.save_skill(name, content, title=title)
        return {"ok": True, "skill": chave}
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "name": name}


def append_skill_note(name: str, note: str) -> dict[str, Any]:
    """Anexa uma dica curta. Vai pra coluna `notes`, sem tocar no manual."""
    limpa = " ".join(str(note or "").split())
    if len(limpa) < MIN_NOTE_CHARS:
        return {"ok": False, "error": "note_too_short", "skill": name}
    if _store().note_skill(name, limpa):
        return {"ok": True, "skill": name, "note": limpa}
    return {"ok": False, "error": "skill_not_found", "skill": name}


def delete_skill(name: str) -> dict[str, Any]:
    return {"ok": _store().delete_skill(name), "skill": name}


# --- XML: <anotar_skill> na resposta -------------------------------------- #

def extract_skill_notes(text: str) -> list[dict[str, str]]:
    """Acha blocos <anotar_skill nome="..."> dica </anotar_skill> na resposta.

    Aceita corpo em texto puro (com o nome no atributo) ou JSON no corpo — os
    modelos alternam entre os dois formatos sozinhos.
    """
    results: list[dict[str, str]] = []
    for match in SKILL_XML_EXTRACT_RE.finditer(str(text or "")):
        body = match.group("body").strip()
        if not body:
            continue
        attr = re.search(r"\b(?:nome|name|skill)\s*=\s*(['\"])(.*?)\1", match.group("attrs") or "", re.IGNORECASE)
        name = attr.group(2).strip() if attr else ""
        note = body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                name = str(parsed.get("skill") or parsed.get("nome") or parsed.get("name") or name).strip()
                note = str(parsed.get("note") or parsed.get("nota") or parsed.get("text") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pass
        if name and len(note) >= MIN_NOTE_CHARS:
            results.append({"skill": name, "note": note})
    return results


def strip_skill_xml_tags(text: str) -> str:
    """Tira os blocos <anotar_skill> pra nunca chegarem no usuario nem no TTS."""
    cleaned = SKILL_XML_BLOCK_RE.sub("", str(text or ""))
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def apply_skill_notes(text: str) -> list[dict[str, Any]]:
    """Grava todas as notas da resposta. Nunca levanta excecao.

    Falha aqui nao pode derrubar o turno: a Nakamura perderia a resposta inteira
    por causa de uma anotacao interna que ela nem ve.
    """
    applied: list[dict[str, Any]] = []
    for entry in extract_skill_notes(text):
        try:
            applied.append(append_skill_note(entry["skill"], entry["note"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao anotar skill %s", entry.get("skill"), exc_info=True)
            applied.append({"ok": False, "error": str(exc), "skill": entry.get("skill")})
    return applied


# --- registro no agente ---------------------------------------------------- #

def _tool_list(args: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, tool="skill.list", output={"skills": list_skills()})


def _resultado(nome: str, r: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=bool(r.get("ok")), tool=nome, output=r, error=None if r.get("ok") else str(r.get("error")))


def _tool_read(args: dict[str, Any]) -> ToolResult:
    return _resultado("skill.read", read_skill(str(args.get("name") or args.get("skill") or "")))


def _tool_create(args: dict[str, Any]) -> ToolResult:
    return _resultado("skill.create", create_skill(
        str(args.get("name") or args.get("skill") or args.get("nome") or ""),
        str(args.get("content") or args.get("conteudo") or args.get("body") or args.get("text") or ""),
        title=str(args.get("title") or args.get("titulo") or ""),
        overwrite=bool(args.get("overwrite") or args.get("sobrescrever") or False),
    ))


def _tool_note(args: dict[str, Any]) -> ToolResult:
    return _resultado("skill.note", append_skill_note(
        str(args.get("name") or args.get("skill") or ""),
        str(args.get("note") or args.get("nota") or args.get("text") or ""),
    ))


def register_skill_tools(registry: ToolRegistry) -> None:
    """Registra as skills vivas pro caminho do agente/terminal."""
    registry.register(RegisteredTool(
        "skill.list", "Lista as skills da Hana com o titulo de cada uma.",
        _tool_list, {"type": "object"}, {}, "low", "skill.module",
    ))
    registry.register(RegisteredTool(
        "skill.read", "Le uma skill inteira pelo nome, com as notas dela.",
        _tool_read,
        {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
        {}, "low", "skill.module",
    ))
    registry.register(RegisteredTool(
        "skill.create",
        "Cria uma skill NOVA (manual em Markdown) na tabela `skills`. Use pra ensinar "
        "um procedimento reutilizavel — nunca escreva o manual com file.write.",
        _tool_create,
        {"type": "object", "required": ["name", "content"], "properties": {
            "name": {"type": "string", "description": "id curto, ex: youtube_music_download"},
            "content": {"type": "string", "description": "a skill inteira em Markdown (passos, tools, pegadinhas)"},
            "title": {"type": "string", "description": "titulo legivel (opcional)"},
            "overwrite": {"type": "boolean", "description": "substituir se ja existir"},
        }},
        {}, "medium", "skill.module",
    ))
    registry.register(RegisteredTool(
        "skill.note", "Anexa uma dica curta e datada numa skill, pra ela melhorar na proxima.",
        _tool_note,
        {"type": "object", "required": ["name", "note"], "properties": {"name": {"type": "string"}, "note": {"type": "string"}}},
        {}, "low", "skill.module",
    ))
