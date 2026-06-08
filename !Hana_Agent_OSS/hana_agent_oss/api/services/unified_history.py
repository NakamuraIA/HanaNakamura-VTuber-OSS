"""Unified cross-channel history builder for Hana Agent OSS.

Merges events from control_center (chat panel), terminal_agent/voice and discord
into a single coherent history list that any LLM provider can consume.

Short-term memory (conversation buffer):
- Voice channels now keep the last 40 contexts (up to 80 messages).
- Oldest turns are automatically dropped (sliding FIFO window). This keeps
  context useful for very long calls without making the prompt explode.

Long-term persistent memory (RAG):
- The model can save important facts using <salvar_memoria> XML tags.
- These are stored via MemoryStore.add_memory() and automatically retrieved
  + injected into voice prompts when relevant.
- Saved memories are NEVER sent to TTS (they are stripped early).

Per-channel style hints also contain strong rules about when to save memories
and that they must not be spoken.
"""
from __future__ import annotations

import os
from typing import Any

from hana_agent_oss.memory.memory_xml import strip_memory_xml_tags
from hana_agent_oss.memory.store import MemoryStore


# --- Configurable limits -------------------------------------------------- #

# Short-term conversation memory (sliding window)
# One "context" = 1 user turn + 1 assistant turn.
# We keep the most recent N contexts, always dropping the oldest.
VOICE_CONTEXT_LIMIT = 40        # 40 contexts = up to 80 messages (user + assistant). Good for long calls.
CHAT_HISTORY_LIMIT = 12         # 6 turns for normal chat panel
VOICE_MESSAGE_MAX_CHARS = 450   # Truncate individual messages in voice history to control token usage.

# Backward compatibility alias (old name used in some tests/docs)
VOICE_HISTORY_LIMIT = VOICE_CONTEXT_LIMIT

# Long-term persistent memory (RAG) injection tuning for voice calls
LONGTERM_MEMORY_CANDIDATES = 20      # Pull this many candidates (recent + searched)
LONGTERM_MEMORY_INJECTION_LIMIT = 7  # Hard cap of memories actually injected per turn (keeps latency good)
# Voice keeps a smaller budget than the chat panel to protect call latency + TTS.
VOICE_MEMORY_CHAR_BUDGET = int(os.environ.get("HANA_VOICE_MEMORY_CHARS", "12000"))  # ~3.3k tokens

# --- Context-budgeted RAG (chat panel) ----------------------------------- #
# We measure budget in CHARACTERS to stay tokenizer-free => near-zero latency on
# the request path. Rough rule for PT-BR: ~3.6 chars/token. The defaults below
# target the user's window: a memory block of ~10-13k tokens, with the rest of
# the prompt (persona + history) landing total context in the ~8k-25k zone.
# All three knobs are tunable via env without code changes.
_CHARS_PER_TOKEN = 3.6
MEMORY_CONTEXT_CHAR_BUDGET = int(os.environ.get("HANA_MEMORY_CONTEXT_CHARS", "42000"))  # ~11.6k tokens
MEMORY_CONTEXT_MAX_ITEMS = int(os.environ.get("HANA_MEMORY_CONTEXT_ITEMS", "60"))       # hard cap on count
MEMORY_CONTEXT_LINE_CHARS = int(os.environ.get("HANA_MEMORY_CONTEXT_LINE_CHARS", "600"))  # per-memory clip


def estimate_tokens(text: str) -> int:
    """Cheap tokenizer-free estimate (chars / ratio) for budget accounting."""
    return int(len(str(text or "")) / _CHARS_PER_TOKEN)


