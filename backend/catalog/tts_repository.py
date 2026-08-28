"""Acesso centralizado aos modelos/vozes salvos em ``tts_models``.

Irmao de ``catalog/repository.py`` (LlmModelRepository), mas mais simples:
nao existe tabela de overrides porque TTS nao tem crawler — todo dado aqui e
manual (DECISOES_CATALOGO_FONTES.md secao 12), entao nao ha "observado vs
corrigido" pra separar.

Segue a regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só LÊ e
ESCREVE dado. Quem cria a tabela é ``backend/bd/tts.py``; quem fala com a API
de cada TTS é ``backend/providers/tts/``.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.bd.tts import criar_tabela_tts
from backend.paths import MEMORY_DB


class TtsModelRepository:
    """Lê e escreve o catálogo de TTS sem conhecer a comunicação com providers."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or MEMORY_DB).resolve()

    def _connect(self) -> sqlite3.Connection:
        """Abre o banco em modo somente leitura para proteger o catálogo."""
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
        """Garante a tabela chamando quem é dono de criá-la (``bd/tts.py``)."""
        with closing(self._write_connection()) as connection:
            criar_tabela_tts(connection)

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data.get("model_id", ""),
            "provider": data.get("provider", ""),
            "label": data.get("label", ""),
            "language": data.get("language") or "",
            "supportsStreaming": bool(data.get("supports_streaming", 0)),
            "supportsPitch": bool(data.get("supports_pitch", 0)),
            "supportsStability": bool(data.get("supports_stability", 0)),
            "supportsSimilarity": bool(data.get("supports_similarity", 0)),
            "supportsStyle": bool(data.get("supports_style", 0)),
            "supportsSpeakerBoost": bool(data.get("supports_speaker_boost", 0)),
            "source": data.get("source", "manual"),
            "fetchedAt": data.get("fetched_at", ""),
            "observedAt": data.get("observed_at") or data.get("fetched_at", ""),
            "status": data.get("lifecycle_status", "active"),
        }

    def list_models(self, provider: str | None = None) -> list[dict[str, Any]]:
        """Lista vozes/modelos do banco, opcionalmente filtrando por provider."""
        query = "SELECT * FROM tts_models"
        parameters: tuple[str, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            parameters = (provider.strip().lower(),)
        query += " ORDER BY provider, model_id"

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.OperationalError:
            # Tabela ainda nao existe (banco novo, seed nunca rodou).
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
                    "SELECT * FROM tts_models WHERE provider = ? AND model_id = ?",
                    (clean_provider, clean_model_id),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return self._row_to_model(row) if row is not None else None

    def save_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Cria ou atualiza uma voz/modelo. Devolve como ficou salvo."""
        provider = str(payload.get("provider") or "").strip().lower()
        model_id = str(payload.get("id") or payload.get("model_id") or "").strip()
        if not provider or not model_id:
            raise ValueError("provider_e_id_obrigatorios")

        def flag(key: str) -> int:
            return 1 if payload.get(key) else 0

        self.ensure_schema()
        with closing(self._write_connection()) as connection:
            connection.execute(
                """
                INSERT INTO tts_models (
                  provider, model_id, label, language, supports_streaming, supports_pitch,
                  supports_stability, supports_similarity, supports_style, supports_speaker_boost,
                  source, fetched_at, lifecycle_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,'manual',datetime('now'),'active')
                ON CONFLICT(provider, model_id) DO UPDATE SET
                  label = excluded.label,
                  language = excluded.language,
                  supports_streaming = excluded.supports_streaming,
                  supports_pitch = excluded.supports_pitch,
                  supports_stability = excluded.supports_stability,
                  supports_similarity = excluded.supports_similarity,
                  supports_style = excluded.supports_style,
                  supports_speaker_boost = excluded.supports_speaker_boost,
                  fetched_at = datetime('now')
                """,
                (
                    provider,
                    model_id,
                    str(payload.get("label") or model_id),
                    str(payload.get("language") or ""),
                    flag("supportsStreaming"),
                    flag("supportsPitch"),
                    flag("supportsStability"),
                    flag("supportsSimilarity"),
                    flag("supportsStyle"),
                    flag("supportsSpeakerBoost"),
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
                "DELETE FROM tts_models WHERE provider = ? AND model_id = ?",
                (clean_provider, clean_model_id),
            )
            connection.commit()
        return cursor.rowcount > 0


def _self_check() -> None:
    """Trava o que ja foi bug uma vez: tabela orfa (bd/tts.py nunca chamado)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "t.db"
        db_path.touch()  # _write_connection() recusa migrar caminho inexistente de proposito
        repo = TtsModelRepository(db_path)
        repo.ensure_schema()

        assert repo.list_models() == []

        edge = repo.save_model({
            "provider": "edge", "id": "pt-BR-FranciscaNeural", "label": "Francisca",
            "language": "pt-BR", "supportsPitch": True,
        })
        assert edge["supportsPitch"] is True
        assert edge["supportsStability"] is False

        eleven = repo.save_model({
            "provider": "elevenlabs", "id": "eleven_flash_v2_5", "label": "Flash v2.5",
            "supportsStability": True, "supportsSimilarity": True, "supportsStyle": True,
            "supportsSpeakerBoost": True,
        })
        assert eleven["supportsStability"] is True
        assert eleven["supportsPitch"] is False

        assert len(repo.list_models()) == 2
        assert len(repo.list_models("edge")) == 1
        assert repo.get_model("elevenlabs", "eleven_flash_v2_5") is not None

        # Upsert: salvar de novo com o mesmo (provider, id) atualiza, nao duplica.
        repo.save_model({"provider": "edge", "id": "pt-BR-FranciscaNeural", "label": "Francisca Neural"})
        assert len(repo.list_models()) == 2
        assert repo.get_model("edge", "pt-BR-FranciscaNeural")["label"] == "Francisca Neural"

        assert repo.delete_model("edge", "pt-BR-FranciscaNeural") is True
        assert repo.delete_model("edge", "pt-BR-FranciscaNeural") is False
        assert len(repo.list_models()) == 1

    print("tts_repository: ok")


if __name__ == "__main__":
    _self_check()
