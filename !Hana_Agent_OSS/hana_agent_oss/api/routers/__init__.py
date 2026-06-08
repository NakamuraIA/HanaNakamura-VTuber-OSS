from hana_agent_oss.api.routers.agent_jobs import router as agent_jobs_router
from hana_agent_oss.api.routers.chat import router as chat_router
from hana_agent_oss.api.routers.config import router as config_router
from hana_agent_oss.api.routers.discord import router as discord_router
from hana_agent_oss.api.routers.image import router as image_router
from hana_agent_oss.api.routers.memory import router as memory_router
from hana_agent_oss.api.routers.mcp import router as mcp_router
from hana_agent_oss.api.routers.status import router as status_router
from hana_agent_oss.api.routers.system import router as system_router
from hana_agent_oss.api.routers.terminal_agent import router as terminal_agent_router
from hana_agent_oss.api.routers.voice import router as voice_router

__all__ = [
    "chat_router",
    "agent_jobs_router",
    "config_router",
    "discord_router",
    "image_router",
    "memory_router",
    "mcp_router",
    "status_router",
    "system_router",
    "terminal_agent_router",
    "voice_router",
]