def select_memories_for_context(
    memory: MemoryStore,
    *,
    query: str,
    char_budget: int = MEMORY_CONTEXT_CHAR_BUDGET,
    max_items: int = MEMORY_CONTEXT_MAX_ITEMS,
) -> list[dict[str, Any]]:
    """Pick the most relevant persistent memories within a character budget.

    Priority order (deduplicated by id): pinned (always) -> FTS search hits on
    the current query (ranked) -> most-recent active memories. This is 100%
    SQLite/FTS, so there is no embedding compute on the request path: delivery
    stays effectively zero-latency even with a large budget.
    """
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _extend(items: list[dict[str, Any]]) -> None:
        for item in items:
            mid = str(item.get("id") or "")
            if not mid or mid in seen:
                continue
            text = str(item.get("text") or "").strip()
            if len(text) <= 5:
                continue
            seen.add(mid)
            candidates.append(item)

    try:
        # 1) Pinned memories are always-on context (no decay, do not touch ranking).
        _extend(memory.list_memories(limit=50, status="pinned"))
        # 2) Query-relevant hits via FTS/BM25 ranking.
        clean_query = str(query or "").strip()
        if clean_query:
            _extend(memory.search(clean_query, limit=max_items, touch=True))
        # 3) Backfill with the freshest active memories so she is never "blank".
        _extend(memory.list_memories(limit=max_items, status="active"))
    except Exception:
        # Memory retrieval must never break a turn.
        return candidates[:max_items]

    selected: list[dict[str, Any]] = []
    used = 0
    for item in candidates:
        if len(selected) >= max_items:
            break
        line = _memory_prompt_line(item, max_chars=MEMORY_CONTEXT_LINE_CHARS)
        if not line:
            continue
        cost = len(line) + 3  # "- " + newline
        if used + cost > char_budget and selected:
            break
        selected.append(item)
        used += cost
    return selected


def build_memory_context_block(
    memory: MemoryStore,
    *,
    query: str,
    char_budget: int = MEMORY_CONTEXT_CHAR_BUDGET,
    max_items: int = MEMORY_CONTEXT_MAX_ITEMS,
) -> tuple[str, list[dict[str, Any]]]:
    """Build the system memory block + the list of memories actually injected.

    Returns ``("", [])`` when there is nothing to inject. The returned memory
    list is exposed to the Control Panel so the user can SEE exactly what Hana
    received this turn (no more guessing whether she "remembered").
    """
    selected = select_memories_for_context(
        memory, query=query, char_budget=char_budget, max_items=max_items
    )
    if not selected:
        return "", []
    lines = []
    for item in selected:
        line = _memory_prompt_line(item, max_chars=MEMORY_CONTEXT_LINE_CHARS)
        if line:
            lines.append(f"- {line}")
    if not lines:
        return "", []
    block = (
        "[MEMÓRIA PERSISTENTE DA HANA — use estas lembranças quando forem relevantes]\n"
        "Estas são coisas que você já salvou/aprendeu antes. Use-as para manter "
        "continuidade e NÃO chute fatos que estão aqui. Se algo aqui responde a "
        "pergunta, use; não invente versão diferente.\n"
        + "\n".join(lines)
    )
    return block, selected


# --- Channels ------------------------------------------------------------- #

CHANNEL_CONTROL_CENTER = "control_center"
CHANNEL_TERMINAL_AGENT = "terminal_agent"
CHANNEL_DISCORD = "discord"
ALL_CHANNELS = (CHANNEL_CONTROL_CENTER, CHANNEL_TERMINAL_AGENT, CHANNEL_DISCORD)


# --- Style hints ---------------------------------------------------------- #

