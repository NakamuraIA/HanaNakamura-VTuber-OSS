"""Regression tests for the new pillars: profile memory, living skills,
terminal hands and reminders.

These protect the features built in the 2026-06 sessions: always-on user
profile block, <anotar_skill> living skills, terminal.run hands and the
reminder scheduler.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hana_agent_oss.api.services.unified_history import (
    build_memory_context_block,
    build_profile_block,
)
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.reminders.scheduler import ReminderScheduler, compute_due
from hana_agent_oss.tools import skill_tools
from hana_agent_oss.tools.terminal_tools import inspect_dir, run_command


def _store(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")


# --- Pillar 2: always-on profile memory ----------------------------------- #

def test_profile_memories_returns_only_profile_categories(tmp_path) -> None:
    memory = _store(tmp_path)
    memory.add_memory("ama yakisoba", metadata={"category": "preference_like"}, kind="long_term")
    memory.add_memory("odeia abacaxi", metadata={"category": "preference_dislike"}, kind="long_term")
    memory.add_memory("tem dislexia", metadata={"category": "personal_fact"}, kind="long_term")
    memory.add_memory("papo aleatorio sobre o tempo", metadata={"category": "topic"}, kind="long_term")

    profile = memory.profile_memories()

    assert len(profile) == 3
    assert {item["category"] for item in profile} == {"preference_like", "preference_dislike", "personal_fact"}


def test_profile_block_always_present_and_sectioned(tmp_path) -> None:
    memory = _store(tmp_path)
    memory.add_memory("ama yakisoba", metadata={"category": "preference_like"}, kind="long_term")
    memory.add_memory("odeia abacaxi na pizza", metadata={"category": "preference_dislike"}, kind="long_term")

    block, items = build_profile_block(memory)

    assert "PERFIL DO USUÁRIO" in block
    assert "GOSTA" in block and "yakisoba" in block
    assert "NÃO GOSTA" in block and "abacaxi" in block
    assert len(items) == 2


def test_memory_context_block_includes_profile_without_duplicates(tmp_path) -> None:
    memory = _store(tmp_path)
    memory.add_memory("odeia abacaxi", metadata={"category": "preference_dislike"}, kind="long_term")
    memory.add_memory("estado do jogo: castelo em obras", metadata={"category": "game_state"}, kind="long_term")

    block, used = build_memory_context_block(memory, query="abacaxi jogo")

    assert "NÃO GOSTA" in block
    assert "castelo" in block
    # The dislike memory must appear once (profile), not duplicated in the RAG list.
    assert block.count("odeia abacaxi") == 1
    assert len(used) == 2


def test_profile_block_empty_when_no_profile_memories(tmp_path) -> None:
    memory = _store(tmp_path)
    memory.add_memory("so um topico", metadata={"category": "topic"}, kind="long_term")

    block, items = build_profile_block(memory)

    assert block == ""
    assert items == []


# --- Pillar 3: living skills ----------------------------------------------- #

def test_skill_note_appends_and_deduplicates(tmp_path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "minha_skill.md").write_text("# Minha Skill\nConteudo.", encoding="utf-8")
    monkeypatch.setattr(skill_tools, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_tools, "EXT_SKILLS_DIR", tmp_path / "nao_existe")

    first = skill_tools.append_skill_note("minha_skill", "usar parametro X")
    duplicate = skill_tools.append_skill_note("minha_skill", "usar parametro X")

    assert first["ok"] and not first.get("duplicate")
    assert duplicate["ok"] and duplicate.get("duplicate")
    content = (skills_dir / "minha_skill.md").read_text(encoding="utf-8")
    assert skill_tools.NOTES_HEADER in content
    assert content.count("usar parametro X") == 1


def test_skill_create_writes_into_own_dir(tmp_path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(skill_tools, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_tools, "EXT_SKILLS_DIR", tmp_path / "nao_existe")

    result = skill_tools.create_skill("youtube_music_download", "Passo a passo aqui.")

    assert result["ok"]
    created = skills_dir / "youtube_music_download.md"
    assert created.exists()
    # Title H1 injected automatically, content preserved.
    body = created.read_text(encoding="utf-8")
    assert body.startswith("# ")
    assert "Passo a passo aqui." in body


def test_skill_create_ignores_guessed_absolute_path(tmp_path, monkeypatch) -> None:
    """A name that looks like another bot's path collapses to a bare stem in our dir."""
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(skill_tools, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_tools, "EXT_SKILLS_DIR", tmp_path / "nao_existe")

    result = skill_tools.create_skill(
        r"C:\\Users\\Operador\\Desktop\\bot_dc\\.agent\\skills\\youtube_music_download",
        "conteudo",
    )

    assert result["ok"]
    # Wrote ONLY inside Hana's own dir, never into the Nyra/bot_dc path.
    assert skills_dir.resolve() in Path(result["path"]).resolve().parents
    assert (skills_dir / "youtube_music_download.md").exists()
    assert "bot_dc" not in result["path"]


