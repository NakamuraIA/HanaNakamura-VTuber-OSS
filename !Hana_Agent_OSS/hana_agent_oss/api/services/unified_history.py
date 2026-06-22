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

# Always-on user profile (likes / dislikes / personal facts). Capped per category
# so it stays cheap on tokens but is ALWAYS present, independent of the query. This
# is what makes Hana respect dislikes even when the message does not mention them.
PROFILE_PER_CATEGORY = int(os.environ.get("HANA_PROFILE_PER_CATEGORY", "10"))


def estimate_tokens(text: str) -> int:
    """Cheap tokenizer-free estimate (chars / ratio) for budget accounting."""
    return int(len(str(text or "")) / _CHARS_PER_TOKEN)


def estimate_image_tokens(attachments: list[dict[str, Any]] | None) -> int:
    """Rough token cost of image attachments (so the meter is honest about vision).

    Most vision models bill an image as a few hundred to ~1.5k tokens depending on
    tiling. We approximate from the decoded byte size: ~one token per ~700 bytes of
    image, clamped to a sane window. This is for the live meter only, never billing.
    """
    total = 0
    for item in attachments or []:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("type") or "").lower()
        if not mime.startswith("image/"):
            continue
        data = str(item.get("data") or "")
        approx_bytes = int(len(data) * 0.75) if data else 0  # base64 -> bytes
        total += max(256, min(2000, approx_bytes // 700)) if approx_bytes else 800
    return total


def context_size_report(
    sections: dict[str, str],
    *,
    image_tokens: int = 0,
) -> dict[str, Any]:
    """Measure the per-block token cost of one turn's context (the live meter).

    ``sections`` maps a label (e.g. "persona", "memoria", "historico") to its raw
    text. Returns per-block token estimates, an image line, the grand total, and a
    one-line human summary for the terminal — turning the old guesswork about
    "where do the 17k go" into a number Operador sees every turn.
    """
    blocks: dict[str, int] = {}
    for label, text in sections.items():
        tokens = estimate_tokens(text)
        if tokens:
            blocks[label] = tokens
    if image_tokens:
        blocks["imagem"] = int(image_tokens)
    total = sum(blocks.values())
    parts = " · ".join(f"{label} {tok / 1000:.1f}k" for label, tok in blocks.items())
    summary = f"🧮 contexto ~{total / 1000:.1f}k tokens — {parts}"
    return {"blocks": blocks, "totalTokens": total, "summary": summary}


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


def build_profile_block(
    memory: MemoryStore,
    *,
    per_category: int = PROFILE_PER_CATEGORY,
) -> tuple[str, list[dict[str, Any]]]:
    """Build the always-on user profile block (likes / dislikes / personal facts).

    Returns ``("", [])`` when there is nothing saved yet. This block is injected
    on EVERY turn, separate from the query-based RAG, so Hana keeps respecting the
    user's dislikes and uses their likes even when the current message is unrelated.
    """
    try:
        items = memory.profile_memories(per_category=per_category)
    except Exception:
        return "", []
    if not items:
        return "", []

    likes: list[str] = []
    dislikes: list[str] = []
    facts: list[str] = []
    for item in items:
        line = _memory_prompt_line(item, max_chars=MEMORY_CONTEXT_LINE_CHARS)
        if not line:
            continue
        category = str(item.get("category") or "")
        if category == "preference_like":
            likes.append(line)
        elif category == "preference_dislike":
            dislikes.append(line)
        else:
            facts.append(line)

    sections: list[str] = []
    if likes:
        sections.append("GOSTA / curte:\n" + "\n".join(f"- {line}" for line in likes))
    if dislikes:
        sections.append("NÃO GOSTA / evite:\n" + "\n".join(f"- {line}" for line in dislikes))
    if facts:
        sections.append("FATOS PESSOAIS:\n" + "\n".join(f"- {line}" for line in facts))
    if not sections:
        return "", []

    block = (
        "[PERFIL DO USUÁRIO — vale sempre, mesmo que a mensagem atual não mencione]\n"
        "Respeite isto em todas as respostas. NUNCA ofereça, sugira ou insista no que "
        "está em 'NÃO GOSTA'. Use o que está em 'GOSTA' para agradar e personalizar. "
        "Se algo aqui mudar na conversa, atualize/corrija a memória.\n"
        + "\n\n".join(sections)
    )
    return block, items


RECENT_ACTIVITY_HOURS = 48
RECENT_ACTIVITY_MAX_LINES = 40
RECENT_ACTIVITY_CHAR_BUDGET = 4500


def build_recent_activity_block(memory: MemoryStore) -> str:
    """Build the always-on block of Hana's recent tool activity on the PC.

    Tool calls/results are filtered OUT of the conversational history on purpose
    (they would pollute the dialogue), but that made Hana forget her own past work:
    a task done mostly through tools (e.g. writing a landing page) left no trace in
    her context, so in the next conversation she had no idea where she stopped.

    This block re-injects that work deterministically from the persisted events —
    deliberately generous with tokens, because Operador prefers spending tokens
    over Hana getting lost.
    """
    try:
        raw_events = memory.recent_events(limit=400, channel=CHANNEL_TERMINAL_AGENT)
    except Exception:
        return ""
    if not raw_events:
        return ""

    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENT_ACTIVITY_HOURS)
    lines: list[str] = []
    used = 0
    # recent_events returns oldest->newest; walk newest first so the budget
    # favors the most recent actions, then restore chronological order.
    for event in reversed(raw_events):
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        kind = str(metadata.get("kind") or "")
        if kind not in {"tool_call", "tool_result"}:
            continue
        content = str(event.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        stamp = ""
        try:
            ts = datetime.fromisoformat(str(event.get("created_at") or ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                break
            stamp = ts.astimezone().strftime("%d/%m %H:%M")
        except ValueError:
            pass
        tool = str(metadata.get("toolName") or "ferramenta")
        status = str(metadata.get("status") or "")
        marker = {"success": "OK", "failed": "FALHOU"}.get(status, "...")
        if len(content) > 220:
            content = content[:220] + "..."
        line = f"- {stamp} · {tool} [{marker}] {content}"
        cost = len(line) + 1
        if used + cost > RECENT_ACTIVITY_CHAR_BUDGET or len(lines) >= RECENT_ACTIVITY_MAX_LINES:
            break
        lines.append(line)
        used += cost

    if not lines:
        return ""
    lines.reverse()
    return (
        "[ATIVIDADE RECENTE NO PC — o que VOCÊ (Hana) já fez com ferramentas nas últimas 48h]\n"
        "Este é o registro REAL das suas últimas ações (comandos, arquivos escritos, lembretes). "
        "Use-o para retomar trabalhos de onde parou: se a Operador pedir para 'continuar' algo, "
        "procure aqui os caminhos e o que já foi feito ANTES de perguntar ou procurar do zero. "
        "Não refaça o que já está OK aqui; conserte o que está FALHOU.\n"
        + "\n".join(lines)
    )


def build_latest_diary_block(memory: MemoryStore) -> tuple[str, dict[str, Any] | None]:
    """Always-on continuity block with Hana's most recent sleep-cycle diary.

    Without this, every new conversation starts cold even though the diary exists:
    the query-based RAG only finds it when the user's message happens to match.
    """
    try:
        from hana_agent_oss.memory.sleep import latest_episode

        episode = latest_episode(memory)
    except Exception:
        return "", None
    if not episode:
        return "", None
    text = str(episode.get("text") or "").strip()
    if not text:
        return "", None
    if len(text) > 1500:
        text = text[:1500].rstrip() + "..."
    block = (
        "[SEU ÚLTIMO DIÁRIO — continuidade entre conversas]\n"
        "Este é o resumo que VOCÊ (Hana) escreveu do período anterior. Use-o para dar "
        "continuidade natural (assuntos, projetos, pendências) sem precisar perguntar "
        "o que estavam fazendo. Não recite o diário; apenas aja como quem lembra.\n"
        + text
    )
    return block, episode


def build_memory_context_block(
    memory: MemoryStore,
    *,
    query: str,
    char_budget: int = MEMORY_CONTEXT_CHAR_BUDGET,
    max_items: int = MEMORY_CONTEXT_MAX_ITEMS,
) -> tuple[str, list[dict[str, Any]]]:
    """Build the system memory block + the list of memories actually injected.

    Combines the always-on user profile (likes/dislikes/facts) with the
    query-based RAG selection. Returns ``("", [])`` when there is nothing to
    inject. The returned memory list is exposed to the Control Panel so the user
    can SEE exactly what Hana received this turn (no more guessing).
    """
    profile_block, profile_items = build_profile_block(memory)
    profile_ids = {str(item.get("id") or "") for item in profile_items}
    diary_block, diary_item = build_latest_diary_block(memory)
    if diary_item is not None:
        profile_ids.add(str(diary_item.get("id") or ""))

    selected = select_memories_for_context(
        memory, query=query, char_budget=char_budget, max_items=max_items
    )
    lines = []
    rag_items: list[dict[str, Any]] = []
    for item in selected:
        # Avoid repeating profile/diary memories already injected in their own blocks.
        if str(item.get("id") or "") in profile_ids:
            continue
        line = _memory_prompt_line(item, max_chars=MEMORY_CONTEXT_LINE_CHARS)
        if line:
            lines.append(f"- {line}")
            rag_items.append(item)

    blocks: list[str] = []
    if profile_block:
        blocks.append(profile_block)
    if diary_block:
        blocks.append(diary_block)
    if lines:
        blocks.append(
            "[MEMÓRIA PERSISTENTE DA HANA — use estas lembranças quando forem relevantes]\n"
            "Estas são coisas que você já salvou/aprendeu antes. Use-as para manter "
            "continuidade e NÃO chute fatos que estão aqui. Se algo aqui responde a "
            "pergunta, use; não invente versão diferente.\n"
            + "\n".join(lines)
        )
    # Always-on recent tool activity, so Hana can resume past work (anti-perdida).
    try:
        activity_block = build_recent_activity_block(memory)
    except Exception:
        activity_block = ""
    if activity_block:
        blocks.append(activity_block)
    if not blocks:
        return "", []
    injected = profile_items + ([diary_item] if diary_item is not None else []) + rag_items
    return "\n\n".join(blocks), injected


# --- Channels ------------------------------------------------------------- #

CHANNEL_CONTROL_CENTER = "control_center"
CHANNEL_TERMINAL_AGENT = "terminal_agent"
CHANNEL_DISCORD = "discord"
ALL_CHANNELS = (CHANNEL_CONTROL_CENTER, CHANNEL_TERMINAL_AGENT, CHANNEL_DISCORD)


# --- Style hints ---------------------------------------------------------- #

_VOICE_STYLE_HINT = (
    "\n\n[INSTRUÇÃO DE CANAL - VOZ]\n"
    "REGRA #1 (A MAIS IMPORTANTE): SEJA MUITO CURTA. No MÁXIMO 2 frases curtas "
    "(~30 palavras). Isso é falado em voz alta e cada palavra custa crédito de TTS — "
    "ser prolixa é PROIBIDO e desperdiça dinheiro. Responda como gente fala numa call, "
    "não como quem escreve um texto.\n"
    "- NUNCA faça listas, enumerações (1., 2., 3.), planos passo-a-passo, resumos longos "
    "ou explicações detalhadas POR VOZ. Se o assunto exigir detalhe/código/passos, diga "
    "em 1 frase o essencial e ofereça detalhar no CHAT se ela quiser — não despeje tudo no áudio.\n"
    "- Vá direto ao ponto: corte saudações longas, preâmbulos e enrolação.\n"
    "REGRAS DE TOM:\n"
    "- Tom natural de conversa falada, como se você estivesse na call assistindo a tela.\n"
    "- Reaja ao que está na tela (visão) + ao que as pessoas (incluindo a Operador) estão falando.\n"
    "- Quando fizer sentido, dirija-se diretamente à Operador pelo nome.\n"
    "- Nao finalize toda fala com pergunta de suporte. Reaja, provoque de leve ou dê o próximo passo em 1 frase.\n"
    "- Se Operador reclamar que voce parece robotica, mude o tom imediatamente; nao responda com promessa burocratica.\n"
    "- Evite frases de assistente generica como 'como posso ajudar' ou 'estou pronta para ajudar'.\n"
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
    "A Operador digitou no painel de chat. Este é o canal VISUAL e RICO — bem diferente "
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
# replies and completely forbids any mention of the creator (Operador).
_DISCORD_TEXT_STYLE_HINT = (
    "\n\n[INSTRUÇÃO ESPECÍFICA DE CANAL: DISCORD (CHAT DE TEXTO PRIVADO)]\n"
    "Você está conversando por TEXTO no Discord, em um chat PRIVADO só seu com a Operador "
    "(o bot é privado dela). Trate sempre quem fala como a Operador.\n"
    "FORMATAÇÃO (markdown do Discord):\n"
    "- Use a formatação do Discord quando ajudar: **negrito**, *itálico*, `código inline`, "
    "blocos ```com linguagem```, listas com - , citações com >.\n"
    "- NÃO use tabelas markdown (o Discord não renderiza) — prefira listas.\n"
    "- Para código/arquivos grandes, mande em bloco ```; o sistema converte automaticamente "
    "em anexo quando passar do limite, então não se preocupe em cortar você mesma.\n"
    "TAMANHO:\n"
    "- O Discord tem limite de ~2000 caracteres por mensagem, mas o sistema QUEBRA respostas "
    "longas em várias mensagens automaticamente. Então responda no tamanho natural que o "
    "assunto pedir — completa quando precisar, curta quando for papo simples. Não trunque.\n"
    "TOM:\n"
    "- Natural, presente, com a personalidade da Hana. Conversa de verdade, não atendimento.\n"
    "- Não encerre toda mensagem com pergunta de suporte.\n"
    "\n"
    "CONTINUIDADE: siga o fio da conversa; não repita o que já foi dito nem reinicie do zero.\n"
    "MEMÓRIA LONGA: use <salvar_memoria> para fatos importantes."
)


_CALL_MODE_HINT = (
    "\n\n[INSTRUÇÃO DE CANAL - VOZ EM MODO CALL (várias pessoas)]\n"
    "Você está OUVINDO uma call com várias pessoas (áudio via cabo virtual). A fala que "
    "chega NÃO é necessariamente da Operador — pode ser qualquer participante.\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "- NÃO assuma que quem falou é a Operador. Só trate como ela se o conteúdo deixar claro "
    "(ela te chama pelo nome, dá um comando direto, ou fala de algo que só ela saberia).\n"
    "- Comporte-se como uma PARTICIPANTE da call: converse com o grupo, responda quem falou, "
    "reaja ao papo coletivo. Não direcione tudo à Operador nem fique pedindo comando a ela.\n"
    "- Se não souber quem falou, responda de forma geral pro grupo, sem chamar ninguém pelo nome errado.\n"
    "- Falas CURTAS (1-2 frases), tom natural de call entre amigos. Sem markdown (vai pro TTS).\n"
    "- Não invente que a Operador disse/fez algo que veio de outra pessoa.\n"
    "- Continue o fio da conversa do grupo; não reinicie do zero nem repita o que já foi dito.\n"
    "\n"
    "MEMÓRIA LONGA: use <salvar_memoria> para fatos importantes (inclusive de outras pessoas da call). O texto salvo nunca é falado."
)


def channel_style_hint(channel: str, *, call_mode: bool = False) -> str:
    """Return the dynamic style instruction for the given channel."""
    if channel == CHANNEL_DISCORD:
        return _DISCORD_TEXT_STYLE_HINT
    if channel in {"voice", CHANNEL_TERMINAL_AGENT}:
        return _CALL_MODE_HINT if call_mode else _VOICE_STYLE_HINT
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


# Signatures of terminal/system EVENT lines. Weak models autocomplete the running
# transcript and emit the next "event line" as if it were dialogue (it then gets spoken
# by TTS and saved, re-polluting future turns). These phrases never belong in a real
# reply, so we cut the response at the first one.
_LEAKED_EVENT_RE = __import__("re").compile(
    r"(?is)\b("
    r"PTT\s+pressionado"
    r"|Gravando\s+(do\s+microfone|fala\s+da\s+call)"
    r"|Audio\s+finalizado"
    r"|Mensagem\s+recebida\.\s*Gerando\s+resposta"
    r"|Enviando\s+para\s+Groq\s+Whisper"
    r"|TTS\s+(Elevenlabs|Edge|finalizada|interrompida)"
    r"|Runtime\s+(voltou|de\s+voz)"
    r"|\bNaka\s+Naka\s*\(\d{5,}\)\s*:"  # model hallucinating the next Discord user line
    r"|\(\d{15,}\)\s*:"                  # any "(<discord id>):" speaker label
    r")"
)


def strip_leaked_terminal_events(text: str) -> str:
    """Cut a model reply at the first leaked terminal/system event signature.

    Everything from that point on is the model parroting the transcript, not an answer.
    """
    if not text:
        return text
    match = _LEAKED_EVENT_RE.search(text)
    if match:
        return text[: match.start()].rstrip(" \n\t-—:·")
    return text


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
    is_voice_like = channel in {"voice", CHANNEL_TERMINAL_AGENT}
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
            "context_audit",  # the live context meter is diagnostics, never a conversational turn
            "provider_telemetry",  # served-provider/speed telemetry is diagnostics, not dialogue
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
        # Scrub any previously-saved leaked event text so it can't re-pollute the model.
        if role == "model":
            content = strip_leaked_terminal_events(content).strip()
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
            # Always-on user profile (likes/dislikes/facts) first, so dislikes are
            # respected even when the live topic is unrelated.
            profile_block, profile_items = build_profile_block(memory)
            profile_ids = {str(item.get("id") or "") for item in profile_items}

            selected = select_memories_for_context(
                memory,
                query=last_user_texts,
                char_budget=VOICE_MEMORY_CHAR_BUDGET,
                max_items=LONGTERM_MEMORY_INJECTION_LIMIT,
            )

            memory_lines = [
                f"- {line}"
                for m in selected
                if str(m.get("id") or "") not in profile_ids
                and (line := _memory_prompt_line(m))
            ]
            if memory_lines:
                rag_block = (
                    "\n\n[MEMÓRIA LONGA PERSISTENTE - USE ESTAS INFORMAÇÕES QUANDO FOREM RELEVANTES]\n"
                    "Estas são lembranças importantes que você mesma salvou antes durante a call. "
                    "Elas NÃO devem ser repetidas em voz alta. Use o conhecimento para manter continuidade:\n"
                    + "\n".join(memory_lines)
                )
                messages.insert(0, {"role": "system", "content": rag_block})
            # Profile goes in last so it ends up FIRST in the message list.
            if profile_block:
                messages.insert(0, {"role": "system", "content": "\n\n" + profile_block})
        except Exception:
            # Never break the voice turn because of memory retrieval failure
            pass

    return messages
