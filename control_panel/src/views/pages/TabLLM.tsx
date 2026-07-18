import { useEffect, useMemo, useState } from "react";
import { ApiController } from "../../controllers/api";
import { LlmConfig, ImageConfig } from "../../models/types";
import { 
  LLM_PROVIDERS, 
  TTS_PROVIDERS, 
  MODEL_CATALOG, 
  VOICE_CATALOG, 
  ModelSpec,
  VoiceSpec,
} from "../../models/providerCatalog";

import { BrainCircuit, Eye, Mic, Plus, Save, Play, Trash2, Image as ImageIcon, Bot } from "lucide-react";
import { useAudioUI } from "../../hooks/useAudioUI";
import { TabHeader } from "../components/shared/TabHeader";
import { Card } from "../components/shared/Card";
import { Button } from "../components/shared/Button";
import { CatalogPicker, CatalogPickerOption } from "../components/shared/CatalogPicker";
import { DEFAULT_OPENROUTER_ROUTING, OpenRouterEndpointPicker } from "../components/shared/OpenRouterEndpointPicker";
import { readRememberedVoices, rememberVoice } from "../../models/voiceMemory";

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

const TTS_MODELS_BY_PROVIDER: Record<string, string[]> = {
  gemini_tts: ["gemini-3.1-flash-tts-preview"],
  elevenlabs: ["eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2", "eleven_v3"],
  fishaudio: ["s2.1-pro-free", "s2.1-pro", "s2-pro", "s1"],
};

// Escala unificada de raciocinio do OpenRouter. "" = automatico (chat pensa fundo,
// voz/terminal pensam pouco); um nivel explicito fixa o esforco em todos os canais.
const OPENROUTER_REASONING_LEVELS: { value: string; label: string }[] = [
  { value: "", label: "Auto" },
  { value: "none", label: "Desligado" },
  { value: "minimal", label: "Minimo" },
  { value: "low", label: "Baixo" },
  { value: "medium", label: "Medio" },
  { value: "high", label: "Alto" },
  { value: "max", label: "Maximo" },
];

// DeepSeek so tem 2 niveis reais (a API deles mapeia low/medium -> high, e xhigh -> max).
const DEEPSEEK_REASONING_LEVELS: { value: string; label: string }[] = [
  { value: "off", label: "Desligado" },
  { value: "high", label: "Alto" },
  { value: "max", label: "Maximo" },
];

function normalizeProvider(provider?: string) {
  const value = String(provider || "").trim().toLowerCase();
  return PROVIDER_ALIASES[value] || value || "gemini_api";
}

function pricePerMillion(value: unknown): string {
  /** OpenRouter reports price PER TOKEN; humans read price per 1M tokens. */
  const n = Number(value);
  if (!Number.isFinite(n)) return "?";
  const perM = n * 1_000_000;
  if (perM === 0) return "$0";
  if (perM >= 100) return `$${perM.toFixed(0)}`;
  if (perM < 0.01) return "<$0.01"; // evita mostrar "$0.00" pra modelo pago
  return `$${perM.toFixed(2)}`;
}

function priceLabel(model?: ModelSpec) {
  const pricing = model?.pricing || {};
  if (model?.free) return "grátis";
  const hasIn = pricing.prompt != null && pricing.prompt !== "";
  const hasOut = pricing.completion != null && pricing.completion !== "";
  if (!hasIn && !hasOut) return "";
  if (Number(pricing.prompt) === 0 && Number(pricing.completion) === 0) return "grátis";
  return `in ${pricePerMillion(pricing.prompt)} / out ${pricePerMillion(pricing.completion)} /M`;
}

function modelPriceScore(model: ModelSpec) {
  /** Convert provider pricing fields into one sortable score within that provider. */
  if (model.free) return 0;
  const prompt = Number(model.pricing?.prompt);
  const completion = Number(model.pricing?.completion);
  const values = [prompt, completion].filter((value) => Number.isFinite(value) && value >= 0);
  return values.length > 0 ? values.reduce((total, value) => total + value, 0) : null;
}

function modelCapabilityScore(model: ModelSpec) {
  /** Rank catalog richness without making subjective quality claims. */
  return [
    model.supportsVision,
    model.supportsDocuments,
    model.supportsTools,
    model.supportsNativeSearch,
    (model.inputModalities?.length || 0) > 2,
    (model.supportedParameters?.length || 0) > 2,
  ].filter(Boolean).length;
}

function modelPickerOption(model: ModelSpec): CatalogPickerOption {
  /** Convert backend model metadata into the shared searchable picker contract. */
  const badges: CatalogPickerOption["badges"] = [];
  if (model.supportsVision) badges.push({ label: "vision", tone: "green" });
  if (model.supportsDocuments) badges.push({ label: "docs", tone: "blue" });
  if (model.supportsTools) badges.push({ label: "tools", tone: "cyan" });
  if (model.supportsNativeSearch) badges.push({ label: "web", tone: "amber" });
  if ((model.outputModalities || []).includes("image")) badges.push({ label: "imagem", tone: "pink" });
  if (model.custom) badges.push({ label: "custom", tone: "purple" });

  return {
    value: model.id,
    label: model.label,
    favoriteId: `${model.provider}:${model.id}`,
    secondary: model.id,
    description: model.description,
    free: model.free,
    priceScore: modelPriceScore(model),
    priceLabel: priceLabel(model),
    contextTokens: model.maxInputTokens,
    capabilityScore: modelCapabilityScore(model),
    supportsVision: model.supportsVision,
    supportsTools: model.supportsTools,
    supportsDocuments: model.supportsDocuments,
    badges,
  };
}

function ensureCurrentOption(options: CatalogPickerOption[], value: string, namespace: string): CatalogPickerOption[] {
  /** Preserve manually configured IDs that are not present in the current endpoint catalog. */
  if (!value || options.some((option) => option.value === value)) return options;
  const customOption: CatalogPickerOption = {
    value,
    label: `${value} (custom)`,
    favoriteId: `${namespace}:${value}`,
    secondary: value,
    badges: [{ label: "custom", tone: "purple" }],
  };
  return [
    ...options,
    customOption,
  ];
}

