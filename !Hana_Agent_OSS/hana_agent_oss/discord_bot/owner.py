from __future__ import annotations

import os

# Hana é PRIVADA: só a Operador pode falar com ela ou usar qualquer comando.
# O ID padrão é o da Operador; pode ser sobrescrito/expandido por env
# (HANA_OWNER_ID / HANA_OWNER_IDS, separados por vírgula ou espaço).
DEFAULT_OWNER_ID = "0"


def _split_ids(value: str | None) -> list[str]:
    raw = str(value or "")
    parts = raw.replace(",", " ").split()
    return [p.strip() for p in parts if p.strip()]


def owner_ids() -> set[str]:
    """Resolve o conjunto de IDs autorizados (default = só a Operador)."""
    configured = _split_ids(os.environ.get("HANA_OWNER_IDS")) + _split_ids(os.environ.get("HANA_OWNER_ID"))
    return set(configured) if configured else {DEFAULT_OWNER_ID}


def is_owner(user_id: object) -> bool:
    """True somente para a dona do bot. Qualquer outro é bloqueado."""
    return str(user_id or "") in owner_ids()
