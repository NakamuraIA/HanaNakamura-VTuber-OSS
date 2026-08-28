import { ChatConfig, ConnectionsConfig, LlmConfig, PortabilityConfig, TtsStreamingMode, TtsVoiceAliases, VisionMonitor, VoiceConfig, VoiceInputDevice, ImageConfig, OpenRouterEndpoint } from "../models/types";
import { normalizeProvider } from "../models/providerCatalog";
import { BACKEND_URL, backendFetch, readJson, readLocalConnections } from "./core";

export const DEFAULT_IMAGE_CONFIG: ImageConfig = {
  imageProvider: "gemini_api",
  imageModel: "sourceful/riverflow-v2.5-pro",
  openrouterReasoning: "medium",
};

function normalizeImageConfig(config: Partial<ImageConfig>): ImageConfig {
  return {
    ...DEFAULT_IMAGE_CONFIG,
    ...config,
    imageModel: String(config.imageModel || config.openrouterImageModel || DEFAULT_IMAGE_CONFIG.imageModel),
  };
}

export const DEFAULT_LLM_CONFIG: LlmConfig = {
  llmProvider: "gemini_api",
  llmModel: "gemini-3.1-pro-preview",
  llmModelByProvider: {},
  agentProvider: "",
  agentModel: "",
  agentModelByProvider: {},
  agentToolRounds: 40,
  ttsByProvider: {},
  llmFilter: "",
  llmTemperature: 0.85,
  groqThinking: true,
  qwenThinking: true,
  qwenRegion: "virginia",
  deepseekReasoningEffort: "",
  openrouterThinking: true,
  openrouterReasoningEffort: "",
  agentThinking: true,
  agentReasoningEffort: "",
  openrouterRoutingByModel: {},
  visionModel: "gemini-3-flash-preview",
  visionModelByProvider: {},
  visionProvider: "",
  ttsProvider: "edge",
  ttsVoice: "pt-BR-FranciscaNeural",
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

function normalizeModelByProvider(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .map(([provider, model]) => [String(provider || "").trim(), String(model || "").trim()])
      .filter(([provider, model]) => Boolean(provider && model))
      .map(([provider, model]) => [normalizeProvider(provider), model]),
  );
}

function normalizeLlmConfig(config: LlmConfig): LlmConfig {
  const merged = { ...DEFAULT_LLM_CONFIG, ...config };
  return {
    ...merged,
    llmProvider: normalizeProvider(merged.llmProvider),
    llmModelByProvider: normalizeModelByProvider(merged.llmModelByProvider),
    agentModelByProvider: normalizeModelByProvider(merged.agentModelByProvider),
    visionModelByProvider: normalizeModelByProvider(merged.visionModelByProvider),
  };
}

function normalizeChatConfig(config: ChatConfig): ChatConfig {
  return { ...config, provider: normalizeProvider(config.provider), openrouterRoutingByModel: config.openrouterRoutingByModel || {} };
}

const LLM_CONFIG_CACHE_KEY = "hana_llm_config";
const LLM_CONFIG_PENDING_KEY = "hana_llm_config_pending";
let lastSyncedLlmConfig: LlmConfig | null = null;

function readLocalLlmConfig(): LlmConfig {
  const savedConfig = localStorage.getItem(LLM_CONFIG_CACHE_KEY);
  return normalizeLlmConfig(savedConfig ? JSON.parse(savedConfig) : DEFAULT_LLM_CONFIG);
}

function readPendingLlmConfig(): Partial<LlmConfig> {
  const pending = localStorage.getItem(LLM_CONFIG_PENDING_KEY);
  return pending ? JSON.parse(pending) : {};
}

function writePendingLlmConfig(config: Partial<LlmConfig>): void {
  if (Object.keys(config).length > 0) {
    localStorage.setItem(LLM_CONFIG_PENDING_KEY, JSON.stringify(config));
  } else {
    localStorage.removeItem(LLM_CONFIG_PENDING_KEY);
  }
}

function clearSyncedLlmFields(sent: Partial<LlmConfig>): void {
  const latest = readPendingLlmConfig();
  for (const key of Object.keys(sent) as Array<keyof LlmConfig>) {
    if (JSON.stringify(latest[key]) === JSON.stringify(sent[key])) delete latest[key];
  }
  writePendingLlmConfig(latest);
}

function changedLlmFields(config: Partial<LlmConfig>): Partial<LlmConfig> {
  if (!lastSyncedLlmConfig) return config;
  const changed: Partial<LlmConfig> = {};
  for (const key of Object.keys(config) as Array<keyof LlmConfig>) {
    if (JSON.stringify(config[key]) !== JSON.stringify(lastSyncedLlmConfig[key])) {
      (changed as Record<string, unknown>)[key] = config[key];
    }
  }
  return changed;
}

