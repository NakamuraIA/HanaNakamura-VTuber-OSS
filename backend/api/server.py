from __future__ import annotations

import argparse
import logging
import os
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def load_runtime_environment() -> None:
    """Load project-level secrets before optional backend-local overrides."""
    from backend.paths import PROJECT_ROOT, AGENT_ROOT
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(AGENT_ROOT / ".env", override=True)
    load_dotenv(override=True)


load_runtime_environment()

from backend.api.routers import (
    agent_jobs_router,
    chat_router,
    config_router,
    discord_router,
    image_router,
    memoria_router,
    mcp_router,
    modelos_router,
    reminders_router,
    status_router,
    setup_router,
    system_router,
    terminal_agent_router,
    validation_router,
    voice_router,
)
from backend.api.services.catalog import DEFAULT_CONNECTIONS
from backend.api.services.agent_jobs import AgentJobManager, set_agent_job_manager
from backend.bd import preparar_catalogos
from backend.core.runtime import HanaAgentCore
from backend.memory.core import HanaMemory
from backend.memory.store import MemoryStore
from backend.paths import MEMORY_DB
from backend.setup.database import garantir_instalacao_inicial
from backend.modules.reminders import ReminderScheduler, set_reminder_scheduler
from backend.modules.voice.runtime import VoiceRuntime, voice_config_with_connections

logger = logging.getLogger(__name__)


def hydrate_voice_runtime_state(app: FastAPI) -> None:
    """Apply persisted voice settings and hotkeys after the app state exists."""
    memory = app.state.memory
    runtime = app.state.voice_runtime
    connections = memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    if not isinstance(connections, dict):
        connections = dict(DEFAULT_CONNECTIONS)
    runtime.configure_hotkeys(connections)
    config = voice_config_with_connections(memory)
    if bool(config.get("sttEnabled")):
        runtime.start(config)
        return
    runtime.apply_config(config)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan hook used for runtime hydration."""
    hydrate_voice_runtime_state(app)
    app.state.reminders.start()
    app.state.sleep_scheduler.start()
    app.state.core.mcp.start_enabled_background()
    # Sobe o bot do Discord automaticamente se o toggle já estava ligado (e há token).
    try:
        from backend.api.routers.config import normalize_connections_config
        from backend.api.services.catalog import DEFAULT_CONNECTIONS
        connections = normalize_connections_config(
            app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
        )
        if connections.get("discord"):
            app.state.discord_bot.start()
    except Exception:
        logger.exception("Falha ao iniciar o bot do Discord no startup.")
    try:
        yield
    finally:
        app.state.discord_bot.stop()
        app.state.sleep_scheduler.stop()
        app.state.reminders.stop()
        await app.state.core.mcp.shutdown()


API_DESCRICAO = """
API local da Hana. Tudo roda no seu PC — nada sai da máquina.

**Onde as coisas moram**

| Camada | Onde | O que é |
|---|---|---|
| Identidade | `backend/persona/` (código) | quem ela é, como fala, o que não pode dizer |
| Memória | `runtime/hana_memory.sqlite3` | o que ela viveu |
| Mídia gerada | `runtime/media/` | imagens e áudio que ela cria |

> **Código = quem ela é. Banco = o que ela viveu.**

**Por onde começar:** `Memória` → `GET /api/memoria/status`.
Para conversar de verdade é `WS /ws/chat` (WebSocket, não aparece aqui — o
Swagger só documenta HTTP).

