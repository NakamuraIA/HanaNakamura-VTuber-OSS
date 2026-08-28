"""Cria o banco inicial e restaura catálogos públicos sob confirmação.

O módulo usa somente a biblioteca padrão ao carregar e validar os JSONs. Isso
permite consultar o estado da instalação antes mesmo de criar o ambiente
virtual. As dependências da Hana só são importadas dentro da criação efetiva do
banco, depois que o instalador já terminou o ``pip install``.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Literal, Sequence

from backend.bd.llm import MODEL_DOMAINS, normalizar_model_domain
from backend.paths import MEMORY_DB

CatalogName = Literal["llm", "tts", "stt"]

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"
SETUP_MARKER_KEY = "setup.initial_catalog.v1"

_CATALOG_FILES: dict[CatalogName, str] = {
    "llm": "llm_models.json",
    "tts": "tts_models.json",
    "stt": "stt_models.json",
}

_TABLES: dict[CatalogName, str] = {
    "llm": "llm_models",
    "tts": "tts_models",
    "stt": "stt_models",
}

_FIELDS: dict[CatalogName, tuple[str, ...]] = {
    "llm": (
        "provider",
        "model_id",
        "label",
        "model_domain",
        "supports_vision",
        "supports_video",
        "supports_tools",
        "supports_streaming",
        "supports_streaming_tools",
        "supports_reasoning",
        "reasoning_modes",
        "supports_structured_output",
        "supports_documents",
        "supports_native_search",
        "max_input_tokens",
        "max_output_tokens",
        "free",
        "pricing",
        "input_modalities",
        "output_modalities",
        "supported_parameters",
        "capabilities",
        "description",
        "source",
        "observed_at",
        "lifecycle_status",
    ),
    "tts": (
        "provider",
        "model_id",
        "label",
        "language",
        "supports_streaming",
        "supports_pitch",
        "supports_stability",
        "supports_similarity",
        "supports_style",
        "supports_speaker_boost",
        "source",
        "observed_at",
        "lifecycle_status",
    ),
    "stt": (
        "provider",
        "model_id",
        "label",
        "language",
        "supports_prompt",
        "source",
        "observed_at",
        "lifecycle_status",
    ),
}

_BOOLEAN_FIELDS = {
    "supports_vision",
    "supports_video",
    "supports_tools",
    "supports_streaming",
    "supports_streaming_tools",
    "supports_reasoning",
    "supports_structured_output",
    "supports_documents",
    "supports_native_search",
    "free",
    "supports_pitch",
    "supports_stability",
    "supports_similarity",
    "supports_style",
    "supports_speaker_boost",
    "supports_prompt",
}
_POSITIVE_INTEGER_FIELDS = {"max_input_tokens", "max_output_tokens"}
_JSON_FIELDS = {
    "reasoning_modes",
    "pricing",
    "input_modalities",
    "output_modalities",
    "supported_parameters",
    "capabilities",
}


class SetupDataError(ValueError):
    """Indica que um JSON público não respeita o contrato do catálogo."""


def _db_path(value: str | Path | None) -> Path:
    return Path(value or MEMORY_DB).resolve()


def installation_status(db_path: str | Path | None = None) -> dict[str, Any]:
    """Consulta a marca sem escrever ou criar o banco."""

    path = _db_path(db_path)
    if not path.exists():
        return {"status": "not_installed", "database_exists": False, "marker_exists": False}

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?",
                (SETUP_MARKER_KEY,),
            ).fetchone()
    except sqlite3.DatabaseError:
        row = None

    if row is None:
        return {"status": "existing_unmarked", "database_exists": True, "marker_exists": False}
    return {"status": "initialized", "database_exists": True, "marker_exists": True}


def _validate_model(catalog: CatalogName, raw: Any, position: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SetupDataError(f"{catalog}: models[{position}] precisa ser um objeto JSON")

    unknown = sorted(set(raw) - set(_FIELDS[catalog]))
    if unknown:
        raise SetupDataError(f"{catalog}: campos desconhecidos em models[{position}]: {unknown}")

    provider = str(raw.get("provider") or "").strip().lower()
    model_id = str(raw.get("model_id") or "").strip()
    label = str(raw.get("label") or "").strip()
    if not provider or not model_id or not label:
        raise SetupDataError(
            f"{catalog}: provider, model_id e label são obrigatórios em models[{position}]"
        )
    if provider == "openrouter":
        raise SetupDataError(
            f"{catalog}: OpenRouter usa catálogo dinâmico e não pode entrar no JSON público"
        )

    model: dict[str, Any] = {}
    for field in _FIELDS[catalog]:
        value = raw.get(field)
        if field in _BOOLEAN_FIELDS:
            if value is not None and not isinstance(value, bool):
                raise SetupDataError(f"{catalog}: {field} precisa ser true, false ou null")
            model[field] = None if value is None else int(value)
        elif field in _POSITIVE_INTEGER_FIELDS:
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
                raise SetupDataError(f"{catalog}: {field} precisa ser inteiro positivo ou null")
            model[field] = value
        elif field in _JSON_FIELDS:
            if value is not None and not isinstance(value, (list, dict)):
                raise SetupDataError(f"{catalog}: {field} precisa ser lista, objeto ou null")
            model[field] = None if value is None else json.dumps(value, ensure_ascii=False)
        else:
            if value is not None and not isinstance(value, str):
                raise SetupDataError(f"{catalog}: {field} precisa ser texto ou null")
            model[field] = value

    model.update(
        provider=provider,
        model_id=model_id,
        label=label,
        source="public_default",
        observed_at=None,
        lifecycle_status="active",
    )
    # Domínio explícito no JSON (opcional); ausente/vazio = chat. Valor
    # desconhecido é erro de contrato, não chute silencioso.
    dominio_bruto = str(raw.get("model_domain") or "").strip().lower()
    if dominio_bruto and dominio_bruto not in MODEL_DOMAINS:
        raise SetupDataError(
            f"{catalog}: model_domain inválido em models[{position}]: {dominio_bruto!r}"
        )
    model["model_domain"] = normalizar_model_domain(dominio_bruto)
    return model


def load_defaults(
    defaults_dir: str | Path | None = None,
    catalogs: Sequence[CatalogName] = ("llm", "tts", "stt"),
) -> dict[CatalogName, list[dict[str, Any]]]:
    """Lê e valida todos os arquivos antes de qualquer escrita no banco."""

    root = Path(defaults_dir or DEFAULTS_DIR).resolve()
    loaded: dict[CatalogName, list[dict[str, Any]]] = {}
    for catalog in catalogs:
        path = root / _CATALOG_FILES[catalog]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SetupDataError(f"Arquivo público ausente: {path.name}") from exc
        except json.JSONDecodeError as exc:
            raise SetupDataError(f"JSON inválido em {path.name}: linha {exc.lineno}") from exc

        if not isinstance(payload, dict):
            raise SetupDataError(f"{path.name}: a raiz precisa ser um objeto JSON")
        if payload.get("catalog") != catalog or payload.get("version") != 1:
            raise SetupDataError(f"{path.name}: catalog ou version inválido")
        raw_models = payload.get("models")
        if not isinstance(raw_models, list) or not raw_models:
            raise SetupDataError(f"{path.name}: models precisa ser uma lista não vazia")

        models = [_validate_model(catalog, raw, index) for index, raw in enumerate(raw_models)]
        keys = [(model["provider"], model["model_id"]) for model in models]
        if len(keys) != len(set(keys)):
            raise SetupDataError(f"{path.name}: existe provider/model_id duplicado")
        loaded[catalog] = models
    return loaded


def preview_defaults(
    catalog: CatalogName | Literal["all"] = "all",
    defaults_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Mostra exatamente o que seria importado, sem abrir o banco."""

    selected: tuple[CatalogName, ...] = ("llm", "tts", "stt") if catalog == "all" else (catalog,)
    defaults = load_defaults(defaults_dir, selected)
    return {
        "catalogs": {
            name: {
                "count": len(models),
                "models": [
                    {"provider": item["provider"], "model_id": item["model_id"], "label": item["label"]}
                    for item in models
                ],
            }
            for name, models in defaults.items()
        },
        "total": sum(len(models) for models in defaults.values()),
        "database_changed": False,
        "confirmation_required": True,
    }


