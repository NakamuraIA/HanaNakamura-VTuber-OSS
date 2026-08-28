"""Cliente de servidores MCP (Model Context Protocol) externos.

Contrato da pasta:
- config.py    : McpConfigStore — quais servidores estão configurados.
- client.py / manager.py : spawn/gerência dos processos (stdio via npx etc.).
- contracts.py : McpServerConfig, McpCallRequest/Result, McpToolInfo.

Regra: MCP é integração EXTERNA e opcional — falha de servidor MCP nunca
derruba o backend; ferramentas MCP entram no turno como ToolResult comum.
"""

from backend.mcp.config import McpConfigStore
from backend.mcp.contracts import McpCallRequest, McpCallResult, McpServerConfig, McpToolInfo

__all__ = [
    "McpCallRequest",
    "McpCallResult",
    "McpConfigStore",
    "McpServerConfig",
    "McpToolInfo",
]