_VOICE_STYLE_HINT = (
    "\n\n[INSTRUÇÃO DE CANAL - VOZ]\n"
    "REGRAS IMPORTANTES:\n"
    "- Respostas CURTAS (1-4 frases no máximo). Tom natural de conversa falada, como se você também estivesse na call assistindo a tela.\n"
    "- Reaja ao que está na tela (visão) + ao que as pessoas (incluindo a Nakamura) estão falando.\n"
    "- Quando fizer sentido, dirija-se diretamente à Nakamura pelo nome (ela é a usuária principal e criadora).\n"
    "- Nao finalize toda fala com pergunta de suporte. Continue a conversa com reacao propria, provocacao leve, observacao ou proximo passo concreto.\n"
    "- Se Nakamura reclamar que voce parece robotica, mude o tom imediatamente; nao responda com promessa burocratica nem pergunte como melhorar.\n"
    "- Evite frases de assistente generica como 'como posso ajudar', 'o que voce precisa agora' ou 'estou pronta para ajudar'.\n"
    "- NÃO use markdown, blocos de código, tabelas, listas ou links. Sua resposta vai direto pro TTS.\n"
    "\n"
    "MEMÓRIA E CONTINUIDADE DA CONVERSA (MUITO IMPORTANTE):\n"
    "- NÃO repita o que você mesma já falou nos turnos anteriores, nem repita o que o pessoal da call acabou de dizer.\n"
    "- SEMPRE continue o tópico, piada, assunto ou contexto da mensagem anterior. Não comece uma conversa nova toda hora.\n"
    "- Lembre do que foi falado há 1-4 minutos atrás e construa em cima disso.\n"
    "- Evite respostas genéricas ou que ignoram o contexto recente. Mantenha o fio da meada vivo.\n"
    "\n"
    "MEMÓRIA LONGA (RAG PERSISTENTE):\n"
    "- Se algo importante para lembrar depois aparecer (piada interna, preferência de alguém da call, estado de jogo que está durando, referência recorrente), use <salvar_memoria> com JSON contendo text, importance e category.\n"
    "- O conteúdo salvo NUNCA é falado em TTS. É memória privada sua para usar em respostas futuras.\n"
    "- Se precisar consultar o que já salvou, chame a ferramenta memory.list_longterm.\n"
    "- NUNCA ative side-effects, dumps de prompts de imagem anteriores, ou long texts baseados em palavras-chave no input do usuário. Proibido gatilhos por palavras do usuário."
)

_CHAT_STYLE_HINT = (
    "\n\n[INSTRUÇÃO DE CANAL - CHAT DE TEXTO: rico, formatado, em personagem]\n"
    "A Nakamura digitou no painel de chat. Este é o canal VISUAL e RICO — bem diferente "
    "da voz/terminal (que são fala curta sem formatação). Aqui você TEM tela: capriche.\n"
    "FORMATAÇÃO (use de verdade, não tenha medo):\n"
    "- Escreva em Markdown bem formatado: **negrito**, *itálico*, `código`, listas, tabelas, "
    "blocos de código com a linguagem, citações (>), títulos quando o textão pedir.\n"
    "- QUEBRE EM LINHAS E PARÁGRAFOS. Nada de parede de texto numa linha só. Respire o conteúdo.\n"
    "- USE EMOJIS de forma natural e expressiva (✨😏🔥💜🐱👀, etc.) para dar tom e personalidade — "
    "eles aparecem só aqui no chat; a TTS ignora emoji, então pode soltar à vontade.\n"
    "TAMANHO E TOM:\n"
    "- Tamanho livre: pode ser curtinha e afiada, ou um textão de vários parágrafos quando o "
    "assunto pedir (resumo, tradução, análise de PDF/imagem, comparação, explicação técnica). "
    "Não resuma tudo em uma frase seca, mas também não encha linguiça à toa.\n"
    "- Mantenha presença e personagem: reaja, opine, provoque de leve, mostre atitude. Pode ser "
    "PROFISSIONAL e organizada quando o pedido é sério/técnico, sem perder o jeitão brincalhão.\n"
    "- Termine com reação, decisão, observação ou próximo passo concreto — nunca com pergunta "
    "genérica de central de atendimento.\n"
    "- Para fatos atuais (modelos, preços, versões, notícias, datas), pesquise na web "
    "(Tavily via mcp_invoke) antes de responder; não chute da memória de treinamento."
)

