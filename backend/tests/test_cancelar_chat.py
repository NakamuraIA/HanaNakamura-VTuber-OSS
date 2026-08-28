from __future__ import annotations

import asyncio

from fastapi import FastAPI
from starlette.requests import Request

from backend.api.routers.chat import cancel_chat


def test_cancelar_chat_interrompe_tarefa_ativa() -> None:
    async def scenario() -> None:
        app = FastAPI()
        task = asyncio.create_task(asyncio.Event().wait())
        app.state.active_chat_tasks = {task}
        request = Request({"type": "http", "app": app, "headers": []})

        result = await cancel_chat(request)
        await asyncio.sleep(0)

        assert result == {"status": "ok", "cancelled": 1}
        assert task.cancelled()

    asyncio.run(scenario())
