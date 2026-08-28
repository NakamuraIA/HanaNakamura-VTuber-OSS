import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Ban,
  ChevronDown,
  Copy,
  Loader2,
  Mic,
  RefreshCw,
  Send,
  Settings,
  Square,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { ApiController } from "../../controllers/api";
import { ConnectionsConfig, TerminalAgentEvent, TerminalAgentEventKind, TerminalAgentStreamMessage, TtsVoiceAliases, VoiceConfig, VoiceInputDevice, VoiceProviderSpec, VoiceRuntimeStatus } from "../../models/types";
import { DEFAULT_VOICE_CONFIG } from "../../api/config";
import { CatalogPicker, CatalogPickerOption } from "../components/shared/CatalogPicker";

const MAX_VISIBLE_EVENTS = 250;
const AUDIO_DEVICE_KEY = "hana_terminal_agent_audio_device";
const MIN_ACTIVE_VOICE_MS = 220;
const MIN_RECORDING_MS = 450;

type ProviderOption = {
  id: string;
  label: string;
  status: string;
  models?: string[];
  defaultModel?: string;
  voices?: { id: string; label: string; locale?: string }[];
  defaultVoice?: string;
  latencyProfile?: string;
  supportsStreaming?: boolean;
};

type RecordingState = "idle" | "recording" | "processing";
type BackendState = "checking" | "online" | "offline";

const FALLBACK_STT_OPTIONS: ProviderOption[] = [
  { id: "groq_whisper", label: "Groq Whisper", status: "available" },
  { id: "gemini_audio", label: "Gemini Audio STT", status: "planned" },
  { id: "local", label: "Local STT", status: "planned" },
  { id: "openai", label: "OpenAI STT", status: "planned" },
];

const FALLBACK_TTS_OPTIONS: ProviderOption[] = [
  { id: "edge", label: "Edge TTS", status: "active", supportsStreaming: true },
  { id: "elevenlabs", label: "ElevenLabs TTS", status: "active", supportsStreaming: true },
  { id: "fishaudio", label: "Fish Audio TTS", status: "active", supportsStreaming: true },
];

const FALLBACK_TTS_VOICES_BY_PROVIDER: Record<string, { value: string; label: string }[]> = {
  edge: [
    { value: "pt-BR-FranciscaNeural", label: "Edge Francisca" },
    { value: "pt-BR-AntonioNeural", label: "Edge Antonio" },
    { value: "pt-BR-ThalitaNeural", label: "Edge Thalita" },
    { value: "pt-PT-RaquelNeural", label: "Edge Raquel" },
    { value: "pt-PT-DuarteNeural", label: "Edge Duarte" },
  ],
  elevenlabs: [
    { value: "JBFqnCBsd6RMkjVDRZzb", label: "Documented sample voice" },
  ],
  fishaudio: [
    { value: "", label: "Voz padrao (sem reference_id)" },
  ],
  local: [{ value: "local-default", label: "Local default" }],
};

const EVENT_LABELS: Record<TerminalAgentEventKind, string> = {
  listening: "Ouvindo",
  processing: "Processando",
  speaking: "Falando",
  transcription: "Transcricao",
  response: "Hana",
  tool: "Tool",
  user_speech: "Nakamura",
  user_text: "Nakamura",
  assistant_thought: "Hana",
  tool_call: "Tool call",
  tool_result: "Tool result",
  assistant_text: "Hana",
  assistant_speech: "Hana/TTS",
  error: "Erro",
  system: "Sistema",
};

type EventLane = "user" | "assistant" | "system";

const HIGHLIGHT_PATTERN = /(Nakamura|Hana|tts|stt|backend|runtime|whisper|Google Cloud TTS|Groq Whisper|erro|falha|failed|success|online|offline|speaking|recording|transcribed)/i;

// Groups event kinds into visual lanes without changing the backend event contract.
function eventLane(event: TerminalAgentEvent): EventLane {
  if (event.kind === "user_speech" || event.kind === "user_text" || event.kind === "transcription") {
    return "user";
  }
  if (event.kind === "assistant_text" || event.kind === "assistant_speech" || event.kind === "assistant_thought" || event.kind === "response" || event.kind === "speaking") {
    return "assistant";
  }
  return "system";
}

// Cores por papel (pedido do Nakamura): Hana=branco, Nakamura=rosa claro,
// sistema=verde, TTS/fala=amarelo suave. Tools=ciano, erro=vermelho.
function eventTerminalColor(event: TerminalAgentEvent) {
  if (event.kind === "error") return { border: "border-[#f00]/40", text: "text-[#f44]", chip: "text-[#f44]" };
  if (event.kind === "tool_call" || event.kind === "tool_result" || event.kind === "tool")
    return { border: "border-[#0ff]/30", text: "text-[#0ff]", chip: "text-[#0ff]" };
  // TTS/voz falada: amarelo suave (separa a fala do texto da Hana).
  if (event.kind === "assistant_speech" || event.kind === "speaking")
    return { border: "border-[#dd8]/25", text: "text-[#dd8]", chip: "text-[#dd8]" };
  // Hana (texto): branco.
  if (event.kind === "assistant_text" || event.kind === "assistant_thought" || event.kind === "response")
    return { border: "border-[#fff]/20", text: "text-[#eee]", chip: "text-[#fff]" };
  // Nakamura: rosa claro.
  if (event.kind === "user_speech" || event.kind === "user_text" || event.kind === "transcription")
    return { border: "border-[#fbc]/20", text: "text-[#fbc]", chip: "text-[#fbc]" };
  // Sistema: verde.
  return { border: "border-[#0f0]/15", text: "text-[#0f0]", chip: "text-[#0f0]" };
}

// Terminal-style keyword highlighting — keeps it simple: bright green for key names, dim green for others.
function highlightedText(text: string, baseClass = "") {
  return String(text || "").split(HIGHLIGHT_PATTERN).map((part, index) => {
    if (!part) return null;
    if (!HIGHLIGHT_PATTERN.test(part)) return <span key={`${part}-${index}`}>{part}</span>;
    const lower = part.toLowerCase();
    const cls =
      lower.includes("erro") || lower.includes("falha") || lower.includes("failed")
        ? "text-[#f44] font-bold"
        : lower.includes("hana")
          ? "text-[#fff] font-bold"
          : lower.includes("nakamura")
            ? "text-[#fbc] font-bold"
            : lower.includes("online") || lower.includes("success")
              ? "text-[#0f0] font-bold"
              : "text-[#0f0]/80 font-bold";
    return <span key={`${part}-${index}`} className={`${baseClass} ${cls}`}>{part}</span>;
  });
}

const LANGUAGE_OPTIONS = [
  { value: "pt", label: "Portugues" },
  { value: "pt-BR", label: "Portugues BR" },
  { value: "en", label: "English" },
  { value: "ja", label: "Japones" },
];

// Picks the best recorder format exposed by the current WebView/browser.
function supportedAudioMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

// Converts any thrown value into a visible terminal error.
function toErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error || "erro desconhecido");
}

function sttApiLanguage(language: string) {
  return language === "pt-BR" ? "pt" : language;
}



// Keeps provider options stable even when the backend catalog is unavailable.
function providerOptions(providers: VoiceProviderSpec[] | undefined, fallback: ProviderOption[]) {
  const byId = new Map<string, ProviderOption>();
  fallback.forEach((item) => byId.set(item.id, item));
  providers?.forEach((item) => byId.set(item.id, {
    id: item.id,
    label: item.label,
    status: item.status,
    models: item.models,
    defaultModel: item.defaultModel,
    voices: item.voices,
    defaultVoice: item.defaultVoice,
    latencyProfile: item.latencyProfile,
    supportsStreaming: item.supportsStreaming,
  }));
  return Array.from(byId.values());
}

