"""Acesso centralizado aos modelos salvos em ``stt_models``.

Irmao de ``catalog/tts_repository.py``: sem tabela de overrides (STT tambem
nao tem crawler, todo dado aqui e manual). So guarda os providers sem
endpoint de listagem proprio (Groq Whisper, Local) — OpenRouter fica de fora,
ver ``bd/stt.py``.

Segue a regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só LÊ e
ESCREVE dado. Quem cria a tabela é ``backend/bd/stt.py``; quem fala com a API
de cada STT é ``backend/providers/stt/``.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.bd.stt import criar_tabela_stt
from backend.paths import MEMORY_DB


class SttModelRepository:
    """Lê e escreve o catálogo de STT sem conhecer a comunicação com providers."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or MEMORY_DB).resolve()

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _write_connection(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Banco do catálogo não encontrado: {self.db_path}")
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        with closing(self._write_connection()) as connection:
            criar_tabela_stt(connection)

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data.get("model_id", ""),
            "provider": data.get("provider", ""),
            "label": data.get("label", ""),
            "language": data.get("language") or "",
            "supportsPrompt": bool(data.get("supports_prompt", 0)),
            "source": data.get("source", "manual"),
            "fetchedAt": data.get("fetched_at", ""),
            "observedAt": data.get("observed_at") or data.get("fetched_at", ""),
            "status": data.get("lifecycle_status", "active"),
        }

    def list_models(self, provider: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM stt_models"
        parameters: tuple[str, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            parameters = (provider.strip().lower(),)
        query += " ORDER BY provider, model_id"

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self._row_to_model(row) for row in rows]

    def get_model(self, provider: str, model_id: str) -> dict[str, Any] | None:
        clean_provider = provider.strip().lower()
        clean_model_id = model_id.strip()
        if not clean_provider or not clean_model_id:
            return None
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM stt_models WHERE provider = ? AND model_id = ?",
                    (clean_provider, clean_model_id),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return self._row_to_model(row) if row is not None else None

    def save_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "").strip().lower()
        model_id = str(payload.get("id") or payload.get("model_id") or "").strip()
        if not provider or not model_id:
            raise ValueError("provider_e_id_obrigatorios")

        self.ensure_schema()
        with closing(self._write_connection()) as connection:
            connection.execute(
                """
                INSERT INTO stt_models (
                  provider, model_id, label, language, supports_prompt,
                  source, fetched_at, lifecycle_status
                ) VALUES (?,?,?,?,?,'manual',datetime('now'),'active')
                ON CONFLICT(provider, model_id) DO UPDATE SET
                  label = excluded.label,
                  language = excluded.language,
                  supports_prompt = excluded.supports_prompt,
                  fetched_at = datetime('now')
                """,
                (
                    provider,
                    model_id,
                    str(payload.get("label") or model_id),
                    str(payload.get("language") or ""),
                    1 if payload.get("supportsPrompt") else 0,
                ),
            )
            connection.commit()
        salvo = self.get_model(provider, model_id)
        if salvo is None:  # pragma: no cover - só se o banco sumir no meio
            raise RuntimeError("modelo_nao_encontrado_apos_salvar")
        return salvo

    def delete_model(self, provider: str, model_id: str) -> bool:
        clean_provider = str(provider or "").strip().lower()
        clean_model_id = str(model_id or "").strip()
        if not clean_provider or not clean_model_id:
            return False
        with closing(self._write_connection()) as connection:
            cursor = connection.execute(
                "DELETE FROM stt_models WHERE provider = ? AND model_id = ?",
                (clean_provider, clean_model_id),
            )
            connection.commit()
        return cursor.rowcount > 0


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "t.db"
        db_path.touch()
        repo = SttModelRepository(db_path)
        repo.ensure_schema()

        assert repo.list_models() == []

        groq = repo.save_model({
            "provider": "groq_whisper", "id": "whisper-large-v3", "label": "Whisper Large v3",
            "language": "pt", "supportsPrompt": True,
        })
        assert groq["supportsPrompt"] is True

        assert len(repo.list_models()) == 1
        assert repo.get_model("groq_whisper", "whisper-large-v3") is not None

        repo.save_model({"provider": "groq_whisper", "id": "whisper-large-v3", "label": "Whisper v3 (atualizado)"})
        assert len(repo.list_models()) == 1
        assert repo.get_model("groq_whisper", "whisper-large-v3")["label"] == "Whisper v3 (atualizado)"

        assert repo.delete_model("groq_whisper", "whisper-large-v3") is True
        assert repo.delete_model("groq_whisper", "whisper-large-v3") is False
        assert len(repo.list_models()) == 0

    print("stt_repository: ok")


if __name__ == "__main__":
    _self_check()
