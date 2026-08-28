"""Extrator de fatos: o "vigia" que salva memória sem depender do modelo do chat.

POR QUE ISTO EXISTE
-------------------
O prompt da Hana manda ela salvar fatos sozinha (regra "APRENDER" em
``persona/profile.py``), mas essa instrução é UMA linha no meio de ~12 mil
caracteres e ~40 outras regras. Modelo pequeno (flash) simplesmente não vê.
Prova no banco real: auto-save funcionou em 28/07 (2 fatos) e parou de vez
quando o chat trocou pra ``qwen3.7-flash``. Oito dias, zero memórias.

A saída não é implorar mais alto no prompt — é dar a tarefa pra uma chamada
SEPARADA que só tem UMA pergunta pra responder. Modelo pequeno com uma tarefa
só quase não erra; é o mesmo motivo do ``sleep.py`` nunca ter falhado.

DECISÕES QUE NÃO SÃO ÓBVIAS LENDO O CÓDIGO
------------------------------------------
- **Nunca apaga, arquiva.** Se o extrator errar ao julgar "isto corrige
  aquilo", apagar perde informação sem volta. Arquivar deixa uma linha parada
  num canto, restaurável pela tela. O pior caso vira reversível.
- **Não recebe o bloco de memória do prompt.** Só a fala crua. Senão: salva um
  fato -> o fato volta injetado no prompt -> a Hana repete -> o extrator salva
  de novo. Loop infinito que enche o banco sozinho.
- **Provider/modelo vêm da config, nunca hardcoded.** Quem clonar o repo não
  tem necessariamente crédito no provider que a Nakamura usa. Vazio = usa o
  mesmo modelo do chat: se a pessoa consegue conversar, consegue extrair.
- **Roda fora do caminho da resposta.** O chamador dispara e segue a vida; a
  Nakamura nunca espera por isto.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

STATUS_SETTING_KEY = "memory_extractor_status"

# Mensagem curta demais não carrega fato ("oi", "kkk", "ok", "sim"). Cortar aqui
# custa zero token — e no banco real 153 de 306 "memórias" já foram entulho, o
# que afunda fato de verdade na busca.
MIN_TEXT_CHARS = 12
_TRIVIAL_RE = re.compile(
    r"^(oi+|ol[áa]|e a[íi]|opa|kk+|rs+|haha+|ok|okay|blz|beleza|valeu|vlw|obrigad[ao]|"
    r"sim|n[ãa]o|nao|certo|entendi|tendi|boa|top|legal|bom dia|boa tarde|boa noite|tchau|"
    r"at[ée] mais|falou|isso|aham|uhum|hm+|eita|nossa|caralho|pqp|kkkk+)[\s!.?…]*$",
    re.IGNORECASE,
)

CATEGORIES = ("preference_like", "preference_dislike", "personal_fact", "correction", "joke", "topic")

# Instrução FIXA — não muda entre chamadas de propósito: provider cobra bem menos
# pelo prefixo repetido (prompt caching). No DeepSeek V4 Flash o cache hit sai a
# US$ 0,0028/M contra US$ 0,14/M sem cache.
_INSTRUCTION = """Você é um extrator de fatos. Sua ÚNICA tarefa é ler uma troca de mensagens e decidir se apareceu algum fato duradouro sobre a pessoa.

Responda SOMENTE com JSON válido, sem texto antes ou depois:
{"fato": "frase curta em 3a pessoa" ou null, "categoria": "...", "importancia": "high" ou "medium", "corrige": "id existente" ou null}

SALVE (fato = texto):
- gosto, desgosto, preferência
- fato pessoal duradouro (rotina, saúde, trabalho, relação, posse, meta)
- correção de algo que a pessoa disse antes

NÃO SALVE (fato = null):
- saudação, piada solta, papo à toa, reação ("kkk", "ok")
- pedido/pergunta pontual ("me ajuda com X", "qual a hora")
- algo que só vale pra este momento ("estou com fome agora")
- o que a assistente falou sobre si mesma

CORREÇÃO: se o fato novo CONTRADIZ uma das memórias existentes listadas, ponha o id dela em "corrige". Se for assunto inédito, "corrige": null.

