import { ChatConfig, ConnectionsConfig, LlmConfig, PortabilityConfig, VisionMonitor, VoiceConfig, VoiceInputDevice, ImageConfig, OpenRouterEndpoint } from "../models/types";
import { BACKEND_URL, backendFetch, readJson, readLocalConnections } from "./core";

const PROVIDER_ALIASES: Record<string, string> = {
  google_platform: "gemini_api",
  google_cloud: "gemini_api",
  google: "gemini_api",
  google_ai_studio: "gemini_api",
  gemini: "gemini_api",
  open_router: "openrouter",
  openrouters: "openrouter",
  openrouter: "openrouter",
  groq_cloud: "groq",
  groqcloud: "groq",
  glock: "groq",
  groq: "groq",
};

function normalizeProvider(provider?: string) {
  const value = String(provider || "").trim().toLowerCase();
  return PROVIDER_ALIASES[value] || value || "gemini_api";
}

export const DEFAULT_IMAGE_CONFIG: ImageConfig = {
  imageProvider: "gemini_api",
  openrouterImageModel: "sourceful/riverflow-v2.5-pro",
  openrouterReasoning: "medium",
};

export const DEFAULT_LLM_CONFIG: LlmConfig = {
  llmProvider: "gemini_api",
  llmModel: "gemini-3.1-pro-preview",
  agentProvider: "",
  agentModel: "",
  agentToolRounds: 40,
  ttsByProvider: {},
  llmFilter: "",
  llmTemperature: 0.85,
  groqThinking: true,
  qwenThinking: true,
  deepseekReasoningEffort: "",
  openrouterThinking: true,
  openrouterReasoningEffort: "",
  agentThinking: true,
  agentReasoningEffort: "",
  openrouterRoutingByModel: {},
  visionModel: "gemini-3-flash-preview",
  visionProvider: "",
  ttsProvider: "google_cloud_tts",
  ttsVoice: "pt-BR-Neural2-C",
  ttsModel: "",
  ttsLanguage: "pt-BR",
  ttsPrompt: "You are generating TTS audio in Brazilian Portuguese.\nVoice character: young adult AI assistant.\nTone: warm, playful, slightly teasing, but not childish.\nPace: medium, with natural pauses.\nAccent: neutral Brazilian Portuguese.\nDo not read these instructions aloud. Only synthesize the transcript.",
  ttsFilter: "",
  ttsSpeed: 1.0,
  ttsPitch: 0.0,
  ttsVolume: 1.0,
  ttsStreaming: false,
  ttsStability: 0.5,
  ttsSimilarity: 0.75,
  ttsStyle: 0.0,
  ttsSpeakerBoost: true,
};

function normalizeLlmConfig(config: LlmConfig): LlmConfig {
  return { ...DEFAULT_LLM_CONFIG, ...config, llmProvider: normalizeProvider(config.llmProvider) };
}

function normalizeChatConfig(config: ChatConfig): ChatConfig {
  return { ...config, provider: normalizeProvider(config.provider), openrouterRoutingByModel: config.openrouterRoutingByModel || {} };
}

function readLocalLlmConfig(): LlmConfig {
  const savedConfig = localStorage.getItem("hana_llm_config");
  return normalizeLlmConfig(savedConfig ? JSON.parse(savedConfig) : DEFAULT_LLM_CONFIG);
}

export const DEFAULT_VOICE_CONFIG: VoiceConfig = {
  sttEnabled: false,
  sttProvider: "groq_whisper",
  sttModel: "whisper-large-v3",
  sttLanguage: "pt",
  inputDeviceId: "",
  inputDeviceLabel: "",
  inputDeviceSource: "sounddevice",
  secondOutputEnabled: false,
  secondOutputDeviceId: "",
  secondOutputDeviceLabel: "",
  vadThreshold: 0.035,
  vadMode: "silero",
  vadProbThreshold: 0.5,
  bargeInEnabled: false,
  silenceTimeoutMs: 900,
  ttsEnabled: false,
  ttsProvider: "edge",
  ttsModel: "",
  ttsVoice: "pt-BR-FranciscaNeural",
  ttsLanguage: "pt-BR",
  ttsPrompt: "You are generating TTS audio in Brazilian Portuguese.\nVoice character: young adult AI assistant.\nTone: warm, playful, slightly teasing, but not childish.\nPace: medium, with natural pauses.\nAccent: neutral Brazilian Portuguese.\nDo not read these instructions aloud. Only synthesize the transcript.",
  ttsSpeed: 1,
  ttsPitch: 0,
  ttsVolume: 1,
  ttsStreaming: false,
  ttsStability: 0.5,
  ttsSimilarity: 0.75,
  ttsStyle: 0,
  ttsSpeakerBoost: true,
  speakTerminalEvents: true,
  callMode: false,
};

