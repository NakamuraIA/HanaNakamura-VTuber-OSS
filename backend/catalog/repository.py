"""Acesso centralizado aos modelos salvos em ``llm_models``.

Segue a regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só LÊ e
ESCREVE dado. Quem cria a tabela é ``backend/bd/llm.py``; quem fala com a API
do provider é ``backend/providers/``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.bd.llm import criar_tabela_llm, normalizar_model_domain
from backend.paths import MEMORY_DB


class LlmModelRepository:
    """Lê e prepara dados do catálogo sem conhecer a comunicação com providers."""

    _OVERRIDABLE_FIELDS = frozenset(
        {
            "label",
            "supportsVision",
            "supportsVideo",
            "supportsTools",
            "supportsStreaming",
            "supportsStreamingTools",
            "supportsReasoning",
            "reasoningModes",
            "supportsStructuredOutput",
            "supportsNativeSearch",
            "supportsDocuments",
            "maxInputTokens",
            "maxOutputTokens",
            "free",
            "pricing",
            "inputModalities",
            "outputModalities",
            "supportedParameters",
            "description",
        }
    )

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Guarda o caminho do banco; nenhuma escrita é feita por esta classe."""
        self.db_path = Path(db_path or MEMORY_DB).resolve()

    def _connect(self) -> sqlite3.Connection:
        """Abre o banco em modo somente leitura para proteger o catálogo."""
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _write_connection(self) -> sqlite3.Connection:
        """Abre escrita somente para migrações e correções manuais do catálogo."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Banco do catálogo não encontrado: {self.db_path}")
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        """Garante a tabela chamando quem é dono de criá-la (``bd/llm.py``)."""
        with closing(self._write_connection()) as connection:
            criar_tabela_llm(connection)

    @staticmethod
    def _decode_json(value: Any) -> Any:
        """Converte uma coluna JSON; conserva o valor original se estiver inválido."""
        if not value:
            return None
        try:
            return json.loads(value) if isinstance(value, str) else value
        except (json.JSONDecodeError, TypeError):
            return value

    @classmethod
    def _row_to_model(cls, row: sqlite3.Row) -> dict[str, Any]:
        """Converte uma linha SQLite para o formato de modelo usado pela API."""
        data = dict(row)
        model: dict[str, Any] = {
            "id": data.get("model_id", ""),
            "provider": data.get("provider", ""),
            "label": data.get("label", ""),
            "modelDomain": str(data.get("model_domain") or "chat"),
            "supportsVision": bool(data.get("supports_vision", 0)),
            "supportsTools": bool(data.get("supports_tools", 0)),
            "supportsNativeSearch": bool(data.get("supports_native_search", 0)),
            "supportsDocuments": bool(data.get("supports_documents", 0)),
            "maxInputTokens": data.get("max_input_tokens") or None,
            "maxOutputTokens": data.get("max_output_tokens") or None,
            "free": bool(data.get("free", 0)),
            "custom": bool(data.get("custom", 0)),
            "fetched_at": data.get("fetched_at", ""),
            "source": data.get("source", "legacy"),
            "observedAt": data.get("observed_at") or data.get("fetched_at", ""),
            "status": data.get("lifecycle_status", "active"),
            "missingSuccessCount": data.get("missing_success_count", 0),
        }

        # Estas colunas guardam listas ou objetos JSON no banco.
        json_columns = {
            "pricing": "pricing",
            "inputModalities": "input_modalities",
            "outputModalities": "output_modalities",
            "supportedParameters": "supported_parameters",
            "reasoningModes": "reasoning_modes",
        }
        for output_key, column in json_columns.items():
            decoded = cls._decode_json(data.get(column))
            if decoded is not None:
                model[output_key] = decoded

        # Capacidades futuras podem existir no JSON sem quebrar este leitor.
        capabilities = cls._decode_json(data.get("capabilities"))
        if isinstance(capabilities, dict):
            for key, value in capabilities.items():
                model.setdefault(key, value)

        # Colunas dedicadas vencem JSON legado quando as duas formas coexistem.
        capability_columns = {
            "supportsVideo": "supports_video",
            "supportsStreaming": "supports_streaming",
            "supportsStreamingTools": "supports_streaming_tools",
            "supportsReasoning": "supports_reasoning",
            "supportsStructuredOutput": "supports_structured_output",
        }
        for output_key, column in capability_columns.items():
            if data.get(column) is not None:
                model[output_key] = bool(data[column])

        field_sources = cls._decode_json(data.get("field_sources"))
        if isinstance(field_sources, dict):
            model["fieldSources"] = field_sources
        return model

    @classmethod
    def _apply_overrides(cls, model: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Retorna o modelo efetivo sem apagar o conhecimento observado."""
        if not overrides:
            return model
        effective = dict(model)
        effective.update(overrides)
        effective["manualOverrides"] = sorted(overrides)
        return effective

    def _overrides_for(self, provider: str, model_id: str) -> dict[str, Any]:
        """Lê correções manuais de um modelo sem consultar nenhuma API externa."""
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT field_name, value_json
                    FROM model_overrides
                    WHERE provider = ? AND model_id = ?
                    """,
                    (provider, model_id),
                ).fetchall()
        except sqlite3.OperationalError:
            # A tabela ainda não existe até a migração ser aplicada.
            return {}
        return {
            str(row["field_name"]): self._decode_json(row["value_json"])
            for row in rows
        }

    def set_override(self, provider: str, model_id: str, field_name: str, value: Any) -> None:
        """Salva uma correção manual de um campo permitido do catálogo."""
        clean_provider = provider.strip().lower()
        clean_model_id = model_id.strip()
        if not clean_provider or not clean_model_id:
            raise ValueError("Provider e identificador do modelo são obrigatórios")
        if field_name not in self._OVERRIDABLE_FIELDS:
            raise ValueError(f"Campo não pode receber correção manual: {field_name}")
        try:
            value_json = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Valor inválido para correção manual: {field_name}") from exc

        with closing(self._write_connection()) as connection:
            connection.execute(
                """
                INSERT INTO model_overrides (provider, model_id, field_name, value_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider, model_id, field_name) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = datetime('now')
                """,
                (clean_provider, clean_model_id, field_name, value_json),
            )
            connection.commit()

    def remove_override(self, provider: str, model_id: str, field_name: str) -> bool:
        """Remove uma correção para voltar ao último valor observado."""
        with closing(self._write_connection()) as connection:
            cursor = connection.execute(
                """
                DELETE FROM model_overrides
                WHERE provider = ? AND model_id = ? AND field_name = ?
                """,
                (provider.strip().lower(), model_id.strip(), field_name),
            )
            connection.commit()
        return cursor.rowcount > 0

    def list_models(self, provider: str | None = None) -> list[dict[str, Any]]:
        """Lista modelos do banco, opcionalmente filtrando por provider."""
        query = "SELECT * FROM llm_models"
        parameters: tuple[str, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            parameters = (provider.strip().lower(),)
        query += " ORDER BY provider, model_id"

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            self._apply_overrides(
                self._row_to_model(row),
                self._overrides_for(str(row["provider"]), str(row["model_id"])),
            )
            for row in rows
        ]

    def get_model(self, provider: str, model_id: str) -> dict[str, Any] | None:
        """Busca um modelo exato por provider e identificador."""
        clean_provider = provider.strip().lower()
        clean_model_id = model_id.strip()
        if not clean_provider or not clean_model_id:
            return None

        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM llm_models WHERE provider = ? AND model_id = ?",
                (clean_provider, clean_model_id),
            ).fetchone()
        if row is None:
            return None
        model = self._row_to_model(row)
        return self._apply_overrides(model, self._overrides_for(clean_provider, clean_model_id))

    def find_provider_for_model(self, model_id: str) -> str:
        """Encontra o provider local sem manter uma lista de providers no código."""

        clean_model_id = model_id.strip()
        if not clean_model_id:
            return ""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT provider FROM llm_models WHERE model_id = ? ORDER BY custom DESC, provider LIMIT 1",
                (clean_model_id,),
            ).fetchone()
        return str(row["provider"]) if row is not None else ""

    # ---- escrita: a tela de Modelos administra o catalogo -------------- #
    #
    # Ate aqui a classe so lia (`_connect` abre o banco em mode=ro de proposito).
    # Cadastrar modelo era: rodar SQL na mao, ou salvar em `custom_models` nos
    # settings — uma segunda lista paralela que o chat nem sempre enxergava.
    # Com estes dois metodos a tela escreve na MESMA tabela que o chat le.

    def save_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Cria ou atualiza um modelo. Devolve o modelo como ficou salvo."""
        provider = str(payload.get("provider") or "").strip().lower()
        model_id = str(payload.get("id") or payload.get("model_id") or "").strip()
        if not provider or not model_id:
            raise ValueError("provider_e_id_obrigatorios")

        def flag(key: str) -> int:
            return 1 if payload.get(key) else 0

        def positivo(key: str) -> int | None:
            try:
                valor = int(payload.get(key) or 0)
            except (TypeError, ValueError):
                return None
            return valor if valor > 0 else None

        def como_json(key: str, padrao: Any) -> str | None:
            valor = payload.get(key, padrao)
            if valor in (None, "", [], {}):
                return None
            return json.dumps(valor, ensure_ascii=False) if not isinstance(valor, str) else valor

        self.ensure_schema()
        with closing(self._write_connection()) as connection:
            connection.execute(
                """
                INSERT INTO llm_models (
                  provider, model_id, label, model_domain, supports_vision, supports_video, supports_tools,
                  supports_streaming, supports_streaming_tools, supports_structured_output,
                  supports_documents, supports_native_search, max_input_tokens, max_output_tokens,
                  free, pricing, input_modalities, output_modalities, supported_parameters,
                  description, custom, source, fetched_at, lifecycle_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'manual',datetime('now'),'active')
                ON CONFLICT(provider, model_id) DO UPDATE SET
                  label = excluded.label,
                  model_domain = CASE
                    -- Dominio implicito ('chat', nao enviado pela tela) preserva
                    -- o valor ja classificado; dominio explicito diferente substitui.
                    WHEN excluded.model_domain = 'chat' AND llm_models.model_domain != ''
                      THEN llm_models.model_domain
                    ELSE excluded.model_domain
                  END,
                  supports_vision = excluded.supports_vision,
                  supports_video = excluded.supports_video,
                  supports_tools = excluded.supports_tools,
                  supports_streaming = excluded.supports_streaming,
                  supports_streaming_tools = excluded.supports_streaming_tools,
                  supports_structured_output = excluded.supports_structured_output,
                  supports_documents = excluded.supports_documents,
                  supports_native_search = excluded.supports_native_search,
                  max_input_tokens = excluded.max_input_tokens,
                  max_output_tokens = excluded.max_output_tokens,
                  free = excluded.free,
                  pricing = excluded.pricing,
                  input_modalities = excluded.input_modalities,
                  output_modalities = excluded.output_modalities,
                  supported_parameters = excluded.supported_parameters,
                  description = excluded.description,
                  custom = excluded.custom,
                  fetched_at = datetime('now')
                """,
                (
                    provider,
                    model_id,
                    str(payload.get("label") or model_id),
                    normalizar_model_domain(payload.get("modelDomain") or payload.get("model_domain")),
                    flag("supportsVision"),
                    flag("supportsVideo"),
                    flag("supportsTools"),
                    1 if payload.get("supportsStreaming", True) else 0,
                    flag("supportsTools"),  # streaming+tools acompanha tools
                    flag("supportsStructuredOutput"),
                    flag("supportsDocuments"),
                    flag("supportsNativeSearch"),
                    positivo("maxInputTokens"),
                    positivo("maxOutputTokens"),
                    flag("free"),
                    como_json("pricing", None),
                    como_json("inputModalities", ["text"]),
                    como_json("outputModalities", ["text"]),
                    como_json("supportedParameters", []),
                    str(payload.get("description") or ""),
                    flag("custom"),
                ),
            )
            connection.commit()
        salvo = self.get_model(provider, model_id)
        if salvo is None:  # pragma: no cover - só se o banco sumir no meio
            raise RuntimeError("modelo_nao_encontrado_apos_salvar")
        return salvo

    def delete_model(self, provider: str, model_id: str) -> bool:
        """Apaga um modelo e as correções manuais dele. False se não existia."""
        clean_provider = str(provider or "").strip().lower()
        clean_model_id = str(model_id or "").strip()
        if not clean_provider or not clean_model_id:
            return False
        with closing(self._write_connection()) as connection:
            cursor = connection.execute(
                "DELETE FROM llm_models WHERE provider = ? AND model_id = ?",
                (clean_provider, clean_model_id),
            )
            # Override orfao voltaria a "assombrar" um model_id recadastrado depois.
            connection.execute(
                "DELETE FROM model_overrides WHERE provider = ? AND model_id = ?",
                (clean_provider, clean_model_id),
            )
            connection.commit()
        return cursor.rowcount > 0