categoria: preference_like, preference_dislike, personal_fact, correction, joke, topic
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def should_skip(user_text: str) -> bool:
    """Descarta a fala antes de gastar token: curta demais ou saudação/reação."""
    clean = str(user_text or "").strip()
    if len(clean) < MIN_TEXT_CHARS:
        return True
    return bool(_TRIVIAL_RE.match(clean))


def _candidate_models(memory: Any) -> list[tuple[str, str]]:
    """Modelos a tentar, em ordem: o do extrator, depois o do chat.

    Provider fixo no codigo quebraria pra qualquer um que nao tenha conta
    naquele provider — e quebra ate pra dona do repo, que troca de provider
    conforme onde tem credito no dia. Duas defesas:

    1. Nada e escolhido aqui: sai da config, editavel pela tela.
    2. Se o modelo do extrator falhar (402 sem credito, 429, modelo removido),
       cai pro do chat NA MESMA chamada. Se a pessoa consegue conversar com a
       Hana, o extrator roda — senao ele morreria calado em toda mensagem, que
       e o pior tipo de falha pra algo que roda em segundo plano.
    """
    cfg = memory.get_setting("llm_config", {}) or {}
    chat = (str(cfg.get("llmProvider") or "").strip(), str(cfg.get("llmModel") or "").strip())
    extrator = (
        str(cfg.get("memoryExtractorProvider") or "").strip(),
        str(cfg.get("memoryExtractorModel") or "").strip(),
    )
    tentativas = [par for par in (extrator, chat) if all(par)]
    return list(dict.fromkeys(tentativas))


def _build_user_block(user_text: str, hana_text: str, candidates: list[dict[str, Any]]) -> str:
    """Monta a parte variável do prompt: a troca + as memórias que podem conflitar."""
    partes = ["<conversa>", f"Pessoa: {str(user_text or '').strip()[:1500]}"]
    resposta = str(hana_text or "").strip()
    if resposta:
        partes.append(f"Assistente: {resposta[:600]}")
    partes.append("</conversa>")
    if candidates:
        partes.append("\n<memorias_existentes>")
        for item in candidates:
            partes.append(f"id={item.get('id')} | {str(item.get('text') or '')[:200]}")
        partes.append("</memorias_existentes>")
    return "\n".join(partes)


def _parse_reply(raw: str) -> dict[str, Any] | None:
    """Lê o JSON da resposta. Modelo pequeno às vezes embrulha em ``` ou texto solto."""
    text = str(raw or "").strip()
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _bump_status(memory: Any, field: str, *, error: str | None = None) -> None:
    """Contador visível na tela de Memória.

    Roda em segundo plano: sem isto, o extrator pode morrer e passar meses sem
    salvar nada com ninguém percebendo — exatamente o tipo de bug silencioso que
    já aconteceu aqui antes.
    """
    try:
        status = memory.get_setting(STATUS_SETTING_KEY, {}) or {}
        status[field] = int(status.get(field) or 0) + 1
        status["lastRunAt"] = _now_iso()
        if error:
            status["lastError"] = error[:300]
        memory.set_setting(STATUS_SETTING_KEY, status)
    except Exception:
        logger.debug("Falha ao atualizar status do extrator", exc_info=True)


