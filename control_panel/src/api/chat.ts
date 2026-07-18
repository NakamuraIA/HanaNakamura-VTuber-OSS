import { ChatMessage, OpenRouterRoutingConfig } from "../models/types";
import { BACKEND_URL, WS_URL } from "./core";

export const ChatApi = {
  connectChatWebSocket: (
    message: string,
    images_b64: string[],
    attachments: { name: string; data: string; type: string; size?: number }[],
    provider: string,
    model: string,
    nativeSearchMode: "auto" | "force" | "off",
    safetyMode: string,
    history: { role: string; content: string }[],
    openrouterRouting: Partial<OpenRouterRoutingConfig>,
    onMessageChunk: (text: string) => void,
    onFinalText: (text: string) => void,
    onMeta: (meta: ChatMessage["meta"]) => void,
    onAgentPlan: (plan: ChatMessage["agentPlan"]) => void,
    onAgentStatus: (status: ChatMessage["agentStatus"]) => void,
    onActivity: (activity: { event?: string; label?: string; detail?: string }) => void,
    onMedia: (media: NonNullable<ChatMessage["media"]>[0]) => void,
    onDone: () => void,
    onError: (err: unknown) => void,
    onReasoning?: (activity: { label: string; detail: string }) => void,
    onToolActivity?: (event: { kind: string; tool: string; args?: Record<string, unknown>; result?: Record<string, unknown> }) => void
  ): { ws: WebSocket; send: (msg: string, imgs?: string[]) => void } => {
    const ws = new WebSocket(`${WS_URL}/ws/chat`);

    ws.onopen = () => {
      ws.send(JSON.stringify({
        text: message,
        images_b64,
        attachments,
        provider,
        model,
        native_search_mode: nativeSearchMode,
        safety_mode: safetyMode,
        history,
        openrouter_routing: openrouterRouting,
      }));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "chunk") {
          onMessageChunk(data.content);
        } else if (data.type === "final") {
          onFinalText(data.content);
        } else if (data.type === "meta") {
          onMeta(data.meta);
        } else if (data.type === "agent_plan") {
          onAgentPlan(data.plan);
        } else if (data.type === "agent_status") {
          onAgentStatus(data.status);
        } else if (data.type === "activity") {
          onActivity(data.activity || {});
        } else if (data.type === "media") {
          onMedia(data.media);
        } else if (data.type === "done") {
          onDone();
        } else if (data.type === "reasoning") {
          onReasoning?.({
            label: "Hana está pensando...",
            detail: data.content || "",
          });
        } else if (data.type === "tool_activity") {
          onToolActivity?.(data.event || {});
        } else if (data.type === "error") {
          onError(data.content);
        }
      } catch (e) {
        console.error("Erro no ws chat:", e);
      }
    };
    ws.onerror = (error) => onError(error);

    return {
      ws,
      send: (msg: string, imgs?: string[]) => {
        ws.send(JSON.stringify({
          text: msg,
          images_b64: imgs || [],
          attachments: [],
          provider,
          model,
          native_search_mode: nativeSearchMode,
          safety_mode: safetyMode,
          history,
          openrouter_routing: openrouterRouting,
        }));
      }
    };
  },

  getAgentSettings: async (): Promise<{safety_mode: string}> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/agent/settings`);
      if (res.ok) return await res.json();
      throw new Error("Falha na API");
    } catch (error) {
      return { safety_mode: localStorage.getItem("hana_agent_safety_mode") || "safe" };
    }
  },

  updateAgentSettings: async (safetyMode: string): Promise<boolean> => {
    localStorage.setItem("hana_agent_safety_mode", safetyMode);
    try {
      const res = await fetch(`${BACKEND_URL}/api/agent/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ safety_mode: safetyMode })
      });
      return res.ok;
    } catch (error) {
      return true;
    }
  },

  getPendingPermissions: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/permissions/pending`);
      if (res.ok) return await res.json();
      throw new Error("Falha na API");
    } catch (error) {
      return { permissions: [] };
    }
  },

  approvePermission: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/permissions/${id}/approve`, { method: "POST" });
      return res.ok;
    } catch (error) {
      return false;
    }
  },

  denyPermission: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/permissions/${id}/deny`, { method: "POST" });
      return res.ok;
    } catch (error) {
      return false;
    }
  },

  cancelAllPermissions: async (): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/permissions/cancel-all`, { method: "POST" });
      return res.ok;
    } catch (error) {
      return false;
    }
  },

  cancelChatResponse: async () => {
    try {
      await fetch(`${BACKEND_URL}/api/chat/cancel`, { method: "POST" });
    } catch (error) {
      console.error("Erro ao cancelar resposta:", error);
    }
  },

  getChatHistory: async (limit: number = 50): Promise<{messages: {role: string, content: string}[]}> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/chat/history?limit=${limit}`);
      if (res.ok) return await res.json();
      throw new Error("Falha na API");
    } catch (error) {
      console.error("Erro ao carregar historico:", error);
      return { messages: [] };
    }
  }
};
