"""Criação das tabelas SQLite, um arquivo por domínio.

Estado atual:
- llm.py cria llm_models + model_overrides; tts.py cria tts_models; stt.py cria
  stt_models; agent_core.py cria as quatro tabelas internas do Agent Core.
- A pasta contém DDL e migração de schema, não leitura/escrita comum de linhas.
- llm.py move explicitamente provider_models e custom_models para llm_models.

Destino: bd/ será o único dono de schema, os repositórios em catalog/ cuidarão
dos dados e as restrições estruturais ficarão no banco. O Agent Core já usa
tabelas com prefixo próprio dentro de runtime/hana_memory.sqlite3.
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.bd.llm import migrar_catalogo_llm
from backend.bd.stt import criar_tabela_stt
from backend.bd.tts import criar_tabela_tts


def preparar_catalogos(db_path: str | Path) -> dict[str, Any]:
    """Cria os três schemas e conclui migrações antigas de forma idempotente."""

    result = migrar_catalogo_llm(db_path)
    with closing(sqlite3.connect(Path(db_path).resolve())) as connection:
        criar_tabela_tts(connection)
        criar_tabela_stt(connection)
    return result
