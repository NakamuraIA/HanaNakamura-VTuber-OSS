import { SystemStatus } from "../models/types";
import { BACKEND_URL, WS_URL, readJson } from "./core";

export const SystemApi = {
  connectEmotionsWebSocket: (onMessage: (data: unknown) => void) => {
    const ws = new WebSocket(`${WS_URL}/ws/emotions`);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error("Erro ao parsear emocoes via WS:", e);
      }
    };
    ws.onerror = (error) => console.debug("WebSocket de emocoes indisponivel ou reiniciado:", error);
    return ws;
  },

  connectStatusWebSocket: (onMessage: (data: SystemStatus) => void) => {
    const ws = new WebSocket(`${WS_URL}/ws/status`);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error("Erro ao parsear status via WS:", e);
      }
    };
    ws.onerror = (error) => console.debug("WebSocket de status indisponivel ou reiniciado:", error);
    return ws;
  },

  getSystemStatus: async (): Promise<SystemStatus> => {
    return readJson("/api/status", {
      cpu: 0,
      ramPercent: 0,
      ramUsedStr: "0.0",
      ramTotalStr: "0.0",
      llmProvider: "—",
      llmModel: "—",
      ttsProvider: "—",
      modules: { llm: false, tts: false, stt: false, visao: false, vtube_studio: false, discord: false, omni: false },
    });
  },

  speakText: async (text: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/voice/tts/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao reproduzir TTS:", error);
      return false;
    }
  },

  shutdownSystem: async () => {
    const res = await fetch(`${BACKEND_URL}/api/system/shutdown`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    return res.ok;
  },

  getSystemLogs: async (limit: number = 100): Promise<{logs: {timestamp: string, level: string, message: string, logger: string}[]}> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/logs?limit=${limit}`);
      if (res.ok) return await res.json();
      throw new Error("Falha na API");
    } catch (error) {
      console.error("Erro ao carregar logs:", error);
      return { logs: [] };
    }
  },

  getVtsState: async () => {
    return readJson("/api/vts/state", {
      status: "disabled",
      connected: false,
      authenticated: false,
      host: "127.0.0.1",
      port: 8001,
      hotkeys: 0,
      expressions: 0,
      mouth_parameter: "N/A",
      tracking_mode: "disabled",
      last_error: "Modulo VTube opcional desativado no runtime base.",
      last_expression: "",
      updated_at: Date.now() / 1000,
    });
  },
};
