from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hana_agent_oss.mcp.contracts import McpServerConfig


from hana_agent_oss.paths import MCP_EXAMPLE_CONFIG as DEFAULT_EXAMPLE_CONFIG, MCP_LOCAL_CONFIG as DEFAULT_LOCAL_CONFIG

MCP_PRESETS: dict[str, dict[str, Any]] = {
    "tavily": {
        "id": "tavily",
        "name": "Tavily Web Search",
        "enabled": False,
        "command": "cmd",
        "args": ["/c", "npx", "-y", "tavily-mcp@0.1.3"],
        "env": {"TAVILY_API_KEY": "${TAVILY_API_KEY}"},
        "cwd": "E:\\Projeto_Hana_AI",
        "timeout": 30,
        "allowed_tools": ["tavily-search"],
    }
}


class McpConfigStore:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self._explicit_path = Path(config_path).resolve() if config_path else None

    @property
    def path(self) -> Path:
        if self._explicit_path:
            return self._explicit_path
        env_path = os.environ.get("HANA_MCP_CONFIG")
        if env_path:
            return Path(env_path).expanduser().resolve()
        if DEFAULT_LOCAL_CONFIG.exists():
            return DEFAULT_LOCAL_CONFIG
        return DEFAULT_EXAMPLE_CONFIG

    @property
    def writable_path(self) -> Path:
        if self._explicit_path:
            return self._explicit_path
        env_path = os.environ.get("HANA_MCP_CONFIG")
        if env_path:
            return Path(env_path).expanduser().resolve()
        return DEFAULT_LOCAL_CONFIG

    def load_payload(self) -> dict[str, Any]:
        path = self.path
        if not path.exists():
            return {"servers": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return {"servers": []}
        if not isinstance(payload, dict):
            return {"servers": []}
        payload.setdefault("servers", [])
        return payload

    def save_payload(self, payload: dict[str, Any]) -> None:
        path = self.writable_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def list_servers(self) -> list[McpServerConfig]:
        servers = self.load_payload().get("servers", [])
        return [McpServerConfig.from_dict(item) for item in servers if isinstance(item, dict)]

    def get_server(self, server_id: str) -> McpServerConfig | None:
        for server in self.list_servers():
            if server.id == server_id:
                return server
        return None

    def update_server(self, server_id: str, **updates: Any) -> McpServerConfig | None:
        payload = self.load_payload()
        next_servers: list[dict[str, Any]] = []
        updated: McpServerConfig | None = None
        for raw in payload.get("servers", []):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("id")) == server_id:
                raw = {**raw, **updates}
                updated = McpServerConfig.from_dict(raw)
            next_servers.append(raw)
        payload["servers"] = next_servers
        if updated:
            self.save_payload(payload)
        return updated

    def set_tool_allowed(self, server_id: str, tool_name: str, allowed: bool) -> McpServerConfig | None:
        server = self.get_server(server_id)
        if not server:
            return None
        tools = set(server.allowed_tools)
        if allowed:
            tools.add(tool_name)
        else:
            tools.discard(tool_name)
        return self.update_server(server_id, allowed_tools=sorted(tools))

    def upsert_preset(self, preset_id: str) -> McpServerConfig | None:
        """Install or refresh a known MCP preset into the local writable config."""
        preset = MCP_PRESETS.get(str(preset_id or "").strip().lower())
        if not preset:
            return None
        payload = self.load_payload()
        servers = [item for item in payload.get("servers", []) if isinstance(item, dict)]
        updated = False
        next_servers: list[dict[str, Any]] = []
        for raw in servers:
            if str(raw.get("id") or "") == preset["id"]:
                raw = {**preset, **raw, "id": preset["id"], "name": raw.get("name") or preset["name"]}
                updated = True
            next_servers.append(raw)
        if not updated:
            next_servers.append(dict(preset))
        payload["version"] = payload.get("version", 1)
        payload["servers"] = next_servers
        self.save_payload(payload)
        return self.get_server(preset["id"]) or McpServerConfig.from_dict(dict(preset))
