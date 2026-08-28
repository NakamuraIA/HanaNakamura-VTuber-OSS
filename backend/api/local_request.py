"""Proteção compartilhada para rotas administrativas locais."""

from ipaddress import ip_address

from fastapi import HTTPException, Request


def require_local_request(request: Request) -> None:
    """Recusa chamadas de outra máquina mesmo com bind em ``0.0.0.0``."""

    host = request.client.host if request.client else ""
    if host in {"localhost", "testclient"}:
        return
    try:
        if ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise HTTPException(status_code=403, detail="Esta ação aceita apenas chamadas locais.")
