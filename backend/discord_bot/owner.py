from __future__ import annotations

import os

# A Hana e PRIVADA: so a dona fala com ela ou usa qualquer comando.
#
# Quem e a dona vem do .env (HANA_OWNER_ID, ou HANA_OWNER_IDS separados por
# virgula/espaco). ID do Discord e dado pessoal e este arquivo vai pro repo
# publico — nunca escreva um ID aqui.
#
# SEM a variavel configurada, NINGUEM e dono e o bot nao responde a ninguem.
# E de proposito: um default aberto transformaria qualquer clone do projeto num
# bot que obedece qualquer pessoa do servidor.


def _split_ids(value: str | None) -> list[str]:
    raw = str(value or "")
    parts = raw.replace(",", " ").split()
    return [p.strip() for p in parts if p.strip()]


def owner_ids() -> set[str]:
    """IDs autorizados. Vazio = ninguem, e o bot nao obedece a ninguem."""
    configured = _split_ids(os.environ.get("HANA_OWNER_IDS")) + _split_ids(os.environ.get("HANA_OWNER_ID"))
    return set(configured)


def is_owner(user_id: object) -> bool:
    """True somente para a dona do bot. Qualquer outro é bloqueado."""
    return str(user_id or "") in owner_ids()


def primary_owner_id() -> str:
    """Dona principal, pras DMs que a Hana manda sozinha (outbox).

    Precedencia: HANA_OWNER_ID > primeiro de HANA_OWNER_IDS. Vazio se nao houver
    nenhum — quem chama trata isso como "nao tem pra quem mandar".

    Fonte unica: sem isto o ID acabaria repetido/fixo dentro dos routers.
    """
    single = _split_ids(os.environ.get("HANA_OWNER_ID"))
    if single:
        return single[0]
    multi = _split_ids(os.environ.get("HANA_OWNER_IDS"))
    return multi[0] if multi else ""
