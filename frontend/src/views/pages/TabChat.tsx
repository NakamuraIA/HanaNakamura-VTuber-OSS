import { useState, useRef, useEffect, useDeferredValue, useMemo, useCallback } from "react";
import { ApiController } from "../../controllers/api";
import { AgentStage, ChatAttachment, ChatConfig, ChatMessage, LlmConfig, ChatSession, SafetyMode, ThinkingItem, VoiceConfig } from "../../models/types";
import { ModelSpec, normalizeProvider } from "../../models/providerCatalog";
import { LONG_MESSAGE_LIMIT } from "../../models/constants";
import { 
  Paperclip, 
  X,
} from "lucide-react";
import { CatalogPickerOption } from "../components/shared/CatalogPicker";
import { DEFAULT_OPENROUTER_ROUTING } from "../components/shared/OpenRouterEndpointPicker";
import { IDENTITY_CHANGED_EVENT, loadIdentity } from "../../identity";
import { ChatHeader } from "../components/chat/ChatHeader";
import { ChatConfigModal } from "../components/chat/ChatConfigModal";
import { ChatMessageList } from "../components/chat/ChatMessageList";
import { ChatInputBar } from "../components/chat/ChatInputBar";

const CHAT_SESSIONS_KEY = "hana_chat_sessions_v1";
const CHAT_ACTIVE_SESSION_KEY = "hana_chat_active_session_v1";
const CHAT_AUTO_TTS_KEY = "hana_chat_auto_tts_v1";
const CHAT_TYPING_SPEED_KEY = "hana_chat_typing_speed_v1";
const CHAT_SHOW_TYPING_SPEED_KEY = "hana_chat_show_typing_speed_v1";
type TypingSpeed = "slow" | "normal" | "fast" | "instant";
const TYPING_SPEED_MS: Record<TypingSpeed, number> = { slow: 24, normal: 16, fast: 12, instant: 0 };
const TYPING_SPEED_CHARS: Record<TypingSpeed, number> = { slow: 2, normal: 5, fast: 14, instant: Number.POSITIVE_INFINITY };
const LEGACY_CHAT_MESSAGES_KEY = "hana_chat_messages";
const MAX_RENDERED_MESSAGES = 80;
const MAX_PERSISTED_MESSAGES = 140;
const MAX_BACKEND_HISTORY_MESSAGES = 12;
const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;

function supportedAudioMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return candidates.find((mime) => MediaRecorder.isTypeSupported(mime)) || "";
}