Detalhes da memória: `backend/docs/MEMORIA.md`.
"""

TAGS_DOC = [
    {"name": "Memória", "description":
     "Memória **curta** (a conversa, por canal), **longa** (fatos que a Hana salva "
     "sozinha, buscados por RAG) e **fixa** (regras que só a Nakamura escreve — a "
     "Hana só lê). Mais o histórico do front, que fica no banco mas **nunca** vai "
     "pra LLM."},
    {"name": "Chat", "description":
     "O turno de conversa. O streaming ao vivo é WebSocket (`/ws/chat`); aqui ficam "
     "só o histórico e o cancelamento."},
    {"name": "Configuração — LLM e chat", "description": "Modelos principais, chat e segurança do agente."},
    {"name": "Configuração — voz", "description": "STT, TTS, dispositivos e catálogo de vozes."},
    {"name": "Configuração — conexões", "description": "Recursos ligados, atalhos, Discord e visão."},
    {"name": "Configuração — ambiente", "description": "Caminhos locais, aparência e monitores."},
    {"name": "Configuração — imagem", "description": "Provider e modelo usados para gerar imagens."},
    {"name": "Modelos", "description":
     "Catálogo de modelos por provider, guardado no banco. Existe porque nem todo "
     "provider tem endpoint de 'liste seus modelos' como o OpenRouter."},
    {"name": "Catálogo", "description": "Catálogo geral e modelos personalizados."},
    {"name": "Voz", "description": "STT (escutar), TTS (falar) e o runtime de voz contínua."},
    {"name": "MCP (ferramentas externas)", "description":
     "Servidores MCP: liga/desliga, lista ferramentas e controla o que a Hana pode chamar."},
    {"name": "Terminal Agente", "description":
     "O modo agente: eventos do terminal, plano de execução e controle da fala."},
    {"name": "Agente — tarefas", "description": "Tarefas longas em segundo plano: listar, acompanhar e cancelar."},
    {"name": "Discord", "description": "Ponte com o bot do Discord: mensagens, status e fila de envio."},
    {"name": "Imagem", "description": "Gerar e editar imagem."},
    {"name": "Lembretes", "description": "Lembretes por horário, criados por você ou pela própria Hana."},
    {"name": "Status e saúde", "description": "Ela está viva? Há quanto tempo? WebSocket de status e emoções."},
    {"name": "Sistema", "description": "Desligar o backend."},
    {"name": "Setup e recuperação", "description":
     "Prévia e restauração manual dos modelos públicos. A escrita exige confirmação "
     "explícita e aceita somente chamadas locais."},
    {"name": "Validação (temporária)", "description":
     "Testes internos da migração. Leitura real é bloqueada para escrita; qualquer "
     "gravação usa um banco temporário. Esta seção será removida antes da publicação."},
]


# Quem pode chamar esta API de dentro de um navegador.
#
# Era `["*"]`, e isso e perigoso de verdade aqui: a API nao tem autenticacao e
# expoe `terminal_run`, `file_write` e controle de mouse/teclado. Com CORS
# aberto, QUALQUER aba do navegador — um site qualquer, um anuncio, uma extensao
# ruim — podia fazer fetch() em http://127.0.0.1:8042 e mandar a Hana rodar
# comando no PC. A regra de "confirme antes de acao destrutiva" e texto no
# prompt, nao trava de codigo: nao segura nada nesse cenario.
#
# Agora so passa o que realmente precisa:
#   localhost / 127.0.0.1  -> o painel em dev (vite) e o app Tauri
#   tauri://  e  tauri.localhost -> o app compilado, que usa esse esquema proprio
#
# Site externo cai no preflight e o navegador bloqueia antes de chegar aqui.
CORS_ORIGENS_PERMITIDAS = r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|tauri://localhost|https?://tauri\.localhost)$"


def create_app() -> FastAPI:
    # Primeira instalação pelo próprio backend: subir direto pelo Uvicorn tem
    # que produzir o mesmo estado do Hana-First-Run.cmd. A decisão usa a marca
    # persistente em settings, nunca a existência do arquivo — o arquivo pode
    # ser criado pelos próprios módulos de runtime antes do setup rodar.
    try:
        garantir_instalacao_inicial(MEMORY_DB)
    except Exception:
        logger.exception(
            "Instalação inicial incompleta; a marca não foi gravada e nada ficou "
            "pela metade. Resolva o problema e suba o backend novamente."
        )
        raise
    app = FastAPI(
        title="Hana Agent OSS API",
        version="0.1.0",
        description=API_DESCRICAO,
        openapi_tags=TAGS_DOC,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=CORS_ORIGENS_PERMITIDAS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.core = HanaAgentCore()
    app.state.memory = MemoryStore()
    preparar_catalogos(MEMORY_DB)
    # Memoria nova (curta + RAG + fixa + historico do front + config).
    # Convive com o MemoryStore antigo enquanto o front nao migra: sao tabelas
    # diferentes no MESMO arquivo, entao backup e reset continuam sendo uma pasta so.
    app.state.memoria = HanaMemory(str(MEMORY_DB))
    app.state.voice_runtime = VoiceRuntime(memory=app.state.memory, core=app.state.core)
    app.state.agent_jobs = AgentJobManager(memory=app.state.memory)
    app.state.agent_jobs.set_speaker(app.state.voice_runtime.speak_text)
    set_agent_job_manager(app.state.agent_jobs)
    app.state.reminders = ReminderScheduler(memory=app.state.memory)
    app.state.reminders.set_speaker(app.state.voice_runtime.speak_text)
    set_reminder_scheduler(app.state.reminders)
    from backend.memory.long_term.sleep import SleepScheduler
    app.state.sleep_scheduler = SleepScheduler(memory=app.state.memory)
    from backend.discord_bot.manager import DiscordBotManager
    app.state.discord_bot = DiscordBotManager()
    app.state.started_at = time.time()

    for router in (
        status_router,
        agent_jobs_router,
        chat_router,
        image_router,
        memoria_router,
        mcp_router,
        modelos_router,
        reminders_router,
        config_router,
        discord_router,
        terminal_agent_router,
        validation_router,
        voice_router,
        setup_router,
        system_router,
    ):
        app.include_router(router)
    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Hana Agent OSS API.")
    parser.add_argument("--host", default=os.environ.get("HANA_BACKEND_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HANA_BACKEND_PORT", "8042")))
    parser.add_argument("--ws-max-size", type=int, default=int(os.environ.get("HANA_WS_MAX_SIZE", str(64 * 1024 * 1024))))
    args = parser.parse_args(argv)
    uvicorn.run(
        "backend.api.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
        ws_max_size=args.ws_max_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
