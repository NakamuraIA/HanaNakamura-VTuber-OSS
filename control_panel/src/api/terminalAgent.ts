import { TerminalAgentEvent, TerminalAgentEventsResponse, TerminalAgentSpeechResponse, TerminalAgentTextResponse, TerminalAgentTranscriptionResponse, VoiceConfig, VoiceInputDevice, VoiceRuntimeStatus } from "../models/types";
import { backendFetch } from "./core";

const LOCAL_TERMINAL_CONFIG_KEY = "hana_terminal_agent_config";

const DEFAULT_TERMINAL_AGENT_CONFIG: VoiceConfig = {
  sttEnabled: false,
  sttProvider: "groq_whisper",
  sttModel: "whisper-large-v3",
  sttLanguage: "pt",
  inputDeviceId: "",
  inputDeviceLabel: "",
  inputDeviceSource: "sounddevice",
  vadThreshold: 0.035,
  silenceTimeoutMs: 900,
  ttsEnabled: false,
  ttsProvider: "edge",
  ttsModel: "",
  ttsVoice: "pt-BR-FranciscaNeural",
  ttsLanguage: "pt-BR",
  ttsSpeed: 1,
  ttsPitch: 0,
  ttsVolume: 1,
  ttsStability: 0.5,
  ttsSimilarity: 0.75,
  ttsStyle: 0,
  ttsSpeakerBoost: true,
  speakTerminalEvents: false,
};

function audioFileName(mimeType: string) {
  if (mimeType.includes("ogg")) return "terminal-agent-stt.ogg";
  if (mimeType.includes("mp4")) return "terminal-agent-stt.m4a";
  if (mimeType.includes("wav")) return "terminal-agent-stt.wav";
  return "terminal-agent-stt.webm";
}

function localConfig(): VoiceConfig {
  try {
    const data = JSON.parse(localStorage.getItem(LOCAL_TERMINAL_CONFIG_KEY) || "{}");
    return { ...DEFAULT_TERMINAL_AGENT_CONFIG, ...data };
  } catch {
    return DEFAULT_TERMINAL_AGENT_CONFIG;
  }
}