export const DEFAULT_PORTABILITY_CONFIG: PortabilityConfig = {
  ffmpegPath: "ffmpeg",
  mediaOutputPath: "./data",
  activeMonitor: 1,
  visionQualityProfile: "full_hd_png",
};

const VISION_QUALITY_PROFILE_IDS = new Set([
  "full_hd_png",
  "readable_jpeg",
  "fast_jpeg",
  "low_color_png",
  "grayscale_readable",
  "grayscale_fast",
]);

function normalizePortabilityConfig(config: Partial<PortabilityConfig>): PortabilityConfig {
  const merged = { ...DEFAULT_PORTABILITY_CONFIG, ...config };
  if (!VISION_QUALITY_PROFILE_IDS.has(String(merged.visionQualityProfile))) {
    merged.visionQualityProfile = DEFAULT_PORTABILITY_CONFIG.visionQualityProfile;
  }
  return merged;
}

function readLocalPortabilityConfig(): PortabilityConfig {
  const saved = localStorage.getItem("hana_portabilidade_config");
  return normalizePortabilityConfig(saved ? JSON.parse(saved) : DEFAULT_PORTABILITY_CONFIG);
}



export const ConfigApi = {
  getLlmConfig: async (): Promise<LlmConfig> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/llm`);
      if (res.ok) return normalizeLlmConfig(await res.json());
      throw new Error("Falha na API");
    } catch (error) {
      return readLocalLlmConfig();
    }
  },

  updateLlmConfig: async (config: Partial<LlmConfig>) => {
    const merged = normalizeLlmConfig({ ...readLocalLlmConfig(), ...config });
    try {
      localStorage.setItem("hana_llm_config", JSON.stringify(merged));
      await fetch(`${BACKEND_URL}/api/config/llm`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(merged)
      });
      return true;
    } catch (error) {
      console.error("Backend não conectado. Salvo apenas localmente.");
      return true;
    }
  },

  getChatConfig: async (): Promise<ChatConfig> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/chat`);
      if (res.ok) return normalizeChatConfig(await res.json());
      throw new Error("Falha na API");
    } catch (error) {
      const saved = localStorage.getItem("hana_chat_config");
      if (saved) return normalizeChatConfig(JSON.parse(saved));
      return normalizeChatConfig({ provider: "gemini_api", model: "gemini-3.1-pro-preview", nativeSearchMode: "auto", openrouterRoutingByModel: {} });
    }
  },

  updateChatConfig: async (config: Partial<ChatConfig>) => {
    try {
      const current = localStorage.getItem("hana_chat_config");
      const merged = normalizeChatConfig({ provider: "gemini_api", model: "gemini-3.1-pro-preview", nativeSearchMode: "auto", openrouterRoutingByModel: {}, ...(current ? JSON.parse(current) : {}), ...config });
      localStorage.setItem("hana_chat_config", JSON.stringify(merged));
      await fetch(`${BACKEND_URL}/api/config/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      return true;
    } catch (error) {
      return true;
    }
  },

  getOpenRouterEndpoints: async (model: string): Promise<{ endpoints: OpenRouterEndpoint[]; error?: string | null }> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/catalog/openrouter/endpoints?model=${encodeURIComponent(model)}`);
      if (res.ok) return await res.json();
    } catch {
      // The selector renders an offline state when the catalog cannot be reached.
    }
    return { endpoints: [], error: "backend_unavailable" };
  },

  getVoiceConfig: async (): Promise<VoiceConfig> => {
    try {
      const res = await backendFetch("/api/config/voice");
      if (res.ok) return { ...DEFAULT_VOICE_CONFIG, ...(await res.json()) };
      throw new Error("Falha na API");
    } catch {
      const saved = localStorage.getItem("hana_voice_config");
      return { ...DEFAULT_VOICE_CONFIG, ...(saved ? JSON.parse(saved) : {}) };
    }
  },

  updateVoiceConfig: async (config: Partial<VoiceConfig>) => {
    const current = localStorage.getItem("hana_voice_config");
    const merged = { ...DEFAULT_VOICE_CONFIG, ...(current ? JSON.parse(current) : {}), ...config };
    localStorage.setItem("hana_voice_config", JSON.stringify(merged));
    try {
      const res = await backendFetch("/api/config/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      return res.ok;
    } catch {
      return false;
    }
  },



  getVoiceCatalog: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/voice/catalog`);
      if (res.ok) return await res.json();
      throw new Error("Falha na API");
    } catch {
      return {
        sttProviders: [
          { id: "groq_whisper", label: "Groq Whisper", status: "available", requiresCredentials: true, inputModalities: ["audio"], outputModalities: ["text"] },
          { id: "gemini_audio", label: "Gemini Audio STT", status: "planned", requiresCredentials: true, inputModalities: ["audio"], outputModalities: ["text"] },
          { id: "local", label: "Local STT", status: "planned", requiresCredentials: false, inputModalities: ["audio"], outputModalities: ["text"] },
          { id: "openai", label: "OpenAI STT", status: "planned", requiresCredentials: true, inputModalities: ["audio"], outputModalities: ["text"] },
        ],
        ttsProviders: [
          { id: "edge", label: "Edge TTS", status: "active", requiresCredentials: false, inputModalities: ["text"], outputModalities: ["audio"] },
          { id: "cartesia", label: "Cartesia Sonic", status: "active", requiresCredentials: true, inputModalities: ["text"], outputModalities: ["audio"] },
          { id: "minimax", label: "Minimax TTS", status: "active", requiresCredentials: true, inputModalities: ["text"], outputModalities: ["audio"] },
          {
            id: "elevenlabs",
            label: "ElevenLabs TTS",
            status: "active",
            requiresCredentials: true,
            inputModalities: ["text"],
            outputModalities: ["audio"],
            models: ["eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2", "eleven_v3"],
            defaultModel: "eleven_flash_v2_5",
            voices: [{ id: "JBFqnCBsd6RMkjVDRZzb", label: "Documented sample voice", locale: "multilingual" }],
            defaultVoice: "JBFqnCBsd6RMkjVDRZzb",
            supportsRate: true,
            supportsPitch: false,
            supportsStability: true,
            supportsSimilarity: true,
            supportsStyle: true,
            supportsSpeakerBoost: true,
          },
          { id: "gemini_tts", label: "Gemini API TTS", status: "active", requiresCredentials: true, inputModalities: ["text"], outputModalities: ["audio"] },
          { id: "google_cloud_tts", label: "Google Cloud TTS", status: "active", requiresCredentials: true, inputModalities: ["text"], outputModalities: ["audio"] },
        ],
      };
    }
  },

  getConnectionsConfig: async (): Promise<ConnectionsConfig> => {
    return readJson("/api/config/conexoes", readLocalConnections());
  },

  updateConnectionsConfig: async (config: Partial<ConnectionsConfig>) => {
    try {
      const merged = { ...readLocalConnections(), ...config };
      localStorage.setItem("hana_conexoes_config", JSON.stringify(merged));
      const res = await fetch(`${BACKEND_URL}/api/config/conexoes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(merged),
      });
      if (res.ok) {
        const saved = await res.json();
        localStorage.setItem("hana_conexoes_config", JSON.stringify(saved));
        return saved as ConnectionsConfig;
      }
      return merged;
    } catch (error) {
      console.error("Backend não conectado. Salvo apenas localmente.");
      return { ...readLocalConnections(), ...config };
    }
  },

  getCatalog: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/catalog`);
      if (res.ok) return await res.json();
      throw new Error("Falha na API");
    } catch (error) {
      console.error("Erro ao carregar catalogo:", error);
      return null;
    }
  },

  upsertCustomModel: async (provider: string, id: string, label: string, supportsVision: boolean, supportsTools: boolean = false, supportsDocuments: boolean = false) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/catalog/custom-models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, id, label, supportsVision, supportsTools, supportsDocuments })
      });
      if (!res.ok) return null;
      const data = await res.json();
      return data.model || null;
    } catch (error) {
      console.error("Erro ao salvar modelo customizado:", error);
      return null;
    }
  },

  deleteCustomModel: async (provider: string, id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/catalog/custom-models`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, id })
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao remover modelo customizado:", error);
      return false;
    }
  },

  /**
   * Fetches portability configuration from backend or local storage.
   */
  getPortabilityConfig: async (): Promise<PortabilityConfig> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/portabilidade`);
      if (res.ok) return normalizePortabilityConfig(await res.json());
      throw new Error("Failed to fetch from backend API");
    } catch (error) {
      return readLocalPortabilityConfig();
    }
  },

  /**
   * Updates portability configuration on the backend and local storage.
   */
  updatePortabilityConfig: async (config: Partial<PortabilityConfig>): Promise<boolean> => {
    const merged = normalizePortabilityConfig({ ...readLocalPortabilityConfig(), ...config });
    try {
      localStorage.setItem("hana_portabilidade_config", JSON.stringify(merged));
      const res = await fetch(`${BACKEND_URL}/api/config/portabilidade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      return res.ok;
    } catch (error) {
      console.error("Backend not connected. Saved portability config locally.", error);
      return true;
    }
  },

  /**
   * Fetches active display monitors from the backend environment.
   */
  getVisionMonitors: async (): Promise<VisionMonitor[]> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/visao/monitors`);
      if (res.ok) {
        const data = await res.json();
        return data.monitors || [];
      }
      throw new Error("Failed to fetch monitors from backend API");
    } catch (error) {
      return [{ id: 1, label: "Monitor 1 (1920x1080)", width: 1920, height: 1080 }];
    }
  },

  /**
   * Fetches list of system microphone input devices.
   */
  getVoiceInputDevices: async (): Promise<VoiceInputDevice[]> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/voice/input-devices`);
      if (res.ok) {
        const data = await res.json();
        return data.devices || [];
      }
      throw new Error("Failed to fetch input devices");
    } catch (error) {
      console.error("Error fetching voice input devices", error);
      return [{ id: "browser_default", label: "Browser default microphone", source: "browser_media_recorder", isDefault: true, available: true }];
    }
  },

  getVoiceOutputDevices: async (): Promise<VoiceInputDevice[]> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/voice/output-devices`);
      if (res.ok) {
        const data = await res.json();
        return data.devices || [];
      }
      throw new Error("Failed to fetch output devices");
    } catch (error) {
      console.error("Error fetching voice output devices", error);
      return [];
    }
  },

  /** Get image generation provider configuration. */
  getImageConfig: async (): Promise<ImageConfig> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/image`);
      if (res.ok) return { ...DEFAULT_IMAGE_CONFIG, ...(await res.json()) };
      throw new Error("Failed to fetch image config");
    } catch {
      const saved = localStorage.getItem("hana_image_config");
      return { ...DEFAULT_IMAGE_CONFIG, ...(saved ? JSON.parse(saved) : {}) };
    }
  },

  /** Update image generation provider configuration. */
  updateImageConfig: async (config: Partial<ImageConfig>): Promise<boolean> => {
    const current = localStorage.getItem("hana_image_config");
    const merged = { ...DEFAULT_IMAGE_CONFIG, ...(current ? JSON.parse(current) : {}), ...config };
    localStorage.setItem("hana_image_config", JSON.stringify(merged));
    try {
      const res = await fetch(`${BACKEND_URL}/api/config/image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      return res.ok;
    } catch {
      return false;
    }
  },
};
