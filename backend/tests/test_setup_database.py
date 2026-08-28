from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from starlette.requests import Request

from backend.api.routers.setup import preview_public_defaults, restore_public_defaults
from backend.api.server import app
from backend.api.server import create_app
from backend.setup import database as setup_database
from backend.setup.database import (
    SETUP_MARKER_KEY,
    SetupDataError,
    initialize_database,
    installation_status,
    load_defaults,
    preview_defaults,
    restore_defaults,
)


def _scalar(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> object:
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(sql, parameters).fetchone()[0]


def _local_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/setup/defaults/llm",
            "raw_path": b"/api/setup/defaults/llm",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8042),
        }
    )


def test_clean_install_seeds_once_and_keeps_user_deletions(tmp_path: Path) -> None:
    database = tmp_path / "hana.sqlite3"
    preview = preview_defaults("all")

    first = initialize_database(database)
    assert first["changed"] is True
    assert installation_status(database)["status"] == "initialized"
    assert _scalar(database, "SELECT COUNT(*) FROM llm_models") == preview["catalogs"]["llm"]["count"]
    assert _scalar(database, "SELECT COUNT(*) FROM tts_models") == preview["catalogs"]["tts"]["count"]
    assert _scalar(database, "SELECT COUNT(*) FROM stt_models") == preview["catalogs"]["stt"]["count"]
    assert _scalar(database, "SELECT COUNT(*) FROM settings WHERE key = ?", (SETUP_MARKER_KEY,)) == 1

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "DELETE FROM llm_models WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'"
        )
        connection.execute(
            "INSERT INTO llm_models (provider, model_id, label) VALUES ('local', 'meu-modelo', 'Meu modelo')"
        )
        connection.commit()

    # Nem um diretório de defaults ausente importa depois que a marca existe:
    # a segunda execução encerra antes de abrir os JSONs.
    second = initialize_database(database, tmp_path / "defaults-ausentes")
    assert second["changed"] is False
    assert _scalar(
        database,
        "SELECT COUNT(*) FROM llm_models WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'",
    ) == 0
    assert _scalar(
        database,
        "SELECT COUNT(*) FROM llm_models WHERE provider = 'local' AND model_id = 'meu-modelo'",
    ) == 1

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM tts_models")
        connection.commit()
    third = initialize_database(database)
    assert third["changed"] is False
    assert _scalar(database, "SELECT COUNT(*) FROM tts_models") == 0


def test_existing_unmarked_database_is_never_modified(tmp_path: Path) -> None:
    database = tmp_path / "existing.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE private_data (value TEXT NOT NULL)")
        connection.execute("INSERT INTO private_data VALUES ('preservar')")
        connection.commit()

    result = initialize_database(database)

    assert result["status"] == "existing_unmarked"
    assert result["changed"] is False
    assert _scalar(database, "SELECT value FROM private_data") == "preservar"
    with closing(sqlite3.connect(database)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"private_data"}