// Formats timestamps as fixed-width console time.
function formatTime(value: string) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Reads structured metadata without coupling the UI to one backend schema.
function metadataText(event: TerminalAgentEvent, key: string) {
  const value = event.metadata?.[key];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

// Reads the background-job id from terminal metadata when a row belongs to a background job.
function eventJobId(event: TerminalAgentEvent) {
  return metadataText(event, "jobId") || metadataText(event, "job_id");
}

// Keeps cancellation as an explicit button action, not a text trigger.
function canCancelEventJob(event: TerminalAgentEvent) {
  const jobId = eventJobId(event);
  const jobEvent = metadataText(event, "jobEvent");
  return Boolean(jobId && ["queued", "running"].includes(event.status || "") && !["job.done", "job.failed", "job.cancelled"].includes(jobEvent));
}

// Produces a compact shell-like status label for each event line.
function eventOperation(event: TerminalAgentEvent) {
  if (event.kind === "user_speech") return event.status || "ouvindo";
  if (event.kind === "listening") return event.status || "ouvindo";
  if (event.kind === "processing") return event.status || "processando";
  if (event.kind === "speaking") return event.status || "falando";
  if (event.kind === "transcription") return event.status || "transcrito";
  if (event.kind === "response") return event.status || "resposta";
  if (event.kind === "tool") return event.toolName || "tool";
  if (event.kind === "assistant_thought") return event.status || "processando";
  if (event.kind === "assistant_speech") return event.status || "falando";
  if (event.kind === "assistant_text") return event.status || "resposta";
  if (event.kind === "tool_call") return event.toolName || "tool";
  if (event.kind === "tool_result") return event.status || "ok";
  if (event.kind === "error") return event.status || "erro";
  return event.status || "info";
}

// Serializes one terminal row exactly as it should be copied.
function serializeEvent(event: TerminalAgentEvent) {
  const details = [
    metadataText(event, "model") && `model=${metadataText(event, "model")}`,
    metadataText(event, "emotion") && `emotion=${metadataText(event, "emotion")}`,
    metadataText(event, "vision") && `vision=${metadataText(event, "vision")}`,
    event.toolName && `tool=${event.toolName}`,
  ].filter(Boolean);

  return [
    `[${formatTime(event.createdAt)}] ${EVENT_LABELS[event.kind] || event.kind} ${eventOperation(event)}${details.length ? ` ${details.join(" ")}` : ""}`,
    event.displayText,
    event.speechText && event.speechText !== event.displayText ? `tts> ${event.speechText}` : "",
  ].filter(Boolean).join("\n");
}

// Uses the async Clipboard API with a DOM fallback for Tauri/WebView edge cases.
async function copyText(text: string) {
  if (!text.trim()) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

interface EventRowProps {
  event: TerminalAgentEvent;
  onCancelJob: (jobId: string) => void;
}

// One memoized terminal-style event row. Flat, no bubbles — pure TUI aesthetic.
const EventRow = memo(function EventRow({ event, onCancelJob }: EventRowProps) {
  const lane = eventLane(event);
  const model = metadataText(event, "model");
  const emotion = metadataText(event, "emotion");
  const vision = metadataText(event, "vision");
  const operation = eventOperation(event);
  const jobId = eventJobId(event);
  const canCancelJob = canCancelEventJob(event);
  const colors = eventTerminalColor(event);
  const roleLabel = EVENT_LABELS[event.kind] || event.kind;
  const isUser = lane === "user";

  return (
    <div className={`group relative mb-2 flex items-start font-mono text-[13px] leading-loose ${colors.text}`}>
      {/* Timestamp: right-aligned, dim */}
      <span className="mr-2 shrink-0 text-right text-[10px] text-[#0f0]/30 w-[70px] select-none">
        [{formatTime(event.createdAt)}]
      </span>

      {/* Role chip: compact, colored */}
      <span className={`mr-1.5 shrink-0 text-[10px] font-bold uppercase ${colors.chip} select-none`}>
        [{roleLabel}]
      </span>

      {/* Operation badge */}
      <span className="mr-1.5 shrink-0 text-[10px] text-[#0f0]/40 select-none">
        {operation}
      </span>

      {/* Metadata inline */}
      <span className="mr-1.5 shrink-0 text-[10px] text-[#0f0]/25 select-none">
        {[
          model && `md=${model}`,
          emotion && `em=${emotion}`,
          vision && `vi=${vision}`,
          event.toolName && `tl=${event.toolName}`,
        ].filter(Boolean).join(" ")}
      </span>

      {/* Main content */}
      <span className="min-w-0 flex-1">
        {/* Prompt prefix for user events */}
        {isUser && <span className="mr-1 text-[#0f0] font-bold select-none">&gt;</span>}

        {highlightedText(event.displayText)}
        {event.metadata?.live === true ? <span className="animate-pulse text-[#0f0] font-bold">_</span> : null}

        {/* TTS: so um indicador curto — o texto completo ja apareceu na fala da Hana acima, repetir cansa. */}
        {event.speechText && event.speechText !== event.displayText && (
          <span className="mt-1 block text-[12px] text-[#dd8]/70">
            🔊 <span className="font-bold text-[#dd8]">falando</span>{" "}
            <span className="text-[#dd8]/50">
              {event.speechText.length > 60 ? `${event.speechText.slice(0, 60).trim()}…` : event.speechText}
            </span>
          </span>
        )}
      </span>

      {/* Action buttons: only visible on hover */}
      <span className="ml-2 flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        {canCancelJob && jobId && (
          <button
            className="text-[#f44] hover:text-[#f00]"
            onClick={() => onCancelJob(jobId)}
            title="Cancelar job"
          >
            <Square size={11} />
          </button>
        )}
        <button
          className="text-[#0f0]/40 hover:text-[#0f0]"
          onClick={() => void copyText(serializeEvent(event))}
          title="Copiar linha"
        >
          <Copy size={11} />
        </button>
      </span>
    </div>
  );
});

interface TabTerminalAgentProps {
  isActive: boolean;
}

