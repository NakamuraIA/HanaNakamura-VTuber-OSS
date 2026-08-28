from __future__ import annotations

import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from backend.api.routers.system import system_shutdown


def _request(host: str) -> Request:
    return Request({"type": "http", "client": (host, 1234), "headers": []})


def test_shutdown_recusa_maquina_remota_sem_agendar_encerramento() -> None:
    background = BackgroundTasks()

    with pytest.raises(HTTPException) as error:
        asyncio.run(system_shutdown(_request("192.168.1.50"), background))

    assert error.value.status_code == 403
    assert background.tasks == []
