from backend.api.routers.agent_jobs import router as agent_jobs_router
from backend.api.routers.chat import router as chat_router
from backend.api.routers.config import router as config_router
from backend.api.routers.discord import router as discord_router
from backend.api.routers.image import router as image_router
from backend.api.routers.memoria import router as memoria_router
from backend.api.routers.mcp import router as mcp_router
from backend.api.routers.modelos import router as modelos_router
from backend.api.routers.reminders import router as reminders_router
from backend.api.routers.status import router as status_router
from backend.api.routers.setup import router as setup_router
from backend.api.routers.system import router as system_router
from backend.api.routers.terminal_agent import router as terminal_agent_router
from backend.api.routers.validation import router as validation_router
from backend.api.routers.voice import router as voice_router

__all__ = [
    "chat_router",
    "agent_jobs_router",
    "config_router",
    "discord_router",
    "image_router",
    "memoria_router",
    "mcp_router",
    "modelos_router",
    "reminders_router",
    "status_router",
    "setup_router",
    "system_router",
    "terminal_agent_router",
    "validation_router",
    "voice_router",
]