def test_skill_create_refuses_clobber_without_overwrite(tmp_path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "ja_existe.md").write_text("# Ja existe\noriginal", encoding="utf-8")
    monkeypatch.setattr(skill_tools, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_tools, "EXT_SKILLS_DIR", tmp_path / "nao_existe")

    blocked = skill_tools.create_skill("ja_existe", "novo conteudo")
    assert not blocked["ok"]
    assert blocked["error"] == "skill_already_exists"
    assert "original" in (skills_dir / "ja_existe.md").read_text(encoding="utf-8")

    forced = skill_tools.create_skill("ja_existe", "novo conteudo", overwrite=True)
    assert forced["ok"]
    assert "novo conteudo" in (skills_dir / "ja_existe.md").read_text(encoding="utf-8")


def test_skill_note_blocks_path_traversal(tmp_path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(skill_tools, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_tools, "EXT_SKILLS_DIR", tmp_path / "nao_existe")

    result = skill_tools.append_skill_note("../../etc/passwd", "hack")

    assert not result["ok"]
    assert result["error"] == "skill_not_found"


def test_skill_notes_are_capped(tmp_path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "s.md").write_text("# S", encoding="utf-8")
    monkeypatch.setattr(skill_tools, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_tools, "EXT_SKILLS_DIR", tmp_path / "nao_existe")

    for index in range(skill_tools.MAX_NOTES + 10):
        skill_tools.append_skill_note("s", f"dica numero {index}")

    content = (skills_dir / "s.md").read_text(encoding="utf-8")
    note_lines = [line for line in content.splitlines() if line.startswith("- [")]
    assert len(note_lines) == skill_tools.MAX_NOTES
    # Oldest notes were dropped; the newest survived.
    assert f"dica numero {skill_tools.MAX_NOTES + 9}" in content
    assert "dica numero 0" not in content


def test_extract_and_strip_skill_xml() -> None:
    raw = 'antes <anotar_skill nome="alvo">minha dica util</anotar_skill> depois'

    notes = skill_tools.extract_skill_notes(raw)
    cleaned = skill_tools.strip_skill_xml_tags(raw)

    assert notes == [{"skill": "alvo", "note": "minha dica util"}]
    assert "anotar_skill" not in cleaned
    assert "antes" in cleaned and "depois" in cleaned


# --- Pillar 4: terminal hands ---------------------------------------------- #

def test_terminal_run_executes_and_reports_exit_code() -> None:
    ok = run_command({"command": "echo hana"})
    fail = run_command({"command": "comando_inexistente_xyz_123"})

    assert ok.ok and "hana" in ok.output["stdout"]
    assert ok.output["exitCode"] == 0
    assert not fail.ok


def test_terminal_run_rejects_empty_and_bad_cwd() -> None:
    assert run_command({"command": "   "}).error == "command_empty"
    bad = run_command({"command": "echo x", "cwd": "Z:/nao/existe"})
    assert not bad.ok and "cwd" in str(bad.error)


def test_terminal_run_times_out() -> None:
    import platform

    sleep_cmd = "ping 127.0.0.1 -n 6 >nul" if platform.system() == "Windows" else "sleep 5"
    result = run_command({"command": sleep_cmd, "timeout": 1})

    assert not result.ok
    assert result.output.get("timedOut") is True


def test_inspect_dir_lists_entries(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "subdir").mkdir()

    result = inspect_dir({"path": str(tmp_path)})

    assert result.ok
    names = {entry["name"] for entry in result.output["entries"]}
    assert names == {"a.txt", "subdir"}


# --- Pillar: reminders ------------------------------------------------------ #

def test_compute_due_accepts_flexible_formats() -> None:
    assert compute_due(at="16:30")[1] is None
    assert compute_due(at="16h")[1] is None
    assert compute_due(at="9")[1] is None
    assert compute_due(in_minutes=5)[1] is None
    assert compute_due(at="25:00")[1] is not None
    assert compute_due()[1] is not None


def test_reminder_crud_and_persistence(tmp_path) -> None:
    memory = _store(tmp_path)
    scheduler = ReminderScheduler(memory=memory)

    created = scheduler.create(text="tomar agua", in_minutes=5)
    assert created["ok"]
    assert len(scheduler.list()) == 1

    # A new scheduler instance over the same store sees the reminder (persistence).
    other = ReminderScheduler(memory=memory)
    assert len(other.list()) == 1

    cancelled = scheduler.cancel(created["reminder"]["id"])
    assert cancelled["ok"]
    assert scheduler.list() == []


def test_reminder_fires_speaks_and_logs(tmp_path) -> None:
    memory = _store(tmp_path)
    spoken: list[str] = []

    async def fake_speak(text: str, **_kwargs) -> bool:
        spoken.append(text)
        return True

    scheduler = ReminderScheduler(memory=memory, check_interval=5)
    scheduler.set_speaker(fake_speak)
    scheduler.create(text="alongar", in_seconds=0.5)

    time.sleep(0.6)
    scheduler._check_due()  # deterministic: run one check directly
    time.sleep(0.3)  # speech runs on a helper thread

    assert spoken == ["Lembrete: alongar"]
    assert scheduler.list() == []
    fired = memory.get_setting("reminders_fired", [])
    assert [item["text"] for item in fired] == ["alongar"]


def test_daily_reminder_fast_forwards_missed_days(tmp_path) -> None:
    memory = _store(tmp_path)
    scheduler = ReminderScheduler(memory=memory)
    created = scheduler.create(text="remedio", in_seconds=0.1, repeat="daily")
    assert created["ok"]

    # Simulate the PC having been off: due date 3 days in the past.
    from datetime import datetime, timedelta

    reminders = memory.get_setting("reminders", [])
    reminders[0]["due_at"] = (datetime.now() - timedelta(days=3)).replace(microsecond=0).isoformat()
    memory.set_setting("reminders", reminders)

    scheduler._check_due()

    updated = memory.get_setting("reminders", [])[0]
    assert updated["status"] == "active"  # daily stays active
    next_due = datetime.fromisoformat(updated["due_at"])
    assert next_due > datetime.now()  # fast-forwarded past all missed days


# --- Memory: sleep cycle (episodic diary) ---------------------------------- #

def _conversation_day(memory: MemoryStore) -> None:
    memory.append_event("user", "bora criar a landing page da Hana?", channel="control_center", metadata={})
    memory.append_event("hana", "bora! vou criar em Desktop/hana-landing", channel="control_center", metadata={})
    memory.append_event("local_hands", "Arquivo salvo: index.html", channel="terminal_agent", metadata={"kind": "tool_result", "toolName": "file.write", "status": "success"})
    memory.append_event("user", "ficou linda, obrigada!", channel="control_center", metadata={})


def test_collect_transcript_keeps_turns_and_drops_tool_noise(tmp_path) -> None:
    from hana_agent_oss.memory import sleep as sleep_mod

    memory = _store(tmp_path)
    _conversation_day(memory)
    transcript = sleep_mod.collect_transcript(memory, None)

    assert "Operador: bora criar a landing" in transcript
    assert "Hana: bora!" in transcript
    assert "Arquivo salvo" not in transcript  # tool_result fica fora do diário


def test_run_sleep_cycle_saves_episode_and_respects_24h_gate(tmp_path, monkeypatch) -> None:
    from hana_agent_oss.memory import sleep as sleep_mod

    memory = _store(tmp_path)
    _conversation_day(memory)
    # transcript mínimo: engorda o dia para passar do MIN_TRANSCRIPT_CHARS
    for i in range(10):
        memory.append_event("user", f"mensagem longa de teste numero {i} sobre o projeto da landing page", channel="control_center", metadata={})

    monkeypatch.setattr(sleep_mod, "_summarize", lambda mem, t: ("Hoje criamos a landing page da Hana em Desktop/hana-landing.", "fake:model"))

    result = sleep_mod.run_sleep_cycle(memory)
    assert result["ok"] is True
    assert result["episodeId"]

    episodes = [m for m in memory.list_memories() if m.get("category") == "episode"]
    assert len(episodes) == 1
    assert "landing page" in episodes[0]["text"]
    # diário é pesquisável via FTS
    found = memory.search("landing page")
    assert any(m.get("category") == "episode" for m in found)

    # segunda chamada no mesmo dia: pulada
    again = sleep_mod.run_sleep_cycle(memory)
    assert again.get("skipped") == "too_soon"
    # force ignora o portão
    forced = sleep_mod.run_sleep_cycle(memory, force=True)
    assert forced.get("skipped") is None


def test_run_sleep_cycle_quiet_day_skips_diary_but_advances(tmp_path, monkeypatch) -> None:
    from hana_agent_oss.memory import sleep as sleep_mod

    memory = _store(tmp_path)
    memory.append_event("user", "oi", channel="control_center", metadata={})

    called = {"n": 0}
    def fake_summarize(mem, t):
        called["n"] += 1
        return ("x", "fake")
    monkeypatch.setattr(sleep_mod, "_summarize", fake_summarize)

    result = sleep_mod.run_sleep_cycle(memory)
    assert result["ok"] is True
    assert result["episodeId"] is None
    assert called["n"] == 0  # dia sem conversa relevante não gasta LLM
    assert memory.get_setting(sleep_mod.SLEEP_SETTING_KEY, {}).get("lastRunAt")


def test_run_sleep_cycle_summary_failure_does_not_advance_gate(tmp_path, monkeypatch) -> None:
    from hana_agent_oss.memory import sleep as sleep_mod

    memory = _store(tmp_path)
    for i in range(12):
        memory.append_event("user", f"conversa importante numero {i} que nao pode ser perdida no resumo", channel="control_center", metadata={})

    def boom(mem, t):
        raise RuntimeError("sem rede")
    monkeypatch.setattr(sleep_mod, "_summarize", boom)

    result = sleep_mod.run_sleep_cycle(memory)
    assert result["ok"] is False
    assert result["summaryError"]
    # portão NÃO avança: o próximo ciclo tenta resumir o mesmo período de novo
    assert not memory.get_setting(sleep_mod.SLEEP_SETTING_KEY, {}).get("lastRunAt")


def test_latest_diary_block_injected_in_chat_context(tmp_path) -> None:
    from hana_agent_oss.api.services.unified_history import build_latest_diary_block, build_memory_context_block

    memory = _store(tmp_path)
    # sem diário: bloco vazio
    block, item = build_latest_diary_block(memory)
    assert block == "" and item is None

    memory.add_memory(
        "[Diário 10/06/2026] Hoje criamos a landing page e o co-piloto de mouse.",
        kind="episode",
        source="sleep_cycle",
        metadata={"category": "episode", "importance": "high", "tags": ["episodio"]},
    )

    block, item = build_latest_diary_block(memory)
    assert "ÚLTIMO DIÁRIO" in block and "landing page" in block
    assert item is not None

    full, injected = build_memory_context_block(memory, query="oi, tudo bem?")
    assert "ÚLTIMO DIÁRIO" in full  # continuidade mesmo com pergunta sem relação
    assert any(m.get("category") == "episode" for m in injected)
    # diário não duplica na seção de RAG
    assert full.count("landing page e o co-piloto") == 1


# --- Memory: chat tools (mãos na memória) ---------------------------------- #

def _chat_tool_runners(memory: MemoryStore):
    from unittest.mock import MagicMock
    from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider

    request = MagicMock()
    request.memory = memory
    request.allow_tools = True
    tools, runners = OpenRouterProvider()._tool_schemas_and_runners(request, supports_tools=True)
    return [t["function"]["name"] for t in tools], runners


def test_memory_chat_tools_full_roundtrip(tmp_path) -> None:
    memory = _store(tmp_path)
    names, runners = _chat_tool_runners(memory)

    for expected in ("memory_search", "memory_save", "memory_update", "memory_delete", "memory_pin"):
        assert expected in names and expected in runners

    # save → search encontra
    saved = runners["memory_save"]({"text": "Operador ama yakisoba", "category": "preference_like", "importance": "high"})
    assert saved["ok"] and saved["memory"]["id"]
    mem_id = saved["memory"]["id"]
    found = runners["memory_search"]({"query": "yakisoba"})
    assert found["ok"] and any(m["id"] == mem_id for m in found["memories"])

    # update corrige o texto
    updated = runners["memory_update"]({"id": mem_id, "text": "Operador ama yakisoba e ramen"})
    assert updated["ok"] and "ramen" in updated["memory"]["text"]

    # pin fixa
    assert runners["memory_pin"]({"id": mem_id, "pinned": True})["ok"]
    assert any(m["id"] == mem_id and m["pinned"] for m in runners["memory_search"]({"query": "ramen"})["memories"])

    # delete (soft) some da busca ativa
    assert runners["memory_delete"]({"id": mem_id})["ok"]
    assert not any(m["id"] == mem_id for m in runners["memory_search"]({"query": "ramen"})["memories"])

    # ids inexistentes falham com erro claro, sem exception
    assert runners["memory_delete"]({"id": "nao-existe"})["ok"] is False
    assert runners["memory_update"]({"id": "", "text": "x"})["ok"] is False


def test_allow_tools_false_disables_all_chat_tools(tmp_path) -> None:
    from unittest.mock import MagicMock
    from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider

    request = MagicMock()
    request.memory = _store(tmp_path)
    request.allow_tools = False
    tools, runners = OpenRouterProvider()._tool_schemas_and_runners(request, supports_tools=True)
    assert tools == [] and runners == {}


# --- Etapa 4: busca semântica / híbrida ----------------------------------- #

class _FakeEmbedder:
    """Deterministic stand-in for FastEmbed: maps animal concepts to fixed axes,
    so synonyms that share no FTS words still land on the same vector."""

    model = "fake-test"

    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = str(text or "").lower()
            if "gato" in lowered or "felino" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            elif "cachorro" in lowered or "canino" in lowered:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def _enable_fake_semantic(monkeypatch):
    """Force the optional semantic layer ON with the fake embedder, no fastembed."""
    from hana_agent_oss.memory import store as store_mod

    embedder = _FakeEmbedder()
    monkeypatch.setattr(store_mod, "is_semantic_enabled", lambda: True)
    monkeypatch.setattr(store_mod, "get_embedding_provider", lambda: embedder)
    monkeypatch.setattr(store_mod, "embed_query", lambda text: embedder.embed([text])[0])
    return embedder


def test_embed_pending_is_noop_when_disabled(tmp_path) -> None:
    memory = _store(tmp_path)
    memory.add_memory("tenho um gato persa", kind="long_term")
    result = memory.embed_pending_memories()
    assert result["skipped"] == "disabled" and result["embedded"] == 0


def test_embed_pending_indexes_and_flips_state(tmp_path, monkeypatch) -> None:
    _enable_fake_semantic(monkeypatch)
    memory = _store(tmp_path)
    memory.add_memory("tenho um gato persa", kind="long_term")
    memory.add_memory("meu cachorro late muito", kind="long_term")

    result = memory.embed_pending_memories()
    assert result["embedded"] == 2 and result["remaining"] == 0
    # idempotente: nada mais pendente
    assert memory.embed_pending_memories()["embedded"] == 0


def test_semantic_search_finds_by_meaning_without_shared_words(tmp_path, monkeypatch) -> None:
    _enable_fake_semantic(monkeypatch)
    memory = _store(tmp_path)
    memory.add_memory("tenho um gato persa branco", kind="long_term")
    memory.add_memory("meu cachorro late muito a noite", kind="long_term")
    memory.embed_pending_memories()

    # "felino" não casa por FTS com "gato", mas casa por significado.
    results = memory.search("felino domestico", touch=False)
    texts = " ".join(item["text"] for item in results)
    assert "gato persa" in texts


def test_semantic_search_degrades_to_fts_on_embed_failure(tmp_path, monkeypatch) -> None:
    from hana_agent_oss.memory import store as store_mod

    monkeypatch.setattr(store_mod, "is_semantic_enabled", lambda: True)
    monkeypatch.setattr(store_mod, "embed_query", lambda text: None)
    memory = _store(tmp_path)
    memory.add_memory("ama ramen de porco", kind="long_term")
    # Sem vetor de query, cai pro FTS sem quebrar.
    results = memory.search("ramen", touch=False)
    assert any("ramen" in item["text"] for item in results)