export function TabLLM() {
  const [config, setConfig] = useState<LlmConfig | null>(null);
  const [imageConfig, setImageConfig] = useState<ImageConfig | null>(null);
  const [catalogModels, setCatalogModels] = useState<ModelSpec[]>(MODEL_CATALOG);
  const [catalogVoices, setCatalogVoices] = useState<VoiceSpec[]>(VOICE_CATALOG);
  const [rememberedVoices, setRememberedVoices] = useState<string[]>([]);
  const [llmProviders, setLlmProviders] = useState<string[]>(LLM_PROVIDERS);
  const [ttsProviders, setTtsProviders] = useState<string[]>(TTS_PROVIDERS);
  const [imageProviders, setImageProviders] = useState<string[]>(["gemini_api", "openrouter"]);
  const [customModelId, setCustomModelId] = useState("");
  const [customModelLabel, setCustomModelLabel] = useState("");
  const [customModelVision, setCustomModelVision] = useState(true);
  const [customModelDocuments, setCustomModelDocuments] = useState(false);
  const [customModelTools, setCustomModelTools] = useState(false);
  const [catalogStatus, setCatalogStatus] = useState("");
  const [ttsTestStatus, setTtsTestStatus] = useState("");
  const audio = useAudioUI();

  useEffect(() => {
    Promise.all([ApiController.getLlmConfig(), ApiController.getImageConfig(), ApiController.getCatalog()])
      .then(([loadedConfig, loadedImageConfig, catalog]) => {
        const models = catalog?.models || MODEL_CATALOG;
        const provider = normalizeProvider(loadedConfig.llmProvider);
        const providerModels = models.filter((item: ModelSpec) => item.provider === provider);
        const llmModel = providerModels.some((item: ModelSpec) => item.id === loadedConfig.llmModel)
          ? loadedConfig.llmModel
          : (providerModels[0]?.id || loadedConfig.llmModel);
        const visionModel = providerModels.some((item: ModelSpec) => item.id === loadedConfig.visionModel && item.supportsVision)
          ? loadedConfig.visionModel
          : (providerModels.find((item: ModelSpec) => item.supportsVision)?.id || loadedConfig.visionModel);
        setConfig({ ...loadedConfig, llmProvider: provider, llmModel, visionModel });
        setImageConfig(loadedImageConfig);
        if (!catalog) return;
        setCatalogModels(models);
        setCatalogVoices(catalog.voices || VOICE_CATALOG);
        setLlmProviders(catalog.llmProviders || LLM_PROVIDERS);
        setTtsProviders(catalog.ttsProviders || TTS_PROVIDERS);
        setImageProviders(catalog.imageProviders || ["gemini_api", "openrouter"]);
      })
      .catch(console.error);
  }, []);

  const availableLlmModels = useMemo(
    () => catalogModels.filter((model) => model.provider === config?.llmProvider && (model.outputModalities || []).includes("text")),
    [catalogModels, config?.llmProvider],
  );
  // Provider de visão: pode ser SEPARADO do chat (pra rotear imagem pra ele quando
  // o chat não vê). Vazio = usar o mesmo do chat (comportamento antigo preservado).
  const visionProvider = (config?.visionProvider || config?.llmProvider || "") as string;
  const availableVisionModels = useMemo(
    () => catalogModels.filter((model) => model.provider === visionProvider && model.supportsVision),
    [catalogModels, visionProvider],
  );
  const availableTtsVoices = useMemo(
    () => catalogVoices.filter((voice) => voice.provider === config?.ttsProvider),
    [catalogVoices, config?.ttsProvider],
  );
  useEffect(() => {
    setRememberedVoices(readRememberedVoices(config?.ttsProvider || ""));
  }, [config?.ttsProvider]);
  const availableTtsModels = useMemo(
    () => TTS_MODELS_BY_PROVIDER[config?.ttsProvider || ""] || [],
    [config?.ttsProvider],
  );
  const availableImageModels = useMemo(
    () => catalogModels.filter((model) => model.provider === imageConfig?.imageProvider && (model.outputModalities || []).includes("image")),
    [catalogModels, imageConfig?.imageProvider],
  );
  const llmPickerOptions = useMemo(
    () => ensureCurrentOption(availableLlmModels.map(modelPickerOption), config?.llmModel || "", config?.llmProvider || "llm"),
    [availableLlmModels, config?.llmModel, config?.llmProvider],
  );
  const visionPickerOptions = useMemo(
    () => ensureCurrentOption(availableVisionModels.map(modelPickerOption), config?.visionModel || "", `${visionProvider || "llm"}:vision`),
    [availableVisionModels, visionProvider, config?.visionModel],
  );
  // Effective agent provider: blank means "same as the main provider".
  const agentProvider = (config?.agentProvider || config?.llmProvider || "") as string;
  const availableAgentModels = useMemo(
    () => catalogModels.filter((model) => model.provider === agentProvider && (model.outputModalities || []).includes("text")),
    [catalogModels, agentProvider],
  );
  const agentPickerOptions = useMemo(
    () => ensureCurrentOption(availableAgentModels.map(modelPickerOption), config?.agentModel || "", `${agentProvider || "llm"}:agent`),
    [availableAgentModels, config?.agentModel, agentProvider],
  );
  const ttsVoicePickerOptions = useMemo(() => {
    const provider = config?.ttsProvider || "tts";
    const known = new Set(availableTtsVoices.map((voice) => voice.id));
    const options: CatalogPickerOption[] = [
      {
        value: "",
        label: "Padrao do provider",
        favoriteId: `${provider}:default`,
      },
      ...availableTtsVoices.map((voice) => ({
        value: voice.id,
        label: voice.label,
        favoriteId: `${voice.provider}:${voice.id}`,
        secondary: voice.id,
      })),
      // Vozes que o usuario ja colou antes (persistidas), pra nao re-copiar do ElevenLabs.
      ...rememberedVoices
        .filter((id) => id && !known.has(id))
        .map((id) => ({
          value: id,
          label: id,
          favoriteId: `${provider}:${id}`,
          secondary: id,
          badges: [{ label: "salva", tone: "purple" as const }],
        })),
    ];
    return ensureCurrentOption(options, config?.ttsVoice || "", provider);
  }, [availableTtsVoices, config?.ttsProvider, config?.ttsVoice, rememberedVoices]);
  const ttsModelPickerOptions = useMemo(() => {
    const options: CatalogPickerOption[] = [
      { value: "", label: "Padrao do provider", favoriteId: `${config?.ttsProvider || "tts"}:default-model` },
      ...availableTtsModels.map((model) => ({
        value: model,
        label: model,
        favoriteId: `${config?.ttsProvider || "tts"}:${model}`,
        secondary: model,
      })),
    ];
    return ensureCurrentOption(options, config?.ttsModel || "", config?.ttsProvider || "tts");
  }, [availableTtsModels, config?.ttsModel, config?.ttsProvider]);
  const imagePickerOptions = useMemo(() => {
    const options: CatalogPickerOption[] = [
      {
        value: "",
        label: "Padrao do provider",
        favoriteId: `${imageConfig?.imageProvider || "image"}:default`,
      },
      ...availableImageModels.map(modelPickerOption),
    ];
    return ensureCurrentOption(options, imageConfig?.openrouterImageModel || "", imageConfig?.imageProvider || "image");
  }, [availableImageModels, imageConfig?.imageProvider, imageConfig?.openrouterImageModel]);

  const handleSave = () => {
    const promises = [];
    if (config) promises.push(ApiController.updateLlmConfig(config));
    if (imageConfig) promises.push(ApiController.updateImageConfig(imageConfig));

    if (promises.length > 0) {
      Promise.all(promises).then(() => {
        alert("Configurações salvas com sucesso!");
      });
    }
  };

  if (!config || !imageConfig) {
    return <div className="w-full h-full flex items-center justify-center"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--purple-neon)]"></div></div>;
  }

  const updateField = <K extends keyof LlmConfig>(field: K, value: LlmConfig[K]) => {
    setConfig(prev => prev ? { ...prev, [field]: value } : prev);
    audio.playClick();
  };

  const updateImageField = <K extends keyof ImageConfig>(field: K, value: ImageConfig[K]) => {
    setImageConfig(prev => prev ? { ...prev, [field]: value } : prev);
    audio.playClick();
  };

  const selectLlmProvider = (providerValue: string) => {
    const provider = normalizeProvider(providerValue);
    const providerModels = catalogModels.filter((item) => item.provider === provider && (item.outputModalities || []).includes("text"));
    const firstModel = providerModels[0];
    const firstVisionModel = providerModels.find((item) => item.supportsVision);
    setConfig(prev => prev ? {
      ...prev,
      llmProvider: provider,
      llmModel: firstModel?.id || "",
      visionModel: firstVisionModel?.id || "",
    } : prev);
    audio.playClick();
  };

  const selectVisionProvider = (providerValue: string) => {
    // "" = mesmo do chat. Ao trocar, escolhe o 1º modelo com visão desse provider.
    const provider = providerValue ? normalizeProvider(providerValue) : "";
    const effective = provider || (config?.llmProvider || "");
    const firstVisionModel = catalogModels.find((item) => item.provider === effective && item.supportsVision);
    setConfig(prev => prev ? {
      ...prev,
      visionProvider: provider,
      visionModel: firstVisionModel?.id || prev.visionModel || "",
    } : prev);
    audio.playClick();
  };

  // Keeps chat TTS defaults valid when the provider changes.
  // Campos de TTS que pertencem a cada provider (voz custom, controles, etc).
  const TTS_PROVIDER_FIELDS = [
    "ttsModel", "ttsVoice", "ttsLanguage", "ttsSpeed", "ttsPitch", "ttsStreaming",
    "ttsStability", "ttsSimilarity", "ttsStyle", "ttsSpeakerBoost",
  ] as const;

  const TTS_PROVIDER_DEFAULTS: Record<string, Partial<LlmConfig>> = {
    gemini_tts: { ttsModel: "gemini-3.1-flash-tts-preview", ttsVoice: "Leda", ttsLanguage: "pt-BR", ttsStreaming: false },
    google_cloud_tts: { ttsModel: "", ttsVoice: "pt-BR-Neural2-C", ttsLanguage: "pt-BR", ttsSpeed: 1, ttsPitch: 0 },
    edge: { ttsModel: "", ttsVoice: "pt-BR-FranciscaNeural", ttsLanguage: "pt-BR", ttsSpeed: 1, ttsPitch: 0, ttsStreaming: false },
    elevenlabs: {
      ttsModel: "eleven_flash_v2_5", ttsVoice: "JBFqnCBsd6RMkjVDRZzb", ttsLanguage: "pt",
      ttsSpeed: 1, ttsPitch: 0, ttsStreaming: false,
      ttsStability: 0.5, ttsSimilarity: 0.75, ttsStyle: 0, ttsSpeakerBoost: true,
    },
    fishaudio: {
      // Voz vazia = padrao da Fish. Cole um reference_id (voz clonada/publica do site) no campo Voz.
      ttsModel: "s2.1-pro-free", ttsVoice: "", ttsLanguage: "pt",
      ttsSpeed: 1, ttsPitch: 0, ttsStreaming: false,
    },
  };

  const updateChatTtsProvider = (provider: string) => {
    setConfig(prev => {
      if (!prev) return prev;
      // 1) Snapshot do provider atual: a voz custom/controles ficam guardados.
      const snapshot: Partial<LlmConfig> = {};
      for (const field of TTS_PROVIDER_FIELDS) (snapshot as any)[field] = prev[field];
      const ttsByProvider = { ...(prev.ttsByProvider || {}), [prev.ttsProvider]: snapshot };
      // 2) Restaura o que foi salvo pro novo provider; senão usa os defaults dele.
      const restored = ttsByProvider[provider] || TTS_PROVIDER_DEFAULTS[provider] || {};
      return { ...prev, ...TTS_PROVIDER_DEFAULTS[provider], ...restored, ttsProvider: provider, ttsByProvider };
    });
    audio.playClick();
  };

  const playChatTtsTest = async () => {
    if (!config) return;
    audio.playClick();
    setTtsTestStatus("Gerando teste de TTS do Chat...");
    await ApiController.updateLlmConfig(config);
    try {
      const result = await ApiController.synthesizeTerminalAgentSpeech("Oi, Operador. Este e um teste da TTS do Chat do Controle.", {
        provider: config.ttsProvider,
        model: config.ttsModel,
        voice: config.ttsVoice,
        language: config.ttsLanguage,
        prompt: config.ttsPrompt,
        speed: config.ttsSpeed,
        pitch: config.ttsPitch,
        streaming: config.ttsStreaming,
        stability: config.ttsStability,
        similarity: config.ttsSimilarity,
        style: config.ttsStyle,
        speakerBoost: config.ttsSpeakerBoost,
      });
      const player = new Audio(`data:${result.mimeType};base64,${result.audioBase64}`);
      player.volume = Math.max(0, Math.min(1, config.ttsVolume));
      await player.play();
      setTtsTestStatus(`Teste gerado com ${result.provider} / ${result.voice}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "falha desconhecida";
      setTtsTestStatus(`Falha no teste: ${message}`);
    }
  };

  // Helper arrays dinâmicos
  const handleAddCustomModel = async () => {
    const id = customModelId.trim();
    const label = customModelLabel.trim() || id;
    if (!id) {
      setCatalogStatus("Digite o ID do modelo.");
      return;
    }

    const saved = await ApiController.upsertCustomModel(config.llmProvider, id, label, customModelVision, customModelTools, customModelDocuments);
    if (!saved) {
      setCatalogStatus("Nao foi possivel salvar o modelo customizado.");
      return;
    }

    setCatalogModels(prev => [
      ...prev.filter(model => !(model.provider === saved.provider && model.id === saved.id)),
      saved,
    ]);
    setConfig(prev => prev ? {
      ...prev,
      llmModel: saved.id,
      visionModel: saved.supportsVision ? (prev.visionModel || saved.id) : prev.visionModel,
    } : prev);
    setCustomModelId("");
    setCustomModelLabel("");
    setCustomModelDocuments(false);
    setCustomModelTools(false);
    setCatalogStatus("Modelo customizado salvo.");
    audio.playClick();
  };

  const handleRemoveSelectedCustomModel = async () => {
    const selected = catalogModels.find(model => model.provider === config.llmProvider && model.id === config.llmModel);
    if (!selected?.custom) return;
    if (!confirm(`Remover o modelo customizado "${selected.id}"?`)) return;

    const ok = await ApiController.deleteCustomModel(selected.provider, selected.id);
    if (!ok) {
      setCatalogStatus("Nao foi possivel remover o modelo customizado.");
      return;
    }

    setCatalogModels(prev => prev.filter(model => !(model.provider === selected.provider && model.id === selected.id)));
    setConfig(prev => prev ? {
      ...prev,
      llmModel: "",
      visionModel: prev.visionModel === selected.id ? "" : prev.visionModel,
    } : prev);
    setCatalogStatus("Modelo customizado removido.");
    audio.playClick();
  };

  const selectedLlmModel = availableLlmModels.find(m => m.id === config.llmModel);
  const selectedPriceLabel = priceLabel(selectedLlmModel);
  const nonGeminiActive = config.llmProvider !== "gemini_api";

  const ttsUsesSpeed = config.ttsProvider !== "gemini_tts";
  const ttsUsesPitch = !["gemini_tts", "cartesia", "elevenlabs"].includes(config.ttsProvider);
  const ttsUsesPrompt = config.ttsProvider === "gemini_tts";
  const ttsCanStream = config.ttsProvider === "google_cloud_tts" || config.ttsProvider === "fishaudio";
  const ttsIsElevenLabs = config.ttsProvider === "elevenlabs";
  const ttsIsFishAudio = config.ttsProvider === "fishaudio";

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] backdrop-blur-2xl p-8 overflow-y-auto custom-scrollbar flex flex-col relative shadow-2xl transition-all duration-500">
      
      {/* HEADER */}
      <TabHeader
        icon={<BrainCircuit size={24} />}
        title="Cérebro & Voz"
        subtitle="IA e voz da Hana — mudanças em tempo real"
        actions={
          <div className="flex items-center gap-3 bg-black/40 border border-white/10 p-3 rounded-[var(--radius-control)] px-5 shadow-inner">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-[var(--success)] animate-pulse"></div>
              <span className="text-[10px] font-black text-white uppercase tracking-widest">Active Core</span>
            </div>
            <div className="w-px h-4 bg-white/10"></div>
            <div className="flex flex-col">
              <span className="text-[9px] text-[var(--text-muted)] uppercase font-bold">LLM: <span className="text-[var(--accent)] font-mono">{config.llmProvider.toUpperCase()}</span></span>
              <span className="text-[9px] text-[var(--text-muted)] uppercase font-bold">TTS: <span className="text-[var(--accent-2)] font-mono">{config.ttsProvider.toUpperCase()}</span></span>
            </div>
          </div>
        }
      />

      <div className="flex flex-col gap-6">
        
        {/* CARD: LLM PRINCIPAL */}
        <Card hover onMouseEnter={() => audio.playHover()}>
          <div className="absolute -top-10 -right-10 w-40 h-40 bg-[var(--purple-neon)] rounded-full blur-[90px] opacity-10 group-hover:opacity-20 transition-opacity"></div>

          <div className="flex items-center gap-3 mb-6 relative z-10">
            <div className="w-10 h-10 rounded-xl bg-[var(--purple-dark)] border border-[var(--purple-neon)] flex items-center justify-center text-[var(--purple-neon)] shadow-[0_0_15px_var(--purple-dark)]">
              <BrainCircuit size={20} />
            </div>
            <h3 className="font-bold text-[var(--text-primary)] text-lg tracking-wide">Motor Cognitivo (LLM)</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-[120px_1fr_120px_1fr] gap-6 items-center relative z-10">

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Provedor:</span>
            <div className="relative">
              <select
                className="w-full bg-black/60 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-[var(--purple-neon)] transition-all cursor-pointer appearance-none shadow-inner"
                value={config.llmProvider}
                onChange={(e) => selectLlmProvider(e.target.value)}
              >
                {llmProviders.map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--purple-neon)] font-bold">▼</div>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Temperatura:</span>
            <div className="flex items-center gap-4 bg-[rgba(0,0,0,0.4)] p-2 rounded-lg border border-[var(--border-strong)] shadow-inner">
              <input
                type="range" min="0" max="2" step="0.01"
                className="w-full accent-[var(--purple-neon)] h-2.5 bg-[rgba(255,255,255,0.05)] rounded-lg appearance-none cursor-pointer"
                value={config.llmTemperature}
                onChange={(e) => updateField("llmTemperature", parseFloat(e.target.value))}
              />
              <span className="text-sm font-bold font-mono text-white bg-[var(--purple-neon)] px-2 py-1 rounded w-[50px] text-center shadow-[0_0_10px_var(--purple-neon)]">
                {config.llmTemperature.toFixed(2)}
              </span>
            </div>

            {config.llmProvider === "openrouter" && (
              <>
                <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Esforço de raciocínio:</span>
                <div className="flex flex-col gap-2 bg-[rgba(0,0,0,0.4)] p-3 rounded-lg border border-[var(--border-strong)] shadow-inner md:col-span-3">
                  {(() => {
                    const current = config.openrouterReasoningEffort || "";
                    const index = OPENROUTER_REASONING_LEVELS.findIndex((lvl) => lvl.value === current);
                    const safeIndex = index >= 0 ? index : 0;
                    return (
                      <>
                        <div className="flex items-center gap-3">
                          <span className="text-[11px] font-bold uppercase text-[var(--text-muted)]">Mais rápido</span>
                          <input
                            type="range"
                            min={0}
                            max={OPENROUTER_REASONING_LEVELS.length - 1}
                            step={1}
                            value={safeIndex}
                            onChange={(e) => updateField("openrouterReasoningEffort", OPENROUTER_REASONING_LEVELS[Number(e.target.value)].value)}
                            className="w-full accent-[var(--purple-neon)] h-2.5 bg-[rgba(255,255,255,0.05)] rounded-lg appearance-none cursor-pointer"
                          />
                          <span className="text-[11px] font-bold uppercase text-[var(--text-muted)]">Mais inteligente</span>
                          <span className="text-sm font-bold font-mono text-white bg-[var(--purple-neon)] px-2 py-1 rounded min-w-[70px] text-center shadow-[0_0_10px_var(--purple-neon)]">
                            {OPENROUTER_REASONING_LEVELS[safeIndex].label}
                          </span>
                        </div>
                        <span className="text-xs text-[var(--text-secondary)]">
                          {current === ""
                            ? "Automático: chat pensa fundo; voz/terminal pensam pouco (effort=low). Só afeta modelos com reasoning suportado."
                            : `Fixado em "${OPENROUTER_REASONING_LEVELS[safeIndex].label}" em todos os canais (chat/voz/terminal). Só afeta modelos com reasoning suportado; nível "Nenhum" desliga o raciocínio.`}
                        </span>
                      </>
                    );
                  })()}
                </div>
              </>
            )}

            {config.llmProvider === "groq" && (
              <>
                <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Pensar antes de falar:</span>
                <div className="flex items-center gap-3 bg-[rgba(0,0,0,0.4)] p-2 rounded-lg border border-[var(--border-strong)] shadow-inner md:col-span-3">
                  <button
                    type="button"
                    onClick={() => updateField("groqThinking", !(config.groqThinking ?? true))}
                    className={`relative h-6 w-11 rounded-full transition-colors ${(config.groqThinking ?? true) ? "bg-[var(--purple-neon)]" : "bg-[rgba(255,255,255,0.15)]"}`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${(config.groqThinking ?? true) ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {(config.groqThinking ?? true)
                      ? "Liga: chat pensa fundo; voz/terminal pensam um pouco (rápido, mas acertam hora/lógica)."
                      : "Desliga: resposta direta e rápida em todos os canais, sem raciocínio."}
                  </span>
                </div>
              </>
            )}

            {config.llmProvider === "qwen" && (
              <>
                <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Pensar antes de falar:</span>
                <div className="flex items-center gap-3 bg-[rgba(0,0,0,0.4)] p-2 rounded-lg border border-[var(--border-strong)] shadow-inner md:col-span-3">
                  <button
                    type="button"
                    onClick={() => updateField("qwenThinking", !(config.qwenThinking ?? true))}
                    className={`relative h-6 w-11 rounded-full transition-colors ${(config.qwenThinking ?? true) ? "bg-[var(--purple-neon)]" : "bg-[rgba(255,255,255,0.15)]"}`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${(config.qwenThinking ?? true) ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {(config.qwenThinking ?? true)
                      ? "Liga: chat pensa fundo (sem limite); voz/terminal pensam pouco (orçamento de ~300 tokens, mais rápido)."
                      : "Desliga: resposta direta e rápida em todos os canais, sem raciocínio. So afeta modelos qwen3.x (aliases genericos qwen-plus/turbo/max nao sao tocados)."}
                  </span>
                </div>
              </>
            )}

            {config.llmProvider === "deepseek" && (
              <>
                <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Esforço de raciocínio:</span>
                <div className="flex flex-col gap-2 bg-[rgba(0,0,0,0.4)] p-3 rounded-lg border border-[var(--border-strong)] shadow-inner md:col-span-3">
                  {(() => {
                    const current = config.deepseekReasoningEffort || "high";
                    const index = DEEPSEEK_REASONING_LEVELS.findIndex((lvl) => lvl.value === current);
                    const safeIndex = index >= 0 ? index : 1;
                    return (
                      <>
                        <div className="flex items-center gap-3">
                          <span className="text-[11px] font-bold uppercase text-[var(--text-muted)]">Mais rápido</span>
                          <input
                            type="range"
                            min={0}
                            max={DEEPSEEK_REASONING_LEVELS.length - 1}
                            step={1}
                            value={safeIndex}
                            onChange={(e) => updateField("deepseekReasoningEffort", DEEPSEEK_REASONING_LEVELS[Number(e.target.value)].value)}
                            className="w-full accent-[var(--purple-neon)] h-2.5 bg-[rgba(255,255,255,0.05)] rounded-lg appearance-none cursor-pointer"
                          />
                          <span className="text-[11px] font-bold uppercase text-[var(--text-muted)]">Mais inteligente</span>
                          <span className="text-sm font-bold font-mono text-white bg-[var(--purple-neon)] px-2 py-1 rounded min-w-[70px] text-center shadow-[0_0_10px_var(--purple-neon)]">
                            {DEEPSEEK_REASONING_LEVELS[safeIndex].label}
                          </span>
                        </div>
                        <span className="text-xs text-[var(--text-secondary)]">
                          DeepSeek so tem 2 niveis reais (a API deles mapeia "baixo/medio" pra "Alto" de qualquer forma) mais desligado — nao existe uma escala continua como no OpenRouter.
                        </span>
                      </>
                    );
                  })()}
                </div>
              </>
            )}

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Modelo Base:</span>
            <div className="md:col-span-3">
              <CatalogPicker
                value={config.llmModel}
                options={llmPickerOptions}
                onChange={(value) => updateField("llmModel", value)}
                favoriteNamespace={`llm:${config.llmProvider}`}
                placeholder="Selecione um modelo"
                searchPlaceholder="Buscar modelo por nome ou ID..."
                emptyMessage="Nenhum modelo deste provider corresponde aos filtros."
                accent="purple"
              />
            </div>
            {config.llmProvider === "openrouter" && (
              <div className="md:col-start-2 md:col-span-3">
                <OpenRouterEndpointPicker
                  model={config.llmModel}
                  value={config.openrouterRoutingByModel[config.llmModel] || DEFAULT_OPENROUTER_ROUTING}
                  onChange={(routing) => updateField("openrouterRoutingByModel", {
                    ...config.openrouterRoutingByModel,
                    [config.llmModel]: routing,
                  })}
                />
              </div>
            )}
          </div>

          {selectedLlmModel && (
            <div className="mt-5 flex flex-wrap gap-2 relative z-10">
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                {selectedLlmModel.maxInputTokens ? `${selectedLlmModel.maxInputTokens.toLocaleString("pt-BR")} ctx` : "ctx n/a"}
              </span>
              {selectedLlmModel.supportsVision && (
                <span className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-emerald-200">vision</span>
              )}
              {selectedLlmModel.supportsDocuments && (
                <span className="rounded-full border border-sky-400/20 bg-sky-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-sky-200">docs</span>
              )}
              {selectedLlmModel.supportsTools && (
                <span className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-cyan-200">tools</span>
              )}
              {selectedLlmModel.supportsNativeSearch && (
                <span className="rounded-full border border-lime-400/20 bg-lime-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-lime-200">native web</span>
              )}
              {selectedPriceLabel && (
                <span className="rounded-full border border-fuchsia-400/20 bg-fuchsia-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-fuchsia-200">{selectedPriceLabel}</span>
              )}
              {nonGeminiActive && (
                <span className="rounded-full border border-amber-400/20 bg-amber-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-amber-200">Gemini native off</span>
              )}
            </div>
          )}

          <div className="mt-6 pt-5 border-t border-white/5 relative z-10">
            <div className="mb-3 flex flex-col md:flex-row md:items-center md:justify-between gap-2">
              <div>
                <h4 className="text-sm font-bold text-white uppercase tracking-wider">Modelo customizado</h4>
                <p className="text-xs text-[var(--text-muted)]">
                  Use quando a API publicar um modelo novo antes do catalogo ser atualizado.
                </p>
              </div>
              {selectedLlmModel?.custom && (
                <Button onClick={handleRemoveSelectedCustomModel} variant="danger" size="sm" icon={<Trash2 size={14} />}>
                  Remover selecionado
                </Button>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto_auto_auto_auto] gap-3">
              <input
                className="bg-black/60 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 text-white rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-[var(--purple-neon)] transition-all"
                placeholder="ID do modelo, ex: gemini-3.1-pro-preview"
                value={customModelId}
                onChange={(e) => setCustomModelId(e.target.value)}
              />
              <input
                className="bg-black/60 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 text-white rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-[var(--purple-neon)] transition-all"
                placeholder="Nome visivel opcional"
                value={customModelLabel}
                onChange={(e) => setCustomModelLabel(e.target.value)}
              />
              <label className="flex items-center gap-2 bg-black/40 border border-[var(--border-strong)] rounded-lg px-3 py-2 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider cursor-pointer">
                <input
                  type="checkbox"
                  checked={customModelVision}
                  onChange={(e) => setCustomModelVision(e.target.checked)}
                  className="accent-[var(--purple-neon)]"
                />
                Vision
              </label>
              <label className="flex items-center gap-2 bg-black/40 border border-[var(--border-strong)] rounded-lg px-3 py-2 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider cursor-pointer">
                <input
                  type="checkbox"
                  checked={customModelDocuments}
                  onChange={(e) => setCustomModelDocuments(e.target.checked)}
                  className="accent-sky-400"
                />
                Docs
              </label>
              <label className="flex items-center gap-2 bg-black/40 border border-[var(--border-strong)] rounded-lg px-3 py-2 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider cursor-pointer">
                <input
                  type="checkbox"
                  checked={customModelTools}
                  onChange={(e) => setCustomModelTools(e.target.checked)}
                  className="accent-cyan-400"
                />
                Tools
              </label>
              <Button onClick={handleAddCustomModel} variant="primary" icon={<Plus size={15} />}>Adicionar</Button>
            </div>

            {catalogStatus && (
              <p className="mt-3 text-xs text-[var(--cyan-neon)] font-mono">{catalogStatus}</p>
            )}
          </div>
        </Card>

        {/* CARD: MODELO DE VISÃO */}
        <Card hover onMouseEnter={() => audio.playHover()}>
          <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-emerald-500 rounded-full blur-[90px] opacity-10 group-hover:opacity-20 transition-opacity"></div>
          
          <div className="flex items-center gap-3 mb-6 relative z-10">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500 flex items-center justify-center text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)]">
              <Eye size={20} />
            </div>
            <h3 className="font-bold text-[var(--text-primary)] text-lg tracking-wide">Visão Computacional</h3>
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-5 relative z-10">
            O <b>olho da Hana</b>: visão sob demanda (ela vê sua tela), co-piloto (<code>screen_find</code>)
            e <b>roteamento de imagem</b> — quando chega uma imagem (chat/Discord) e o provider do chat
            não enxerga, ela manda a imagem pra ESTE provider/modelo em vez de ignorar. Deixe o provider
            vazio pra usar o mesmo do chat.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-[120px_1fr] gap-4 items-center relative z-10">
            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Provedor Vision:</span>
            <div className="relative w-full md:w-2/3">
              <select
                className="w-full appearance-none bg-black/60 border border-[var(--border-strong)] hover:border-emerald-500/50 text-white rounded-lg p-2.5 pr-10 outline-none font-mono text-sm focus:ring-2 focus:ring-emerald-500 transition-all shadow-inner cursor-pointer"
                value={config.visionProvider || ""}
                onChange={(e) => selectVisionProvider(e.target.value)}
              >
                <option value="">Mesmo do chat ({(config.llmProvider || "").toUpperCase()})</option>
                {llmProviders.map((p) => <option key={p} value={p}>{p.toUpperCase()}</option>)}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-emerald-400 font-bold">▼</div>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Modelo Vision:</span>
            <div className="w-full md:w-2/3">
              <CatalogPicker
                value={config.visionModel}
                options={visionPickerOptions}
                onChange={(value) => updateField("visionModel", value)}
                favoriteNamespace={`vision:${visionProvider}`}
                placeholder={availableVisionModels.length === 0 ? "Provider sem suporte a visao" : "Selecione um modelo"}
                searchPlaceholder="Buscar modelo de visao..."
                emptyMessage="Nenhum modelo de visao encontrado."
                accent="emerald"
                disabled={availableVisionModels.length === 0}
              />
            </div>
          </div>
        </Card>

        {/* CARD: MODELO DE AGENTE (cérebro econômico) */}
        <Card hover onMouseEnter={() => audio.playHover()}>
          <div className="absolute -bottom-10 -right-10 w-40 h-40 bg-amber-500 rounded-full blur-[90px] opacity-10 group-hover:opacity-20 transition-opacity"></div>

          <div className="flex items-center gap-3 mb-3 relative z-10">
            <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500 flex items-center justify-center text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.2)]">
              <Bot size={20} />
            </div>
            <h3 className="font-bold text-[var(--text-primary)] text-lg tracking-wide">Modelo de Agente</h3>
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-5 relative z-10">
            Cérebro econômico: o chat normal usa o modelo principal (barato). Quando a Hana
            <b> usa ferramentas</b> (terminal, lembretes, pesquisa), ela troca para este modelo,
            que costuma ser melhor com ações. Pode até ser de <b>outro provedor</b> (ex: chat no
            OpenRouter, agente na Groq). Deixe vazio para usar sempre o modelo principal.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-[120px_1fr] gap-y-5 gap-x-6 items-center relative z-10">
            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Provedor Agente:</span>
            <div className="relative w-full md:w-2/3">
              <select
                className="w-full bg-black/60 border border-[var(--border-strong)] hover:border-amber-500/50 text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-amber-500 transition-all cursor-pointer appearance-none shadow-inner"
                value={config.agentProvider || ""}
                onChange={(e) => setConfig((prev) => prev && ({ ...prev, agentProvider: e.target.value, agentModel: "" }))}
              >
                <option value="">Mesmo do principal ({config.llmProvider.toUpperCase()})</option>
                {llmProviders.map((p) => <option key={p} value={p}>{p.toUpperCase()}</option>)}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-amber-400 font-bold">▼</div>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Modelo Agente:</span>
            <div className="w-full md:w-2/3">
              <CatalogPicker
                value={config.agentModel}
                options={agentPickerOptions}
                onChange={(value) => updateField("agentModel", value)}
                favoriteNamespace={`agent:${agentProvider}`}
                placeholder="Usar o modelo principal (padrão)"
                searchPlaceholder="Buscar modelo de agente..."
                emptyMessage="Nenhum modelo encontrado."
                accent="blue"
              />
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Rodadas Tools:</span>
            <div className="flex items-center gap-3 w-full md:w-2/3">
              <input
                type="number" min="0" max="500"
                className="w-28 bg-black/60 border border-[var(--border-strong)] hover:border-amber-500/50 text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-amber-500 transition-all shadow-inner"
                value={config.agentToolRounds ?? 40}
                onChange={(e) => {
                  const parsed = parseInt(e.target.value);
                  updateField("agentToolRounds", Number.isNaN(parsed) ? 40 : Math.max(0, Math.min(500, parsed)));
                }}
              />
              <span className="text-xs text-[var(--text-muted)]">
                Máx. de rodadas de ferramentas por turno. <b>0 = sem limite</b> (ela trabalha até terminar).
                Com limite, se estourar a Hana avisa o que fez e o que faltou (nunca corta no silêncio).
              </span>
            </div>

            {/* Pensar do MODELO DE AGENTE — independente do chat. Slider (openrouter/deepseek) ou toggle (groq/qwen). */}
            {(agentProvider === "openrouter" || agentProvider === "deepseek") && (
              <>
                <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Pensar (agente):</span>
                <div className="flex flex-col gap-2 bg-[rgba(0,0,0,0.4)] p-3 rounded-lg border border-[var(--border-strong)] shadow-inner w-full md:w-2/3">
                  {(() => {
                    const levels = agentProvider === "deepseek" ? DEEPSEEK_REASONING_LEVELS : OPENROUTER_REASONING_LEVELS;
                    const fallback = agentProvider === "deepseek" ? "high" : "";
                    const current = config.agentReasoningEffort || fallback;
                    const index = levels.findIndex((lvl) => lvl.value === current);
                    const safeIndex = index >= 0 ? index : 0;
                    return (
                      <>
                        <div className="flex items-center gap-3">
                          <span className="text-[11px] font-bold uppercase text-[var(--text-muted)]">Mais rápido</span>
                          <input
                            type="range"
                            min={0}
                            max={levels.length - 1}
                            step={1}
                            value={safeIndex}
                            onChange={(e) => updateField("agentReasoningEffort", levels[Number(e.target.value)].value)}
                            className="w-full accent-amber-400 h-2.5 bg-[rgba(255,255,255,0.05)] rounded-lg appearance-none cursor-pointer"
                          />
                          <span className="text-[11px] font-bold uppercase text-[var(--text-muted)]">Mais inteligente</span>
                          <span className="text-sm font-bold font-mono text-white bg-amber-500 px-2 py-1 rounded min-w-[70px] text-center shadow-[0_0_10px_rgba(245,158,11,0.7)]">
                            {levels[safeIndex].label}
                          </span>
                        </div>
                        <span className="text-xs text-[var(--text-secondary)]">
                          Esforço de raciocínio SÓ do modelo de agente (quando usa ferramentas). Não mexe no chat normal.
                        </span>
                      </>
                    );
                  })()}
                </div>
              </>
            )}

            {(agentProvider === "groq" || agentProvider === "qwen") && (
              <>
                <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Pensar (agente):</span>
                <div className="flex items-center gap-3 bg-[rgba(0,0,0,0.4)] p-2 rounded-lg border border-[var(--border-strong)] shadow-inner w-full md:w-2/3">
                  <button
                    type="button"
                    onClick={() => updateField("agentThinking", !(config.agentThinking ?? true))}
                    className={`relative h-6 w-11 rounded-full transition-colors ${(config.agentThinking ?? true) ? "bg-amber-500" : "bg-[rgba(255,255,255,0.15)]"}`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${(config.agentThinking ?? true) ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {(config.agentThinking ?? true)
                      ? "Liga: o modelo de agente raciocina antes de agir com ferramentas."
                      : "Desliga: agente responde direto/rápido, sem raciocínio. Não mexe no chat normal."}
                  </span>
                </div>
              </>
            )}
          </div>
        </Card>

        {/* CARD: TTS DO CHAT */}
        <Card hover onMouseEnter={() => audio.playHover()}>
          <div className="absolute top-1/2 left-1/2 h-full w-full -translate-x-1/2 -translate-y-1/2 bg-gradient-to-r from-transparent via-pink-500/5 to-transparent pointer-events-none group-hover:via-pink-500/10 transition-colors"></div>
          
          <div className="flex items-center gap-3 mb-6 relative z-10">
            <div className="w-10 h-10 rounded-xl bg-pink-500/20 border border-pink-400 flex items-center justify-center text-pink-200 shadow-[0_0_15px_rgba(236,72,153,0.3)]">
              <Mic size={20} />
            </div>
            <div>
              <h3 className="font-bold text-[var(--text-primary)] text-lg tracking-wide">TTS do Chat</h3>
              <p className="text-xs text-[var(--text-muted)]">Configura a voz usada no Chat do Controle. O Terminal Agente continua com a propria TTS.</p>
            </div>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-[120px_1fr_120px_1fr] gap-y-5 gap-x-6 items-center relative z-10">
            
            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Provedor TTS:</span>
            <div className="relative">
              <select
                className="w-full bg-black/60 border border-[var(--border-strong)] hover:border-blue-500/50 text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-blue-500 transition-all cursor-pointer appearance-none shadow-inner"
                value={config.ttsProvider}
                onChange={(e) => updateChatTtsProvider(e.target.value)}
              >
                {ttsProviders.map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-blue-500 font-bold">▼</div>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Modelo TTS:</span>
            <div className="space-y-2">
              <CatalogPicker
                value={config.ttsModel}
                options={ttsModelPickerOptions}
                onChange={(value) => updateField("ttsModel", value)}
                favoriteNamespace={`chat-tts-model:${config.ttsProvider}`}
                searchPlaceholder="Buscar modelo TTS..."
                accent="blue"
                showAdvancedFilters={false}
                compact
              />
              {ttsIsElevenLabs && (
                <input
                  className="w-full rounded-lg border border-blue-400/20 bg-black/60 p-2.5 font-mono text-xs text-white outline-none focus:ring-2 focus:ring-blue-500"
                  value={config.ttsModel}
                  onChange={(event) => updateField("ttsModel", event.target.value.trim())}
                  placeholder="ID customizado do modelo ElevenLabs"
                />
              )}
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Voz:</span>
            <div className="space-y-2 md:col-span-3">
              <CatalogPicker
                value={config.ttsVoice}
                options={ttsVoicePickerOptions}
                onChange={(value) => updateField("ttsVoice", value)}
                favoriteNamespace={`chat-tts-voice:${config.ttsProvider}`}
                searchPlaceholder="Buscar voz por nome ou ID..."
                emptyMessage="Nenhuma voz encontrada para este provider."
                accent="pink"
                showAdvancedFilters={false}
                compact
              />
              {ttsIsElevenLabs && (
                <input
                  className="w-full rounded-lg border border-pink-400/20 bg-black/60 p-2.5 font-mono text-sm text-white outline-none focus:ring-2 focus:ring-pink-500"
                  value={config.ttsVoice}
                  onChange={(event) => updateField("ttsVoice", event.target.value.trim())}
                  onBlur={(event) => {
                    const id = event.target.value.trim();
                    if (id) setRememberedVoices(rememberVoice(config.ttsProvider, id));
                  }}
                  placeholder="Cole qualquer Voice ID da sua biblioteca ElevenLabs"
                />
              )}
              {ttsIsFishAudio && (
                <input
                  className="w-full rounded-lg border border-pink-400/20 bg-black/60 p-2.5 font-mono text-sm text-white outline-none focus:ring-2 focus:ring-pink-500"
                  value={config.ttsVoice}
                  onChange={(event) => updateField("ttsVoice", event.target.value.trim())}
                  onBlur={(event) => {
                    const id = event.target.value.trim();
                    if (id) setRememberedVoices(rememberVoice(config.ttsProvider, id));
                  }}
                  placeholder="Cole um reference_id do Fish Audio (vazio = voz padrao)"
                />
              )}
            </div>

            {/* SLIDERS TTS */}
            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Velocidade:</span>
            <div className={`flex items-center gap-4 bg-[rgba(0,0,0,0.4)] p-2 rounded-lg border border-[var(--border-strong)] shadow-inner ${!ttsUsesSpeed ? "opacity-50" : ""}`}>
              <input 
                type="range" min="0.7" max="1.5" step="0.01" disabled={!ttsUsesSpeed}
                className="w-full accent-blue-500 h-2.5 bg-[rgba(255,255,255,0.05)] rounded-lg appearance-none cursor-pointer disabled:cursor-not-allowed"
                value={config.ttsSpeed}
                onChange={(e) => updateField("ttsSpeed", parseFloat(e.target.value))}
              />
              <span className="text-sm font-bold font-mono text-white bg-blue-500 px-2 py-1 rounded w-[60px] text-center shadow-[0_0_10px_rgba(59,130,246,0.8)]">{config.ttsSpeed.toFixed(2)}x</span>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Pitch:</span>
            <div className={`flex items-center gap-4 bg-[rgba(0,0,0,0.4)] p-2 rounded-lg border border-[var(--border-strong)] shadow-inner ${!ttsUsesPitch ? "opacity-50" : ""}`}>
              <input 
                type="range" min="-20" max="20" step="1" disabled={!ttsUsesPitch}
                className="w-full accent-emerald-500 h-2.5 bg-[rgba(255,255,255,0.05)] rounded-lg appearance-none cursor-pointer disabled:cursor-not-allowed"
                value={config.ttsPitch}
                onChange={(e) => updateField("ttsPitch", parseFloat(e.target.value))}
              />
              <span className="text-sm font-bold font-mono text-white bg-emerald-500 px-2 py-1 rounded w-[60px] text-center shadow-[0_0_10px_rgba(16,185,129,0.8)]">{config.ttsPitch.toFixed(1)}</span>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Volume:</span>
            <div className="flex items-center gap-4 rounded-lg border border-[var(--border-strong)] bg-[rgba(0,0,0,0.4)] p-2 shadow-inner">
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                className="h-2.5 w-full cursor-pointer appearance-none rounded-lg bg-[rgba(255,255,255,0.05)] accent-pink-500"
                value={config.ttsVolume}
                onChange={(event) => updateField("ttsVolume", Number(event.target.value))}
              />
              <span className="w-[60px] rounded bg-pink-500 px-2 py-1 text-center font-mono text-sm font-bold text-white shadow-[0_0_10px_rgba(236,72,153,0.7)]">
                {Math.round(config.ttsVolume * 100)}%
              </span>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Idioma:</span>
            <input
              className="w-full bg-black/60 border border-[var(--border-strong)] hover:border-pink-500/50 text-white rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-pink-500 transition-all shadow-inner"
              value={config.ttsLanguage}
              onChange={(e) => updateField("ttsLanguage", e.target.value)}
              placeholder="pt-BR"
            />

            {ttsIsElevenLabs && (
              <div className="col-span-1 grid gap-4 rounded-lg border border-pink-400/20 bg-black/40 p-4 md:col-span-4 md:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">Estabilidade</span>
                  <input type="range" min="0" max="1" step="0.01" value={config.ttsStability} onChange={(event) => updateField("ttsStability", Number(event.target.value))} className="w-full accent-pink-500" />
                  <span className="font-mono text-xs text-pink-200">{config.ttsStability.toFixed(2)}</span>
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">Similaridade da voz</span>
                  <input type="range" min="0" max="1" step="0.01" value={config.ttsSimilarity} onChange={(event) => updateField("ttsSimilarity", Number(event.target.value))} className="w-full accent-cyan-500" />
                  <span className="font-mono text-xs text-cyan-200">{config.ttsSimilarity.toFixed(2)}</span>
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">Exagero de estilo</span>
                  <input type="range" min="0" max="1" step="0.01" value={config.ttsStyle} onChange={(event) => updateField("ttsStyle", Number(event.target.value))} className="w-full accent-purple-500" />
                  <span className="font-mono text-xs text-purple-200">{config.ttsStyle.toFixed(2)}</span>
                </label>
                <label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/40 px-3 py-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">Speaker boost</span>
                  <input type="checkbox" checked={config.ttsSpeakerBoost} onChange={(event) => updateField("ttsSpeakerBoost", event.target.checked)} className="h-4 w-4 accent-pink-500" />
                </label>
              </div>
            )}

            {ttsCanStream && (
              <div className="md:col-start-4 flex items-center">
                <label className="flex items-center gap-3 cursor-pointer group">
                  <input type="checkbox" className="peer sr-only" checked={config.ttsStreaming} onChange={(e) => updateField("ttsStreaming", e.target.checked)} />
                  <div className="relative w-12 h-6 bg-black/50 border border-[var(--border-strong)] rounded-full peer-checked:bg-cyan-500/60 after:content-[''] after:absolute after:top-[1px] after:left-[1px] after:h-5 after:w-5 after:rounded-full after:bg-gray-400 after:transition-all peer-checked:after:translate-x-6 peer-checked:after:bg-white"></div>
                  <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider group-hover:text-white">Streaming Cloud TTS</span>
                </label>
              </div>
            )}

            {ttsUsesPrompt && (
              <div className="col-span-1 md:col-span-4">
                <span className="mb-2 block text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Prompt de atuacao Gemini TTS:</span>
                <textarea
                  className="min-h-[120px] w-full resize-y rounded-xl border border-pink-400/20 bg-black/60 p-3 font-mono text-xs leading-relaxed text-white outline-none transition-all placeholder:text-[var(--border-strong)] focus:ring-2 focus:ring-pink-500"
                  value={config.ttsPrompt}
                  onChange={(e) => updateField("ttsPrompt", e.target.value)}
                  placeholder="Direcao de voz para o Gemini TTS. Ex: Brazilian Portuguese, playful, natural pauses..."
                />
              </div>
            )}

            <div className="col-span-1 md:col-span-4 flex flex-col md:flex-row md:items-center gap-4 mt-6 pt-6 border-t border-white/5">
              <Button onMouseEnter={() => audio.playHover()} onClick={playChatTtsTest} variant="primary" icon={<Play size={18} fill="currentColor" />}>
                Testar TTS do Chat
              </Button>
              <span className="text-xs text-[var(--text-secondary)] bg-[rgba(0,0,0,0.4)] px-4 py-2 rounded-lg border border-[var(--border-strong)] font-mono">
                <span className="text-pink-300">Info:</span> {ttsIsElevenLabs ? "Voice ID livre, modelos v2.5/v3 e controles ElevenLabs ativos." : ttsIsFishAudio ? "Fish Audio: s2.1-pro-free e gratis; cole um reference_id pra trocar de voz." : ttsUsesSpeed ? "Controles numericos disponiveis conforme o provider." : "Gemini usa prompt de atuacao; rate/pitch ficam desativados aqui."}
              </span>
              {ttsTestStatus && (
                <span className="text-xs text-pink-100/80 bg-pink-500/10 px-4 py-2 rounded-lg border border-pink-400/20 font-mono">
                  {ttsTestStatus}
                </span>
              )}
            </div>

          </div>
        </Card>

        {/* CARD: GERAÇÃO DE IMAGENS */}
        <Card hover onMouseEnter={() => audio.playHover()} className="mt-6">
          <div className="absolute top-1/2 left-1/2 h-full w-full -translate-x-1/2 -translate-y-1/2 bg-gradient-to-r from-transparent via-cyan-500/5 to-transparent pointer-events-none group-hover:via-cyan-500/10 transition-colors"></div>

          <div className="flex items-center gap-3 mb-6 relative z-10">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/20 border border-cyan-400 flex items-center justify-center text-cyan-200 shadow-[0_0_15px_rgba(34,211,238,0.3)]">
              <ImageIcon size={20} />
            </div>
            <div>
              <h3 className="font-bold text-[var(--text-primary)] text-lg tracking-wide">Geração de Imagens</h3>
              <p className="text-xs text-[var(--text-muted)]">Configure o provedor de criação e edição de imagens.</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-[120px_1fr_120px_1fr] gap-y-5 gap-x-6 items-center relative z-10">

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Provedor:</span>
            <div className="relative">
              <select
                className="w-full bg-black/60 border border-[var(--border-strong)] hover:border-cyan-500/50 text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-cyan-500 transition-all cursor-pointer appearance-none shadow-inner"
                value={imageConfig.imageProvider}
                onChange={(e) => updateImageField("imageProvider", e.target.value)}
              >
                {imageProviders.map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-cyan-500 font-bold">▼</div>
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] md:pl-4 uppercase tracking-wider">Modelo:</span>
            <div className="relative">
              {imageConfig.imageProvider === "openrouter" ? (
                <CatalogPicker
                  value={imageConfig.openrouterImageModel}
                  options={imagePickerOptions}
                  onChange={(value) => updateImageField("openrouterImageModel", value)}
                  favoriteNamespace={`image:${imageConfig.imageProvider}`}
                  searchPlaceholder="Buscar modelo de imagem..."
                  emptyMessage="Nenhum modelo de imagem encontrado."
                  accent="cyan"
                />
              ) : (
                <CatalogPicker
                  value=""
                  options={[{ value: "", label: "Automatico pelo provider" }]}
                  onChange={() => undefined}
                  favoriteNamespace={`image:${imageConfig.imageProvider}`}
                  accent="cyan"
                  disabled
                />
              )}
            </div>

            <span className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-wider">Raciocínio:</span>
            <div className="relative">
              <select
                className="w-full bg-black/60 border border-[var(--border-strong)] hover:border-cyan-500/50 text-[var(--text-primary)] rounded-lg p-2.5 outline-none font-mono text-sm focus:ring-2 focus:ring-cyan-500 transition-all cursor-pointer appearance-none shadow-inner disabled:opacity-50"
                value={imageConfig.openrouterReasoning}
                onChange={(e) => updateImageField("openrouterReasoning", e.target.value)}
                disabled={imageConfig.imageProvider !== "openrouter"}
              >
                <option value="none">Desligado</option>
                <option value="low">Baixo (Rápido)</option>
                <option value="medium">Médio</option>
                <option value="high">Alto (Qualidade)</option>
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-cyan-500 font-bold opacity-50">▼</div>
            </div>
          </div>
        </Card>
      </div>

      {/* SAVE ACTIONS */}
      <div className="mt-8 pt-6 border-t border-white/5 flex justify-end">
        <Button
          onMouseEnter={() => audio.playHover()}
          onClick={() => { audio.playClick(); handleSave(); }}
          variant="primary"
          icon={<Save size={18} />}
        >
          Salvar Alterações
        </Button>
      </div>

    </div>
  );
}
