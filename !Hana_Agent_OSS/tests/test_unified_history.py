"""Tests for the unified cross-channel history module."""
from __future__ import annotations

from hana_agent_oss.api.services.unified_history import (
    CHANNEL_CONTROL_CENTER,
    CHANNEL_TERMINAL_AGENT,
    VOICE_HISTORY_LIMIT,
    VOICE_MESSAGE_MAX_CHARS,
    build_unified_history,
    channel_style_hint,
    truncate_for_voice,
)
from hana_agent_oss.memory.store import MemoryStore


def _make_memory(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")


# --- truncate_for_voice --------------------------------------------------- #


def test_truncate_short_text_unchanged() -> None:
    assert truncate_for_voice("Oi Hana") == "Oi Hana"


def test_truncate_exact_limit_unchanged() -> None:
    text = "a" * VOICE_MESSAGE_MAX_CHARS
    assert truncate_for_voice(text) == text


def test_truncate_long_text_gets_ellipsis() -> None:
    text = "x" * (VOICE_MESSAGE_MAX_CHARS + 50)
    result = truncate_for_voice(text)
    assert result.endswith("...")
    assert len(result) == VOICE_MESSAGE_MAX_CHARS + 3


def test_truncate_empty_returns_empty() -> None:
    assert truncate_for_voice("") == ""
    assert truncate_for_voice("   ") == ""


# --- channel_style_hint --------------------------------------------------- #


def test_voice_hint_mentions_microfone() -> None:
    hint = channel_style_hint("voice")
    assert "microfone" in hint.lower() or "voz" in hint.lower()
    assert "markdown" in hint.lower()
    assert "pergunta de suporte" in hint.lower()
    assert "robotica" in hint.lower()


def test_chat_hint_mentions_painel() -> None:
    hint = channel_style_hint("control_center")
    assert "painel" in hint.lower() or "chat" in hint.lower() or "texto" in hint.lower()


def test_terminal_agent_channel_uses_voice_hint() -> None:
    assert channel_style_hint(CHANNEL_TERMINAL_AGENT) == channel_style_hint("voice")


# --- build_unified_history ------------------------------------------------ #


def test_empty_memory_returns_empty_list(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    assert build_unified_history(memory, channel="voice") == []


def test_single_channel_events_appear_in_history(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    memory.append_event("user", "Oi Hana", channel=CHANNEL_CONTROL_CENTER)
    memory.append_event("hana", "Oi Nakamura!", channel=CHANNEL_CONTROL_CENTER)

    result = build_unified_history(memory, channel=CHANNEL_CONTROL_CENTER)
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "Oi Hana"
    assert result[1]["role"] == "model"
    assert result[1]["content"] == "Oi Nakamura!"


def test_cross_channel_events_are_merged(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    memory.append_event("user", "Me fala sobre Python", channel=CHANNEL_CONTROL_CENTER)
    memory.append_event("hana", "Python e uma linguagem incrivel.", channel=CHANNEL_CONTROL_CENTER)
    memory.append_event("user", "O que eu acabei de perguntar?", channel=CHANNEL_TERMINAL_AGENT, metadata={"kind": "user_text"})

    result = build_unified_history(memory, channel="voice")
    assert len(result) == 3
    # First message from chat channel should appear
    assert "Python" in result[0]["content"]
    # Voice question should be last
    assert "acabei" in result[-1]["content"]


def test_voice_channel_truncates_long_messages(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    long_code = "def foo():\n" + "    pass\n" * 100
    memory.append_event("hana", long_code, channel=CHANNEL_CONTROL_CENTER)

    result = build_unified_history(memory, channel="voice")
    assert len(result) == 1
    assert result[0]["content"].endswith("...")
    assert len(result[0]["content"]) <= VOICE_MESSAGE_MAX_CHARS + 3


def test_chat_channel_does_not_truncate(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    long_code = "def foo():\n" + "    pass\n" * 100
    memory.append_event("hana", long_code, channel=CHANNEL_CONTROL_CENTER)

    result = build_unified_history(memory, channel=CHANNEL_CONTROL_CENTER)
    assert len(result) == 1
    assert not result[0]["content"].endswith("...")


def test_voice_history_respects_limit(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    for i in range(20):
        role = "user" if i % 2 == 0 else "hana"
        memory.append_event(role, f"Msg {i}", channel=CHANNEL_CONTROL_CENTER)

    result = build_unified_history(memory, channel="voice")
    assert len(result) <= VOICE_HISTORY_LIMIT


def test_system_events_are_filtered_out(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    memory.append_event("user", "Oi", channel=CHANNEL_TERMINAL_AGENT, metadata={"kind": "user_text"})
    memory.append_event("system", "Ouvindo microfone", channel=CHANNEL_TERMINAL_AGENT, metadata={"kind": "listening"})
    memory.append_event("system", "Processando audio", channel=CHANNEL_TERMINAL_AGENT, metadata={"kind": "processing"})
    memory.append_event("hana", "Oi!", channel=CHANNEL_TERMINAL_AGENT, metadata={"kind": "assistant_text"})

    result = build_unified_history(memory, channel="voice")
    # Only the user text and assistant text should survive
    assert len(result) == 2
    assert result[0]["content"] == "Oi"
    assert result[1]["content"] == "Oi!"


def test_consecutive_same_role_messages_are_collapsed(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    memory.append_event("user", "primeira parte", channel=CHANNEL_CONTROL_CENTER)
    memory.append_event("user", "segunda parte", channel=CHANNEL_CONTROL_CENTER)
    memory.append_event("hana", "resposta", channel=CHANNEL_CONTROL_CENTER)

    result = build_unified_history(memory, channel=CHANNEL_CONTROL_CENTER)
    assert len(result) == 2
    assert "primeira parte" in result[0]["content"]
    assert "segunda parte" in result[0]["content"]


def test_custom_limit_overrides_default(tmp_path) -> None:
    memory = _make_memory(tmp_path)
    for i in range(10):
        role = "user" if i % 2 == 0 else "hana"
        memory.append_event(role, f"Msg {i}", channel=CHANNEL_CONTROL_CENTER)

    # limit=4 now means 4 contexts (user+assistant pairs) = up to 8 messages for voice
    result = build_unified_history(memory, channel="voice", limit=4)
    assert len(result) <= 8