export const TerminalAgentApi = {
  getTerminalAgentConfig: async (): Promise<VoiceConfig> => {
    try {
      const res = await backendFetch("/api/config/voice");
      if (res.ok) return { ...DEFAULT_TERMINAL_AGENT_CONFIG, ...await res.json() };
      throw new Error("Falha na API");
    } catch {
      return localConfig();
    }
  },

  updateTerminalAgentConfig: async (payload: Partial<VoiceConfig>): Promise<boolean> => {
    const merged = { ...localConfig(), ...payload };
    localStorage.setItem(LOCAL_TERMINAL_CONFIG_KEY, JSON.stringify(merged));

    try {
      const res = await backendFetch("/api/config/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(merged),
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  getTerminalAgentEvents: async (limit = 200): Promise<TerminalAgentEventsResponse> => {
    try {
      const res = await backendFetch(`/api/terminal-agent/events?limit=${limit}`, {}, 4000);
      if (res.ok) {
        const data = await res.json();
        return { events: Array.isArray(data.events) ? data.events : [], backendAvailable: true };
      }
      throw new Error("Falha na API");
    } catch {
      return {
        events: [],
        backendAvailable: false,
        message: "Endpoint do Terminal Agente ainda indisponivel.",
      };
    }
  },

  appendTerminalAgentEvent: async (payload: Partial<TerminalAgentEvent>): Promise<TerminalAgentEvent | null> => {
    try {
      const res = await backendFetch("/api/terminal-agent/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }, 4000);
      if (res.ok) {
        const data = await res.json();
        return data.event || null;
      }
      throw new Error("Falha na API");
    } catch {
      const event: TerminalAgentEvent = {
        id: `local-${Date.now()}`,
        kind: payload.kind || "user_text",
        source: payload.source || "control_panel",
        displayText: payload.displayText || "",
        speechText: payload.speechText || "",
        toolName: payload.toolName || "",
        status: payload.status || "",
        createdAt: new Date().toISOString(),
        metadata: payload.metadata || {},
      };
      return event;
    }
  },

  clearTerminalAgentEvents: async (): Promise<boolean> => {
    try {
      const res = await backendFetch("/api/terminal-agent/clear", { method: "POST" }, 4000);
      return res.ok;
    } catch {
      return false;
    }
  },

  transcribeTerminalAgentAudio: async (
    audio: Blob,
    options: {
      provider: string;
      model?: string;
      language?: string;
      durationMs?: number;
      respond?: boolean;
    },
  ): Promise<TerminalAgentTranscriptionResponse> => {
    const formData = new FormData();
    formData.append("audio", audio, audioFileName(audio.type));
    formData.append("provider", options.provider);
    if (options.model) formData.append("model", options.model);
    if (options.language) formData.append("language", options.language);
    if (options.durationMs !== undefined) formData.append("durationMs", String(options.durationMs));
    formData.append("respond", options.respond ? "true" : "false");
    formData.append("tts", "false");

    const res = await backendFetch("/api/voice/stt/transcribe", {
      method: "POST",
      body: formData,
    }, 45000);

    const contentType = res.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await res.json() : { text: await res.text() };
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }

    const text = String(data?.text || data?.transcription || data?.transcript || data?.displayText || "").trim();
    return {
      text,
      assistantText: data?.assistantText ? String(data.assistantText) : "",
      responded: Boolean(data?.responded),
      provider: String(data?.provider || options.provider),
      model: data?.model ? String(data.model) : options.model,
      language: data?.language ? String(data.language) : options.language,
      durationMs: typeof data?.durationMs === "number" ? data.durationMs : options.durationMs,
      raw: data,
    };
  },

  respondTerminalAgentText: async (
    text: string,
    options: {
      llmProvider?: string;
      llmModel?: string;
      nativeSearchMode?: string;
      safetyMode?: string;
    } = {},
  ): Promise<TerminalAgentTextResponse> => {
    const res = await backendFetch("/api/voice/text/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, ...options }),
    }, 45000);
    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return {
      ok: Boolean(data?.ok),
      text: String(data?.text || text),
      assistantText: String(data?.assistantText || ""),
      responded: Boolean(data?.responded),
      assistant: data?.assistant,
    };
  },

  sanitizeTtsText: async (text: string): Promise<string> => {
    try {
      const res = await backendFetch("/api/terminal-agent/sanitize-tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }, 4000);
      const data = await res.json();
      return data.text || "";
    } catch {
      return text
        .replace(/```[\s\S]*?```/g, " ")
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
        .replace(/https?:\/\/\S+|www\.\S+/g, " ")
        .replace(/[`*_~>#()[\]{}|\\/]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }
  },

  synthesizeTerminalAgentSpeech: async (
    text: string,
    options: {
      provider?: string;
      model?: string;
      voice?: string;
      language?: string;
      prompt?: string;
      speed?: number;
      pitch?: number;
      streaming?: boolean;
      stability?: number;
      similarity?: number;
      style?: number;
      speakerBoost?: boolean;
    } = {},
  ): Promise<TerminalAgentSpeechResponse> => {
    const res = await backendFetch("/api/voice/tts/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        provider: options.provider,
        model: options.model,
        voice: options.voice,
        language: options.language,
        prompt: options.prompt,
        speed: options.speed,
        pitch: options.pitch,
        streaming: options.streaming,
        stability: options.stability,
        similarity: options.similarity,
        style: options.style,
        speakerBoost: options.speakerBoost,
      }),
    }, 45000);

    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }

    return {
      ok: Boolean(data?.ok),
      provider: String(data?.provider || options.provider || "edge"),
      voice: String(data?.voice || options.voice || ""),
      text: String(data?.text || text),
      mimeType: String(data?.mimeType || "audio/mpeg"),
      audioBase64: String(data?.audioBase64 || ""),
      durationMs: typeof data?.durationMs === "number" ? data.durationMs : undefined,
    };
  },

  speakTerminalAgentText: async (text: string): Promise<boolean> => {
    const res = await backendFetch("/api/voice/tts/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }, 60000);
    return res.ok;
  },



  stopTerminalAgentSpeech: async (): Promise<boolean> => {
    try {
      await backendFetch("/api/voice/tts/stop", { method: "POST" }, 4000);
      return true;
    } catch {
      return false;
    }
  },

  startVoiceRuntime: async (payload: Partial<VoiceConfig> = {}): Promise<VoiceRuntimeStatus> => {
    const res = await backendFetch("/api/voice/runtime/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }, 8000);
    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data.runtime as VoiceRuntimeStatus;
  },

  configureVoiceRuntime: async (payload: Partial<VoiceConfig> = {}): Promise<VoiceRuntimeStatus> => {
    const res = await backendFetch("/api/voice/runtime/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }, 8000);
    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data.runtime as VoiceRuntimeStatus;
  },

  stopVoiceRuntime: async (reason = "control_panel"): Promise<VoiceRuntimeStatus> => {
    const res = await backendFetch("/api/voice/runtime/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }, 8000);
    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data.runtime as VoiceRuntimeStatus;
  },

  getVoiceRuntimeStatus: async (): Promise<VoiceRuntimeStatus> => {
    const res = await backendFetch("/api/voice/runtime/status", {}, 3000);
    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data.runtime as VoiceRuntimeStatus;
  },

  interruptVoiceRuntime: async (reason = "control_panel"): Promise<VoiceRuntimeStatus> => {
    const res = await backendFetch("/api/voice/runtime/interrupt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }, 8000);
    const data = await res.json();
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data.runtime as VoiceRuntimeStatus;
  },

  getVoiceInputDevices: async (): Promise<VoiceInputDevice[]> => {
    try {
      const res = await backendFetch("/api/config/voice/input-devices", {}, 5000);
      if (res.ok) {
        const data = await res.json();
        return Array.isArray(data.devices) ? data.devices : [];
      }
      return [];
    } catch {
      return [];
    }
  },
};
