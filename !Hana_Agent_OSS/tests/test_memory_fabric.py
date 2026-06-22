from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from hana_agent_oss.api.server import app
from hana_agent_oss.memory.memory_xml import extract_memory_saves, strip_memory_xml_tags
from hana_agent_oss.memory.store import MemoryStore


def _memory(tmp_path) -> MemoryStore:
    """Create an isolated memory store for tests."""
    return MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")


def test_memory_store_migrates_v1_rows_to_v2(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE memory_items (
              id TEXT PRIMARY KEY,
              text TEXT NOT NULL,
              kind TEXT NOT NULL DEFAULT 'note',
              source TEXT NOT NULL DEFAULT 'manual',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO memory_items (id, text, kind, source, metadata_json, created_at, updated_at)
            VALUES ('old-1', 'Operador gosta de yakisoba', 'long_term', 'model', '{"importance":"high","category":"preference","tags":["food"]}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            """
        )

    memory = MemoryStore(db_path, tmp_path / "events.jsonl")
    items = memory.list_memories()

    assert items[0]["id"] == "old-1"
    assert items[0]["importance"] == "high"
    assert items[0]["category"] == "preference"
    assert items[0]["tags"] == ["food"]
    assert memory.search("yakisoba")[0]["id"] == "old-1"


def test_memory_crud_soft_delete_restore_and_hard_delete(tmp_path):
    memory = _memory(tmp_path)
    item = memory.add_memory("Hana deve lembrar do projeto Memory Fabric", metadata={"category": "project", "importance": "high"})

    updated = memory.add_memory(
        "Hana deve lembrar do Memory Fabric v1",
        memory_id=item["id"],
        metadata={"category": "project", "importance": "critical", "tags": ["memory", "rag"]},
    )
    assert updated["importance"] == "critical"
    assert updated["tags"] == ["memory", "rag"]

    assert memory.delete_memory(item["id"]) is True
    assert memory.search("Memory Fabric") == []
    assert memory.list_memories(status="deleted")[0]["id"] == item["id"]

    assert memory.restore_memory(item["id"]) is True
    assert memory.search("Memory Fabric")[0]["id"] == item["id"]

    assert memory.delete_memory(item["id"], hard=True) is True
    assert memory.list_memories(status="all") == []


def test_memory_ranking_uses_pin_and_strengthens_usage(tmp_path):
    memory = _memory(tmp_path)
    first = memory.add_memory("Operador gosta de yakisoba", metadata={"importance": "medium"})
    second = memory.add_memory("Operador gosta de yakisoba no fim da noite", metadata={"importance": "medium"})
    memory.pin_memory(second["id"], pinned=True)

    results = memory.search("yakisoba", limit=2)

    assert results[0]["id"] == second["id"]
    refreshed = {item["id"]: item for item in memory.list_memories(limit=10)}
    assert refreshed[first["id"]]["metadata"]["useCount"] >= 1
    assert refreshed[second["id"]]["metadata"]["useCount"] >= 1


def test_memory_compact_merge_and_maintenance(tmp_path):
    memory = _memory(tmp_path)
    first = memory.add_memory("Operador prefere memoria leve", metadata={"category": "preference"})
    second = memory.add_memory("Operador prefere memoria leve", metadata={"category": "preference"})
    third = memory.add_memory("Hana deve compactar conversas antigas", metadata={"category": "maintenance"})

    compacted = memory.compact(memory_ids=[first["id"], third["id"]], archive_originals=True)
    assert compacted["created"] is True
    assert compacted["sourceCount"] == 2
    assert {item["id"] for item in memory.list_memories(status="archived")} >= {first["id"], third["id"]}

    restored_first = memory.restore_memory(first["id"])
    restored_third = memory.restore_memory(third["id"])
    assert restored_first and restored_third

    merged = memory.merge_memories([first["id"], third["id"]], archive_originals=True)
    assert merged["created"] is True
    assert merged["sourceCount"] == 2

    duplicate = memory.add_memory("Operador prefere memoria leve", metadata={"category": "preference"})
    maintenance = memory.run_maintenance()
    assert maintenance["ok"] is True
    assert maintenance["archivedDuplicates"] >= 1
    archived_ids = {item["id"] for item in memory.list_memories(status="archived")}
    assert second["id"] in archived_ids or duplicate["id"] in archived_ids


def test_memory_xml_accepts_attributes_and_strips_private_blocks():
    raw = 'Falando normal <salvar_memoria category="minecraft_world" importance="high">Base fica em X 10 Z 20</salvar_memoria>'

    saves = extract_memory_saves(raw)

    assert saves == [
        {
            "text": "Base fica em X 10 Z 20",
            "importance": "high",
            "category": "minecraft_world",
            "source": "model_self_save",
        }
    ]
    assert strip_memory_xml_tags(raw) == "Falando normal"


def test_memory_api_v2_lifecycle(tmp_path):
    app.state.memory = _memory(tmp_path)
    client = TestClient(app)

    create = client.post("/api/memory/rag", json={"text": "Operador quer memoria RAG leve", "category": "project", "importance": "high"})
    assert create.status_code == 200
    memory_id = create.json()["memory"]["id"]

    found = client.get("/api/memory/rag", params={"query": "RAG leve", "status": "active", "limit": 5})
    assert found.status_code == 200
    assert found.json()["memories"][0]["id"] == memory_id

    assert client.post(f"/api/memory/rag/{memory_id}/pin", json={"pinned": True}).status_code == 200
    assert client.post(f"/api/memory/rag/{memory_id}/archive").status_code == 200
    assert client.get("/api/memory/rag", params={"status": "archived"}).json()["memories"][0]["id"] == memory_id
    assert client.post(f"/api/memory/rag/{memory_id}/restore").status_code == 200

    assert client.delete(f"/api/memory/rag/{memory_id}").status_code == 200
    assert client.get("/api/memory/rag", params={"status": "deleted"}).json()["memories"][0]["id"] == memory_id
    assert client.delete(f"/api/memory/rag/{memory_id}", params={"hard": "true"}).status_code == 200


def test_memory_semantic_falls_back_to_fts_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HANA_MEMORY_SEMANTIC", "0")
    memory = _memory(tmp_path)

    status = memory.semantic_status()

    assert status["enabled"] is False
    assert status["mode"] == "fts"
