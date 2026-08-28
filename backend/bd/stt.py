"""Cria a tabela de STT no banco. So Python, sem arquivo .sql, sem classe global."""

import sqlite3


def criar_tabela_stt(conexao: sqlite3.Connection) -> None:
    """Cria (se nao existir) a tabela stt_models.

    So entram aqui providers SEM lista de modelos ao vivo boa o bastante (Groq
    Whisper, Local) — OpenRouter tem endpoint proprio de transcricao e le
    direto de la, sem passar por aqui (DECISOES_CATALOGO_FONTES.md secao 1,
    mesma regra ja usada pros modelos LLM do OpenRouter).
    """
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS stt_models (
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            language TEXT,

            supports_prompt INTEGER,

            source TEXT NOT NULL DEFAULT 'manual',
            observed_at TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            lifecycle_status TEXT NOT NULL DEFAULT 'active',

            PRIMARY KEY (provider, model_id)
        )
        """
    )
    conexao.commit()