def test_invalid_json_does_not_leave_partial_database(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source = Path(__file__).resolve().parents[1] / "setup" / "defaults"
    for name in ("llm_models.json", "tts_models.json", "stt_models.json"):
        (defaults / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")
    (defaults / "llm_models.json").write_text('{"catalog":"llm","version":1,"models":[', encoding="utf-8")
    database = tmp_path / "hana.sqlite3"

    with pytest.raises(SetupDataError):
        initialize_database(database, defaults)

    assert not database.exists()
    assert not list(tmp_path.glob("*.setup.tmp*"))


def test_failure_during_seed_never_replaces_the_main_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "hana.sqlite3"
    original = setup_database._upsert_catalog

    def fail_on_tts(
        connection: sqlite3.Connection,
        catalog: setup_database.CatalogName,
        models: list[dict[str, object]],
    ) -> None:
        if catalog == "tts":
            raise sqlite3.DatabaseError("falha controlada")
        original(connection, catalog, models)

    monkeypatch.setattr(setup_database, "_upsert_catalog", fail_on_tts)

    with pytest.raises(sqlite3.DatabaseError):
        initialize_database(database)

    assert not database.exists()
    assert not list(tmp_path.glob("*.setup.tmp*"))


def test_manual_restore_requires_confirmation_and_touches_only_catalog(tmp_path: Path) -> None:
    database = tmp_path / "hana.sqlite3"
    initialize_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "DELETE FROM llm_models WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'"
        )
        connection.execute(
            "INSERT INTO pinned (text, kind) VALUES ('não alterar', 'regra')"
        )
        connection.commit()

    preview = restore_defaults("llm", db_path=database)
    assert preview["database_changed"] is False
    assert _scalar(
        database,
        "SELECT COUNT(*) FROM llm_models WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'",
    ) == 0

    restored = restore_defaults("llm", confirm=True, db_path=database)
    assert restored["database_changed"] is True
    assert _scalar(
        database,
        "SELECT COUNT(*) FROM llm_models WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'",
    ) == 1
    assert _scalar(database, "SELECT text FROM pinned") == "não alterar"


def test_public_defaults_exclude_dynamic_and_fake_models() -> None:
    defaults = load_defaults()
    llm_keys = {(item["provider"], item["model_id"]) for item in defaults["llm"]}
    stt_providers = {item["provider"] for item in defaults["stt"]}

    assert all(provider != "openrouter" for provider, _ in llm_keys)
    assert "openrouter" not in stt_providers
    assert all("fake" not in model_id.lower() for _, model_id in llm_keys)


def test_qwen_defaults_mark_documented_streaming_with_tools_models() -> None:
    """Mantém no catálogo só combinações confirmadas pela documentação oficial."""

    documented = {
        "deepseek-v3.2",
        "deepseek-v4-flash",
        "deepseek-v4-flash-0731",
        "deepseek-v4-flash-us",
        "deepseek-v4-pro",
        "deepseek-v4-pro-us",
        "qwen-flash",
        "qwen-plus",
        "qwen3.5-flash",
        "qwen3.5-plus",
        "qwen3.6-35b-a3b",
        "qwen3.6-flash",
        "qwen3.6-max-preview",
        "qwen3.6-plus",
        "qwen3.7-max",
        "qwen3.7-plus",
    }
    qwen_models = {
        item["model_id"]: item
        for item in load_defaults()["llm"]
        if item["provider"] == "qwen"
    }

    assert all(qwen_models[model_id]["supports_streaming_tools"] == 1 for model_id in documented)
    assert qwen_models["qwen3.7-flash"]["supports_streaming_tools"] is None
    assert qwen_models["qwen3.8-flash"]["label"] == "Qwen3.8 Flash — Singapura"
    assert qwen_models["qwen3.8-flash"]["supports_vision"] == 1
    assert "disponível em Singapura" in qwen_models["qwen3.8-flash"]["description"]
    assert qwen_models["qwen3.8-max"]["supports_streaming_tools"] is None


def test_catalogo_qwen_guarda_regioes_e_preserva_modelo_customizado(tmp_path: Path) -> None:
    """A etiqueta regional chega ao banco sem mudar o identificador técnico."""

    database = tmp_path / "hana.sqlite3"
    initialize_database(database)

    with closing(sqlite3.connect(database)) as connection:
        flash = connection.execute(
            "SELECT label, capabilities FROM llm_models WHERE provider = 'qwen' AND model_id = 'qwen3.8-flash'"
        ).fetchone()
        assert flash == (
            "Qwen3.8 Flash — Singapura",
            '{"availableRegions": ["singapore"], "deploymentScope": "international"}',
        )
        connection.execute(
            "UPDATE llm_models SET label = 'Minha etiqueta', custom = 1, source = 'manual' "
            "WHERE provider = 'qwen' AND model_id = 'qwen3.8-flash'"
        )
        connection.commit()

    from backend.bd import preparar_catalogos

    preparar_catalogos(database)
    assert _scalar(
        database,
        "SELECT label FROM llm_models WHERE provider = 'qwen' AND model_id = 'qwen3.8-flash'",
    ) == "Minha etiqueta"


def test_setup_recovery_routes_are_documented_in_swagger() -> None:
    schema = app.openapi()

    assert "/api/setup/defaults/{catalog}" in schema["paths"]
    assert "/api/setup/defaults/{catalog}/restore" in schema["paths"]
    restore = schema["paths"]["/api/setup/defaults/{catalog}/restore"]["post"]
    assert restore["tags"] == ["Setup e recuperação"]
    assert any(parameter["name"] == "confirm" for parameter in restore["parameters"])

    preview = preview_public_defaults(_local_request(), "llm")
    guarded_restore = restore_public_defaults(_local_request(), "llm", confirm=False)
    assert preview["database_changed"] is False
    assert guarded_restore["database_changed"] is False


def test_normal_hana_startup_does_not_open_default_jsons(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.read_text

    def guarded_read(path: Path, *args: object, **kwargs: object) -> str:
        if path.parent.name == "defaults" and path.name.endswith("_models.json"):
            raise AssertionError("a inicialização normal tentou abrir um JSON de setup")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    # Com a instalação já marcada, o startup não pode tentar importar nada.
    # O stub isola o teste de máquinas cujo banco real ainda não tem marca.
    import backend.api.server as api_server

    chamadas: list[object] = []

    def instalacao_ja_concluida(*args: object, **kwargs: object) -> dict[str, str]:
        chamadas.append(args)
        return {"status": "initialized", "changed": False}

    monkeypatch.setattr(api_server, "garantir_instalacao_inicial", instalacao_ja_concluida)

    created = create_app()
    assert created.title == "Hana Agent OSS API"
    assert len(chamadas) == 1