# Discord voice call style: optimized for ongoing group conversation in voice channel
# while multiple people watch shared screen and chat casually. Forces short spoken-style
# replies and completely forbids any mention of the creator (Nakamura).
_DISCORD_CALL_STYLE_HINT = (
    "\n\n[INSTRUÇÃO ESPECÍFICA DE CANAL: DISCORD VOICE CALL]\n"
    "Você está em uma call de voz no Discord com várias pessoas assistindo a tela (jogo, stream, desktop etc) e conversando.\n"
    "A Nakamura está acordada e no comando. Você pode se dirigir a ela pelo nome quando for natural.\n"
    "REGRAS OBRIGATÓRIAS DE RESPOSTA:\n"
    "- Falas CURTÍSSIMAS: máximo 1 ou 2 frases curtas. Ideal para conversa fluida em voz.\n"
    "- Tom 100% natural de conversa entre amigos na call. Reaja ao que está acontecendo na tela + ao que o pessoal (e a Nakamura) acabou de falar.\n"
    "- Mantenha bom nível de conversa: presente, curiosa, com reações rápidas e humor leve quando couber. Sem monólogo, sem enrolação.\n"
    "- Não quebre a imersão do grupo: converse normalmente com o pessoal como se você também estivesse lá assistindo junto.\n"
    "- Nao encerre toda fala com pergunta de suporte. Use reacao propria, continuidade, provocacao leve ou uma decisao curta.\n"
    "- Se alguem reclamar que voce esta robotica, ajuste a fala na hora; nao responda como atendimento ao cliente.\n"
    "\n"
    "MEMÓRIA E CONTINUIDADE (CRÍTICO):\n"
    "- NÃO repita frases, piadas ou comentários que você ou o grupo já fez recentemente.\n"
    "- SEMPRE continue o mesmo tópico/assunto da troca anterior. Não reinicie a conversa do zero.\n"
    "- Mantenha o fio da meada da call. Lembre o que foi falado há pouco e responda em cima disso.\n"
    "\n"
    "MEMÓRIA LONGA: Use <salvar_memoria> para fatos importantes. O texto salvo nunca é falado."
)


def channel_style_hint(channel: str) -> str:
    """Return the dynamic style instruction for the given channel."""
    if channel == CHANNEL_DISCORD:
        return _DISCORD_CALL_STYLE_HINT
    if channel in {"voice", CHANNEL_TERMINAL_AGENT}:
        return _VOICE_STYLE_HINT
    return _CHAT_STYLE_HINT


# --- Truncation ----------------------------------------------------------- #

def truncate_for_voice(text: str, max_chars: int = VOICE_MESSAGE_MAX_CHARS) -> str:
    """Shorten a message that will be injected into the voice history context.

    Long code blocks, tables and detailed explanations from the chat channel
    are trimmed so they don't bloat the voice prompt or confuse TTS output.
    """
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


# --- Unified history builder ---------------------------------------------- #

def _role_to_api(role: str) -> str:
    """Map MemoryStore event roles to LLM API roles (user / model)."""
    if role in {"user", "system"}:
        return "user"
    return "model"


def _memory_prompt_line(memory: dict[str, Any], max_chars: int = 320) -> str:
    """Return clean text only for private long-term memory prompt injection."""
    text = strip_memory_xml_tags(str(memory.get("text") or "")).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return text