def _create_schemas(db_path: Path, events_path: Path) -> None:
    """Chama os donos atuais de cada schema no banco novo temporário."""

    from backend.bd import preparar_catalogos
    from backend.memory.core import HanaMemory
    from backend.memory.storage import RuntimeStore
    from backend.memory.store import MemoryStore

    MemoryStore(db_path=db_path, events_path=events_path)
    HanaMemory(str(db_path))
    RuntimeStore(db_path)
    preparar_catalogos(db_path)


def _upsert_catalog(
    connection: sqlite3.Connection,
    catalog: CatalogName,
    models: Sequence[dict[str, Any]],
) -> None:
    fields = _FIELDS[catalog]
    placeholders = ",".join("?" for _ in fields)
    updates = ",".join(
        f"{field}=excluded.{field}" for field in fields if field not in {"provider", "model_id"}
    )
    sql = (
        f"INSERT INTO {_TABLES[catalog]} ({','.join(fields)}) VALUES ({placeholders}) "
        f"ON CONFLICT(provider, model_id) DO UPDATE SET {updates}"
    )
    connection.executemany(sql, [tuple(model[field] for field in fields) for model in models])


def _insert_missing_catalog(
    connection: sqlite3.Connection,
    catalog: CatalogName,
    models: Sequence[dict[str, Any]],
) -> None:
    """Insere somente modelos públicos ausentes; linhas existentes ficam intocadas.

    Usado na instalação automática de banco legado sem marca: um modelo público
    que a dona já personalizou (mesmo provider/model_id) não pode ser
    sobrescrito por carga nenhuma. A restauração manual confirmada continua
    usando ``_upsert_catalog``, porque ali a substituição é explícita.
    """

    fields = _FIELDS[catalog]
    placeholders = ",".join("?" for _ in fields)
    sql = f"INSERT OR IGNORE INTO {_TABLES[catalog]} ({','.join(fields)}) VALUES ({placeholders})"
    connection.executemany(sql, [tuple(model[field] for field in fields) for model in models])


