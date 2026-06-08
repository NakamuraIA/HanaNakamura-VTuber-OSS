# Hana MCP Client

Hana Agent OSS acts as an MCP client in this version. It connects to external
MCP servers, discovers tools and maps MCP calls into the internal
`ToolCall -> ToolResult` contract.

Hana does not expose its own MCP server yet.

## Configuration

Public example:

```txt
!Hana_Agent_OSS/config/mcp_servers.example.json
```

Local runtime file:

```txt
!Hana_Agent_OSS/runtime/mcp_servers.local.json
```

Override path:

```env
HANA_MCP_CONFIG=E:\Projeto_Hana_AI\!Hana_Agent_OSS\runtime\mcp_servers.local.json
```

Servers are disabled by default. Tools are blocked until they are explicitly
added to `allowed_tools`.

## Windows Examples

Filesystem dev server:

```json
{
  "id": "filesystem",
  "enabled": false,
  "command": "cmd",
  "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "E:\\Projeto_Hana_AI"],
  "allowed_tools": []
}
```

Git dev server:

```json
{
  "id": "git",
  "enabled": false,
  "command": "uvx",
  "args": ["mcp-server-git", "--repository", "E:\\Projeto_Hana_AI"],
  "allowed_tools": []
}
```

Tavily web search server:

```json
{
  "id": "tavily",
  "name": "Tavily Web Search",
  "enabled": false,
  "command": "cmd",
  "args": ["/c", "npx", "-y", "tavily-mcp@0.1.3"],
  "env": {
    "TAVILY_API_KEY": "${TAVILY_API_KEY}"
  },
  "cwd": "E:\\Projeto_Hana_AI",
  "timeout": 30,
  "allowed_tools": ["tavily-search"]
}
```

## Tavily Setup

1. Put the free Tavily key in local `.env`:

```env
TAVILY_API_KEY=tvly-your-key-here
```

2. Start or restart the backend so `.env` is loaded.
3. Open the Control Panel MCP tab.
4. Select `Tavily Web Search`, enable the server and click discovery.
5. Confirm `tavily-search` is allowed. Keep `tavily-extract` blocked until you
   explicitly want extraction.

The runtime config keeps `${TAVILY_API_KEY}` as a placeholder. The backend
resolves it only when spawning the MCP subprocess and never returns the real key
through the MCP API/panel. If the variable is missing, discovery/invocation
returns `mcp_env_missing:TAVILY_API_KEY`.

## API

- `GET /api/mcp/servers`
- `GET /api/mcp/servers/{server_id}/tools`
- `POST /api/mcp/servers/{server_id}/enable`
- `POST /api/mcp/servers/{server_id}/disable`
- `POST /api/mcp/servers/{server_id}/tools/{tool_name}/allow`
- `POST /api/mcp/servers/{server_id}/tools/{tool_name}/block`
- `POST /api/mcp/call`

## Agent Tools

- `mcp.discover`: lists configured servers and tools for enabled servers.
- `mcp.invoke`: calls one allowed tool on one enabled server.

Provider-backed chat can also expose MCP as local LLM tools named
`mcp_discover` and `mcp_invoke`. Those tools still call the same backend MCP
manager and keep the same server-enabled and allowlist checks.

Disabled servers are never connected during discovery.

## Safety Rules

- The chat cannot create new MCP server commands.
- Server config lives in local JSON, not prompt text.
- A server must be enabled before discovery.
- A tool must be allowlisted before execution.
- Connection/protocol errors return structured errors such as
  `mcp_server_unavailable`, `mcp_server_disabled`, `mcp_tool_not_allowed` or
  `mcp_sdk_missing`.
