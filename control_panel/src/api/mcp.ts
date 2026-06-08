import { McpServer, McpToolsResponse } from "../models/types";
import { BACKEND_URL, postJson, readJson } from "./core";

export const McpApi = {
  getMcpServers: async (): Promise<{servers: McpServer[]}> => {
    return readJson("/api/mcp/servers", { servers: [] }, "Erro ao carregar servidores MCP:");
  },

  getMcpServerTools: async (serverId: string): Promise<McpToolsResponse> => {
    return readJson(`/api/mcp/servers/${encodeURIComponent(serverId)}/tools`, {
      id: serverId,
      name: serverId,
      enabled: false,
      command: "",
      args: [],
      timeout: 0,
      allowed_tools: [],
      status: "error",
      error: "backend_unavailable",
      tools: [],
    });
  },

  setMcpServerEnabled: async (serverId: string, enabled: boolean): Promise<boolean> => {
    return postJson(`/api/mcp/servers/${encodeURIComponent(serverId)}/${enabled ? "enable" : "disable"}`);
  },

  setMcpToolAllowed: async (serverId: string, toolName: string, allowed: boolean): Promise<boolean> => {
    return postJson(`/api/mcp/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/${allowed ? "allow" : "block"}`);
  },

  installMcpPreset: async (presetId: string): Promise<boolean> => {
    return postJson(`/api/mcp/presets/${encodeURIComponent(presetId)}/install`);
  },

  callMcpTool: async (serverId: string, tool: string, args: Record<string, unknown>) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/mcp/call`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ server_id: serverId, tool, arguments: args }),
      });
      if (res.ok) return await res.json();
      return { ok: false, error: `HTTP ${res.status}` };
    } catch (error) {
      console.error("Erro ao chamar tool MCP:", error);
      return { ok: false, error: "backend_unavailable" };
    }
  }
};