def _write_defaults(
    db_path: Path,
    defaults: dict[CatalogName, list[dict[str, Any]]],
    *,
    write_marker: bool,
    update_existing: bool = True,
) -> None:
    """Grava todos os catálogos selecionados numa única transação.

    ``update_existing=True`` (padrão) sobrescreve linhas conflitantes via
    upsert — comportamento da restauração manual confirmada. Com
    ``update_existing=False``, linhas existentes são preservadas exatamente
    como estão e apenas modelos públicos ausentes são inseridos.
    """

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for catalog, models in defaults.items():
                if update_existing:
                    _upsert_catalog(connection, catalog, models)
                else:
                    _insert_missing_catalog(connection, catalog, models)
            if write_marker:
                marker = json.dumps(
                    {"version": 1, "catalogs": list(defaults)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                connection.execute(
                    """
                    INSERT INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                      value_json = excluded.value_json,
                      updated_at = excluded.updated_at
                    """,
                    (SETUP_MARKER_KEY, marker),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _cleanup_setup_files(db_path: Path, events_path: Path) -> None:
    for path in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        events_path,
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def initialize_database(
    db_path: str | Path | None = None,
    defaults_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Cria uma instalação nova; protege qualquer banco que já exista."""

    path = _db_path(db_path)
    status = installation_status(path)
    if status["status"] == "initialized":
        return {**status, "changed": False, "message": "A instalação inicial já foi concluída."}
    if status["status"] == "existing_unmarked":
        return {
            **status,
            "changed": False,
            "message": "Banco existente protegido; nenhuma carga automática foi executada.",
        }

    defaults = load_defaults(defaults_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_db = path.with_name(f".{path.name}.setup.tmp")
    temporary_events = path.with_name(f".{path.stem}.setup-events.jsonl")
    _cleanup_setup_files(temporary_db, temporary_events)
    try:
        _create_schemas(temporary_db, temporary_events)
        _write_defaults(temporary_db, defaults, write_marker=True)
        with closing(sqlite3.connect(temporary_db)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
        if path.exists():
            raise FileExistsError("O banco principal apareceu durante a instalação; ele foi preservado.")
        os.replace(temporary_db, path)
        # O catálogo recém-gravado também passa pelas migrações idempotentes
        # (por exemplo, metadados regionais de modelos já conhecidos).
        from backend.bd import preparar_catalogos

        preparar_catalogos(path)
    except Exception:
        _cleanup_setup_files(temporary_db, temporary_events)
        raise
    _cleanup_setup_files(temporary_db, temporary_events)
    return {
        "status": "initialized",
        "changed": True,
        "database_exists": True,
        "marker_exists": True,
        "counts": {name: len(models) for name, models in defaults.items()},
        "message": "Banco e catálogos públicos criados com sucesso.",
    }


def garantir_instalacao_inicial(
    db_path: str | Path | None = None,
    defaults_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Garante que o banco principal tenha a instalação inicial concluída.

    Chamada no startup do backend para que subir direto pelo Uvicorn produza o
    mesmo estado do ``Hana-First-Run.cmd``. A decisão usa SEMPRE a marca
    persistente em ``settings`` — nunca a existência do arquivo nem tabela
    vazia — porque os módulos de runtime podem criar o arquivo antes do setup
    rodar.

    Comportamento por estado da marca:
    - ``initialized``: não faz nada. Não reimporta catálogo, não restaura
      modelo removido pela dona e não mexe em modelo personalizado.
    - ``not_installed``: banco novo -> fluxo público completo
      (``initialize_database``, atômico via arquivo temporário).
    - ``existing_unmarked``: banco que existe sem marca (ex.: criado por um
      startup antigo interrompido, ou banco legado) -> cria a tabela
      ``settings`` se faltar, semeia os catálogos públicos NA PRÓPRIA base
      numa única transação e grava a marca só no fim. Nada existente é
      alterado: linhas já presentes ficam exatamente como estão (mesmo um
      modelo público editado pela dona) e apenas modelos ausentes entram.

    Se algo falhar, a exceção sobe sem marca gravada (transação única com
    rollback): o próximo start tenta de novo com segurança.
    """

    path = _db_path(db_path)
    status_atual = installation_status(path)
    status = status_atual["status"]
    if status == "initialized":
        return {
            **status_atual,
            "changed": False,
            "message": "A instalação inicial já foi concluída.",
        }

    if status == "not_installed":
        result = initialize_database(path, defaults_dir)
        if result.get("status") != "initialized":
            raise RuntimeError(f"Instalação inicial não concluída: {result.get('message')}")
        return result

    # Banco existente sem marca: conclui o setup pendente na própria base.
    # Diferente do banco novo, aqui não há arquivo temporário nem replace.
    # Nada existente é alterado: a tabela settings é criada só se faltar e os
    # catálogos usam "inserir se não existir" — linhas já presentes (incluindo
    # modelos públicos editados pela dona) ficam exatamente como estão.
    defaults = load_defaults(defaults_dir)
    _ensure_settings_table(path)
    for catalog in defaults:
        _ensure_catalog_schema(path, catalog)
    _write_defaults(path, defaults, write_marker=True, update_existing=False)
    return {
        "status": "initialized",
        "changed": True,
        "database_exists": True,
        "marker_exists": True,
        "counts": {name: len(models) for name, models in defaults.items()},
        "message": "Catálogos públicos carregados no banco existente; instalação concluída.",
    }


def _ensure_settings_table(db_path: Path) -> None:
    """Cria a tabela settings quando o banco legado não a tem.

    Mesma definição dos donos dela (``memory/core.py`` e ``memory/store.py``),
    para que gravar a marca nunca falhe por ausência de tabela em banco antigo.
    ``CREATE TABLE IF NOT EXISTS``: nenhuma tabela ou linha existente é tocada.
    """

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key        TEXT PRIMARY KEY,
              value_json TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.commit()


def _ensure_catalog_schema(db_path: Path, catalog: CatalogName) -> None:
    from backend.bd.llm import criar_tabela_llm
    from backend.bd.stt import criar_tabela_stt
    from backend.bd.tts import criar_tabela_tts

    creators = {"llm": criar_tabela_llm, "tts": criar_tabela_tts, "stt": criar_tabela_stt}
    with closing(sqlite3.connect(db_path)) as connection:
        creators[catalog](connection)


def restore_defaults(
    catalog: CatalogName | Literal["all"],
    *,
    confirm: bool = False,
    db_path: str | Path | None = None,
    defaults_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Restaura somente catálogos confirmados e nunca remove linhas extras."""

    preview = preview_defaults(catalog, defaults_dir)
    if not confirm:
        return preview

    path = _db_path(db_path)
    if not path.exists():
        raise FileNotFoundError("Banco principal não encontrado; execute a primeira instalação.")
    selected: tuple[CatalogName, ...] = ("llm", "tts", "stt") if catalog == "all" else (catalog,)
    defaults = load_defaults(defaults_dir, selected)
    for name in selected:
        _ensure_catalog_schema(path, name)
    _write_defaults(path, defaults, write_marker=False)
    return {
        **preview,
        "database_changed": True,
        "confirmation_required": False,
        "restored": {name: len(models) for name, models in defaults.items()},
    }


def _print_result(result: dict[str, Any], *, quiet: bool = False) -> None:
    if not quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Primeira instalação e recuperação dos catálogos da Hana.")
    commands = parser.add_subparsers(dest="command", required=True)

    status_parser = commands.add_parser("status", help="Consultar sem alterar o banco.")
    status_parser.add_argument("--quiet", action="store_true")
    commands.add_parser("initialize", help="Criar uma instalação nova.")
    restore_parser = commands.add_parser("restore", help="Prévia ou restauração manual de modelos.")
    restore_parser.add_argument("catalog", choices=("llm", "tts", "stt", "all"))
    restore_parser.add_argument("--confirm", action="store_true", help="Autoriza a escrita no banco real.")
    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            result = installation_status()
            _print_result(result, quiet=args.quiet)
            return {"initialized": 0, "not_installed": 2, "existing_unmarked": 3}[result["status"]]
        if args.command == "initialize":
            result = initialize_database()
            _print_result(result)
            return 3 if result["status"] == "existing_unmarked" else 0
        result = restore_defaults(args.catalog, confirm=args.confirm)
        _print_result(result)
        return 0
    except (OSError, sqlite3.DatabaseError, SetupDataError) as exc:
        print(f"Erro: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
