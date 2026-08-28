"""Impede que dado pessoal volte pro codigo que vai pro repo publico.

A persona foi dividida em duas:

    backend/persona/profile.py   como ela USA ferramenta, escreve e se protege
                                 -> vai pro GitHub, tem que ser generico
    tabela `pinned` no banco     quem e o operador, os gostos dele, a personagem
                                 -> fica no runtime/, que e gitignored

O risco real: alguem (ou eu mesma, num loop) reescreve o profile.py e cola de
volta um nome, um gosto ou uma preferencia. Nao da erro nenhum — so vaza a vida
da pessoa no proximo `git push`.

Roda com:  python -m backend.tests.test_persona_publica
"""

from __future__ import annotations

import re
from pathlib import Path

PROFILE = Path("backend/persona/profile.py")

# Coisas que so podem existir no banco. Se aparecerem aqui, e vazamento.
PROIBIDO = (
    "nakamura",
    "nyra",
    "shogun",
    "yakisoba",
    "hentai",
    "nsfw",
    "buceta",
    "fortnite",
    "abacaxi",
    "nightcore",
    "phonk",
    "otaku",
    "onee-san",
    "sakura",
)


def _texto() -> str:
    return PROFILE.read_text(encoding="utf-8").lower()


def test_profile_nao_tem_nome_nem_gosto_pessoal() -> None:
    achados = sorted({p for p in PROIBIDO if re.search(rf"\b{re.escape(p)}\b", _texto())})
    assert not achados, (
        f"dado pessoal voltou pro profile.py: {achados}. "
        "Isso vai pro repo publico — mova pra tabela `pinned` (tela Memoria -> Fixas)."
    )


def test_nome_do_usuario_vem_do_ambiente() -> None:
    # Hardcodar o nome obriga quem clonar a editar Python so pra se apresentar.
    t = _texto()
    assert "hana_user_name" in t and "hana_assistant_name" in t, (
        "nome do operador e da assistente tem que sair do .env, nao do codigo"
    )


def test_campos_pessoais_ficaram_vazios() -> None:
    from backend.persona.profile import default_persona_profile

    p = default_persona_profile()
    for campo in ("relationship", "character_voice", "preferences"):
        assert not getattr(p, campo), (
            f"'{campo}' voltou a ter conteudo no codigo — esse campo agora mora em `pinned`"
        )


def test_as_regras_tecnicas_continuam_no_codigo() -> None:
    # O contrario tambem quebra: se alguem mover TUDO pro banco, quem clonar o
    # projeto recebe uma assistente que nao sabe usar as proprias ferramentas.
    from backend.persona.profile import default_persona_profile

    regras = " ".join(default_persona_profile().behavior_rules).lower()
    for essencial in ("file_write", "skill_read", "memory_search", "seguranca", "nunca invente resultado"):
        assert essencial in regras, f"regra tecnica essencial sumiu do codigo: {essencial}"


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
    print("\nok: profile.py esta seguro pro repo publico" if not falhou else "\nTEM VAZAMENTO")
