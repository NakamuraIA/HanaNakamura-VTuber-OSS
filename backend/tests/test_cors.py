"""Impede o CORS de voltar a ficar aberto.

A API roda em 127.0.0.1 SEM autenticacao e expoe `terminal_run`, `file_write` e
controle de mouse/teclado. Com `allow_origins=["*"]` — como estava — qualquer
aba do navegador podia fazer fetch() na porta 8042 e mandar a Hana rodar comando
no PC. Um site qualquer, um anuncio, uma extensao ruim.

A regra de "confirme antes de acao destrutiva" e texto no prompt da persona, nao
trava de codigo: nao segura nada nesse cenario.

Trocar de volta pra "*" nao quebra nenhum teste funcional nem da erro — a Hana
continua respondendo normalmente. Por isso precisa de teste.

Roda com:  python -m backend.tests.test_cors
"""

from __future__ import annotations

import re

from backend.api.server import CORS_ORIGENS_PERMITIDAS

_regex = re.compile(CORS_ORIGENS_PERMITIDAS)

PERMITIDAS = [
    "http://localhost:1425",      # painel em dev (vite)
    "http://127.0.0.1:1425",
    "http://localhost:8042",      # o proprio backend
    "tauri://localhost",          # app compilado
    "http://tauri.localhost",
]

BLOQUEADAS = [
    "https://site-malicioso.com",
    "http://evil.com",
    "https://localhost.evil.com",       # o "localhost" aqui e so parte do dominio
    "http://127.0.0.1.evil.com",
    "https://evil.com/localhost",
    "null",                              # iframe sandbox / arquivo local
    "http://192.168.0.10:1425",          # outra maquina da rede
]


def test_origens_do_painel_passam() -> None:
    for origem in PERMITIDAS:
        assert _regex.match(origem), f"o painel foi bloqueado: {origem}"


def test_site_externo_e_bloqueado() -> None:
    for origem in BLOQUEADAS:
        assert not _regex.match(origem), (
            f"origem externa passou no CORS: {origem}. "
            "Com a API sem auth e com terminal_run exposto, isso e execucao de "
            "comando disparada por uma aba de navegador."
        )


def test_nao_voltou_a_ser_curinga() -> None:
    from backend.api import server

    fonte = open(server.__file__, encoding="utf-8").read()
    assert 'allow_origins=["*"]' not in fonte, (
        "CORS voltou a aceitar qualquer origem — veja o docstring deste teste"
    )


if __name__ == "__main__":
    falhou = False
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok  {nome}")
            except AssertionError as exc:
                falhou = True
                print(f"FALHOU  {nome}: {exc}")
    print("\nok: CORS fechado pro que importa" if not falhou else "\nTEM TESTE FALHANDO")