// Terminal Agent renders operational voice-agent events as a lightweight console.
export function TabTerminalAgent({ isActive }: TabTerminalAgentProps) {
  const [events, setEvents] = useState<TerminalAgentEvent[]>([]);
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig>(DEFAULT_VOICE_CONFIG);

  const [sttProviders, setSttProviders] = useState<VoiceProviderSpec[]>([]);
  const [ttsProviders, setTtsProviders] = useState<VoiceProviderSpec[]>([]);
  const [draft, setDraft] = useState("");
  const [sanitizedPreview, setSanitizedPreview] = useState("");
  const [status, setStatus] = useState("");
  const [connections, setConnections] = useState<ConnectionsConfig | null>(null);
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<VoiceRuntimeStatus | null>(null);
  const [ttsVoiceAliases, setTtsVoiceAliases] = useState<TtsVoiceAliases>({});
  const [ttsVoiceName, setTtsVoiceName] = useState("");
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [liveStream, setLiveStream] = useState<TerminalAgentEvent | null>(null);

  const [recordingState, setRecordingState] = useState<RecordingState>("idle");
  const [recordingStartedAt, setRecordingStartedAt] = useState<number | null>(null);
  const [recordingElapsedSeconds, setRecordingElapsedSeconds] = useState(0);
  const [audioDevices, setAudioDevices] = useState<VoiceInputDevice[]>([]);
  const [outputDevices, setOutputDevices] = useState<VoiceInputDevice[]>([]);
  const [selectedAudioDeviceId, setSelectedAudioDeviceId] = useState(() => localStorage.getItem(AUDIO_DEVICE_KEY) || "");
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);
  const manualScrollRef = useRef(false);
  const loadedEventsRef = useRef(false);
  const eventsSignatureRef = useRef("");
  const chunksRef = useRef<Blob[]>([]);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const autoStopTimerRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const vadFrameRef = useRef<number | null>(null);
  const vadStatsRef = useRef({ activeMs: 0, maxRms: 0, lastAt: 0 });
  const runtimeStatusLoadingRef = useRef(false);

  const visibleEvents = useMemo(() => {
    // Colapsa repetições consecutivas de eventos de sistema idênticos (ex: o
    // "Runtime de voz em espera..." que aparecia 15x seguidas) mantendo o último.
    const collapsed: TerminalAgentEvent[] = [];
    for (const event of events) {
      const prev = collapsed[collapsed.length - 1];
      if (
        prev &&
        eventLane(event) === "system" &&
        prev.kind === event.kind &&
        prev.displayText === event.displayText &&
        prev.status === event.status
      ) {
        collapsed[collapsed.length - 1] = event;
        continue;
      }
      collapsed.push(event);
    }
    const liveStreamId = String(liveStream?.metadata?.streamId || "");
    const finalAlreadyLoaded = liveStreamId && collapsed.some((event) => event.metadata?.streamId === liveStreamId);
    if (liveStream && !finalAlreadyLoaded) collapsed.push(liveStream);
    return collapsed.slice(-MAX_VISIBLE_EVENTS);
  }, [events, liveStream]);
  const sttOptions = providerOptions(sttProviders, FALLBACK_STT_OPTIONS);
  const ttsOptions = providerOptions(ttsProviders, FALLBACK_TTS_OPTIONS);
  const activeSttProvider = sttOptions.find((item) => item.id === voiceConfig.sttProvider);
  const activeTtsProvider = ttsOptions.find((item) => item.id === voiceConfig.ttsProvider);
  const ttsUsesSpeed = voiceConfig.ttsProvider !== "gemini_tts";
  const ttsUsesPitch = !["gemini_tts", "cartesia", "elevenlabs", "fishaudio"].includes(voiceConfig.ttsProvider);
  const ttsCanStream = Boolean(activeTtsProvider?.supportsStreaming);
  const ttsIsElevenLabs = voiceConfig.ttsProvider === "elevenlabs";
  const ttsIsFishAudio = voiceConfig.ttsProvider === "fishaudio";
  useEffect(() => {
    const provider = voiceConfig.ttsProvider || "";
    const voiceId = voiceConfig.ttsVoice || "";
    setTtsVoiceName(ttsVoiceAliases[provider]?.[voiceId] || "");
  }, [ttsVoiceAliases, voiceConfig.ttsProvider, voiceConfig.ttsVoice]);
  const sttModelOptions = useMemo<CatalogPickerOption[]>(() => {
    const models = activeSttProvider?.models || [];
    const options: CatalogPickerOption[] = models.map((model) => ({
      value: model,
      label: model,
      favoriteId: `${voiceConfig.sttProvider}:${model}`,
      secondary: activeSttProvider?.label,
      badges: activeSttProvider?.latencyProfile
        ? [{ label: activeSttProvider.latencyProfile, tone: "green" as const }]
        : undefined,
    }));
    if (voiceConfig.sttModel && !options.some((option) => option.value === voiceConfig.sttModel)) {
      options.push({
        value: voiceConfig.sttModel,
        label: `${voiceConfig.sttModel} (custom)`,
        favoriteId: `${voiceConfig.sttProvider}:${voiceConfig.sttModel}`,
        badges: [{ label: "custom", tone: "neutral" }],
      });
    }
    return options;
  }, [activeSttProvider, voiceConfig.sttModel, voiceConfig.sttProvider]);
  const ttsModelOptions = useMemo<CatalogPickerOption[]>(() => {
    const models = activeTtsProvider?.models || [];
    const options: CatalogPickerOption[] = [
      {
        value: "",
        label: "Padrao do provider",
        favoriteId: `${voiceConfig.ttsProvider}:default-model`,
      },
      ...models.map((model) => ({
        value: model,
        label: model,
        favoriteId: `${voiceConfig.ttsProvider}:${model}`,
        secondary: activeTtsProvider?.label,
      })),
    ];
    if (voiceConfig.ttsModel && !options.some((option) => option.value === voiceConfig.ttsModel)) {
      options.push({
        value: voiceConfig.ttsModel,
        label: `${voiceConfig.ttsModel} (custom)`,
        favoriteId: `${voiceConfig.ttsProvider}:${voiceConfig.ttsModel}`,
        badges: [{ label: "custom", tone: "neutral" }],
      });
    }
    return options;
  }, [activeTtsProvider, voiceConfig.ttsModel, voiceConfig.ttsProvider]);
  const ttsVoiceOptions = useMemo<CatalogPickerOption[]>(() => {
    const merged = new Map<string, CatalogPickerOption>();
    const aliases = ttsVoiceAliases[voiceConfig.ttsProvider] || {};
    merged.set("", {
      value: "",
      label: "Padrao do provider",
      favoriteId: `${voiceConfig.ttsProvider}:default-voice`,
    });
    const fallback = FALLBACK_TTS_VOICES_BY_PROVIDER[voiceConfig.ttsProvider] || [];
    fallback.forEach((item) => merged.set(item.value, {
      ...item,
      label: aliases[item.value] || item.label,
      favoriteId: `${voiceConfig.ttsProvider}:${item.value}`,
      secondary: item.value,
    }));
    activeTtsProvider?.voices?.forEach((voice) => merged.set(voice.id, {
      value: voice.id,
      label: aliases[voice.id] || voice.label || voice.id,
      favoriteId: `${voiceConfig.ttsProvider}:${voice.id}`,
      secondary: [voice.id, voice.locale].filter(Boolean).join(" - "),
    }));
    Object.entries(aliases).forEach(([id, name]) => {
      if (id && !merged.has(id)) {
        merged.set(id, {
          value: id,
          label: name,
          favoriteId: `${voiceConfig.ttsProvider}:${id}`,
          secondary: id,
          badges: [{ label: "banco", tone: "purple" }],
        });
      }
    });
    if (voiceConfig.ttsVoice && !merged.has(voiceConfig.ttsVoice)) {
      merged.set(voiceConfig.ttsVoice, {
        value: voiceConfig.ttsVoice,
        label: `${voiceConfig.ttsVoice} (custom)`,
        favoriteId: `${voiceConfig.ttsProvider}:${voiceConfig.ttsVoice}`,
        badges: [{ label: "custom", tone: "neutral" }],
      });
    }
    return Array.from(merged.values());
  }, [activeTtsProvider, ttsVoiceAliases, voiceConfig.ttsProvider, voiceConfig.ttsVoice]);

  const loadEvents = async () => {
    const data = await ApiController.getTerminalAgentEvents(MAX_VISIBLE_EVENTS);
    setBackendState(data.backendAvailable === false ? "offline" : "online");
    const nextEvents = data.events || [];
    // Nada mudou desde o último poll → não recria o array (evita re-render de
    // todas as bolhas a cada 2s, que era o que deixava a aba pesada).
    const signature = `${nextEvents.length}:${nextEvents[nextEvents.length - 1]?.id || ""}`;
    if (loadedEventsRef.current && signature === eventsSignatureRef.current) return;

    eventsSignatureRef.current = signature;
    loadedEventsRef.current = true;
    setEvents(nextEvents);
  };

  const loadRuntimeStatus = async () => {
    if (runtimeStatusLoadingRef.current) return;
    runtimeStatusLoadingRef.current = true;
    try {
      setRuntimeStatus(await ApiController.getVoiceRuntimeStatus());
      setBackendState("online");
    } catch (error) {
      setRuntimeStatus(null);
      setBackendState("offline");
      setStatus(`Backend offline: ${toErrorMessage(error)}`);
    } finally {
      runtimeStatusLoadingRef.current = false;
    }
  };

  const refreshAudioDevices = async () => {
    setAudioDevices(await ApiController.getVoiceInputDevices());
  };

  const refreshOutputDevices = async () => {
    setOutputDevices(await ApiController.getVoiceOutputDevices());
  };

  const updateSecondOutput = (patch: Partial<VoiceConfig>) => {
    void updateVoiceConfig(patch, false);
    void ApiController.configureVoiceRuntime()
      .then((runtime) => {
        setRuntimeStatus(runtime);
        setBackendState("online");
      })
      .catch((error) => {
        setBackendState("offline");
        setStatus(`Falha ao atualizar segunda saida: ${toErrorMessage(error)}`);
      });
  };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let closed = false;
    const onMessage = (message: TerminalAgentStreamMessage) => {
      if (message.type === "done") {
        setLiveStream((current) => current?.metadata?.streamId === message.streamId ? null : current);
        void loadEvents();
        return;
      }
      if (!message.delta) return;
      const delta = message.delta;
      setLiveStream((current) => {
        if (current?.metadata?.streamId === message.streamId) {
          return { ...current, displayText: `${current.displayText}${delta}` };
        }
        return {
          id: `live-${message.streamId}`,
          kind: "assistant_text",
          source: "hana",
          displayText: delta,
          status: "streaming",
          createdAt: new Date().toISOString(),
          metadata: { live: true, streamId: message.streamId },
        };
      });
    };
    const connect = () => {
      ws = ApiController.connectTerminalAgentStream(onMessage);
      ws.onclose = () => {
        if (!closed) reconnectTimer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    Promise.all([
      ApiController.getVoiceConfig(),
      ApiController.getVoiceCatalog(),
      ApiController.getConnectionsConfig(),
      ApiController.getTtsVoiceAliases(),
    ])
      .then(([config, catalog, connectionsConfig, voiceAliases]) => {
        setVoiceConfig(config);
        setSttProviders(catalog?.sttProviders || []);
        setTtsProviders(catalog?.ttsProviders || []);
        setConnections(connectionsConfig);
        setTtsVoiceAliases(voiceAliases || {});
      })
      .catch(() => setStatus("Backend indisponivel. Usando cache local."));
    void loadEvents();
    void refreshAudioDevices();
    void refreshOutputDevices();
    void loadRuntimeStatus();

    // Um unico timer de 2s: antes eram dois intervals separados na mesma
    // cadencia (loadEvents + config/runtime), duplicando o agendamento sem
    // motivo. Junto num so tick, mesmo comportamento, menos overhead.
    const timer = window.setInterval(() => {
      void loadEvents();
      Promise.all([ApiController.getVoiceConfig(), ApiController.getConnectionsConfig(), loadRuntimeStatus()])
        .then(([config, connectionsConfig]) => {
          setVoiceConfig(config);
          setConnections(connectionsConfig);
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    return () => {
      if (autoStopTimerRef.current) window.clearTimeout(autoStopTimerRef.current);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
      stopVadMonitor();
    };
  }, []);

  // Follow event height changes until the user explicitly scrolls upward.
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

  // Entering the Terminal always opens at the newest operational event.
  useEffect(() => {
    if (!isActive) return;
    const frame = requestAnimationFrame(() => {
      if (!scrollRef.current) return;
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      userScrolledUpRef.current = false;
      setShowScrollToBottom(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [isActive]);

  // Distinguish manual history inspection from content-driven layout changes.
  const handleTerminalScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (distance <= 48) {
      userScrolledUpRef.current = false;
      setShowScrollToBottom(false);
      return;
    }
    if (manualScrollRef.current) {
      userScrolledUpRef.current = true;
      setShowScrollToBottom(true);
    }
  };

  const handleTerminalWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < 0) {
      userScrolledUpRef.current = true;
      setShowScrollToBottom(true);
    }
  };

  const scrollTerminalToLatest = () => {
    userScrolledUpRef.current = false;
    setShowScrollToBottom(false);
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  };

  useEffect(() => {
    if (recordingState !== "recording" || !recordingStartedAt) {
      setRecordingElapsedSeconds(0);
      return;
    }

    const timer = window.setInterval(() => {
      setRecordingElapsedSeconds(Math.max(0, Math.round((Date.now() - recordingStartedAt) / 1000)));
    }, 500);
    return () => window.clearInterval(timer);
  }, [recordingState, recordingStartedAt]);

  useEffect(() => {
    ApiController.sanitizeTtsText(draft).then(setSanitizedPreview);
  }, [draft]);

  const updateVoiceConfig = async (patch: Partial<VoiceConfig>, syncRuntime = true) => {
    const next = { ...voiceConfig, ...patch };
    setVoiceConfig(next);
    const saved = await ApiController.updateVoiceConfig(patch);
    setBackendState(saved ? "online" : "offline");
    if (!saved) setStatus("Config de voz salva apenas no cache local; backend indisponivel.");
    if (syncRuntime) {
      ApiController.configureVoiceRuntime().then((runtime) => {
        setRuntimeStatus(runtime);
        setBackendState("online");
      }).catch((error) => {
        setBackendState("offline");
        setStatus(`Falha ao sincronizar runtime: ${toErrorMessage(error)}`);
      });
    }
  };

  const saveTtsVoiceName = async () => {
    const provider = voiceConfig.ttsProvider;
    const voiceId = voiceConfig.ttsVoice.trim();
    const name = ttsVoiceName.trim();
    if (!voiceId || !name) {
      setStatus("Informe o identificador e o nome da voz.");
      return;
    }
    try {
      const aliases = await ApiController.saveTtsVoiceAlias(provider, voiceId, name);
      setTtsVoiceAliases(aliases);
      setStatus(`Voz salva no banco como “${name}”.`);
      setBackendState("online");
    } catch (error) {
      setStatus(toErrorMessage(error));
      setBackendState("offline");
    }
  };

  // Keeps provider-specific TTS defaults valid when switching between providers.
  const updateTtsProvider = (provider: string) => {
    if (provider === "edge" && !String(voiceConfig.ttsVoice || "").startsWith("pt-")) {
      void updateVoiceConfig({ ttsProvider: provider, ttsModel: "", ttsVoice: "pt-BR-FranciscaNeural", ttsStreaming: false });
      return;
    }
    if (provider === "elevenlabs") {
      void updateVoiceConfig({
        ttsProvider: provider,
        ttsModel: "eleven_flash_v2_5",
        ttsVoice: "JBFqnCBsd6RMkjVDRZzb",
        ttsLanguage: "pt",
        ttsSpeed: 1,
        ttsPitch: 0,
        ttsStreaming: false,
        ttsStability: 0.5,
        ttsSimilarity: 0.75,
        ttsStyle: 0,
        ttsSpeakerBoost: true,
      });
      return;
    }
    void updateVoiceConfig({ ttsProvider: provider });
  };



  const appendTerminalEvent = async (payload: Partial<TerminalAgentEvent>) => {
    const event = await ApiController.appendTerminalAgentEvent(payload);
    if (event) setEvents((prev) => [...prev, event].slice(-MAX_VISIBLE_EVENTS));
    return event;
  };

  const appendCommand = async () => {
    const text = draft.trim();
    if (!text) return;
    setStatus("Enviando comando manual para Hana...");
    setDraft("");
    try {
      await ApiController.respondTerminalAgentText(text, {
        safetyMode: localStorage.getItem("hana_agent_safety_mode") || "safe",
      });
      await loadEvents();
      setStatus("Hana respondeu ao comando manual.");
    } catch (error) {
      const message = toErrorMessage(error);
      await appendTerminalEvent({
        kind: "error",
        source: "operator",
        displayText: `Falha ao responder comando manual: ${message}`,
        speechText: "",
        status: "failed",
      });
      setStatus(`Falha no comando manual: ${message}`);
    }
  };

  // "Ejetar": botao de emergencia pra quando um job do Terminal Agente pendura.
  // O botao por linha so aparece em evento que TEM jobId; quando o processo trava
  // sem emitir evento, nao havia como matar pela UI. O backend ja sabia fazer isso
  // (cancel_active -> process.terminate()), so faltava alguem chamar.
  const ejectStuckJob = async () => {
    setStatus("Ejetando job travado...");
    try {
      const result = await ApiController.cancelActiveAgentJobs("terminal_agent", "eject_button");
      // TTS junto: um turno pendurado normalmente deixa a fala presa tambem.
      await ApiController.stopTerminalAgentSpeech().catch(() => undefined);
      await loadEvents();
      const killed = Number(result?.cancelled || 0);
      setStatus(killed ? `Ejetado: ${killed} job(s) cancelado(s).` : "Nada rodando pra ejetar. Fala interrompida.");
    } catch (error) {
      setStatus(`Falha ao ejetar: ${toErrorMessage(error)}`);
    }
  };

  const cancelEventJob = async (jobId: string) => {
    setStatus(`Cancelando job ${jobId}...`);
    await ApiController.cancelAgentJob(jobId, "terminal_agent");
    await loadEvents();
    setStatus(`Cancelamento solicitado para ${jobId}.`);
  };

  // Callbacks estáveis para o EventRow memoizado (senão o memo não adianta nada).
  const cancelEventJobRef = useRef(cancelEventJob);
  cancelEventJobRef.current = cancelEventJob;
  const handleCancelJob = useCallback((jobId: string) => { void cancelEventJobRef.current(jobId); }, []);
  const releaseMicrophone = () => {
    stopVadMonitor();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    mediaRecorderRef.current = null;
  };

  const stopVadMonitor = () => {
    if (vadFrameRef.current) {
      cancelAnimationFrame(vadFrameRef.current);
      vadFrameRef.current = null;
    }
    audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
  };

  const startVadMonitor = (stream: MediaStream) => {
    stopVadMonitor();
    const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;

    const context = new AudioContextCtor();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    const source = context.createMediaStreamSource(stream);
    source.connect(analyser);
    const data = new Float32Array(analyser.fftSize);
    const threshold = Math.max(0.005, Number(voiceConfig.vadThreshold || 0.035));
    vadStatsRef.current = { activeMs: 0, maxRms: 0, lastAt: performance.now() };
    audioContextRef.current = context;

    const tick = () => {
      analyser.getFloatTimeDomainData(data);
      let sum = 0;
      for (const sample of data) sum += sample * sample;
      const rms = Math.sqrt(sum / data.length);
      const now = performance.now();
      const delta = Math.min(120, Math.max(0, now - vadStatsRef.current.lastAt));
      vadStatsRef.current.lastAt = now;
      vadStatsRef.current.maxRms = Math.max(vadStatsRef.current.maxRms, rms);
      if (rms >= threshold) {
        vadStatsRef.current.activeMs += delta;
      }
      vadFrameRef.current = requestAnimationFrame(tick);
    };
    vadFrameRef.current = requestAnimationFrame(tick);
  };

  const transcribeRecordedAudio = async (audio: Blob, durationMs?: number) => {
    const voiceStats = vadStatsRef.current;
    if (!audio.size) {
      await appendTerminalEvent({
        kind: "error",
        source: "stt",
        displayText: "STT nao recebeu audio gravado.",
        speechText: "",
        toolName: "stt.transcribe",
        status: "empty_audio",
      });
      setStatus("Audio vazio. Nada foi enviado para STT.");
      return;
    }
    if ((durationMs || 0) < MIN_RECORDING_MS || voiceStats.activeMs < MIN_ACTIVE_VOICE_MS) {
      await appendTerminalEvent({
        kind: "system",
        source: "stt",
        displayText: `Audio descartado: pouca voz ativa (active=${Math.round(voiceStats.activeMs)}ms rms=${voiceStats.maxRms.toFixed(4)}).`,
        speechText: "",
        toolName: "stt.vad",
        status: "ignored",
        metadata: { durationMs, activeMs: Math.round(voiceStats.activeMs), maxRms: voiceStats.maxRms, tts: false },
      });
      setStatus("Audio descartado: pouca voz ativa.");
      return;
    }

    try {
      setRecordingState("processing");
      setStatus("Processando audio no STT...");
      await appendTerminalEvent({
        kind: "assistant_thought",
        source: "control_panel",
        displayText: "Audio capturado. Enviando para transcricao e resposta em texto.",
        speechText: "",
        status: "processando",
        metadata: { model: voiceConfig.sttModel, sttProvider: voiceConfig.sttProvider, durationMs },
      });

      const result = await ApiController.transcribeTerminalAgentAudio(audio, {
        provider: voiceConfig.sttProvider,
        model: voiceConfig.sttModel,
        language: sttApiLanguage(voiceConfig.sttLanguage),
        durationMs,
        respond: true,
      });

      const text = result.text.trim();
      if (!text) {
        await appendTerminalEvent({
          kind: "system",
          source: "stt",
          displayText: "STT retornou sem texto transcrito.",
          speechText: "",
          toolName: "stt.transcribe",
          status: "empty_text",
          metadata: { provider: result.provider, model: result.model, language: result.language, durationMs },
        });
        setStatus("STT concluiu, mas nao retornou texto.");
        return;
      }

      setDraft(text);
      await loadEvents();
      setStatus(result.responded ? "Hana respondeu em texto." : "Transcricao registrada.");
    } catch (error) {
      const message = toErrorMessage(error);
      await appendTerminalEvent({
        kind: "error",
        source: "stt",
        displayText: `Falha ao transcrever audio por ${voiceConfig.sttProvider}: ${message}`,
        speechText: "",
        toolName: "stt.transcribe",
        status: "failed",
        metadata: { provider: voiceConfig.sttProvider, language: voiceConfig.sttLanguage, durationMs },
      });
      setStatus(`Falha no STT: ${message}`);
    } finally {
      setRecordingState("idle");
      setRecordingStartedAt(null);
      setRecordingElapsedSeconds(0);
    }
  };

  const startSttRecording = async (options: { autoStopMs?: number; source?: "manual" | "auto" | "ptt" } = {}) => {
    if (recordingState !== "idle") return;
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      await appendTerminalEvent({
        kind: "error",
        source: "control_panel",
        displayText: "Este WebView/navegador nao oferece MediaRecorder para capturar microfone.",
        speechText: "",
        toolName: "media_recorder",
        status: "unsupported",
      });
      setStatus("MediaRecorder indisponivel neste ambiente.");
      return;
    }

    try {
      const browserDevice = audioDevices.find((device) => device.id === selectedAudioDeviceId && device.source === "browser_media_recorder");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: browserDevice?.id && browserDevice.id !== "browser_default"
          ? { deviceId: { exact: browserDevice.id }, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
          : { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      await refreshAudioDevices();
      const mimeType = supportedAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      streamRef.current = stream;
      mediaRecorderRef.current = recorder;
      const startedAt = Date.now();
      startVadMonitor(stream);

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType || mimeType || "audio/webm" });
        const durationMs = Date.now() - startedAt;
        releaseMicrophone();
        void transcribeRecordedAudio(audio, durationMs);
      };

      recorder.start();
      if (autoStopTimerRef.current) window.clearTimeout(autoStopTimerRef.current);
      if (options.autoStopMs) {
        autoStopTimerRef.current = window.setTimeout(() => {
          stopSttRecording();
        }, options.autoStopMs);
      }
      setRecordingStartedAt(startedAt);
      setRecordingElapsedSeconds(0);
      setRecordingState("recording");
      setStatus("Ouvindo microfone...");
      await appendTerminalEvent({
        kind: "user_speech",
        source: "microphone",
        displayText: "Microfone aberto. Hana esta ouvindo Nakamura.",
        speechText: "",
        status: "ouvindo",
        metadata: { deviceId: selectedAudioDeviceId || "default", sttProvider: voiceConfig.sttProvider, model: voiceConfig.sttModel, mode: options.source || "manual" },
      });
    } catch (error) {
      releaseMicrophone();
      const message = toErrorMessage(error);
      await appendTerminalEvent({
        kind: "error",
        source: "control_panel",
        displayText: `Falha ao abrir microfone para STT: ${message}`,
        speechText: "",
        toolName: "media_recorder",
        status: "failed",
      });
      setStatus(`Falha no microfone: ${message}`);
    }
  };

  const stopSttRecording = () => {
    if (autoStopTimerRef.current) {
      window.clearTimeout(autoStopTimerRef.current);
      autoStopTimerRef.current = null;
    }
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.requestData();
    recorder.stop();
    setRecordingState("processing");
    setStatus("Finalizando audio...");
  };

  const stopTts = async () => {
    window.speechSynthesis?.cancel();
    await ApiController.stopTerminalAgentSpeech();
    await loadRuntimeStatus();
    await loadEvents();
    setStatus("Parada de fala/TTS enviada.");
  };

  const testTts = async () => {
    const text = sanitizedPreview || draft.trim() || "Oi Nakamura, teste de voz da Hana.";
    setStatus("Enviando teste TTS...");
    let ok = false;
    let errorMessage = "";
    try {
      ok = await ApiController.speakTerminalAgentText(text);
      setBackendState("online");
    } catch (error) {
      errorMessage = toErrorMessage(error);
      setBackendState("offline");
      setStatus(`Falha no teste TTS: ${errorMessage}`);
    }
    await loadRuntimeStatus();
    await loadEvents();
    setStatus(ok ? "Teste TTS enviado." : (errorMessage ? `Falha no teste TTS: ${errorMessage}` : "TTS desativada ou indisponivel."));
  };



  const clearEvents = async () => {
    if (!confirm("Limpar os eventos do Terminal Agente?")) return;
    await ApiController.clearTerminalAgentEvents();
    setEvents([]);
  };

  const copyVisibleLog = () => {
    const text = visibleEvents.map(serializeEvent).join("\n\n");
    copyText(text);
    setStatus("Eventos visiveis copiados.");
  };

  const updateAudioDevice = (deviceId: string) => {
    const device = audioDevices.find((item) => item.id === deviceId);
    setSelectedAudioDeviceId(deviceId);
    localStorage.setItem(AUDIO_DEVICE_KEY, deviceId);
    const patch = {
      inputDeviceId: deviceId,
      inputDeviceLabel: device?.label || "",
      inputDeviceSource: device?.source || "sounddevice",
    };
    void updateVoiceConfig(patch, false);
    void ApiController.configureVoiceRuntime()
      .then((runtime) => {
        setRuntimeStatus(runtime);
        setBackendState("online");
      })
      .catch((error) => {
        setBackendState("offline");
        setStatus(`Falha ao atualizar microfone: ${toErrorMessage(error)}`);
      });
  };

  return (
    <div className="w-full h-full overflow-hidden bg-[#000] flex flex-col font-mono">
      {/* Terminal header bar: thin, minimal, hostname style */}
      <div className="flex items-center justify-between border-b border-[#0f0]/15 bg-[#000] px-4 py-1.5">
        <div className="flex items-center gap-3 text-[12px]">
          <span className="font-bold text-[#0f0] select-none">hana@nexus:~$</span>
          <span className="text-[#0f0]/40 text-[10px]">Terminal Agente</span>
          {runtimeStatus?.state && (
            <span className="text-[#0f0]/30 text-[10px]">[{runtimeStatus.state}]</span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-[10px]">
          {backendState === "offline" && <span className="text-[#f44] font-bold">OFFLINE</span>}
          {backendState === "checking" && <span className="text-[#ff0]/80">checking...</span>}
          {status && <span className="text-[#0f0]/50 max-w-[400px] truncate">{status}</span>}
          <span className={`ml-2 ${connections?.tts ? "text-[#faf]" : "text-[#0f0]/25"}`}>tts:{connections?.tts ? "on" : "off"}</span>
          <span className={`${connections?.visao ? "text-[#0f0]" : "text-[#0f0]/25"}`}>vis:{connections?.visao ? "on" : "off"}</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={loadEvents} className="px-2 py-0.5 text-[#0f0]/50 hover:text-[#0f0] text-[10px]" title="Atualizar">
            <RefreshCw size={12} />
          </button>
          <button onClick={stopTts} className="px-2 py-0.5 text-[#faf]/50 hover:text-[#faf] text-[10px]" title="Parar fala">
            <Volume2 size={12} />
          </button>
          <button onClick={ejectStuckJob} className="px-2 py-0.5 text-[#fa0]/50 hover:text-[#fa0] text-[10px]" title="Ejetar: mata o processo/job travado do Terminal Agente">
            <Ban size={12} />
          </button>
          <button onClick={() => setSettingsOpen(true)} className="px-2 py-0.5 text-[#0f0]/50 hover:text-[#0f0] text-[10px]" title="Config">
            <Settings size={12} />
          </button>
          <button onClick={copyVisibleLog} className="px-2 py-0.5 text-[#0f0]/30 hover:text-[#0f0] text-[10px]" title="Copiar log">
            <Copy size={12} />
          </button>
          <button onClick={clearEvents} className="px-2 py-0.5 text-[#f44]/40 hover:text-[#f44] text-[10px]" title="Limpar">
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1" style={{ scrollbarWidth: "thin", scrollbarColor: "#0f0 #000" }}>
      <div
        ref={scrollRef}
        onScroll={handleTerminalScroll}
        onWheel={handleTerminalWheel}
        onPointerDown={() => { manualScrollRef.current = true; }}
        onPointerUp={() => { manualScrollRef.current = false; }}
        onPointerCancel={() => { manualScrollRef.current = false; }}
        className="h-full overflow-y-auto bg-[#000] px-4 py-2 font-mono text-[12px]"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#0a0 #000" }}
      >
        <div ref={contentRef} className="mx-auto w-full max-w-5xl">
        {visibleEvents.length === 0 ? (
          <div className="flex h-full min-h-[320px] items-center justify-center">
            <span className="text-[#0f0]/25 font-mono text-[11px] select-none">hana@nexus:~$ _</span>
          </div>
        ) : visibleEvents.map((event) => (
          <EventRow
            key={event.id}
            event={event}
            onCancelJob={handleCancelJob}
          />
        ))}
        </div>
      </div>
      {showScrollToBottom && (
        <button
          type="button"
          onClick={scrollTerminalToLatest}
          className="absolute bottom-4 right-4 z-40 flex h-8 items-center gap-1.5 border border-[#0f0]/30 bg-[#000] px-3 text-[10px] text-[#0f0] hover:border-[#0f0]/60 hover:text-[#0f0] font-mono"
          title="Ir para o evento mais recente"
          aria-label="Ir para o evento mais recente"
        >
          <ChevronDown size={14} />
          <span>latest</span>
        </button>
      )}
      </div>

      <div className="border-t border-[#0f0]/15 bg-[#000] px-4 py-2">
        <div className="relative mx-auto w-full max-w-5xl">
          <span className="absolute left-3 top-3 text-[#0f0] font-bold text-sm select-none">&gt;</span>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) appendCommand();
            }}
            className="h-[66px] w-full resize-none bg-transparent py-2.5 pl-7 pr-12 font-mono text-sm text-[#0f0] outline-none placeholder:text-[#0f0]/20"
            placeholder="digite um comando manual..."
          />
          <button
            onClick={appendCommand}
            disabled={!draft.trim()}
            title="Enviar (Ctrl+Enter)"
            aria-label="Enviar"
            className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center text-[#0f0]/50 hover:text-[#0f0] disabled:opacity-20"
          >
            <Send size={16} />
          </button>
        </div>
      </div>

      {settingsOpen && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
          <div className="flex h-full max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden border border-[#0f0]/20 bg-[#000]">
            <div className="flex items-center justify-between border-b border-[#0f0]/15 px-4 py-2">
              <h3 className="font-mono text-sm font-bold text-[#0f0]">hana@nexus:~$ config</h3>
              <button onClick={() => setSettingsOpen(false)} className="text-[#0f0]/40 hover:text-[#0f0]" title="Fechar">
                <X size={16} />
              </button>
            </div>

            <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto p-4 font-mono text-xs md:grid-cols-2" style={{ scrollbarWidth: "thin", scrollbarColor: "#0a0 #000" }}>
              <label className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">STT provider</span>
                <select value={voiceConfig.sttProvider} onChange={(event) => updateVoiceConfig({ sttProvider: event.target.value })} className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none">
                  {sttOptions.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.status})</option>)}
                </select>
              </label>

              <div className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">STT modelo</span>
                {activeSttProvider?.models?.length ? (
                  <CatalogPicker
                    value={voiceConfig.sttModel}
                    options={sttModelOptions}
                    onChange={(value) => updateVoiceConfig({ sttModel: value })}
                    favoriteNamespace={`terminal-stt-model:${voiceConfig.sttProvider}`}
                    searchPlaceholder="Buscar modelo STT..."
                    accent="emerald"
                    showAdvancedFilters={false}
                    compact
                  />
                ) : (
                  <input value={voiceConfig.sttModel} onChange={(event) => updateVoiceConfig({ sttModel: event.target.value })} className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none" placeholder="whisper-large-v3" />
                )}
              </div>

              <label className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Idioma STT</span>
                <select value={voiceConfig.sttLanguage} onChange={(event) => updateVoiceConfig({ sttLanguage: event.target.value })} className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none">
                  {LANGUAGE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Microfone</span>
                <select value={selectedAudioDeviceId} onChange={(event) => updateAudioDevice(event.target.value)} onFocus={refreshAudioDevices} className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none">
                  <option value="">Dispositivo padrao do backend</option>
                  {audioDevices.map((device, index) => (
                    <option key={device.id || index} value={device.id}>{device.label || `Microfone ${index + 1}`} [{device.source}]</option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 flex items-center justify-between text-[#0f0]/60 text-[10px] uppercase tracking-wider">
                  Segunda saida de audio
                  <input
                    type="checkbox"
                    checked={!!voiceConfig.secondOutputEnabled}
                    onChange={(event) => updateSecondOutput({ secondOutputEnabled: event.target.checked })}
                    onFocus={refreshOutputDevices}
                    className="h-3.5 w-3.5 accent-[#0f0]"
                  />
                </span>
                <select
                  value={voiceConfig.secondOutputDeviceId || ""}
                  disabled={!voiceConfig.secondOutputEnabled}
                  onChange={(event) => {
                    const device = outputDevices.find((item) => item.id === event.target.value);
                    updateSecondOutput({ secondOutputDeviceId: event.target.value, secondOutputDeviceLabel: device?.label || "" });
                  }}
                  onFocus={refreshOutputDevices}
                  className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none disabled:opacity-30"
                >
                  <option value="">Selecione a saida (ex.: CABLE Input)</option>
                  {outputDevices.map((device, index) => (
                    <option key={device.id || index} value={device.id}>{device.label || `Saida ${index + 1}`}</option>
                  ))}
                </select>
                <span className="text-[#0f0]/25 text-[10px]">A voz toca no PC e tambem nesse dispositivo (cabo virtual p/ Discord, VTube etc.).</span>
              </label>

              <label className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Modo VAD</span>
                <select value={voiceConfig.vadMode || "silero"} onChange={(event) => updateVoiceConfig({ vadMode: event.target.value as "silero" | "rms" })} className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none">
                  <option value="silero">Silero neural (ignora ruido)</option>
                  <option value="rms">Energia RMS (simples)</option>
                </select>
                <span className="text-[#0f0]/25 text-[10px]">{(voiceConfig.vadMode || "silero") === "silero" ? "Rede neural distingue voz de ruido." : "So volume: dispara com barulho alto."}</span>
              </label>

              {(voiceConfig.vadMode || "silero") === "silero" && (
                <label className="block">
                  <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Sensibilidade Silero</span>
                  <input type="range" min="0.2" max="0.9" step="0.05" value={voiceConfig.vadProbThreshold ?? 0.5} onChange={(event) => updateVoiceConfig({ vadProbThreshold: Number(event.target.value) })} className="w-full accent-[#0f0]" />
                  <span className="text-[#0f0]/40 text-[10px]">{Number(voiceConfig.vadProbThreshold ?? 0.5).toFixed(2)} — maior = exige mais certeza</span>
                </label>
              )}

              <label className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Threshold VAD</span>
                <input type="range" min="0.005" max="0.12" step="0.001" value={voiceConfig.vadThreshold || 0.035} onChange={(event) => updateVoiceConfig({ vadThreshold: Number(event.target.value) })} className="w-full accent-[#0f0]" />
                <span className="text-[#0f0]/40 text-[10px]">{Number(voiceConfig.vadThreshold || 0.035).toFixed(3)}</span>
              </label>

              <label className="block">
                <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Limite de fala (TTS)</span>
                <input type="range" min="0" max="1200" step="50" value={voiceConfig.ttsMaxChars ?? 350} onChange={(event) => updateVoiceConfig({ ttsMaxChars: Number(event.target.value) })} className="w-full accent-[#faf]" />
                <span className="text-[#faf]/40 text-[10px]">{(voiceConfig.ttsMaxChars ?? 350) === 0 ? "sem limite" : `${voiceConfig.ttsMaxChars ?? 350} chars`}</span>
              </label>

              <label className="flex items-center justify-between gap-3">
                <span className="block">
                  <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Barge-in (falar por cima)</span>
                  <span className="text-[#0f0]/25 text-[10px]">Interrompe a fala da Hana falando por cima.</span>
                </span>
                <input type="checkbox" checked={!!voiceConfig.bargeInEnabled} onChange={(event) => updateVoiceConfig({ bargeInEnabled: event.target.checked })} className="h-4 w-4 accent-[#0f0]" />
              </label>

              <label className="block">
                <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Silencio final</span>
                <input type="range" min="300" max="1800" step="50" value={voiceConfig.silenceTimeoutMs || 900} onChange={(event) => updateVoiceConfig({ silenceTimeoutMs: Number(event.target.value) })} className="w-full accent-[#0f0]" />
                <span className="text-[#0f0]/40 text-[10px]">{Number(voiceConfig.silenceTimeoutMs || 900)}ms</span>
              </label>

              <label className="block">
                <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">TTS provider</span>
                <select value={voiceConfig.ttsProvider} onChange={(event) => updateTtsProvider(event.target.value)} className="w-full border border-[#faf]/20 bg-[#000] px-2 py-1.5 text-[#faf] font-mono text-xs outline-none">
                  {ttsOptions.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.status})</option>)}
                </select>
              </label>

              <div className="block">
                <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">TTS modelo</span>
                {activeTtsProvider?.models?.length ? (
                  <CatalogPicker
                    value={voiceConfig.ttsModel}
                    options={ttsModelOptions}
                    onChange={(value) => updateVoiceConfig({ ttsModel: value })}
                    favoriteNamespace={`terminal-tts-model:${voiceConfig.ttsProvider}`}
                    searchPlaceholder="Buscar modelo TTS..."
                    accent="cyan"
                    showAdvancedFilters={false}
                    compact
                  />
                ) : (
                  <input value={voiceConfig.ttsModel} onChange={(event) => updateVoiceConfig({ ttsModel: event.target.value })} className="w-full border border-[#faf]/20 bg-[#000] px-2 py-1.5 text-[#faf] font-mono text-xs outline-none" placeholder="modelo do provider" />
                )}
                {ttsIsElevenLabs && (
                  <input
                    value={voiceConfig.ttsModel}
                    onChange={(event) => updateVoiceConfig({ ttsModel: event.target.value.trim() })}
                    className="mt-1.5 w-full border border-[#0ff]/20 bg-[#000] px-2 py-1.5 text-[#0ff] font-mono text-xs outline-none"
                    placeholder="ID customizado do modelo ElevenLabs"
                  />
                )}
              </div>

              <div className="block">
                <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Voz</span>
                <CatalogPicker
                  value={voiceConfig.ttsVoice}
                  options={ttsVoiceOptions}
                  onChange={(value) => updateVoiceConfig({ ttsVoice: value })}
                  favoriteNamespace={`terminal-tts-voice:${voiceConfig.ttsProvider}`}
                  searchPlaceholder="Buscar voz por nome ou ID..."
                  accent="pink"
                  showAdvancedFilters={false}
                  compact
                />
                {(ttsIsElevenLabs || ttsIsFishAudio) && (
                  <input
                    value={voiceConfig.ttsVoice}
                    onChange={(event) => updateVoiceConfig({ ttsVoice: event.target.value.trim() })}
                    className="mt-1.5 w-full border border-[#faf]/20 bg-[#000] px-2 py-1.5 text-[#faf] font-mono text-xs outline-none"
                    placeholder={ttsIsFishAudio ? "Cole um reference_id do Fish Audio" : "Cole qualquer Voice ID"}
                  />
                )}
                {(ttsIsElevenLabs || ttsIsFishAudio) && voiceConfig.ttsVoice && (
                  <div className="mt-1.5 flex gap-2">
                    <input
                      value={ttsVoiceName}
                      onChange={(event) => setTtsVoiceName(event.target.value)}
                      className="min-w-0 flex-1 border border-[#faf]/20 bg-[#000] px-2 py-1.5 text-[#faf] text-xs outline-none"
                      placeholder="Nome da voz, ex.: Hana principal"
                      maxLength={80}
                    />
                    <button
                      type="button"
                      onClick={() => void saveTtsVoiceName()}
                      className="border border-[#faf]/30 px-3 py-1.5 text-[#faf]/80 text-[10px] uppercase hover:bg-[#faf]/10"
                    >
                      Salvar nome
                    </button>
                  </div>
                )}
              </div>

              <label className="block">
                <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Idioma TTS</span>
                <select value={voiceConfig.ttsLanguage} onChange={(event) => updateVoiceConfig({ ttsLanguage: event.target.value })} className="w-full border border-[#faf]/20 bg-[#000] px-2 py-1.5 text-[#faf] font-mono text-xs outline-none">
                  {LANGUAGE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </label>

              {ttsUsesSpeed && (
                <label className="block">
                  <span className="mb-1 block text-[#0ff]/60 text-[10px] uppercase tracking-wider">Velocidade TTS</span>
                  <input type="range" min="0.75" max="1.35" step="0.01" value={voiceConfig.ttsSpeed} onChange={(event) => updateVoiceConfig({ ttsSpeed: Number(event.target.value) })} className="w-full accent-[#0ff]" />
                  <span className="text-[#0ff]/40 text-[10px]">{voiceConfig.ttsSpeed.toFixed(2)}x</span>
                </label>
              )}

              {ttsUsesPitch && (
                <label className="block">
                  <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Pitch TTS</span>
                  <input type="range" min="-20" max="20" step="1" value={voiceConfig.ttsPitch} onChange={(event) => updateVoiceConfig({ ttsPitch: Number(event.target.value) })} className="w-full accent-[#faf]" />
                  <span className="text-[#faf]/40 text-[10px]">{voiceConfig.ttsPitch.toFixed(0)} semitons</span>
                </label>
              )}

              <label className="block">
                <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Volume TTS</span>
                <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsVolume} onChange={(event) => updateVoiceConfig({ ttsVolume: Number(event.target.value) })} className="w-full accent-[#faf]" />
                <span className="text-[#faf] font-mono text-[10px]">{Math.round(voiceConfig.ttsVolume * 100)}%</span>
              </label>

              {ttsIsElevenLabs && (
                <div className="grid gap-3 border border-[#faf]/15 p-3 md:col-span-2 md:grid-cols-2">
                  <label className="block">
                    <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Estabilidade</span>
                    <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsStability} onChange={(event) => updateVoiceConfig({ ttsStability: Number(event.target.value) })} className="w-full accent-[#faf]" />
                    <span className="text-[#faf] font-mono text-[10px]">{voiceConfig.ttsStability.toFixed(2)}</span>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[#0ff]/60 text-[10px] uppercase tracking-wider">Similaridade</span>
                    <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsSimilarity} onChange={(event) => updateVoiceConfig({ ttsSimilarity: Number(event.target.value) })} className="w-full accent-[#0ff]" />
                    <span className="text-[#0ff] font-mono text-[10px]">{voiceConfig.ttsSimilarity.toFixed(2)}</span>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[#f0f]/60 text-[10px] uppercase tracking-wider">Estilo</span>
                    <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsStyle} onChange={(event) => updateVoiceConfig({ ttsStyle: Number(event.target.value) })} className="w-full accent-[#f0f]" />
                    <span className="text-[#f0f] font-mono text-[10px]">{voiceConfig.ttsStyle.toFixed(2)}</span>
                  </label>
                  <label className="flex items-center justify-between gap-3 border border-[#0f0]/15 px-2 py-1.5">
                    <span className="text-[#0f0]/60 text-[10px] uppercase tracking-wider">Speaker boost</span>
                    <input type="checkbox" checked={voiceConfig.ttsSpeakerBoost} onChange={(event) => updateVoiceConfig({ ttsSpeakerBoost: event.target.checked })} className="h-3.5 w-3.5 accent-[#faf]" />
                  </label>
                </div>
              )}

              <label className="flex items-center justify-between gap-3 border border-[#f0f]/20 px-3 py-2 md:col-span-2">
                <span>
                  <span className="block text-[#f0f] text-[10px] uppercase tracking-wider">Modo Call (ouvir o grupo)</span>
                  <span className="text-[#0f0]/40 text-[10px]">Para quando a Hana ouve a call com varias pessoas. Ela age como participante do grupo.</span>
                </span>
                <input type="checkbox" checked={Boolean(voiceConfig.callMode)} onChange={(event) => updateVoiceConfig({ callMode: event.target.checked })} className="h-3.5 w-3.5 accent-[#f0f]" />
              </label>

              {ttsCanStream && voiceConfig.ttsProvider === "fishaudio" && (
                <label className="block border border-[#0f0]/15 px-3 py-2 md:col-span-2">
                  <span className="mb-1 block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Streaming Fish Audio</span>
                  <select
                    value={voiceConfig.ttsStreamingMode || (voiceConfig.ttsStreaming ? "sentences" : "off")}
                    onChange={(event) => {
                      const mode = event.target.value as "off" | "sentences" | "audio";
                      void updateVoiceConfig({ ttsStreamingMode: mode, ttsStreaming: mode !== "off" });
                    }}
                    className="w-full border border-[#0f0]/20 bg-[#000] px-2 py-1.5 text-[#0f0] font-mono text-xs outline-none"
                  >
                    <option value="off">Desligado — espera o áudio completo</option>
                    <option value="audio">Somente áudio — uma fala contínua</option>
                    <option value="sentences">Frase a frase — começa antes</option>
                  </select>
                  <span className="mt-1 block text-[#0f0]/35 text-[10px]">
                    Somente áudio espera a LLM terminar, mas toca enquanto o Fish ainda gera a fala.
                  </span>
                </label>
              )}

              {ttsCanStream && voiceConfig.ttsProvider !== "fishaudio" && (
                <label className="flex items-center justify-between gap-3 border border-[#0f0]/15 px-3 py-2 md:col-span-2">
                  <span>
                    <span className="block text-[#0f0]/60 text-[10px] uppercase tracking-wider">Streaming TTS</span>
                    <span className="text-[#0f0]/25 text-[10px]">Começa a tocar enquanto o provider ainda envia o restante do áudio.</span>
                  </span>
                  <input type="checkbox" checked={Boolean(voiceConfig.ttsStreaming)} onChange={(event) => updateVoiceConfig({ ttsStreaming: event.target.checked })} className="h-3.5 w-3.5 accent-[#0ff]" />
                </label>
              )}

              {voiceConfig.ttsProvider === "gemini_tts" && (
                <label className="block md:col-span-2">
                  <span className="mb-1 block text-[#faf]/60 text-[10px] uppercase tracking-wider">Prompt de atuacao Gemini TTS</span>
                  <textarea
                    value={voiceConfig.ttsPrompt || ""}
                    onChange={(event) => updateVoiceConfig({ ttsPrompt: event.target.value })}
                    className="min-h-[120px] w-full resize-y border border-[#faf]/20 bg-[#000] px-2 py-1.5 text-[#faf] font-mono text-xs outline-none"
                    placeholder="Tone, pace, accent and acting instructions."
                  />
                </label>
              )}

              <div className="border border-[#0f0]/15 p-3 md:col-span-2">
                <div className="mb-1 text-[#0f0]/60 text-[10px] uppercase tracking-wider">Runtime</div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[#0f0] text-[10px] font-mono">
                  <span>state={runtimeStatus?.state || "idle"}</span>
                  <span>running={runtimeStatus?.running ? "yes" : "no"}</span>
                  <span>stt={connections?.stt ? "on" : "off"}</span>
                  <span>tts={connections?.tts ? "on" : "off"}</span>
                </div>
                {runtimeStatus?.error && <div className="mt-1.5 text-[#f44] text-[10px]">error={runtimeStatus.error}</div>}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-[#0f0]/15 px-4 py-2 font-mono text-[10px]">
              <button onClick={refreshAudioDevices} className="px-2 py-1 text-[#0f0]/50 hover:text-[#0f0]">
                <RefreshCw size={12} /> atualizar microfones
              </button>
              {recordingState === "recording" ? (
                <button onClick={stopSttRecording} className="border border-[#f44]/40 px-2 py-1 text-[#f44] font-bold uppercase hover:border-[#f44]">
                  <Square size={12} /> parar STT {recordingElapsedSeconds}s
                </button>
              ) : (
                <button
                  onClick={() => startSttRecording({ source: "manual" })}
                  disabled={recordingState === "processing"}
                  className="border border-[#0f0]/30 px-2 py-1 text-[#0f0] font-bold uppercase hover:border-[#0f0] disabled:opacity-30"
                >
                  {recordingState === "processing" ? <Loader2 size={12} className="animate-spin" /> : <Mic size={12} />} testar STT
                </button>
              )}
              <button onClick={testTts} className="border border-[#faf]/30 px-2 py-1 text-[#faf] font-bold uppercase hover:border-[#faf]">
                <Volume2 size={12} /> testar TTS
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