function nowTime() {
  return new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function createWelcomeMessage(): ChatMessage {
  return {
    id: "system-1",
    role: "system",
    content: "Control Center online. Este chat e uma conversa local nova. Historicos antigos ficam no seletor acima para nao pesar a GUI.",
    timestamp: nowTime(),
  };
}

function createChatSession(): ChatSession {
  const now = new Date().toISOString();
  return {
    id: `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: "Nova conversa",
    createdAt: now,
    updatedAt: now,
    messages: [createWelcomeMessage()],
  };
}

function isAttachmentObject(value: string | ChatAttachment): value is ChatAttachment {
  return typeof value === "object" && value !== null && "data" in value;
}

function slimMessageForStorage(message: ChatMessage): ChatMessage {
  const attachments = message.attachments?.map((attachment, index) => {
    if (!isAttachmentObject(attachment)) {
      return { name: `imagem-${index + 1}.png`, type: "image/png", data: "", size: 0 };
    }
    return {
      name: attachment.name,
      type: attachment.type,
      size: attachment.size,
      data: attachment.data && attachment.data.length < 512 ? attachment.data : "",
    };
  });
  const media = message.media?.map((item) => {
    if (item.url?.startsWith("data:")) {
      return { ...item, url: undefined, status: "expired" as const };
    }
    return item;
  });
  return {
    ...message,
    attachments,
    media,
    images_b64: undefined,
  };
}

function isEmptyStreamingPlaceholder(message: ChatMessage) {
  return message.id === "streaming-res"
    && !message.content?.trim()
    && !message.media?.length
    && !message.attachments?.length;
}

function trimMessagesForStorage(messages: ChatMessage[]) {
  return messages
    .filter((message) => !isEmptyStreamingPlaceholder(message))
    .slice(-MAX_PERSISTED_MESSAGES)
    .map(slimMessageForStorage);
}

function restoreStoredMessages(sessionId: string, messages: ChatMessage[]) {
  return messages
    .filter((message) => !isEmptyStreamingPlaceholder(message))
    .map((message, index) => (
      message.id === "streaming-res"
        ? { ...message, id: `hana-interrompida-${sessionId}-${index}` }
        : message
    ));
}

function loadStoredSessions(): ChatSession[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_SESSIONS_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((session) => session && typeof session.id === "string" && Array.isArray(session.messages))
      .map((session) => ({
        ...session,
        messages: restoreStoredMessages(session.id, session.messages),
      }))
      .filter((session) => session.messages.some((message: ChatMessage) => (
        (message.role === "user" || message.role === "hana")
        && (message.content?.trim() || message.media?.length || message.attachments?.length)
      )))
      .slice(0, 30);
  } catch {
    return [];
  }
}

function buildInitialChatState() {
  const stored = loadStoredSessions();
  if (stored.length > 0) {
    const activeId = localStorage.getItem(CHAT_ACTIVE_SESSION_KEY);
    const active = stored.find((session) => session.id === activeId) || stored[0];
    return {
      sessions: stored,
      activeSessionId: active.id,
      messages: active.messages?.length ? active.messages : [createWelcomeMessage()],
    };
  }
  const fresh = createChatSession();
  return {
    sessions: [fresh],
    activeSessionId: fresh.id,
    messages: fresh.messages,
  };
}

function titleFromMessages(messages: ChatMessage[]) {
  const firstUser = messages.find((message) => message.role === "user" && message.content.trim());
  const title = firstUser?.content.trim().replace(/\s+/g, " ") || "Nova conversa";
  return title.length > 48 ? `${title.slice(0, 45)}...` : title;
}

// A plain LLM chat turn produces only a trivial "llm.provider" step. Those should never
// draw the operational Agent Mode card; we only surface it for real tools / agent-core steps.

const SAFETY_MODES: { id: SafetyMode; label: string }[] = [
  { id: "safe", label: "Safe" },
  { id: "assisted", label: "Assisted" },
  { id: "trusted", label: "Trusted" },
  { id: "dev-unsafe", label: "Dev Unsafe" },
];

function tierNumbers(value: unknown): number[] {
  /** Preco pode ser um numero fixo (string) ou faixas por contexto (array). */
  if (Array.isArray(value)) {
    return value
      .map((tier) => Number((tier as { price?: unknown })?.price))
      .filter((n) => Number.isFinite(n));
  }
  const n = Number(value);
  return Number.isFinite(n) ? [n] : [];
}

function modelPriceScore(model: ModelSpec) {
  /** Convert catalog pricing into a sortable score for the shared picker.
   * Com faixas, usa a media de cada lado (aproximacao — nao precisa ser exata pra ordenar). */
  if (model.free) return 0;
  const average = (values: number[]) => (values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : null);
  const promptAvg = average(tierNumbers(model.pricing?.prompt));
  const completionAvg = average(tierNumbers(model.pricing?.completion));
  if (promptAvg === null && completionAvg === null) return null;
  return (promptAvg || 0) + (completionAvg || 0);
}

function pricePerMillion(value: unknown): string {
  /** Catalogo reporta preco POR TOKEN; humanos leem preco por 1M tokens.
   * Com faixas, mostra menor-maior (ex.: $0.03-0.20). */
  const numbers = tierNumbers(value);
  if (numbers.length === 0) return "?";
  const format = (n: number) => {
    const perM = n * 1_000_000;
    if (perM === 0) return "$0";
    if (perM >= 100) return `$${perM.toFixed(0)}`;
    if (perM < 0.01) return "<$0.01"; // evita mostrar "$0.00" pra modelo pago
    return `$${perM.toFixed(2)}`;
  };
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  return min === max ? format(min) : `${format(min)}-${format(max)}`;
}

function chatModelOption(model: ModelSpec): CatalogPickerOption {
  /** Expose Chat models through the same searchable and favorite-aware catalog as Cerebro. */
  const badges: CatalogPickerOption["badges"] = [];
  if (model.supportsVision) badges.push({ label: "vision", tone: "green" });
  if (model.supportsDocuments) badges.push({ label: "docs", tone: "blue" });
  if (model.supportsTools) badges.push({ label: "tools", tone: "cyan" });
  if (model.supportsNativeSearch) badges.push({ label: "web", tone: "amber" });
  if (model.custom) badges.push({ label: "custom", tone: "neutral" });
  return {
    value: model.id,
    label: model.label,
    favoriteId: `${model.provider}:${model.id}`,
    secondary: model.id,
    description: model.description,
    free: model.free,
    priceScore: modelPriceScore(model),
    priceLabel: model.free
      ? "free"
      : model.pricing?.prompt || model.pricing?.completion
        ? `in ${pricePerMillion(model.pricing?.prompt)} / out ${pricePerMillion(model.pricing?.completion)} /M`
        : "",
    contextTokens: model.maxInputTokens,
    capabilityScore: [
      model.supportsVision,
      model.supportsDocuments,
      model.supportsTools,
      model.supportsNativeSearch,
    ].filter(Boolean).length,
    supportsVision: model.supportsVision,
    supportsTools: model.supportsTools,
    supportsDocuments: model.supportsDocuments,
    badges,
  };
}

function asSafetyMode(value: string | undefined | null): SafetyMode {
  return SAFETY_MODES.some((mode) => mode.id === value) ? (value as SafetyMode) : "safe";
}

function statusLabel(stage?: string) {
  const labels: Record<string, string> = {
    planning: "Planejando",
    waiting_permission: "Aguardando permissao",
    executing: "Executando",
    verifying: "Verificando",
    success: "Concluido",
    failed: "Falhou",
    denied: "Negado",
    expired: "Expirado",
  };
  return labels[stage || ""] || stage || "Agent Mode";
}

interface TabChatProps {
  isActive: boolean;
}

export function TabChat({ isActive }: TabChatProps) {
  const [initialChatState] = useState(buildInitialChatState);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>(initialChatState.sessions);
  const [activeSessionId, setActiveSessionId] = useState(initialChatState.activeSessionId);
  const [messages, setMessages] = useState<ChatMessage[]>(initialChatState.messages);
  // Identidade customizável (nome/avatar da Personalização); atualiza ao vivo via evento.
  const [identity, setIdentityState] = useState(() => loadIdentity());
  useEffect(() => {
    const onChanged = () => setIdentityState(loadIdentity());
    window.addEventListener(IDENTITY_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(IDENTITY_CHANGED_EVENT, onChanged);
  }, []);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [provider, setProvider] = useState("gemini_api");
  const [model, setModel] = useState("gemini-3.1-pro-preview");
  const [nativeSearchMode, setNativeSearchMode] = useState<"auto" | "force" | "off">("auto");
  const [openrouterRoutingByModel, setOpenrouterRoutingByModel] = useState<ChatConfig["openrouterRoutingByModel"]>({});
  const [catalogModels, setCatalogModels] = useState<ModelSpec[]>([]);
  const [llmProviders, setLlmProviders] = useState<string[]>([]);
  const [chatConfigLoaded, setChatConfigLoaded] = useState(false);
  const [safetyMode, setSafetyMode] = useState<SafetyMode>((localStorage.getItem("hana_agent_safety_mode") as SafetyMode) || "safe");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [chatControlsOpen, setChatControlsOpen] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState<Record<string, boolean>>({});
  const [showFullHistory, setShowFullHistory] = useState(false);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [chatTtsConfig, setChatTtsConfig] = useState<LlmConfig | null>(null);
  // Ajustar "Pensar" aqui muda o MESMO llm_config lido pela aba Cerebro (chat.py
  // le direto do backend a cada turno) -- so precisa atualizar o estado local pra
  // UI refletir na hora, sem esperar reload.
  const updateThinkingConfig = async (patch: Partial<LlmConfig>) => {
    setChatTtsConfig((prev) => (prev ? { ...prev, ...patch } : prev));
    if (!(await ApiController.updateLlmConfig(patch))) {
      alert("A alteração ficou pendente e será sincronizada quando a Hana voltar.");
    }
  };
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [autoTtsEnabled, setAutoTtsEnabled] = useState(() => localStorage.getItem(CHAT_AUTO_TTS_KEY) === "true");
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [liveActivity, setLiveActivity] = useState({ label: "", detail: "" });
  const [liveThinking, setLiveThinking] = useState<ThinkingItem[]>([]);
  const [showTypingSpeed, setShowTypingSpeed] = useState(() => localStorage.getItem(CHAT_SHOW_TYPING_SPEED_KEY) !== "false");
  const [typingSpeed, setTypingSpeed] = useState<TypingSpeed>(() => {
    const stored = localStorage.getItem(CHAT_TYPING_SPEED_KEY) as TypingSpeed | null;
    return stored && stored in TYPING_SPEED_MS ? stored : "normal";
  });
  const typingBufferRef = useRef("");
  const typingDisplayedRef = useRef(0);
  const typingTimerRef = useRef<number | null>(null);
  const typingCompleteRef = useRef<(() => void) | null>(null);
  const typingSpeedMsRef = useRef(TYPING_SPEED_MS[typingSpeed]);
  const typingSpeedCharsRef = useRef(TYPING_SPEED_CHARS[typingSpeed]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const currentResponseRef = useRef("");
  const currentMetaRef = useRef<ChatMessage["meta"] | null>(null);
  const thinkingAccumulatorRef = useRef<ThinkingItem[]>([]);
  const reasoningStartTimeRef = useRef<number>(0);
  const userScrolledUpRef = useRef(false);
  const manualScrollRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recorderChunksRef = useRef<Blob[]>([]);
  const recorderStartedAtRef = useRef(0);
  const recorderStreamRef = useRef<MediaStream | null>(null);
  const autoTtsEnabledRef = useRef(autoTtsEnabled);
  const deferredMessages = useDeferredValue(messages);
  // Never defer the active streamer message. React may intentionally skip deferred
  // intermediate states, which makes character-by-character output appear all at once.
  const renderedMessages = isTyping ? messages : deferredMessages;
  const hiddenMessages = showFullHistory ? 0 : Math.max(0, renderedMessages.length - MAX_RENDERED_MESSAGES);
  const visibleMessages = showFullHistory ? renderedMessages : renderedMessages.slice(-MAX_RENDERED_MESSAGES);

  const availableModels = useMemo(
    () => catalogModels.filter((item) => item.provider === provider && (item.modelDomain || "chat") === "chat" && (item.outputModalities || []).includes("text")),
    [catalogModels, provider],
  );
  const modelPickerOptions = useMemo(() => {
    const options = availableModels.map(chatModelOption);
    if (model && !options.some((option) => option.value === model)) {
      options.push({
        value: model,
        label: `${model} (custom)`,
        favoriteId: `${provider}:${model}`,
        secondary: model,
        badges: [{ label: "custom", tone: "neutral" }],
      });
    }
    return options;
  }, [availableModels, model, provider]);

  const selectChatProvider = (providerValue: string) => {
    const selectedProvider = normalizeProvider(providerValue);
    const providerModels = catalogModels.filter((item) => item.provider === selectedProvider && (item.modelDomain || "chat") === "chat" && (item.outputModalities || []).includes("text"));
    setProvider(selectedProvider);
    setModel(providerModels[0]?.id || "");
    setNativeSearchMode(selectedProvider === "gemini_api" ? "auto" : "off");
  };

  // Gemini tem grounding nativo; OpenRouter tem o plugin "web" (cobrado por busca,
  // então o padrão lá é off e a Nakamura liga quando quiser).
  const providerHasWebSearch = provider === "gemini_api" || provider === "openrouter";

  useEffect(() => {
    if (!availableModels.some((item) => item.id === model)) {
      setModel(availableModels[0]?.id || "");
    }
  }, [availableModels, model]);

  // Keep follow mode independent from layout-driven scroll events while content grows.
  const handleChatScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom <= 48) {
      userScrolledUpRef.current = false;
      setShowScrollToBottom(false);
      return;
    }
    if (manualScrollRef.current) {
      userScrolledUpRef.current = true;
      setShowScrollToBottom(true);
    }
  };

  // Upward wheel input is explicit intent to inspect older messages.
  const handleChatWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < 0) {
      userScrolledUpRef.current = true;
      setShowScrollToBottom(true);
    }
  };

  // Scroll after the hidden tab becomes visible so the container has a real height.
  useEffect(() => {
    if (!isActive) return;
    let raf2 = 0;
    let settleTimer = 0;
    // Double RAF handles tab visibility; the short timer catches late media layout.
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
          userScrolledUpRef.current = false;
          setShowScrollToBottom(false);
        }
      });
      settleTimer = window.setTimeout(() => {
        if (scrollRef.current && !userScrolledUpRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
      }, 150);
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      window.clearTimeout(settleTimer);
    };
  }, [activeSessionId, isActive]);

  // Follow every height change from streamed text, tools, sources and media.
  useEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (!isActive || userScrolledUpRef.current || !scrollRef.current) return;
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [isActive]);

  // When user sends a new message, always scroll to bottom
  const forceScrollToBottom = (behavior: ScrollBehavior = "auto") => {
    userScrolledUpRef.current = false;
    setShowScrollToBottom(false);
    if (scrollRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTo({
            top: scrollRef.current.scrollHeight,
            behavior,
          });
        }
      });
    }
  };

  const scrollToBottomButton = () => {
    forceScrollToBottom("smooth");
  };

  useEffect(() => {
    localStorage.removeItem(LEGACY_CHAT_MESSAGES_KEY);
  }, []);

  useEffect(() => {
    autoTtsEnabledRef.current = autoTtsEnabled;
    localStorage.setItem(CHAT_AUTO_TTS_KEY, String(autoTtsEnabled));
  }, [autoTtsEnabled]);

  useEffect(() => {
    localStorage.setItem(CHAT_SHOW_TYPING_SPEED_KEY, String(showTypingSpeed));
  }, [showTypingSpeed]);

  useEffect(() => {
    typingSpeedMsRef.current = TYPING_SPEED_MS[typingSpeed];
    typingSpeedCharsRef.current = TYPING_SPEED_CHARS[typingSpeed];
    localStorage.setItem(CHAT_TYPING_SPEED_KEY, typingSpeed);
  }, [typingSpeed]);

  useEffect(() => {
    localStorage.setItem(CHAT_ACTIVE_SESSION_KEY, activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    setChatSessions((prev) => prev.map((session) => (
      session.id === activeSessionId
        ? {
            ...session,
            title: titleFromMessages(messages),
            updatedAt: new Date().toISOString(),
            messages: trimMessagesForStorage(messages),
          }
        : session
    )));
  }, [messages, activeSessionId]);

  useEffect(() => {
    localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify(chatSessions.slice(0, 30)));
  }, [chatSessions]);

  // Carrega as configuraÃ§Ãµes de LLM e histÃ³rico do servidor
  useEffect(() => {
    Promise.all([
      ApiController.getChatConfig(),
      ApiController.getCatalog(),
      ApiController.getAgentSettings(),
      ApiController.getVoiceConfig(),
      ApiController.getLlmConfig(),
    ])
      .then(([chatConfig, catalog, settings, loadedVoiceConfig, loadedLlmConfig]) => {
        const providers = catalog?.llmProviders || [];
        const models = catalog?.models || [];
        const selectedProvider = normalizeProvider(chatConfig?.provider || providers[0] || "gemini_api");
        const providerModels = models.filter((item: ModelSpec) => item.provider === selectedProvider);
        const selectedModel = providerModels.some((item: ModelSpec) => item.id === chatConfig?.model)
          ? String(chatConfig.model)
          : (providerModels[0]?.id || chatConfig?.model || "gemini-3.1-pro-preview");
        setLlmProviders(providers);
        setCatalogModels(models);
        setProvider(selectedProvider);
        setModel(selectedModel);
        setNativeSearchMode((selectedProvider === "gemini_api" || selectedProvider === "openrouter") ? ((chatConfig?.nativeSearchMode || (selectedProvider === "gemini_api" ? "auto" : "off")) as "auto" | "force" | "off") : "off");
        setOpenrouterRoutingByModel(chatConfig?.openrouterRoutingByModel || {});
        const mode = asSafetyMode(settings?.safety_mode);
        setSafetyMode(mode);
        setVoiceConfig(loadedVoiceConfig);
        setChatTtsConfig(loadedLlmConfig);
        localStorage.setItem("hana_agent_safety_mode", mode);
        setChatConfigLoaded(true);
      })
      .catch(() => {
        setChatConfigLoaded(true);
      });

    // Carrega o histÃ³rico persistente do servidor
    /*
    ApiController.getChatHistory(80).then(({ messages: serverMessages }) => {
      if (serverMessages.length === 0) return;
      
      // Converte msg {role, content} para ChatMessage {id, role, content, timestamp}
      const historyMsgs: ChatMessage[] = serverMessages
        .filter(m => m.role !== "system") // ignora system do histÃ³rico
        .map(m => ({
          id: `hist-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          role: m.role === "Nakamura" ? "user" as const : "hana" as const,
          content: m.content,
          timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
        }));

      setMessages(prev => {
        // Se jÃ¡ tem mais que sÃ³ a msg de sistema, mantÃ©m (pode ter carregado do localStorage)
        if (prev.length > 1) return prev;
        return [prev[0], ...historyMsgs.slice(-50)];
      });
    });
    */
  }, []);

  useEffect(() => {
    if (!chatConfigLoaded) return;
    ApiController.updateChatConfig({
      provider,
      model,
      nativeSearchMode: providerHasWebSearch ? nativeSearchMode : "off",
      openrouterRoutingByModel,
    });
  }, [provider, model, nativeSearchMode, openrouterRoutingByModel, chatConfigLoaded]);

  useEffect(() => {
    ApiController.updateAgentSettings(safetyMode);
  }, [safetyMode]);

  // Limpeza do WebSocket ao desmontar
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (mediaRecorderRef.current?.state === "recording") mediaRecorderRef.current.stop();
      recorderStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    if (!imagePreviewUrl) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setImagePreviewUrl(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [imagePreviewUrl]);

  const startNewChat = () => {
    const session = createChatSession();
    setChatSessions((prev) => [session, ...prev].slice(0, 30));
    setActiveSessionId(session.id);
    setMessages(session.messages);
    setExpandedMessages({});
    setShowFullHistory(false);
    userScrolledUpRef.current = false;
    setShowScrollToBottom(false);
  };

  /**
   * Traz uma conversa do BANCO pra uma sessao local NOVA.
   *
   * Sessao nova de proposito: importar por cima da conversa aberta apagaria o
   * que a Nakamura esta usando agora. Assim ela importa, olha, e as conversas
   * dela continuam intactas do lado.
   */
  const importarDoBanco = useCallback((titulo: string, mensagens: ChatMessage[]) => {
    if (!mensagens.length) return;
    const agora = new Date().toISOString();
    const session: ChatSession = {
      id: `db-${Date.now()}`,
      title: `📁 ${titulo}`,
      createdAt: agora,
      updatedAt: agora,
      messages: mensagens,
    };
    setChatSessions((prev) => [session, ...prev].slice(0, 30));
    setActiveSessionId(session.id);
    setMessages(mensagens);
    setExpandedMessages({});
    setShowFullHistory(true);
  }, []);

  const switchChatSession = (sessionId: string) => {
    const session = chatSessions.find((item) => item.id === sessionId);
    if (!session) return;
    setActiveSessionId(session.id);
    setMessages(session.messages?.length ? session.messages : [createWelcomeMessage()]);
    setExpandedMessages({});
    setShowFullHistory(false);
    userScrolledUpRef.current = false;
    setShowScrollToBottom(false);
  };

  const deleteChatSession = (sessionId: string) => {
    const remaining = chatSessions.filter((item) => item.id !== sessionId);
    if (remaining.length === 0) {
      const session = createChatSession();
      setChatSessions([session]);
      setActiveSessionId(session.id);
      setMessages(session.messages);
      return;
    }
    setChatSessions(remaining);
    if (sessionId === activeSessionId) {
      setActiveSessionId(remaining[0].id);
      setMessages(remaining[0].messages?.length ? remaining[0].messages : [createWelcomeMessage()]);
    }
  };

  const clearCurrentChat = () => {
    setMessages([createWelcomeMessage()]);
    setExpandedMessages({});
    setShowFullHistory(false);
  };

  // useCallback com deps estaveis (so setState funcional) pra essas referencias
  // nao mudarem a cada render -- senao o React.memo das linhas de mensagem no
  // ChatMessageList nao segura nada, e o chat volta a travar com muito texto.
  const deleteMessage = useCallback((messageId: string) => {
    setMessages((prev) => {
      const next = prev.filter((message) => message.id !== messageId);
      return next.length ? next : [createWelcomeMessage()];
    });
  }, []);

  const deleteMediaItem = useCallback((messageId: string, mediaIndex: number) => {
    setMessages((prev) => prev.map((message) => {
      if (message.id !== messageId || !message.media) return message;
      return {
        ...message,
        media: message.media.filter((_, index) => index !== mediaIndex),
      };
    }));
  }, []);

  const toggleExpandMessage = useCallback((msgId: string) => {
    setExpandedMessages((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  }, []);

  // Sugestao da tela inicial: preenche a caixa e deixa o cursor no fim, pra
  // Nakamura so completar a frase em vez de encarar a tela em branco.
  const handlePickStarterPrompt = useCallback((prompt: string) => {
    setInput(prompt);
    window.setTimeout(() => {
      const field = inputRef.current;
      if (!field) return;
      field.focus();
      field.setSelectionRange(prompt.length, prompt.length);
    }, 0);
  }, []);

  const renderMessageContent = useCallback((message: ChatMessage) => {
    const expanded = Boolean(expandedMessages[message.id]);
    const shouldTrim = message.content.length > LONG_MESSAGE_LIMIT && !expanded;
    return shouldTrim ? `${message.content.slice(0, LONG_MESSAGE_LIMIT)}\n\n...` : message.content;
  }, [expandedMessages]);

  // Finish the network turn only after the visible streamer drains its buffer.
  const completeTypingIfReady = () => {
    if (typingDisplayedRef.current < typingBufferRef.current.length) return;
    const complete = typingCompleteRef.current;
    if (!complete) return;
    typingCompleteRef.current = null;
    stopTypingAnimation();
    // Force a final render of the WHOLE buffer. The authoritative `final` text is often
    // shorter than the raw stream (image/memory XML tags stripped), and the reveal loop
    // can stop on a stale partial render without painting the cleaned text — which then
    // gets frozen as the saved message (raw tag visible + cut mid-word). Paint it fully.
    const full = typingBufferRef.current;
    typingDisplayedRef.current = full.length;
    currentResponseRef.current = full;
    setMessages(prev => {
      const last = prev[prev.length - 1];
      if (last && last.role === "hana" && last.id === "streaming-res" && last.content !== full) {
        return [...prev.slice(0, -1), { ...last, content: full }];
      }
      return prev;
    });
    complete();
  };

  // Typing animation reveals provider output at a readable pace on every provider.
  // resume=true keeps the already-revealed position (used when the live stream is replaced
  // by the cleaned final text), instead of re-typing from the start.
  const startTypingAnimation = (resume = false) => {
    stopTypingAnimation();
    if (!resume) typingDisplayedRef.current = 0;
    typingTimerRef.current = window.setInterval(() => {
      const fullText = typingBufferRef.current;
      const displayed = typingDisplayedRef.current;
      if (!fullText || displayed >= fullText.length) {
        completeTypingIfReady();
        return;
      }

      const remaining = fullText.length - displayed;
      // Drain the provider buffer in small, stable character batches. This keeps
      // the visual rhythm smooth without re-rendering Markdown for every character.
      const catchUpMultiplier = remaining > 1200 ? 4 : remaining > 500 ? 2 : 1;
      const step = typingSpeedMsRef.current === 0
        ? remaining
        : Math.min(remaining, typingSpeedCharsRef.current * catchUpMultiplier);
      const nextDisp = Math.min(fullText.length, displayed + step);
      typingDisplayedRef.current = nextDisp;
      const visible = fullText.slice(0, nextDisp);
      currentResponseRef.current = visible;

      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.role === "hana" && last.id === "streaming-res") {
          return [...prev.slice(0, -1), { ...last, content: visible }];
        }
        return prev;
      });

      completeTypingIfReady();
    }, typingSpeedMsRef.current > 0 ? typingSpeedMsRef.current : 8);
  };

  const stopTypingAnimation = () => {
    if (typingTimerRef.current !== null) {
      window.clearInterval(typingTimerRef.current);
      typingTimerRef.current = null;
    }
  };

  const feedTypingBuffer = (token: string) => {
    typingBufferRef.current += token;
    setLiveActivity({ label: "Hana está escrevendo", detail: "Montando a resposta em tempo real." });
    if (typingTimerRef.current === null) {
      // Create a streaming-res message placeholder first
      setMessages(prev => {
        if (prev[prev.length - 1]?.id === "streaming-res") return prev;
        return [...prev, { id: "streaming-res", role: "hana", content: "", timestamp: nowTime(), meta: currentMetaRef.current || undefined }];
      });
      startTypingAnimation();
    }
  };

  // Replace the streaming buffer with the authoritative cleaned final text (tags stripped),
  // keeping the current typed position so the reveal animation finishes smoothly.
  const replaceTypingBuffer = (text: string) => {
    typingBufferRef.current = text;
    if (typingDisplayedRef.current > text.length) {
      typingDisplayedRef.current = text.length;
    }
    if (typingTimerRef.current === null && typingDisplayedRef.current < text.length) {
      // Placeholder must exist if no delta ever created it (defensive).
      setMessages((prev) => {
        if (prev[prev.length - 1]?.id === "streaming-res") return prev;
        return [...prev, { id: "streaming-res", role: "hana", content: "", timestamp: nowTime(), meta: currentMetaRef.current || undefined }];
      });
      startTypingAnimation(true);
    }
    completeTypingIfReady();
  };

  const flushTypingBuffer = () => {
    typingCompleteRef.current = null;
    stopTypingAnimation();
    const fullText = typingBufferRef.current;
    if (fullText) {
      typingDisplayedRef.current = fullText.length;
      currentResponseRef.current = fullText;
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.role === "hana" && last.id === "streaming-res") {
          return [...prev.slice(0, -1), { ...last, content: fullText }];
        }
        return prev;
      });
    }
  };

  const stopCurrentResponse = () => {
    ApiController.cancelChatResponse();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    flushTypingBuffer();
    stopTypingAnimation();
    setIsTyping(false);
    setLiveActivity({ label: "", detail: "" });
    setMessages(prev => {
      const last = prev[prev.length - 1];
      if (last && last.id === "streaming-res") {
        return [...prev.slice(0, -1), { ...last, id: Date.now().toString() }];
      }
      return prev;
    });
  };

  const appendSystemMessage = (content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `system-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        role: "system",
        content,
        timestamp: nowTime(),
      },
    ]);
  };

  // Adds visible operational steps to the message Agent Mode panel.
  const appendMessageAgentStep = (messageId: string, step: { tool: string; status: string; risk?: string; summary?: string }) => {
    setMessages((prev) => prev.map((message) => {
      if (message.id !== messageId) return message;
      return {
        ...message,
        agentStatus: {
          stage: step.status as AgentStage,
          tool_name: step.tool,
          risk: step.risk || "low",
          detail: step.summary || "",
        },
        agentPlan: {
          ...(message.agentPlan || { intent: "chat_control_center", steps: [] }),
          steps: [...(message.agentPlan?.steps || []), { tool: step.tool, status: step.status, risk: step.risk || "low", summary: step.summary }],
        },
      };
    }));
  };

  // Generates a chat-local audio player instead of speaking directly through the backend.
  const generateMessageSpeech = async (messageId: string, text: string) => {
    const cleanText = text.trim();
    if (!cleanText) return;
    const jobId = `tts-${messageId}`;
    appendMessageAgentStep(messageId, { tool: "tts.synthesize", status: "executing", summary: "Gerando audio da resposta." });
    setMessages((prev) => prev.map((message) => {
      if (message.id !== messageId) return message;
      const media = message.media || [];
      const existingIndex = media.findIndex((item) => item.job_id === jobId);
      const nextAudio = { type: "audio" as const, job_id: jobId, name: "Voz da Hana", status: "generating" as const };
      return {
        ...message,
        media: existingIndex >= 0
          ? [...media.slice(0, existingIndex), { ...media[existingIndex], ...nextAudio }, ...media.slice(existingIndex + 1)]
          : [...media, nextAudio],
      };
    }));

    try {
      const effectiveTtsConfig = await ApiController.getLlmConfig().catch(() => chatTtsConfig);
      if (effectiveTtsConfig) setChatTtsConfig(effectiveTtsConfig);
      const result = await ApiController.synthesizeTerminalAgentSpeech(cleanText, {
        provider: effectiveTtsConfig?.ttsProvider,
        model: effectiveTtsConfig?.ttsModel,
        voice: effectiveTtsConfig?.ttsVoice,
        language: effectiveTtsConfig?.ttsLanguage,
        prompt: effectiveTtsConfig?.ttsPrompt,
        speed: effectiveTtsConfig?.ttsSpeed,
        pitch: effectiveTtsConfig?.ttsPitch,
        streaming: effectiveTtsConfig?.ttsStreaming,
        stability: effectiveTtsConfig?.ttsStability,
        similarity: effectiveTtsConfig?.ttsSimilarity,
        style: effectiveTtsConfig?.ttsStyle,
        speakerBoost: effectiveTtsConfig?.ttsSpeakerBoost,
      });
      const url = `data:${result.mimeType};base64,${result.audioBase64}`;
      setMessages((prev) => prev.map((message) => {
        if (message.id !== messageId) return message;
        const media = message.media || [];
        return {
          ...message,
          media: media.map((item) => item.job_id === jobId
            ? {
                ...item,
                url,
                status: "ready",
                provider: result.provider,
                voice: result.voice,
                mimeType: result.mimeType,
                durationMs: result.durationMs,
                volume: Math.max(0, Math.min(1, effectiveTtsConfig?.ttsVolume ?? 1)),
              }
            : item),
        };
      }));
      appendMessageAgentStep(messageId, { tool: "tts.synthesize", status: "success", summary: `Audio gerado com ${result.provider}.` });
    } catch (error) {
      const message = error instanceof Error ? error.message : "falha desconhecida";
      setMessages((prev) => prev.map((item) => {
        if (item.id !== messageId) return item;
        return {
          ...item,
          media: (item.media || []).map((media) => media.job_id === jobId ? { ...media, status: "failed" } : media),
        };
      }));
      appendMessageAgentStep(messageId, { tool: "tts.synthesize", status: "failed", risk: "medium", summary: message });
    }
  };

  // Referencia estavel pra passar pro ChatMessageList sem quebrar o memo das
  // linhas de mensagem (mesmo truque do handleCancelJob em TabTerminalAgent.tsx).
  const generateMessageSpeechRef = useRef(generateMessageSpeech);
  generateMessageSpeechRef.current = generateMessageSpeech;
  const handleGenerateSpeech = useCallback((msgId: string, content: string) => {
    void generateMessageSpeechRef.current(msgId, content);
  }, []);

  const transcribeChatAudio = async (audio: Blob, durationMs: number) => {
    setIsTranscribing(true);
    try {
      appendSystemMessage("Transcrevendo audio do microfone...");
      const result = await ApiController.transcribeTerminalAgentAudio(audio, {
        provider: voiceConfig?.sttProvider || "groq_whisper",
        model: voiceConfig?.sttModel || "whisper-large-v3",
        language: voiceConfig?.sttLanguage || "pt",
        durationMs,
        respond: false,
      });
      if (!result.text) {
        appendSystemMessage("STT terminou, mas nao retornou texto.");
        return;
      }
      setInput((prev) => [prev.trim(), result.text].filter(Boolean).join(prev.trim() ? "\n" : ""));
      inputRef.current?.focus();
    } catch (error) {
      const message = error instanceof Error ? error.message : "falha desconhecida";
      appendSystemMessage(`Falha ao transcrever audio: ${message}`);
    } finally {
      setIsTranscribing(false);
    }
  };

  const startChatRecording = async () => {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      appendSystemMessage("Este WebView/navegador nao oferece MediaRecorder para capturar microfone.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = supportedAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderChunksRef.current = [];
      recorderStartedAtRef.current = performance.now();
      recorderStreamRef.current = stream;
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recorderChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const durationMs = Math.max(0, Math.round(performance.now() - recorderStartedAtRef.current));
        const audio = new Blob(recorderChunksRef.current, { type: recorder.mimeType || mimeType || "audio/webm" });
        stream.getTracks().forEach((track) => track.stop());
        recorderStreamRef.current = null;
        mediaRecorderRef.current = null;
        setIsRecording(false);
        if (audio.size > 0) void transcribeChatAudio(audio, durationMs);
        else appendSystemMessage("Microfone nao gravou audio.");
      };
      recorder.start();
      setIsRecording(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "falha desconhecida";
      appendSystemMessage(`Falha ao abrir microfone: ${message}`);
      setIsRecording(false);
    }
  };

  const stopChatRecording = () => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
      return;
    }
    setIsRecording(false);
  };

  const toggleChatRecording = () => {
    if (isRecording) {
      stopChatRecording();
      return;
    }
    void startChatRecording();
  };

  const shutdownHana = async () => {
    const confirmed = window.confirm("Desligar a Hana agora? Isso encerra o backend local.");
    if (!confirmed) return;
    try {
      await ApiController.shutdownSystem();
      appendSystemMessage("Shutdown solicitado. A Hana deve encerrar em alguns segundos.");
    } catch {
      appendSystemMessage("Nao consegui solicitar o shutdown pelo Control Center.");
    }
  };

  const handleSend = () => {
    if (!input.trim() && attachments.length === 0) return;

    // Se jÃ¡ estiver processando, nÃ£o deixa mandar outra
    if (isTyping) return;

    // Fecha conexÃ£o anterior se existir
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: input.trim(),
      timestamp: nowTime(),
      attachments: attachments.map((attachment) => ({ ...attachment }))
    };
    const imageAttachments = attachments
      .filter((attachment) => attachment.type.startsWith("image/"))
      .map((attachment) => attachment.data);
    const historyForBackend = messages
      .filter((msg) => (msg.role === "user" || msg.role === "hana") && !msg.meta?.providerError)
      .slice(-MAX_BACKEND_HISTORY_MESSAGES)
      .map((msg) => ({ role: msg.role, content: msg.content }));

    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setAttachments([]);
    setIsTyping(true);
    setLiveActivity({ label: "Hana recebeu a mensagem", detail: "Preparando contexto e escolhendo o próximo passo." });
    currentResponseRef.current = "";
    currentMetaRef.current = null;
    thinkingAccumulatorRef.current = [];
    reasoningStartTimeRef.current = 0;
    setLiveThinking([]);
    forceScrollToBottom();

    // Modo Streamer (SSE) com digitação letra-por-letra
    typingBufferRef.current = "";
    typingDisplayedRef.current = 0;
    typingCompleteRef.current = null;
    stopTypingAnimation();

    // Garante que a bolha "streaming-res" existe assim que o primeiro evento ao vivo
    // chega (pensamento OU ferramenta) — sem isso, um turno que começa direto numa
    // chamada de ferramenta (sem texto antes) não tem onde o "meta" (que chega logo
    // depois) se anexar, e o evento é descartado (bug: nenhuma caixa aparecia).
    const ensureStreamingPlaceholder = () => {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.role === "hana" && last.id === "streaming-res") return prev;
        return [...prev, {
          id: "streaming-res",
          role: "hana" as const,
          content: "",
          timestamp: nowTime(),
          meta: currentMetaRef.current || undefined,
        }];
      });
    };

    // Preserve operational Agent Mode events while visually streaming every provider.
    const { ws } = ApiController.connectChatWebSocket(
        userMsg.content,
        imageAttachments,
        attachments,
        provider,
        model,
        providerHasWebSearch ? nativeSearchMode : "off",
        safetyMode,
        historyForBackend,
        provider === "openrouter" ? (openrouterRoutingByModel[model] || DEFAULT_OPENROUTER_ROUTING) : {},
        // onChunk
        (chunk) => feedTypingBuffer(chunk),
        // onFinalText (authoritative cleaned text after live streaming)
        (finalText) => replaceTypingBuffer(finalText),
        // onMeta
        (meta) => {
          currentMetaRef.current = meta;
          if (meta?.toolRuns?.length) {
            const lastRun = meta.toolRuns[meta.toolRuns.length - 1];
            setLiveActivity({
              label: `${meta.toolRuns.length} chamada${meta.toolRuns.length === 1 ? "" : "s"} concluída${meta.toolRuns.length === 1 ? "" : "s"}`,
              detail: lastRun?.summary || lastRun?.tool || "Ferramentas processadas.",
            });
          }
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last && last.role === "hana" && last.id === "streaming-res") {
              return [...prev.slice(0, -1), { ...last, meta }];
            }
            return prev;
          });
        },
        // onAgentPlan
        (plan) => {
          setLiveActivity({ label: "Hana está planejando", detail: plan?.intent || "Organizando os próximos passos." });
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last && last.role === "hana" && last.id === "streaming-res") {
              return [...prev.slice(0, -1), { ...last, agentPlan: plan }];
            }
            return [...prev, {
              id: "streaming-res",
              role: "hana",
              content: "",
              timestamp: nowTime(),
              agentPlan: plan
            }];
          });
        },
        // onAgentStatus
        (status) => {
          setLiveActivity({
            label: statusLabel(status?.stage),
            detail: status?.detail || status?.tool_name || "Processando o turno.",
          });
          setMessages(prev => {
            const step = {
              tool: status?.tool_name || "agent",
              status: status?.stage || "planning",
              risk: status?.risk || "low",
              summary: status?.detail || status?.source || "",
            };
            const last = prev[prev.length - 1];
            if (last && last.role === "hana" && last.id === "streaming-res") {
              return [...prev.slice(0, -1), {
                ...last,
                agentStatus: status,
                agentPlan: {
                  ...(last.agentPlan || { intent: "tool_action", steps: [] }),
                  steps: [...(last.agentPlan?.steps || []), step],
                }
              }];
            }
            return [...prev, {
              id: "streaming-res",
              role: "hana",
              content: "",
              timestamp: nowTime(),
              meta: currentMetaRef.current || undefined,
              agentStatus: status,
              agentPlan: { intent: "tool_action", steps: [step] },
            }];
          });
        },
        // onActivity: compact operational preview, never hidden chain-of-thought.
        (activity) => {
          setLiveActivity({
            label: activity?.label || "Hana está processando",
            detail: activity?.detail || "Executando o próximo passo.",
          });
        },
        // onMedia
        (media) => {
           setMessages(prev => {
             const last = prev[prev.length - 1];
             if (last && last.role === "hana") {
               let updatedMedia = last.media || [];
               const existingIndex = updatedMedia.findIndex(m => m.job_id === media.job_id);

               if (existingIndex !== -1) {
                 updatedMedia = [
                   ...updatedMedia.slice(0, existingIndex),
                   { ...updatedMedia[existingIndex], ...media },
                   ...updatedMedia.slice(existingIndex + 1)
                 ];
               } else {
                 updatedMedia = [...updatedMedia, media];
               }

               return [...prev.slice(0, -1), { ...last, media: updatedMedia }];
             }
             return prev;
           });
        },
        // onDone
        () => {
          typingCompleteRef.current = () => {
            setIsTyping(false);
            setLiveActivity({ label: "", detail: "" });
            const finalId = `hana-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
            const finalText = typingBufferRef.current.trim();
            const thinkingElapsedMs = reasoningStartTimeRef.current ? Date.now() - reasoningStartTimeRef.current : 0;

            setMessages(prev => {
              const last = prev[prev.length - 1];
              if (last && last.id === "streaming-res") {
                return [...prev.slice(0, -1), {
                  ...last,
                  id: finalId,
                  thinking: thinkingAccumulatorRef.current.length ? thinkingAccumulatorRef.current : undefined,
                  thinkingElapsedMs,
                }];
              }
              return prev;
            });

            // Clean up accumulators
            thinkingAccumulatorRef.current = [];
            reasoningStartTimeRef.current = 0;
            setLiveThinking([]);

            if (autoTtsEnabledRef.current && finalText) {
              window.setTimeout(() => void generateMessageSpeech(finalId, finalText), 0);
            }
          };
          completeTypingIfReady();
        },
        // onError
        (err) => {
          console.error("Erro no chat:", err);
          flushTypingBuffer();
          setIsTyping(false);
          setLiveActivity({ label: "", detail: "" });
          setMessages(prev => [...prev, {
            id: `err-${Date.now()}`,
            role: "system",
            content: "Erro na conexão com o servidor da Hana.",
            timestamp: nowTime()
          }]);
        },
        // onReasoning: acumula o texto pensado na timeline única (thinking).
        (activity) => {
          if (!reasoningStartTimeRef.current) {
            reasoningStartTimeRef.current = Date.now();
          }
          const chunk = activity?.detail || "";
          const items = thinkingAccumulatorRef.current;
          const lastItem = items[items.length - 1];
          if (lastItem && lastItem.type === "text") {
            lastItem.content += chunk;
          } else {
            items.push({ type: "text", content: chunk });
          }
          setLiveThinking([...items]);
          ensureStreamingPlaceholder();

          setLiveActivity({
            label: activity?.label || "Hana está pensando...",
            detail: "",
          });
        },
        // onToolActivity: chamada de ferramenta entra na MESMA timeline do "pensando"
        // (era um card "Ferramentas" + outro "Agent Mode" duplicando a mesma info).
        (event: { kind?: string; tool?: string; args?: Record<string, unknown>; result?: Record<string, unknown> }) => {
          const toolName = event?.tool || event?.kind || "tool";
          const isToolCall = event?.kind === "tool_call";
          const isToolResult = event?.kind === "tool_result";
          const ok = isToolResult ? ((event?.result as Record<string, unknown>)?.ok !== false) : undefined;

          thinkingAccumulatorRef.current = [
            ...thinkingAccumulatorRef.current,
            { type: (event?.kind || "tool_call") as "tool_call" | "tool_result", tool: toolName, args: event?.args, result: event?.result },
          ];
          setLiveThinking([...thinkingAccumulatorRef.current]);
          ensureStreamingPlaceholder();

          const label = isToolCall
            ? `Chamando ${toolName}...`
            : isToolResult
              ? (ok ? `${toolName} concluida` : `Erro em ${toolName}`)
              : `${toolName}`;
          // Sem dump de JSON cru aqui — só o label curto; o footer mostra um cursor piscando.
          setLiveActivity({ label, detail: "" });
        }
      );

    wsRef.current = ws;
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const addFilesAsAttachments = (files: FileList | File[]) => {
    Array.from(files).forEach((file) => {
      if (file.size > MAX_ATTACHMENT_BYTES) {
        setMessages((prev) => [...prev, {
          id: `warn-${Date.now()}`,
          role: "system",
          content: `Anexo ignorado: ${file.name} passa de 25 MB.`,
          timestamp: nowTime(),
        }]);
        return;
      }
      const reader = new FileReader();
      reader.onload = (ev) => {
        const base64 = ev.target?.result as string;
        setAttachments((prev) => [...prev, {
          name: file.name,
          data: base64,
          type: file.type || "application/octet-stream",
          size: file.size,
        }]);
      };
      reader.readAsDataURL(file);
    });
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") !== -1) {
        const file = items[i].getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            const base64 = ev.target?.result as string;
            setAttachments(prev => [...prev, { name: "pasted_image.png", data: base64, type: "image/png", size: file.size }]);
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    addFilesAsAttachments(files);
    e.target.value = "";
  };

  const removeAttachment = (index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (!files) return;

    addFilesAsAttachments(files);
  };

  return (
    <div 
      className="w-full h-full overflow-hidden relative flex flex-col bg-[var(--bg-sidebar)] hana-glass"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Overlay Drag & Drop */}
      {isDragging && (
        <div className="absolute inset-0 bg-[var(--purple-dark)]/80 backdrop-blur-md z-50 flex items-center justify-center border-[3px] border-dashed border-[var(--purple-neon)] m-4 rounded-xl transition-all">
           <div className="flex flex-col items-center justify-center p-12 bg-black/40 rounded-2xl animate-pulse">
             <div className="w-20 h-20 bg-[var(--purple-neon)]/20 text-[var(--purple-neon)] rounded-full flex items-center justify-center mb-4 border border-[var(--purple-neon)]">
               <Paperclip size={40} />
             </div>
              <h2 className="text-3xl font-extrabold text-white mb-2 tracking-widest uppercase">Soltar arquivo aqui</h2>
              <p className="text-[var(--cyan-neon)] font-mono">Imagens, audio, PDF, texto, GIF e video entram como anexos</p>
           </div>
        </div>
      )}
      
      <ChatHeader
        identity={identity}
        provider={provider}
        model={model}
        configOpen={chatControlsOpen}
        onToggleConfig={() => setChatControlsOpen((value) => !value)}
        isStreaming={isTyping}
        onStop={stopCurrentResponse}
        safetyMode={safetyMode}
        onEmergencyStop={stopCurrentResponse}
        onShutdown={shutdownHana}
      />

      {chatControlsOpen && (
        <ChatConfigModal
          showConfig={chatControlsOpen}
          onClose={() => setChatControlsOpen(false)}
          provider={provider}
          model={model}
          llmProviders={llmProviders}
          modelPickerOptions={modelPickerOptions}
          selectChatProvider={selectChatProvider}
          setModel={setModel}
          providerHasWebSearch={providerHasWebSearch}
          nativeSearchMode={nativeSearchMode}
          setNativeSearchMode={setNativeSearchMode}
          safetyMode={safetyMode}
          setSafetyMode={setSafetyMode}
          autoTtsEnabled={autoTtsEnabled}
          setAutoTtsEnabled={setAutoTtsEnabled}
          showTypingSpeed={showTypingSpeed}
          setShowTypingSpeed={setShowTypingSpeed}
          typingSpeed={typingSpeed}
          setTypingSpeed={setTypingSpeed}
          activeSessionId={activeSessionId}
          chatSessions={chatSessions}
          switchChatSession={switchChatSession}
          startNewChat={startNewChat}
          clearCurrentChat={clearCurrentChat}
          deleteChatSession={deleteChatSession}
          openrouterRoutingByModel={openrouterRoutingByModel}
          setOpenrouterRoutingByModel={setOpenrouterRoutingByModel}
          thinkingConfig={chatTtsConfig}
          onUpdateThinking={updateThinkingConfig}
          onImportarDoBanco={importarDoBanco}
        />
      )}

      <ChatMessageList
        visibleMessages={visibleMessages}
        hiddenMessages={hiddenMessages}
        onShowFullHistory={() => setShowFullHistory(true)}
        renderMessageContent={renderMessageContent}
        expandedMessages={expandedMessages}
        onToggleExpand={toggleExpandMessage}
        onDeleteMessage={deleteMessage}
        onDeleteMedia={deleteMediaItem}
        onGenerateSpeech={handleGenerateSpeech}
        onOpenImage={setImagePreviewUrl}
        identity={identity}
        isTyping={isTyping}
        liveThinking={liveThinking}
        liveActivity={liveActivity}
        onPickStarterPrompt={handlePickStarterPrompt}
        showScrollToBottom={showScrollToBottom}
        onScrollToBottom={scrollToBottomButton}
        scrollRef={scrollRef}
        contentRef={contentRef}
        onScroll={handleChatScroll}
        onWheel={handleChatWheel}
        onPointerDown={() => { manualScrollRef.current = true; }}
        onPointerUp={() => { manualScrollRef.current = false; }}
        onPointerCancel={() => { manualScrollRef.current = false; }}
      />

      <ChatInputBar
        input={input}
        onInputChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onSend={handleSend}
        isTyping={isTyping}
        isRecording={isRecording}
        isTranscribing={isTranscribing}
        onToggleRecording={toggleChatRecording}
        onFileUpload={handleFileUpload}
        attachments={attachments}
        onRemoveAttachment={removeAttachment}
        identity={identity}
        inputRef={inputRef}
      />

      {imagePreviewUrl && (
        <div
          className="absolute inset-0 z-[80] bg-black/85 backdrop-blur-md flex items-center justify-center p-6"
          onClick={() => setImagePreviewUrl(null)}
        >
          <button
            onClick={() => setImagePreviewUrl(null)}
            className="absolute top-5 right-5 w-11 h-11 rounded-full bg-white/10 hover:bg-white/20 border border-white/10 text-white flex items-center justify-center transition-colors"
            title="Fechar imagem"
          >
            <X size={22} />
          </button>
          <img
            src={imagePreviewUrl}
            alt="Preview"
            className="max-w-full max-h-full object-contain rounded-2xl border border-white/10 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      )}

    </div>
  );
}
