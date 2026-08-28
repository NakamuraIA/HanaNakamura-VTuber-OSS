from __future__ import annotations

import sqlite3
from pathlib import Path


class _AutoClosingConnection(sqlite3.Connection):
    """Conexao que FECHA no fim do `with`, alem de fechar a transacao.

    Pegadinha do modulo sqlite3: `with sqlite3.connect(...) as conn` faz commit
    ou rollback, mas NAO fecha a conexao. Como todo o projeto usa esse `with`,
    cada operacao deixava um handle aberto — o arquivo do banco ficava travado
    (no Windows nem da pra apagar) e os handles iam se acumulando.

    Consertar aqui vale pros ~40 pontos que chamam `_connect()` de uma vez.
    """

    def __exit__(self, *exc: object) -> None:
        try:
            super().__exit__(*exc)  # type: ignore[arg-type]
        finally:
            self.close()


class SQLiteStore:
    """Shared SQLite connection helper for local Agent OSS stores."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        # timeout=15s em vez dos 5s padrao: aqui escrevem ao mesmo tempo a API,
        # o agendador de sono, o runtime de voz e o bot do Discord. Sob carga,
        # 5s estoura e vira "database is locked" no meio de uma conversa.
        conn = sqlite3.connect(self.db_path, factory=_AutoClosingConnection, timeout=15.0)
        conn.row_factory = sqlite3.Row
        # WAL: leitor nao bloqueia escritor e vice-versa. No modo padrao
        # (DELETE), ler a memoria durante uma escrita ja segurava a outra ponta.
        # E uma propriedade do ARQUIVO — basta ativar uma vez, mas repetir e
        # barato e cobre banco criado por fora (DBeaver, script solto).
        #
        # CUIDADO NO BACKUP: com WAL surgem `-wal` e `-shm` ao lado do .db. Com
        # a Hana ligada, as escritas mais recentes podem estar no `-wal` e ainda
        # nao no .db — copiar so o .db perderia elas. Copie a pasta `runtime`
        # inteira, ou desligue a Hana antes (no shutdown limpo o WAL e aplicado).
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # seguro com WAL, bem mais rapido
        except sqlite3.DatabaseError:
            # Banco em disco de rede ou so-leitura nao aceita WAL. Segue no modo
            # padrao: mais lento sob concorrencia, mas funciona.
            pass
        return conn

    def _executescript(self, script: str) -> None:
        with self._connect() as conn:
            conn.executescript(script)
            conn.commit()
