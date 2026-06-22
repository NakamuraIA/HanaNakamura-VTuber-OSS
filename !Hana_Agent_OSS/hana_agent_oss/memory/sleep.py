from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

# Ciclo de Sono da Hana (memória episódica).
#
# Sem isto, qualquer conversa que sai da janela de contexto morre para sempre.
# Uma vez por dia (ou sob demanda) a Hana "dorme": resume as conversas desde o
# último sono num diário em primeira pessoa, salva como memória episódica
# pesquisável (categoria "episode") e roda a manutenção (decay/dedup) que antes
# era manual. O resumo usa o modelo barato configurado, sem ferramentas.

SLEEP_SETTING_KEY = "memory_sleep"
SLEEP_INTERVAL_HOURS = 24
SLEEP_CHECK_SECONDS = 30 * 60
MAX_TRANSCRIPT_CHARS = 14000
MIN_TRANSCRIPT_CHARS = 200  # dia sem conversa relevante não vira episódio

CONVERSATION_KINDS_EXCLUDED = {
    "listening", "processing", "speaking", "system",
    "assistant_thought", "tool_call", "tool_result",
    "assistant_speech", "provider_error",
}

SUMMARY_PROMPT = (
    "Você é a Hana revisando o próprio dia antes de dormir. Abaixo está a transcrição "
    "das suas conversas com a Operador desde o último resumo.\n"
    "Escreva um DIÁRIO curto em primeira pessoa (você = Hana), em português, com no "
    "máximo 10 linhas, cobrindo:\n"
    "- o que vocês fizeram/criaram (com nomes e caminhos quando houver),\n"
    "- decisões tomadas e pendências (o que ficou para depois),\n"
    "- fatos novos importantes sobre a Operador ou pessoas citadas,\n"
    "- clima geral do dia.\n"
    "Seja específica e factual; não invente nada que não esteja na transcrição. "
    "Responda APENAS com o texto do diário, sem títulos nem comentários extras.\n\n"
    "=== TRANSCRIÇÃO ===\n"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def collect_transcript(memory: Any, since: datetime | None) -> str:
    """Build a compact transcript of real conversational turns since the last sleep."""
    events = memory.recent_events(limit=2000)
    lines: list[str] = []
    used = 0
    for event in reversed(events):  # newest first; budget favors recent turns
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "") in CONVERSATION_KINDS_EXCLUDED:
            continue
        content = str(event.get("content") or "").strip()
        if not content:
            continue
        created = _parse_iso(event.get("created_at"))
        if since is not None and created is not None and created <= since:
            break
        role = str(event.get("role") or "user")
        speaker = "Hana" if role in {"hana", "assistant", "model"} else "Operador"
        if len(content) > 600:
            content = content[:600] + "..."
        line = f"{speaker}: {content}"
        if used + len(line) > MAX_TRANSCRIPT_CHARS:
            break
        lines.append(line)
        used += len(line)
    lines.reverse()
    return "\n".join(lines)


def _summarize(memory: Any, transcript: str) -> tuple[str, str]:
    """Ask the configured (cheap) chat model for the diary text. Returns (text, model)."""
    cfg = memory.get_setting("llm_config", {}) or {}
    provider = str(cfg.get("llmProvider") or "gemini_api")
    model = str(cfg.get("llmModel") or "")

    from hana_agent_oss.providers import ProviderRequest, ProviderSelector

    request = ProviderRequest(
        provider=provider,
        model=model,
        messages=[{"role": "user", "content": SUMMARY_PROMPT + transcript}],
        temperature=0.3,
        native_search_mode="off",
        allow_tools=False,
        memory=memory,
    )
    response = ProviderSelector().generate(request)
    if not response.ok or not (response.text or "").strip():
        raise RuntimeError(f"sleep_summary_failed:{response.error or 'empty'}")
    return response.text.strip(), f"{provider}:{model}"


def run_sleep_cycle(memory: Any, *, force: bool = False) -> dict[str, Any]:
    """Run one full sleep cycle: episodic diary + maintenance. Idempotent per day."""
    state = memory.get_setting(SLEEP_SETTING_KEY, {}) or {}
    last_run = _parse_iso(state.get("lastRunAt"))
    if not force and last_run is not None and _now() - last_run < timedelta(hours=SLEEP_INTERVAL_HOURS):
        return {"ok": True, "skipped": "too_soon", "lastRunAt": state.get("lastRunAt")}

    transcript = collect_transcript(memory, last_run)
    episode_id = None
    summary_error = None
    if len(transcript) >= MIN_TRANSCRIPT_CHARS:
        try:
            diary, used_model = _summarize(memory, transcript)
            date_label = _now().astimezone().strftime("%d/%m/%Y")
            saved = memory.add_memory(
                f"[Diário {date_label}] {diary}",
                kind="episode",
                source="sleep_cycle",
                metadata={
                    "category": "episode",
                    "importance": "high",
                    "tags": ["episodio", "diario"],
                    "model": used_model,
                },
            )
            episode_id = saved.get("id")
        except Exception as exc:  # noqa: BLE001
            # Sem rede/modelo o sono não pode travar: manutenção roda mesmo assim e
            # o transcript continua coberto pelo próximo ciclo (lastRunAt só avança
            # quando o diário é salvo).
            summary_error = str(exc)

    maintenance = memory.run_maintenance(channel="sleep_cycle")

    # Indexa embeddings pendentes (no-op quando a memória semântica está desligada).
    embeddings = None
    try:
        embeddings = memory.embed_pending_memories()
    except Exception:
        embeddings = None

    if episode_id or len(transcript) < MIN_TRANSCRIPT_CHARS:
        memory.set_setting(SLEEP_SETTING_KEY, {"lastRunAt": _now().isoformat(), "lastEpisodeId": episode_id})

    return {
        "ok": summary_error is None,
        "episodeId": episode_id,
        "transcriptChars": len(transcript),
        "summaryError": summary_error,
        "maintenance": maintenance,
        "embeddings": embeddings,
    }


def latest_episode(memory: Any) -> dict[str, Any] | None:
    """Most recent episodic diary (used by the wake-up continuity block)."""
    try:
        for item in memory.list_memories(limit=100):
            if str(item.get("category") or "") == "episode":
                return item
    except Exception:
        return None
    return None


class SleepScheduler:
    """Tiny background thread that runs the sleep cycle once per day."""

    def __init__(self, memory: Any) -> None:
        self.memory = memory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="hana-sleep-cycle", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Primeiro check rápido após subir (cobre PC que ficou desligado no horário).
        if self._stop.wait(120):
            return
        while not self._stop.is_set():
            try:
                run_sleep_cycle(self.memory)
            except Exception:
                pass
            # Mantém o índice semântico fresco entre os ciclos diários: memórias
            # criadas durante o dia ficam 'pending' e são indexadas aqui (no-op se
            # a memória semântica estiver desligada).
            try:
                self.memory.embed_pending_memories()
            except Exception:
                pass
            if self._stop.wait(SLEEP_CHECK_SECONDS):
                return
