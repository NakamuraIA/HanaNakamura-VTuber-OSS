import { useState, useRef, useEffect, useDeferredValue, useMemo } from "react";
import { ApiController } from "../../controllers/api";
import { AgentStage, ChatAttachment, ChatConfig, ChatMessage, LlmConfig, PermissionRequest, ChatSession, SafetyMode, VoiceConfig } from "../../models/types";
import { LLM_PROVIDERS, MODEL_CATALOG, ModelSpec } from "../../models/providerCatalog";
import { LONG_MESSAGE_LIMIT } from "../../models/constants";
import { 
  Send, 
  Paperclip, 
  Mic, 
  StopCircle, 
  Copy, 
  Volume2, 
  User, 
  Bot, 
  Terminal,
  MessageSquareText,
  BrainCircuit,
  Globe2,
  Image as ImageIcon,
  Trash2,
  X,
  File,
  FileAudio,
  FileVideo,
  ChevronDown,
  ShieldCheck,
  Siren,
  Power,
  Loader2,
  VolumeX,
  Wrench
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { MediaRenderer } from "../components/chat/MediaRenderer";
import { PermissionModal } from "../components/chat/PermissionModal";
import { CatalogPicker, CatalogPickerOption } from "../components/shared/CatalogPicker";
import { Button } from "../components/shared/Button";
import { DEFAULT_OPENROUTER_ROUTING, OpenRouterEndpointPicker } from "../components/shared/OpenRouterEndpointPicker";

const CHAT_SESSIONS_KEY = "hana_chat_sessions_v1";
const CHAT_ACTIVE_SESSION_KEY = "hana_chat_active_session_v1";
const CHAT_AUTO_TTS_KEY = "hana_chat_auto_tts_v1";
const CHAT_TYPING_SPEED_KEY = "hana_chat_typing_speed_v1";
type TypingSpeed = "slow" | "normal" | "fast" | "instant";
const TYPING_SPEED_MS: Record<TypingSpeed, number> = { slow: 24, normal: 16, fast: 12, instant: 0 };
const TYPING_SPEED_CHARS: Record<TypingSpeed, number> = { slow: 2, normal: 5, fast: 14, instant: Number.POSITIVE_INFINITY };
const TYPING_SPEED_LABEL: Record<TypingSpeed, string> = { slow: "Lenta", normal: "Normal", fast: "Rapida", instant: "Instantanea" };
const TYPING_SPEED_ORDER: TypingSpeed[] = ["slow", "normal", "fast", "instant"];
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

function attachmentLabel(attachment: string | ChatAttachment, index: number) {
  if (isAttachmentObject(attachment)) return attachment.name || `anexo-${index + 1}`;
  return `imagem-${index + 1}`;
}

function attachmentType(attachment: string | ChatAttachment) {
  if (isAttachmentObject(attachment)) return attachment.type || "application/octet-stream";
  return "image/png";
}

function attachmentData(attachment: string | ChatAttachment) {
  return isAttachmentObject(attachment) ? attachment.data : attachment;
}

function isImageAttachment(attachment: string | ChatAttachment) {
  return attachmentType(attachment).startsWith("image/");
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

function trimMessagesForStorage(messages: ChatMessage[]) {
  return messages.slice(-MAX_PERSISTED_MESSAGES).map(slimMessageForStorage);
}

function loadStoredSessions(): ChatSession[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_SESSIONS_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((session) => session && typeof session.id === "string" && Array.isArray(session.messages))
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

function fileIconFor(type: string) {
  if (type.startsWith("audio/")) return <FileAudio size={16} />;
  if (type.startsWith("video/")) return <FileVideo size={16} />;
  if (type.startsWith("image/")) return <ImageIcon size={16} />;
  return <File size={16} />;
}

// A plain LLM chat turn produces only a trivial "llm.provider" step. Those should never
// draw the operational Agent Mode card; we only surface it for real tools / agent-core steps.
function planHasRealSteps(plan?: ChatMessage["agentPlan"]) {
  const steps = plan?.steps || [];
  return steps.some((step) => {
    const tool = String(step.tool || "").toLowerCase();
    return Boolean(tool) && !tool.startsWith("llm.");
  });
}

// Collapsible "Atividade de ferramentas" card (amber, like the Terminal Agente tool events).
// Shows every tool Hana used this turn: which tool, ok/fail, query and a short return — so
// Operador can see if she tried a tool, if it failed, and what it returned.
function ToolRunsRenderer({ toolRuns }: { toolRuns: NonNullable<NonNullable<ChatMessage["meta"]>["toolRuns"]> }) {
  const [expanded, setExpanded] = useState(false);
  const failed = toolRuns.filter((run) => !run.ok).length;

  return (
    <div className="mb-3 rounded-xl border border-amber-400/20 bg-amber-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-amber-200">
          <Wrench size={14} />
          Ferramentas
          <span className="font-mono text-[var(--text-muted)] normal-case tracking-normal">
            {toolRuns.length} {toolRuns.length === 1 ? "chamada" : "chamadas"}
            {failed ? ` · ${failed} falhou` : ""}
          </span>
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {!expanded && (
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2">
          {toolRuns.map((run, index) => (
            <span
              key={`${run.tool}-${index}`}
              className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-mono ${
                run.ok
                  ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                  : "border-red-400/20 bg-red-500/10 text-red-200"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${run.ok ? "bg-emerald-400" : "bg-red-400"}`} />
              {run.tool}
            </span>
          ))}
        </div>
      )}

      {expanded && (
        <div className="grid gap-2 px-3 pb-3">
          {toolRuns.map((run, index) => (
            <div key={`${run.tool}-${index}`} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${run.ok ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]" : "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.7)]"}`} />
                <span className="flex-1 truncate font-mono text-[11px] text-[var(--text-secondary)]">{run.tool}</span>
                <span className={`text-[9px] font-black uppercase tracking-widest ${run.ok ? "text-emerald-300" : "text-red-300"}`}>
                  {run.ok ? "ok" : "falhou"}
                </span>
              </div>
              {run.query && (
                <div className="mt-1 truncate text-[10px] font-mono text-[var(--text-muted)]">busca&gt; {run.query}</div>
              )}
              {run.summary && (
                <div className="mt-1 border-l border-amber-300/20 pl-2 text-[10px] leading-relaxed text-[var(--text-muted)] line-clamp-3">
                  {run.summary}
                </div>
              )}
              {run.sources && run.sources.length > 0 && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  {run.sources.slice(0, 5).map((source, sourceIndex) => (
                    <img
                      key={`${source.uri}-${sourceIndex}`}
                      src={`https://www.google.com/s2/favicons?domain=${hostFromUri(source.uri || "")}&sz=64`}
                      alt=""
                      className="h-3.5 w-3.5 rounded-sm bg-white/10"
                      loading="lazy"
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Collapsible "Memória usada" card: shows exactly which persistent memories were
// fed to the LLM this turn (proof against amnesia). Compact = count + token cost;
// expanded = the actual memory snippets, pinned ones flagged.
function MemoryContextRenderer({ memoryContext }: { memoryContext: NonNullable<NonNullable<ChatMessage["meta"]>["memoryContext"]> }) {
  const [expanded, setExpanded] = useState(false);
  const memories = memoryContext.memories || [];
  if (!memories.length) return null;

  return (
    <div className="mb-3 rounded-xl border border-violet-400/20 bg-violet-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-violet-200">
          <BrainCircuit size={14} />
          Memória usada
          <span className="font-mono text-[var(--text-muted)] normal-case tracking-normal">
            {memoryContext.count} {memoryContext.count === 1 ? "lembrança" : "lembranças"}
            {memoryContext.approxTokens ? ` · ~${memoryContext.approxTokens} tokens` : ""}
          </span>
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="grid gap-1.5 px-3 pb-3">
          {memories.map((mem, index) => (
            <div key={mem.id || index} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
              <div className="flex items-center gap-2">
                {mem.pinned && <span className="text-[9px] font-black uppercase tracking-widest text-amber-300">fixada</span>}
                {mem.category && (
                  <span className="rounded-full border border-violet-400/20 bg-violet-500/10 px-1.5 py-0.5 text-[9px] font-mono text-violet-200">
                    {mem.category}
                  </span>
                )}
              </div>
              <div className="mt-1 text-[11px] leading-relaxed text-[var(--text-secondary)] line-clamp-3">{mem.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function hostFromUri(uri: string) {
  try {
    return new URL(uri).hostname.replace(/^www\./, "");
  } catch {
    return uri.replace(/^https?:\/\//, "").split("/")[0];
  }
}

// Collapsible "Pesquisa e fontes" card, ChatGPT/Gemini-style: a compact summary row that
// expands to show the search queries and the list of source links with favicons.
function SearchSourcesRenderer({ grounding }: { grounding: NonNullable<NonNullable<ChatMessage["meta"]>["grounding"]> }) {
  const [expanded, setExpanded] = useState(false);
  const queries = grounding.queries || [];
  const sources = (grounding.sources || []).filter((source) => source.uri);

  return (
    <div className="mb-3 rounded-xl border border-emerald-400/20 bg-emerald-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-emerald-200">
          <Globe2 size={14} />
          Pesquisa na web
          <span className="font-mono text-[var(--text-muted)] normal-case tracking-normal">
            {sources.length ? `${sources.length} fontes` : "concluida"}
          </span>
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {!expanded && sources.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 pb-2">
          {sources.slice(0, 6).map((source, index) => (
            <img
              key={`${source.uri}-${index}`}
              src={`https://www.google.com/s2/favicons?domain=${hostFromUri(source.uri || "")}&sz=64`}
              alt=""
              className="h-4 w-4 rounded-sm bg-white/10"
              loading="lazy"
            />
          ))}
        </div>
      )}

      {expanded && (
        <div className="px-3 pb-3">
          {queries.map((query) => (
            <div key={query} className="mb-1 text-[10px] font-mono text-[var(--text-muted)]">
              busca&gt; {query}
            </div>
          ))}
          <div className="mt-2 grid gap-2">
            {sources.map((source, index) => (
              <a
                key={`${source.uri}-${index}`}
                href={source.uri}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 truncate rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-[11px] text-cyan-200 hover:border-cyan-300/30 hover:text-white"
              >
                <img
                  src={`https://www.google.com/s2/favicons?domain=${hostFromUri(source.uri || "")}&sz=64`}
                  alt=""
                  className="h-4 w-4 shrink-0 rounded-sm bg-white/10"
                  loading="lazy"
                />
                <span className="truncate">{source.title || source.uri}</span>
                <span className="ml-auto shrink-0 text-[9px] font-mono text-[var(--text-muted)]">{hostFromUri(source.uri || "")}</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentPlanRendererProps {
  plan: NonNullable<ChatMessage["agentPlan"]>;
  active?: boolean;
}

function AgentPlanRenderer({ plan, active = false }: AgentPlanRendererProps) {
  const [expanded, setExpanded] = useState(active);
  const steps = plan.steps || [];
  const lastStep = steps[steps.length - 1];

  useEffect(() => {
    if (active) setExpanded(true);
  }, [active]);

  return (
    <div className="mb-4 rounded-xl border border-cyan-400/20 bg-cyan-500/5 p-3 shadow-[0_0_18px_rgba(34,211,238,0.06)]">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="w-full flex items-center justify-between gap-3 text-left"
      >
        <div className="flex items-center gap-2">
          <BrainCircuit size={15} className="text-[var(--cyan-neon)]" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--cyan-neon)]">Agent Mode</span>
          {lastStep && (
            <span className="max-w-[260px] truncate text-[10px] font-mono text-[var(--text-muted)]">
              {lastStep.tool} · {lastStep.status}
            </span>
          )}
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {!expanded && plan.project && (
        <div className="mt-2 truncate text-[10px] font-mono text-[var(--text-muted)]">Projeto: {plan.project}</div>
      )}

      {expanded && (
        <>
          {plan.project && (
            <div className="mt-3 text-[10px] font-mono text-[var(--text-muted)] truncate max-w-[320px]">
              Projeto: {plan.project}
            </div>
          )}

          <div className="grid gap-2">
            {steps.map((step, index) => {
              const ok = step.status === "success" || step.status === "ok" || step.status === "done";
              const running = ["planning", "executing", "verifying", "queued", "running"].includes(step.status);
              return (
                <div key={`${step.tool}-${index}`} className="rounded-xl bg-black/20 border border-white/5 px-3 py-2">
                  <div className="flex items-center gap-3">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${
                      ok
                        ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"
                        : running
                          ? "animate-pulse bg-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.8)]"
                          : "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.8)]"
                    }`} />
                    <span className="text-[11px] font-mono text-[var(--text-secondary)] flex-1 truncate">{step.tool}</span>
                    <span className={`text-[9px] font-black uppercase tracking-widest ${ok ? "text-emerald-300" : running ? "text-cyan-200" : "text-red-300"}`}>
                      {step.status}
                    </span>
                    <span className="text-[9px] font-bold uppercase text-[var(--text-muted)]">{step.risk}</span>
                  </div>
                  {step.summary && (
                    <div className="mt-2 border-l border-cyan-300/20 pl-3 text-[10px] leading-relaxed text-[var(--text-muted)]">
                      {step.summary}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
const SAFETY_MODES: { id: SafetyMode; label: string }[] = [
  { id: "safe", label: "Safe" },
  { id: "assisted", label: "Assisted" },
  { id: "trusted", label: "Trusted" },
  { id: "dev-unsafe", label: "Dev Unsafe" },
];

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

function modelPriceScore(model: ModelSpec) {
  /** Convert catalog pricing into a sortable score for the shared picker. */
  if (model.free) return 0;
  const values = [Number(model.pricing?.prompt), Number(model.pricing?.completion)]
    .filter((value) => Number.isFinite(value) && value >= 0);
  return values.length ? values.reduce((total, value) => total + value, 0) : null;
}

function chatModelOption(model: ModelSpec): CatalogPickerOption {
  /** Expose Chat models through the same searchable and favorite-aware catalog as Cerebro. */
  const badges: CatalogPickerOption["badges"] = [];
  if (model.supportsVision) badges.push({ label: "vision", tone: "green" });
  if (model.supportsDocuments) badges.push({ label: "docs", tone: "blue" });
  if (model.supportsTools) badges.push({ label: "tools", tone: "cyan" });
  if (model.supportsNativeSearch) badges.push({ label: "web", tone: "amber" });
  if (model.custom) badges.push({ label: "custom", tone: "purple" });
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
        ? `in ${model.pricing?.prompt || "?"} / out ${model.pricing?.completion || "?"}`
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
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [provider, setProvider] = useState("gemini_api");
  const [model, setModel] = useState("gemini-3.1-pro-preview");
  const [nativeSearchMode, setNativeSearchMode] = useState<"auto" | "force" | "off">("auto");
  const [openrouterRoutingByModel, setOpenrouterRoutingByModel] = useState<ChatConfig["openrouterRoutingByModel"]>({});
  const [catalogModels, setCatalogModels] = useState<ModelSpec[]>(MODEL_CATALOG);
  const [llmProviders, setLlmProviders] = useState<string[]>(LLM_PROVIDERS);
  const [chatConfigLoaded, setChatConfigLoaded] = useState(false);
  const [safetyMode, setSafetyMode] = useState<SafetyMode>((localStorage.getItem("hana_agent_safety_mode") as SafetyMode) || "safe");
  const [pendingPermission, setPendingPermission] = useState<PermissionRequest | null>(null);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [chatControlsOpen, setChatControlsOpen] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState<Record<string, boolean>>({});
  const [showFullHistory, setShowFullHistory] = useState(false);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [chatTtsConfig, setChatTtsConfig] = useState<LlmConfig | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [autoTtsEnabled, setAutoTtsEnabled] = useState(() => localStorage.getItem(CHAT_AUTO_TTS_KEY) === "true");
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [liveActivity, setLiveActivity] = useState({ label: "", detail: "" });
  const streamerMode = true;
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
    () => catalogModels.filter((item) => item.provider === provider && (item.outputModalities || []).includes("text")),
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
        badges: [{ label: "custom", tone: "purple" }],
      });
    }
    return options;
  }, [availableModels, model, provider]);

  const selectChatProvider = (providerValue: string) => {
    const selectedProvider = normalizeProvider(providerValue);
    const providerModels = catalogModels.filter((item) => item.provider === selectedProvider && (item.outputModalities || []).includes("text"));
    setProvider(selectedProvider);
    setModel(providerModels[0]?.id || "");
    setNativeSearchMode(selectedProvider === "gemini_api" ? "auto" : "off");
  };

  // Gemini tem grounding nativo; OpenRouter tem o plugin "web" (cobrado por busca,
  // então o padrão lá é off e a Operador liga quando quiser).
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
        const providers = catalog?.llmProviders || LLM_PROVIDERS;
        const models = catalog?.models || MODEL_CATALOG;
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
          role: m.role === "Operador" ? "user" as const : "hana" as const,
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

  useEffect(() => {
    if (safetyMode === "dev-unsafe") {
      setPendingPermission(null);
      return;
    }
    const loadPending = () => {
      ApiController.getPendingPermissions().then((data) => {
        const next = Array.isArray(data?.permissions) ? data.permissions[0] || null : null;
        setPendingPermission(next);
      });
    };
    loadPending();
    const timer = window.setInterval(loadPending, 1000);
    return () => window.clearInterval(timer);
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

  const deleteMessage = (messageId: string) => {
    setMessages((prev) => {
      const next = prev.filter((message) => message.id !== messageId);
      return next.length ? next : [createWelcomeMessage()];
    });
  };

  const deleteMediaItem = (messageId: string, mediaIndex: number) => {
    setMessages((prev) => prev.map((message) => {
      if (message.id !== messageId || !message.media) return message;
      return {
        ...message,
        media: message.media.filter((_, index) => index !== mediaIndex),
      };
    }));
  };

  const renderMessageContent = (message: ChatMessage) => {
    const expanded = Boolean(expandedMessages[message.id]);
    const shouldTrim = message.content.length > LONG_MESSAGE_LIMIT && !expanded;
    return shouldTrim ? `${message.content.slice(0, LONG_MESSAGE_LIMIT)}\n\n...` : message.content;
  };

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
        return [...prev, { id: "streaming-res", role: "hana", content: "", timestamp: nowTime() }];
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
        return [...prev, { id: "streaming-res", role: "hana", content: "", timestamp: nowTime() }];
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
    forceScrollToBottom();

    // Modo Streamer (SSE) com digitação letra-por-letra
    typingBufferRef.current = "";
    typingDisplayedRef.current = 0;
    typingCompleteRef.current = null;
    stopTypingAnimation();

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
            setMessages(prev => {
              const last = prev[prev.length - 1];
              if (last && last.id === "streaming-res") {
                return [...prev.slice(0, -1), { ...last, id: finalId }];
              }
              return prev;
            });
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
            content: "Erro na conexÃ£o com o servidor da Hana.",
            timestamp: nowTime()
          }]);
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
      className="w-full h-full overflow-hidden relative flex flex-col"
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
      
      {/* HEADER / TOOLBAR */}
      <div className="bg-[rgba(10,10,15,0.85)] border-b border-[var(--border-strong)] p-3 z-10 shadow-lg backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[var(--purple-dark)] flex items-center justify-center border border-[var(--purple-neon)] shadow-[0_0_15px_var(--purple-dark)]">
              <MessageSquareText size={18} className="text-[var(--purple-neon)]" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-[var(--purple-neon)] to-[var(--cyan-neon)]">
                Hana Nexus Chat
              </h2>
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest font-bold truncate">
                {provider} · {model}
              </p>
            </div>
          </div>
          
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setChatControlsOpen((value) => !value)}
              className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-[var(--text-secondary)] hover:text-white"
              title="Mostrar ou esconder configuracoes do chat"
            >
              Config
              <ChevronDown size={14} className={`transition-transform ${chatControlsOpen ? "rotate-180" : ""}`} />
            </button>
            {isTyping && (
              <button
                onClick={stopCurrentResponse}
                className="bg-red-500/20 hover:bg-red-500/40 text-red-400 border border-red-500/30 transition-all p-2 rounded-xl animate-pulse"
                title="Parar Resposta"
              >
                <StopCircle size={18} />
              </button>
            )}
            {safetyMode === "dev-unsafe" && (
              <button
                onClick={() => {
                  ApiController.cancelAllPermissions();
                  stopCurrentResponse();
                }}
                className="bg-red-600/30 hover:bg-red-600/50 text-red-100 border border-red-400/40 transition-all p-2 rounded-xl"
                title="Emergency stop"
              >
                <Siren size={18} />
              </button>
            )}
            <button
              type="button"
              onClick={shutdownHana}
              className="bg-red-950/70 hover:bg-red-800/80 text-red-200 border border-red-400/30 transition-all p-2 rounded-xl"
              title="Desligar Hana"
            >
              <Power size={18} />
            </button>
          </div>
        </div>

        {chatControlsOpen && (
          <div className="mt-2 max-h-[34vh] space-y-2 overflow-y-auto rounded-xl border border-white/10 bg-black/40 p-2.5 backdrop-blur-sm">
            {/* SECAO: MOTOR (provider + modelo) */}
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1.5 rounded-lg border border-[var(--purple-neon)]/20 bg-[var(--purple-neon)]/5 px-2.5 py-1.5 transition-colors hover:border-[var(--purple-neon)]/40">
                  <Terminal size={13} className="text-[var(--purple-neon)]" />
                  <select
                    className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                    value={provider}
                    onChange={(e) => selectChatProvider(e.target.value)}
                  >
                    {llmProviders.map((p) => <option key={p} value={p} className="bg-[#0f0f13]">{p}</option>)}
                  </select>
                </div>
                <div className="flex min-w-[260px] flex-1 items-center gap-2">
                  <BrainCircuit size={14} className="shrink-0 text-[var(--cyan-neon)]" />
                  <div className="min-w-0 flex-1">
                    <CatalogPicker
                      value={model}
                      options={modelPickerOptions}
                      onChange={setModel}
                      favoriteNamespace={`chat-llm:${provider}`}
                      placeholder="Selecione um modelo"
                      searchPlaceholder="Buscar modelo por nome ou ID..."
                      emptyMessage="Nenhum modelo deste provider corresponde aos filtros."
                      accent="cyan"
                      compact
                    />
                  </div>
                </div>
              </div>
              {provider === "openrouter" && (
                <OpenRouterEndpointPicker
                  model={model}
                  value={openrouterRoutingByModel[model] || DEFAULT_OPENROUTER_ROUTING}
                  onChange={(routing) => setOpenrouterRoutingByModel((current) => ({ ...current, [model]: routing }))}
                  compact
                />
              )}
            </div>

            {/* SECAO: COMPORTAMENTO */}
            <div className="flex flex-col gap-2 border-t border-white/5 pt-2">
              <div className="flex flex-wrap items-center gap-2">
                {providerHasWebSearch ? (
                  <div className="flex items-center gap-1.5 rounded-lg border border-emerald-400/15 bg-emerald-500/5 px-2.5 py-1.5 transition-colors hover:border-emerald-400/30">
                    <Globe2 size={13} className="text-emerald-300" />
                    <select
                      className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                      value={nativeSearchMode}
                      onChange={(e) => setNativeSearchMode(e.target.value as "auto" | "force" | "off")}
                      title={provider === "gemini_api" ? "Grounding nativo com Google Search" : "Pesquisa web do OpenRouter (plugin web, cobrado por busca)"}
                    >
                      <option value="auto" className="bg-[#0f0f13]">Web auto</option>
                      <option value="force" className="bg-[#0f0f13]">Web on</option>
                      <option value="off" className="bg-[#0f0f13]">Web off</option>
                    </select>
                  </div>
                ) : (
                  <span
                    className="flex items-center gap-1.5 rounded-lg border border-emerald-400/20 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-bold text-emerald-200"
                    title="Este provider pesquisa na web pela ferramenta Tavily (MCP) quando o modelo suporta tools. Ative o Tavily na aba MCP."
                  >
                    <Globe2 size={13} />
                    Web via Tavily
                  </span>
                )}

                <div className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 transition-colors ${
                  safetyMode === "dev-unsafe"
                    ? "bg-red-500/15 border-red-400/30"
                    : "bg-amber-500/5 border-amber-400/15 hover:border-amber-400/30"
                }`}>
                  <ShieldCheck size={13} className={safetyMode === "dev-unsafe" ? "text-red-300" : "text-amber-200"} />
                  <select
                    className="cursor-pointer bg-transparent font-mono text-[11px] font-bold uppercase text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                    value={safetyMode}
                    onChange={(e) => setSafetyMode(asSafetyMode(e.target.value))}
                    title="Modo de seguranca para tools do Agent Mode"
                  >
                    {SAFETY_MODES.map((mode) => (
                      <option key={mode.id} value={mode.id} className="bg-[#0f0f13]">{mode.label}</option>
                    ))}
                  </select>
                </div>

                <button
                  type="button"
                  onClick={() => setAutoTtsEnabled((value) => !value)}
                  className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-black uppercase tracking-wider transition-colors ${
                    autoTtsEnabled
                      ? "border-pink-300/30 bg-pink-500/15 text-pink-200"
                      : "border-white/10 bg-white/5 text-[var(--text-muted)] hover:text-white"
                  }`}
                  title="Gerar audio TTS automaticamente para novas respostas da Hana"
                >
                  {autoTtsEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
                  TTS {autoTtsEnabled ? "on" : "off"}
                </button>

                {streamerMode && (
                  <button
                    type="button"
                    onClick={() => setTypingSpeed((prev) => TYPING_SPEED_ORDER[(TYPING_SPEED_ORDER.indexOf(prev) + 1) % TYPING_SPEED_ORDER.length])}
                    className="flex items-center gap-1.5 rounded-lg border border-cyan-300/30 bg-cyan-500/15 px-2.5 py-1.5 text-[11px] font-black uppercase tracking-wider text-cyan-200 transition-colors hover:bg-cyan-500/25"
                    title="Velocidade da digitacao da Hana (clique para alternar)"
                  >
                    <Terminal size={14} />
                    {TYPING_SPEED_LABEL[typingSpeed]}
                  </button>
                )}
              </div>
            </div>

            {/* SECAO: CONVERSAS */}
            <div className="flex flex-col gap-2 border-t border-white/5 pt-2">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={activeSessionId}
                  onChange={(event) => switchChatSession(event.target.value)}
                  className="min-w-[180px] max-w-[300px] flex-1 cursor-pointer rounded-lg border border-white/10 bg-black/40 px-2.5 py-1.5 text-[11px] font-bold text-[var(--text-primary)] outline-none [&>option]:bg-[#0f0f13]"
                  title="Historico local de conversas"
                >
                  {chatSessions.map((session) => (
                    <option key={session.id} value={session.id} className="bg-[#0f0f13]">
                      {session.title}
                    </option>
                  ))}
                </select>
                <Button onClick={startNewChat} variant="secondary" size="sm">Nova</Button>
                <Button onClick={clearCurrentChat} variant="success" size="sm">Limpar</Button>
                <Button onClick={() => deleteChatSession(activeSessionId)} variant="danger" size="sm">Apagar</Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* CHAT AREA */}
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={handleChatScroll}
          onWheel={handleChatWheel}
          onPointerDown={() => { manualScrollRef.current = true; }}
          onPointerUp={() => { manualScrollRef.current = false; }}
          onPointerCancel={() => { manualScrollRef.current = false; }}
          className="relative h-full overflow-y-auto p-6 custom-scrollbar"
        >
        <div ref={contentRef} className="space-y-8">
        {/* Marca d'Ã¡gua */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 opacity-[0.03] pointer-events-none select-none">
          <img src="/hana_foto_01.png" alt="" className="w-[500px] grayscale" />
        </div>

        {hiddenMessages > 0 && (
          <div className="flex justify-center">
            <button
              onClick={() => setShowFullHistory(true)}
              className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-white hover:border-[var(--cyan-neon)]/40 transition-colors"
            >
              <ChevronDown size={12} /> Mostrar {hiddenMessages} mensagens antigas
            </button>
          </div>
        )}

        {visibleMessages.map((msg) => (
          <div key={msg.id} className={`flex w-full animate-fade-in ${msg.role === 'user' ? 'justify-end' : (msg.role === 'system' ? 'justify-center' : 'justify-start')}`}>
            
            {msg.role === 'system' && (
              <div className="bg-[rgba(255,255,255,0.03)] border border-[var(--border-strong)] text-[var(--text-muted)] text-[10px] px-6 py-2 rounded-full font-mono tracking-tighter uppercase backdrop-blur-sm shadow-sm">
                {msg.content}
              </div>
            )}

            {msg.role === 'user' && (
              <div className="flex flex-col items-end gap-2 max-w-[80%]">
                <div className="flex items-center gap-2 mb-1 px-1">
                  <span className="text-[10px] font-mono text-[var(--text-muted)]">{msg.timestamp}</span>
                  <span className="text-xs font-black text-blue-400 uppercase tracking-widest">Voce</span>
                  <div className="w-6 h-6 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center">
                    <User size={12} className="text-blue-400" />
                  </div>
                  <button onClick={() => deleteMessage(msg.id)} className="p-1 rounded-lg text-[var(--text-muted)] hover:text-red-300 hover:bg-red-500/10 transition-colors" title="Apagar mensagem">
                    <Trash2 size={12} />
                  </button>
                </div>
                
                <div className="bg-[rgba(59,130,246,0.1)] border border-blue-500/30 rounded-3xl rounded-tr-none p-5 shadow-[0_10px_30px_rgba(0,0,0,0.3)] backdrop-blur-xl group relative">
                  {/* Miniaturas de anexos enviados */}
                  {msg.attachments && msg.attachments.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-4">
                      {msg.attachments.map((att, i) => (
                        <div key={i} className="w-28 min-h-24 rounded-xl overflow-hidden border border-white/10 shadow-lg group/img bg-black/25">
                          {isImageAttachment(att) && attachmentData(att) ? (
                            <img src={attachmentData(att)} loading="lazy" className="w-full h-20 object-cover transition-transform group-hover/img:scale-110" alt={attachmentLabel(att, i)} />
                          ) : (
                            <div className="w-full h-20 flex items-center justify-center text-[var(--cyan-neon)]">
                              {fileIconFor(attachmentType(att))}
                            </div>
                          )}
                          <div className="px-2 py-1 text-[9px] text-[var(--text-muted)] truncate">{attachmentLabel(att, i)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="text-[15px] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap font-medium">{renderMessageContent(msg)}</p>
                  {msg.content.length > LONG_MESSAGE_LIMIT && (
                    <button
                      onClick={() => setExpandedMessages((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))}
                      className="mt-3 text-[10px] font-black uppercase tracking-widest text-blue-300 hover:text-white"
                    >
                      {expandedMessages[msg.id] ? "Ver menos" : "Ver mais"}
                    </button>
                  )}
                </div>
              </div>
            )}

            {msg.role === 'hana' && (
              <div className="flex flex-col items-start gap-2 w-full max-w-[90%]">
                <div className="flex items-center gap-2 mb-1 px-1">
                  <div className="w-8 h-8 rounded-full bg-[var(--purple-dark)] border border-[var(--purple-neon)] flex items-center justify-center shadow-[0_0_10px_var(--purple-dark)] overflow-hidden">
                    <img src="/hana_perfil.png" className="w-full h-full object-cover" alt="H" />
                  </div>
                  <span className="text-xs font-black text-[var(--purple-neon)] uppercase tracking-[0.2em] drop-shadow-[0_0_5px_var(--purple-dark)]">Hana Operador</span>
                  <span className="text-[10px] font-mono text-[var(--text-muted)]">{msg.timestamp}</span>
                  <button onClick={() => deleteMessage(msg.id)} className="p-1 rounded-lg text-[var(--text-muted)] hover:text-red-300 hover:bg-red-500/10 transition-colors" title="Apagar mensagem">
                    <Trash2 size={12} />
                  </button>
                </div>
                
                <div className="w-full relative group/hana pl-1">
                  {msg.meta && (
                    <div className="mb-4 text-[9px] font-bold font-mono text-[var(--text-muted)] flex items-center gap-3">
                      <span className="bg-black/40 px-3 py-1 rounded-full border border-white/5 uppercase tracking-widest">{msg.meta.provider} • {msg.meta.model}</span>
                      {typeof msg.meta.nativeSearch === "boolean" && (
                        <span className={`px-3 py-1 rounded-full border uppercase tracking-widest ${msg.meta.nativeSearch ? "bg-emerald-500/10 text-emerald-300 border-emerald-400/20" : "bg-white/5 text-[var(--text-muted)] border-white/10"}`}>
                          WEB {msg.meta.nativeSearch ? "ON" : "OFF"} {msg.meta.nativeSearchMode ? `• ${msg.meta.nativeSearchMode}` : ""}
                        </span>
                      )}
                      {msg.meta.safetyMode && (
                        <span className={`px-3 py-1 rounded-full border uppercase tracking-widest ${msg.meta.safetyMode === "dev-unsafe" ? "bg-red-500/10 text-red-300 border-red-400/20" : "bg-amber-400/10 text-amber-200 border-amber-300/20"}`}>
                          SAFE {msg.meta.safetyMode}
                        </span>
                      )}
                      {msg.meta.tokens && <span className="bg-[var(--purple-dark)] text-[var(--purple-neon)] px-3 py-1 rounded-full border border-[var(--purple-neon)]/20">{msg.meta.tokens} TOKENS</span>}
                    </div>
                  )}
                  
                  {planHasRealSteps(msg.agentPlan) && msg.agentPlan && <AgentPlanRenderer plan={msg.agentPlan} active={msg.id === "streaming-res" && isTyping} />}

                  {msg.meta?.memoryContext?.memories?.length ? (
                    <MemoryContextRenderer memoryContext={msg.meta.memoryContext} />
                  ) : null}

                  {msg.meta?.toolRuns?.length ? (
                    <ToolRunsRenderer toolRuns={msg.meta.toolRuns} />
                  ) : null}

                  {(msg.meta?.grounding?.queries?.length || msg.meta?.grounding?.sources?.length) ? (
                    <SearchSourcesRenderer grounding={msg.meta.grounding} />
                  ) : null}

                  <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-black/50 prose-pre:border prose-pre:border-white/10 prose-code:text-[var(--cyan-neon)] prose-a:text-[var(--cyan-neon)] prose-a:no-underline hover:prose-a:underline">
                    <ReactMarkdown 
                      remarkPlugins={[remarkGfm, remarkBreaks]}
                      components={{
                        a: ({node, ...props}) => <a {...props} target="_blank" rel="noreferrer" className="flex items-center gap-1 inline-flex" />
                      }}
                    >
                      {renderMessageContent(msg)}
                    </ReactMarkdown>
                  </div>

                  {msg.content.length > LONG_MESSAGE_LIMIT && (
                    <button
                      onClick={() => setExpandedMessages((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))}
                      className="mt-3 text-[10px] font-black uppercase tracking-widest text-[var(--cyan-neon)] hover:text-white"
                    >
                      {expandedMessages[msg.id] ? "Ver menos" : "Ver mais"}
                    </button>
                  )}

                  {/* RenderizaÃ§Ã£o de MÃ­dias */}
                  {msg.media && msg.media.map((m, i) => (
                    <MediaRenderer
                      key={`${m.job_id || m.url || "media"}-${i}`}
                      media={m}
                      onOpenImage={setImagePreviewUrl}
                      onDelete={() => deleteMediaItem(msg.id, i)}
                      onReSynthesize={() => void generateMessageSpeech(msg.id, msg.content)}
                    />
                  ))}

                  {/* Action Buttons Footer */}
                  <div className="mt-3 opacity-0 group-hover/hana:opacity-100 transition-all duration-300 flex items-center gap-3">
                    <button
                      onClick={() => void generateMessageSpeech(msg.id, msg.content)}
                      className="text-[10px] font-bold uppercase tracking-widest bg-white/5 hover:bg-[var(--purple-dark)] text-[var(--text-secondary)] hover:text-white px-4 py-2 rounded-full border border-white/5 transition-all flex items-center gap-2"
                    >
                      <Volume2 size={12} /> Gerar voz
                    </button>
                    <button
                      onClick={() => navigator.clipboard?.writeText(msg.content)}
                      className="text-[10px] font-bold uppercase tracking-widest bg-white/5 hover:bg-[var(--purple-dark)] text-[var(--text-secondary)] hover:text-white px-4 py-2 rounded-full border border-white/5 transition-all flex items-center gap-2"
                    >
                      <Copy size={12} /> Copiar
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}

        {isTyping && liveActivity.label && (
          <div className="sticky bottom-3 z-20 flex w-full justify-start animate-fade-in pointer-events-none">
            <div className="max-w-[620px] rounded-lg border border-fuchsia-400/25 bg-black/85 px-4 py-3 shadow-[0_0_24px_rgba(236,72,153,0.12)] backdrop-blur-xl">
              <div className="flex items-center gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-fuchsia-400/30 bg-fuchsia-500/10">
                  <Bot size={14} className="text-fuchsia-300 animate-pulse" />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="block text-[10px] font-black uppercase tracking-widest text-fuchsia-300">{liveActivity.label}</span>
                  <span className="block truncate text-[11px] text-[var(--text-muted)]">{liveActivity.detail}</span>
                </div>
                <div className="flex items-center gap-1">
                  {[0, 120, 240].map((delay) => (
                    <div key={delay} className="h-1.5 w-1.5 rounded-full bg-fuchsia-300 animate-bounce" style={{ animationDelay: `${delay}ms` }} />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        </div>
        </div>

        {showScrollToBottom && (
          <button
            type="button"
            onClick={scrollToBottomButton}
            className="absolute bottom-5 right-5 z-40 flex h-11 items-center gap-2 rounded-full border border-[var(--cyan-neon)]/40 bg-[#071217]/95 px-3 text-[var(--cyan-neon)] shadow-[0_0_22px_rgba(34,211,238,0.22)] backdrop-blur-md transition-all hover:scale-105 hover:bg-[#0b2028]"
            title="Ir para a mensagem mais recente"
            aria-label="Ir para a mensagem mais recente"
          >
            <ChevronDown size={18} />
            <span className="text-[10px] font-black uppercase tracking-widest">Mais recente</span>
          </button>
        )}
      </div>

      {/* INPUT AREA */}
      <div className="z-10 relative px-7 pt-3 pb-5">
        
        <div className="flex items-end gap-4 max-w-6xl mx-auto">
          <div className="flex gap-2 mb-1 shrink-0">
            <button
              type="button"
              onClick={toggleChatRecording}
              disabled={isTranscribing}
              className={`w-12 h-12 flex items-center justify-center rounded-2xl border transition-all shadow-lg group ${
                isRecording
                  ? "bg-red-500/20 border-red-400/40 text-red-200 animate-pulse"
                  : "bg-white/5 hover:bg-[var(--purple-dark)] border-white/5 hover:border-[var(--purple-neon)]/30 text-[var(--text-secondary)] hover:text-[var(--purple-neon)]"
              } disabled:opacity-50`}
              title={isRecording ? "Parar gravacao" : "Gravar voz para preencher o texto"}
            >
              {isTranscribing ? <Loader2 size={20} className="animate-spin" /> : (isRecording ? <StopCircle size={20} /> : <Mic size={20} className="group-hover:scale-110 transition-transform" />)}
            </button>
            
            <label className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white/5 hover:bg-blue-500/10 border border-white/5 hover:border-blue-500/30 text-[var(--text-secondary)] hover:text-blue-400 transition-all shadow-lg cursor-pointer group">
              <Paperclip size={20} className="group-hover:rotate-45 transition-transform" />
              <input type="file" className="hidden" multiple accept="image/*,audio/*,video/*,application/pdf,text/plain,text/markdown,application/json,.txt,.md,.pdf,.mp3,.wav,.ogg,.mp4,.webm,.gif" onChange={handleFileUpload} />
            </label>
          </div>

          <div className="flex-1 bg-[rgba(0,0,0,0.5)] border border-[var(--border-strong)] rounded-[1.5rem] p-1.5 relative group focus-within:border-[var(--purple-neon)] focus-within:shadow-[0_0_40px_rgba(168,85,247,0.2)] transition-all duration-500 shadow-2xl flex flex-col">
            
            {/* Preview de Anexos dentro da caixa de texto */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 p-3 pb-0 animate-fade-in">
                {attachments.map((att, i) => (
                  <div key={i} className="group/att relative w-12 h-12 rounded-lg border border-[var(--purple-neon)]/30 overflow-hidden shadow-lg">
                    {att.type.startsWith("image/") ? (
                      <img src={att.data} loading="lazy" className="w-full h-full object-cover" alt="preview" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-[var(--cyan-neon)] bg-black/30">
                        {fileIconFor(att.type)}
                      </div>
                    )}
                    <button 
                      onClick={() => removeAttachment(i)}
                      className="absolute top-0.5 right-0.5 bg-red-500 rounded-full w-4 h-4 flex items-center justify-center text-white text-[10px] font-bold opacity-0 group-hover/att:opacity-100 transition-opacity"
                    >
                      x
                    </button>
                  </div>
                ))}
              </div>
            )}

            <textarea 
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              className="w-full bg-transparent text-[var(--text-primary)] text-[15px] resize-none outline-none custom-scrollbar p-3 pl-5 max-h-60 min-h-[54px] font-medium placeholder:text-[var(--text-muted)] leading-relaxed"
              placeholder={attachments.length > 0 ? "Adicione uma descricao para os anexos..." : "Fale com a Hana Operador... (Ou arraste arquivos para aqui)"}
              rows={1}
            />
          </div>

          <button 
            onClick={handleSend}
            disabled={(!input.trim() && attachments.length === 0) || isTyping}
            className="w-[60px] h-[60px] bg-gradient-to-br from-[var(--purple-neon)] to-[#7e22ce] hover:brightness-110 disabled:from-gray-800 disabled:to-gray-900 text-white disabled:text-gray-600 rounded-[1.2rem] flex items-center justify-center transition-all shadow-[0_10px_25px_rgba(168,85,247,0.4)] hover:shadow-[0_15px_35px_rgba(168,85,247,0.6)] active:scale-90 shrink-0 mb-0.5 border border-white/10"
          >
            <Send size={24} />
          </button>
        </div>
        
      </div>

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

      {safetyMode !== "dev-unsafe" && (
        <PermissionModal
          request={pendingPermission}
          onApprove={(id) => {
            ApiController.approvePermission(id);
            setPendingPermission(null);
          }}
          onDeny={(id) => {
            ApiController.denyPermission(id);
            setPendingPermission(null);
          }}
        />
      )}

    </div>
  );
}