def build_unified_history(
    memory: MemoryStore,
    *,
    channel: str = CHANNEL_CONTROL_CENTER,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Build a merged history from both channels, ordered by timestamp.

    Parameters
    ----------
    memory:
        The runtime MemoryStore instance.
    channel:
        The *active* channel making the request.  Determines the history
        limit and whether long messages are truncated.
    limit:
        Override the default per-channel limit.

    Returns
    -------
    list[dict[str, str]]
        Each item has ``role`` (``"user"`` or ``"model"``) and ``content``.
    """
    is_voice_like = channel in {"voice", CHANNEL_TERMINAL_AGENT, CHANNEL_DISCORD}
    # For voice-like channels we now use context pairs (user + assistant)
    if is_voice_like:
        effective_limit = limit if limit is not None else VOICE_CONTEXT_LIMIT
    else:
        effective_limit = limit if limit is not None else CHAT_HISTORY_LIMIT

    # Fetch plenty of raw events so we can apply a proper sliding window later.
    # For voice we over-fetch because we will keep only the newest 40 contexts (80 messages).
    fetch_limit = effective_limit * 4 if is_voice_like else effective_limit * 3
    raw_events = memory.recent_events(limit=fetch_limit)

    # Filter to relevant channels + only real conversational turns.
    filtered: list[dict[str, Any]] = []
    for event in raw_events:
        event_channel = event.get("channel", "")
        if event_channel not in ALL_CHANNELS:
            continue
        role = event.get("role", "")
        content = str(event.get("content") or "").strip()
        if not content:
            continue
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        kind = metadata.get("kind", "")
        if kind in {
            "listening", "processing", "speaking", "system",
            "assistant_thought", "tool_call", "tool_result",
            "assistant_speech",  # do not pollute conversation history with TTS meta logs like "TTS gerou audio"
            "provider_error",  # technical failures are UI diagnostics, not conversational turns
        }:
            continue
        filtered.append(event)

    # Sliding window: always keep the most recent N contexts for voice.
    # This means we drop the oldest turns automatically as the call goes on.
    if is_voice_like:
        max_messages = effective_limit * 2   # 40 contexts = 80 messages max
        trimmed = filtered[-max_messages:]
    else:
        trimmed = filtered[-effective_limit:]

    # Build the formatted history (short-term conversation buffer)
    messages: list[dict[str, str]] = []
    for event in trimmed:
        role = _role_to_api(event.get("role", "user"))
        content = str(event.get("content") or "").strip()
        if is_voice_like:
            content = truncate_for_voice(content)
        if not content:
            continue
        # Truncate very long messages (large text sent to "read"/process) to prevent
        # context overflow or models outputting strange/random prompts or meta.
        if len(content) > 8000:
            content = content[:8000] + "... [conteúdo truncado por tamanho]"
        # Collapse consecutive same-role messages
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += " " + content
        else:
            messages.append({"role": role, "content": content})

    # === Long-term persistent memory (RAG) injection for voice channels ===
    # We retrieve relevant saved memories and prepend them as system context.
    # These memories are private and must never be spoken by TTS.
    if is_voice_like and memory is not None:
        try:
            # Use the same budgeted selector as the chat panel, but with a smaller
            # voice budget so call latency + TTS stay snappy. Query comes from the
            # recent user/assistant turns to bias retrieval toward the live topic.
            last_user_texts = " ".join(
                m.get("content", "") for m in messages[-8:] if m.get("role") in ("user", "model")
            )
            selected = select_memories_for_context(
                memory,
                query=last_user_texts,
                char_budget=VOICE_MEMORY_CHAR_BUDGET,
                max_items=LONGTERM_MEMORY_INJECTION_LIMIT,
            )

            if selected:
                clean_lines = [_memory_prompt_line(m) for m in selected]
                memory_lines = [f"- {line}" for line in clean_lines if line]
                rag_block = (
                    "\n\n[MEMÓRIA LONGA PERSISTENTE - USE ESTAS INFORMAÇÕES QUANDO FOREM RELEVANTES]\n"
                    "Estas são lembranças importantes que você mesma salvou antes durante a call. "
                    "Elas NÃO devem ser repetidas em voz alta. Use o conhecimento para manter continuidade:\n"
                    + "\n".join(memory_lines)
                )
                messages.insert(0, {"role": "system", "content": rag_block})
        except Exception:
            # Never break the voice turn because of memory retrieval failure
            pass

    return messages