def extract_and_save(
    memory: Any,
    *,
    user_text: str,
    hana_text: str = "",
    channel: str = "control_center",
) -> dict[str, Any]:
    """Lê uma troca, decide se há fato, e salva. Nunca levanta exceção.

    Devolve o que aconteceu para quem quiser logar/testar. Chamado fora do
    caminho da resposta — a usuária nunca espera por isto.
    """
    if should_skip(user_text):
        return {"ok": True, "action": "skipped_trivial"}

    tentativas = _candidate_models(memory)
    if not tentativas:
        return {"ok": False, "action": "no_model_configured"}

    try:
        candidates = memory.search(user_text, limit=5, touch=False)
    except Exception:
        # Busca é otimização (achar o fato que este contradiz), não requisito.
        logger.debug("Busca de candidatos falhou no extrator", exc_info=True)
        candidates = []

    from backend.providers import ProviderRequest, ProviderSelector

    conteudo = _INSTRUCTION + "\n" + _build_user_block(user_text, hana_text, candidates)
    response = None
    provider = model = ""
    ultimo_erro = "sem tentativa"
    for provider, model in tentativas:
        request = ProviderRequest(
            provider=provider,
            model=model,
            messages=[{"role": "user", "content": conteudo}],
            temperature=0.0,
            native_search_mode="off",
            allow_tools=False,
            channel=channel,
            memory=memory,
        )
        try:
            resposta = ProviderSelector().generate(request)
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = f"{provider}:{model} {exc}"
            logger.debug("Extrator falhou em %s:%s, tentando o proximo", provider, model, exc_info=True)
            continue
        if resposta.ok:
            response = resposta
            break
        ultimo_erro = f"{provider}:{model} {resposta.error}"

    if response is None:
        _bump_status(memory, "failures", error=ultimo_erro)
        logger.warning("Extrator de memória: nenhum modelo respondeu (%s)", ultimo_erro)
        return {"ok": False, "action": "provider_error", "error": ultimo_erro}

    data = _parse_reply(response.text)
    if data is None:
        _bump_status(memory, "failures", error="json_invalido")
        return {"ok": False, "action": "bad_json"}

    fato = str(data.get("fato") or "").strip()
    if not fato or fato.lower() in {"null", "none", "nao", "não"}:
        _bump_status(memory, "nothing")
        return {"ok": True, "action": "no_fact"}

    categoria = str(data.get("categoria") or "personal_fact").strip()
    if categoria not in CATEGORIES:
        categoria = "personal_fact"
    importancia = "high" if str(data.get("importancia") or "").strip().lower() == "high" else "medium"

    # Arquiva a antiga em vez de sobrescrever: se o julgamento "isto corrige
    # aquilo" estiver errado, o certo continua no banco e dá pra restaurar.
    corrige = str(data.get("corrige") or "").strip()
    arquivada: str | None = None
    if corrige and any(str(item.get("id")) == corrige for item in candidates):
        try:
            if memory.archive_memory(corrige):
                arquivada = corrige
        except Exception:
            logger.debug("Falha ao arquivar memória corrigida", exc_info=True)

    try:
        saved = memory.add_memory(
            fato,
            kind="long_term",
            source="memory_extractor",
            metadata={
                "category": categoria,
                "importance": importancia,
                "channel": channel,
                "auto_saved": True,
                "extractorModel": f"{provider}:{model}",
                "replaces": arquivada,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _bump_status(memory, "failures", error=str(exc))
        logger.warning("Extrator não conseguiu gravar a memória", exc_info=True)
        return {"ok": False, "action": "save_failed", "error": str(exc)}

    _bump_status(memory, "updated" if arquivada else "saved")
    return {
        "ok": True,
        "action": "updated" if arquivada else "saved",
        "id": saved.get("id"),
        "text": fato,
        "replaced": arquivada,
    }


def demo() -> None:
    """Self-check das partes puras (sem LLM, sem banco)."""
    assert should_skip("oi")
    assert should_skip("kkkkk")
    assert should_skip("   ok   ")
    assert should_skip("beleza!")
    assert not should_skip("eu odeio acordar cedo de manhã")

    assert _parse_reply('{"fato": "x", "categoria": "topic"}')["fato"] == "x"
    assert _parse_reply('```json\n{"fato": null}\n```')["fato"] is None
    assert _parse_reply("blá blá {\"fato\": \"y\"} fim")["fato"] == "y"
    assert _parse_reply("desculpa, não entendi") is None
    assert _parse_reply("") is None

    bloco = _build_user_block("gosto de pão", "que fome", [{"id": "abc", "text": "odeia pão"}])
    assert "id=abc" in bloco and "gosto de pão" in bloco
    assert "memorias_existentes" not in _build_user_block("x", "y", [])
    print("ok: extrator (guarda, parse, prompt) passou")


if __name__ == "__main__":
    demo()
