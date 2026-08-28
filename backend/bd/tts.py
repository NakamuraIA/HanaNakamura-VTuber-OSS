"""Cria a tabela de TTS no banco. So Python, sem arquivo .sql, sem classe global."""

import sqlite3


def criar_tabela_tts(conexao: sqlite3.Connection) -> None:
    """Cria (se nao existir) a tabela tts_models.

    Uma linha por (provider, model_id) — mesmo formato de llm_models. O id e
    a voz (Edge, que nao separa voz de motor) ou o modelo (Fish Audio,
    ElevenLabs) — cada provider so tem UM desses catalogavel por vez, nunca
    os dois ao mesmo tempo (DECISOES_CATALOGO_FONTES.md secao 12).

    Capacidade fica por linha, nao hardcoded num arquivo Python por provider
    — mesma razao do bug do Qwen em llm.py: um provider novo pode aceitar
    pitch e outro nao, sem precisar mexer em codigo pra registrar isso.
    """
    # A versão antiga tinha ``languages`` e não tinha ``language``. Ela é
    # renomeada para que qualquer linha seja copiada antes da remoção.
    colunas_atuais = {row[1] for row in conexao.execute("PRAGMA table_info(tts_models)").fetchall()}
    tabela_legada = False
    if colunas_atuais and "language" not in colunas_atuais:
        conexao.execute("ALTER TABLE tts_models RENAME TO tts_models_legacy")
        tabela_legada = True

    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS tts_models (
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            language TEXT,

            supports_streaming INTEGER,
            supports_pitch INTEGER,
            supports_stability INTEGER,
            supports_similarity INTEGER,
            supports_style INTEGER,
            supports_speaker_boost INTEGER,

            source TEXT NOT NULL DEFAULT 'manual',
            observed_at TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            lifecycle_status TEXT NOT NULL DEFAULT 'active',

            PRIMARY KEY (provider, model_id)
        )
        """
    )
    if tabela_legada:
        antigas = {
            str(row[1]) for row in conexao.execute("PRAGMA table_info(tts_models_legacy)")
        }
        if {"provider", "model_id"} <= antigas:
            label = '"label"' if "label" in antigas else '"model_id"'
            language = '"languages"' if "languages" in antigas else "NULL"
            conexao.execute(
                f"""
                INSERT INTO tts_models (provider, model_id, label, language, source)
                SELECT provider, model_id, {label}, {language}, 'legacy_migration'
                FROM tts_models_legacy WHERE 1
                ON CONFLICT(provider, model_id) DO NOTHING
                """
            )
        conexao.execute("DROP TABLE tts_models_legacy")
    conexao.commit()