async function postPendingLlmConfig(pending: Partial<LlmConfig>): Promise<LlmConfig> {
  const res = await backendFetch("/api/config/llm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pending),
  });
  if (!res.ok) throw new Error("Falha ao sincronizar a configuração da LLM.");
  const saved = normalizeLlmConfig(await res.json());
  lastSyncedLlmConfig = saved;
  clearSyncedLlmFields(pending);
  const visible = normalizeLlmConfig({ ...saved, ...readPendingLlmConfig() });
  localStorage.setItem(LLM_CONFIG_CACHE_KEY, JSON.stringify(visible));
  return visible;
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
  ttsStreamingMode: "off",
  ttsStability: 0.5,
  ttsSimilarity: 0.75,
  ttsStyle: 0,
  ttsSpeakerBoost: true,
  speakTerminalEvents: true,
  callMode: false,
};

const TTS_STREAMING_MODES = new Set<TtsStreamingMode>(["off", "sentences", "audio"]);

function normalizeVoiceConfig(config: Partial<VoiceConfig>): VoiceConfig {
  const rawMode = String(config.ttsStreamingMode || "") as TtsStreamingMode;
  const mode = TTS_STREAMING_MODES.has(rawMode) ? rawMode : (config.ttsStreaming ? "sentences" : "off");
  return { ...DEFAULT_VOICE_CONFIG, ...config, ttsStreamingMode: mode, ttsStreaming: mode !== "off" };
}

export const DEFAULT_PORTABILITY_CONFIG: PortabilityConfig = {
  ffmpegPath: "ffmpeg",
  mediaOutputPath: "./data",
  activeMonitor: 1,
  visionQualityProfile: "readable_jpeg",
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
    const pending = readPendingLlmConfig();
    try {
      if (Object.keys(pending).length > 0) return await postPendingLlmConfig(pending);
      const res = await backendFetch("/api/config/llm");
      if (res.ok) {
        const saved = normalizeLlmConfig(await res.json());
        lastSyncedLlmConfig = saved;
        localStorage.setItem(LLM_CONFIG_CACHE_KEY, JSON.stringify(saved));
        return saved;
      }
      throw new Error("Falha na API");
    } catch {
      return normalizeLlmConfig({ ...readLocalLlmConfig(), ...pending });
    }
  },

  updateLlmConfig: async (config: Partial<LlmConfig>) => {
    const pending = { ...readPendingLlmConfig(), ...changedLlmFields(config) };
    const local = normalizeLlmConfig({ ...readLocalLlmConfig(), ...config, ...pending });
    localStorage.setItem(LLM_CONFIG_CACHE_KEY, JSON.stringify(local));
    writePendingLlmConfig(pending);
    if (Object.keys(pending).length === 0) return true;
    try {
      await postPendingLlmConfig(pending);
      return true;
    } catch {
      console.error("Configuração da LLM pendente de sincronização com a Hana.");
      return false;
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
      const res = await fetch(`${BACKEND_URL}/api/config/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      return res.ok;
    } catch (error) {
      return false;
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
      if (res.ok) return normalizeVoiceConfig(await res.json());
      throw new Error("Falha na API");
    } catch {
      const saved = localStorage.getItem("hana_voice_config");
      return normalizeVoiceConfig(saved ? JSON.parse(saved) : {});
    }
  },

  updateVoiceConfig: async (config: Partial<VoiceConfig>) => {
    const current = localStorage.getItem("hana_voice_config");
    const previous = current ? JSON.parse(current) : {};
    const compatibilityMode = "ttsStreaming" in config && !("ttsStreamingMode" in config)
      ? (config.ttsStreaming ? "sentences" : "off")
      : config.ttsStreamingMode;
    const merged = normalizeVoiceConfig({ ...previous, ...config, ...(compatibilityMode ? { ttsStreamingMode: compatibilityMode } : {}) });
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

  getTtsVoiceAliases: async (): Promise<TtsVoiceAliases> => {
    try {
      const res = await backendFetch("/api/config/voice/aliases");
      return res.ok ? await res.json() : {};
    } catch {
      return {};
    }
  },

  saveTtsVoiceAlias: async (provider: string, voiceId: string, name: string): Promise<TtsVoiceAliases> => {
    const res = await backendFetch("/api/config/voice/aliases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, voiceId, name }),
    });
    if (!res.ok) throw new Error("Não foi possível salvar o nome da voz.");
    return await res.json();
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
          { id: "edge", label: "Edge TTS", status: "active", requiresCredentials: false, inputModalities: ["text"], outputModalities: ["audio"], supportsStreaming: true },
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
            supportsStreaming: true,
          },
          {
            id: "fishaudio",
            label: "Fish Audio TTS",
            status: "active",
            requiresCredentials: true,
            inputModalities: ["text"],
            outputModalities: ["audio"],
            models: ["s2.1-pro-free", "s2.1-pro", "s2-pro", "s1"],
            defaultModel: "s2.1-pro-free",
            supportsRate: true,
            supportsStreaming: true,
          },
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
      return false;
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
      if (res.ok) return normalizeImageConfig(await res.json());
      throw new Error("Failed to fetch image config");
    } catch {
      const saved = localStorage.getItem("hana_image_config");
      return normalizeImageConfig(saved ? JSON.parse(saved) : {});
    }
  },

  /** Update image generation provider configuration. */
  updateImageConfig: async (config: Partial<ImageConfig>): Promise<boolean> => {
    const current = localStorage.getItem("hana_image_config");
    const merged = normalizeImageConfig({ ...(current ? JSON.parse(current) : {}), ...config });
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
