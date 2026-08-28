from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request

from backend.api.local_request import require_local_request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sistema"])


@router.post("/api/tts/speak", summary="Falar um texto (atalho global)")
async def speak(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    request.app.state.memory.append_event("system", f"TTS requested but voice integration is optional: {text[:120]}", channel="control_center")
    return {"status": "disabled", "message": "TTS is now an optional integration."}


@router.post("/api/system/shutdown", summary="Desligar a Hana")
async def system_shutdown(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    """Desliga de verdade — o processo se encerra sozinho.

    Antes esta rota so devolvia uma mensagem dizendo "pare o supervisor", e o
    backend continuava de pe. Quem quisesse desligar tinha que cacar o PID e
    matar na mao — e `taskkill` falha quando o processo foi aberto por outra
    sessao (outro terminal, ou o pythonw que o Hana.cmd usa).

    Pedir pro proprio processo sair resolve isso: nao existe questao de
    permissao, e o lifespan do FastAPI ainda roda — bot do Discord, agendador e
    voz fecham direito em vez de morrer no meio.

    O encerramento vai pro background pra resposta HTTP sair ANTES. Sem isso
    quem chamou recebe "conexao perdida" e nao sabe se funcionou.
    """
    require_local_request(request)
    background.add_task(_encerrar_processo)
    return {"ok": True, "message": "Desligando a Hana."}


def _encerrar_processo() -> None:
    """Pede o encerramento gracioso; se travar, sai na forca."""

    def _sair() -> None:
        time.sleep(0.4)  # tempo da resposta HTTP chegar em quem pediu
        try:
            # SIGINT e o mesmo que Ctrl+C: o uvicorn intercepta e roda o
            # shutdown do lifespan. Funciona no Windows desde o Python 3.8.
            signal.raise_signal(signal.SIGINT)
        except Exception:  # noqa: BLE001
            logger.warning("SIGINT falhou; encerrando na marra", exc_info=True)
            os._exit(0)
        # Rede de seguranca: se algo segurar o loop (thread de audio, subprocesso
        # travado), sai na forca em vez de ficar de pe pra sempre.
        time.sleep(6)
        logger.warning("Shutdown gracioso demorou demais; encerrando na marra")
        os._exit(0)

    threading.Thread(target=_sair, daemon=True).start()
