import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Copy,
  Eye,
  Loader2,
  Mic,
  RefreshCw,
  Send,
  Settings,
  Square,
  SquareTerminal,
  Trash2,
  Volume2,
  Wrench,
  X,
} from "lucide-react";
import { ApiController } from "../../controllers/api";
import { ConnectionsConfig, TerminalAgentEvent, TerminalAgentEventKind, VoiceConfig, VoiceInputDevice, VoiceProviderSpec, VoiceRuntimeStatus } from "../../models/types";
import { DEFAULT_VOICE_CONFIG } from "../../api/config";
import { CatalogPicker, CatalogPickerOption } from "../components/shared/CatalogPicker";
import { readRememberedVoices, rememberVoice } from "../../models/voiceMemory";

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
  { id: "edge", label: "Edge TTS", status: "active" },
  { id: "gemini_tts", label: "Gemini API TTS", status: "active" },
  { id: "google_cloud_tts", label: "Google Cloud TTS", status: "active" },
  { id: "elevenlabs", label: "ElevenLabs TTS", status: "active" },
  { id: "fishaudio", label: "Fish Audio TTS", status: "active" },
];

const GEMINI_TTS_VOICES = [
  { value: "Zephyr", label: "Zephyr - bright" },
  { value: "Puck", label: "Puck - upbeat" },
  { value: "Charon", label: "Charon - informative" },
  { value: "Kore", label: "Kore - firm" },
  { value: "Fenrir", label: "Fenrir - excitable" },
  { value: "Leda", label: "Leda - youthful" },
  { value: "Orus", label: "Orus - firm" },
  { value: "Aoede", label: "Aoede - breezy" },
  { value: "Callirrhoe", label: "Callirrhoe - easy-going" },
  { value: "Autonoe", label: "Autonoe - bright" },
  { value: "Enceladus", label: "Enceladus - breathy" },
  { value: "Iapetus", label: "Iapetus - clear" },
  { value: "Umbriel", label: "Umbriel - easy-going" },
  { value: "Algieba", label: "Algieba - smooth" },
  { value: "Despina", label: "Despina - smooth" },
  { value: "Erinome", label: "Erinome - clear" },
  { value: "Algenib", label: "Algenib - gravelly" },
  { value: "Rasalgethi", label: "Rasalgethi - informative" },
  { value: "Laomedeia", label: "Laomedeia - upbeat" },
  { value: "Achernar", label: "Achernar - soft" },
  { value: "Alnilam", label: "Alnilam - firm" },
  { value: "Schedar", label: "Schedar - even" },
  { value: "Gacrux", label: "Gacrux - mature" },
  { value: "Pulcherrima", label: "Pulcherrima - forward" },
  { value: "Achird", label: "Achird - friendly" },
  { value: "Zubenelgenubi", label: "Zubenelgenubi - casual" },
  { value: "Vindemiatrix", label: "Vindemiatrix - gentle" },
  { value: "Sadachbia", label: "Sadachbia - lively" },
  { value: "Sadaltager", label: "Sadaltager - knowledgeable" },
  { value: "Sulafat", label: "Sulafat - warm" },
];

const FALLBACK_TTS_VOICES_BY_PROVIDER: Record<string, { value: string; label: string }[]> = {
  edge: [
    { value: "pt-BR-FranciscaNeural", label: "Edge Francisca" },
    { value: "pt-BR-AntonioNeural", label: "Edge Antonio" },
    { value: "pt-BR-ThalitaNeural", label: "Edge Thalita" },
    { value: "pt-PT-RaquelNeural", label: "Edge Raquel" },
    { value: "pt-PT-DuarteNeural", label: "Edge Duarte" },
  ],
  gemini_tts: GEMINI_TTS_VOICES,
  google_cloud_tts: [
    { value: "pt-BR-Neural2-C", label: "Google Cloud Neural2 C" },
    { value: "pt-BR-Neural2-A", label: "Google Cloud Neural2 A" },
    { value: "pt-BR-Wavenet-A", label: "Google Cloud Wavenet A" },
    { value: "pt-BR-Standard-A", label: "Google Cloud Standard A" },
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
  user_speech: "Operador",
  user_text: "Operador",
  assistant_thought: "Hana",
  tool_call: "Tool call",
  tool_result: "Tool result",
  assistant_text: "Hana",
  assistant_speech: "Hana/TTS",
  error: "Erro",
  system: "Sistema",
};

type EventLane = "user" | "assistant" | "system";

const HIGHLIGHT_PATTERN = /(Operador|Hana|tts|stt|backend|runtime|whisper|Google Cloud TTS|Groq Whisper|erro|falha|failed|success|online|offline|speaking|recording|transcribed)/i;

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

// Builds the bubble container style for each side of the conversation.
function eventBubbleClass(event: TerminalAgentEvent) {
  const lane = eventLane(event);
  if (event.kind === "error") {
    return "ml-auto border-red-400/40 bg-red-950/45 text-red-50";
  }
  if (lane === "user") {
    return "ml-auto border-cyan-400/30 bg-cyan-950/30 text-cyan-50";
  }
  if (lane === "assistant") {
    return "mr-auto border-fuchsia-400/30 bg-fuchsia-950/25 text-fuchsia-50";
  }
  if (event.kind === "tool_call" || event.kind === "tool_result" || event.kind === "tool") {
    return "mx-auto border-amber-400/25 bg-amber-950/15 text-amber-50";
  }
  return "mx-auto border-zinc-800 bg-zinc-900/40 text-zinc-200";
}

// Colors the compact role chip independently from the full message tone.
function eventChipClass(event: TerminalAgentEvent) {
  const lane = eventLane(event);
  if (event.kind === "error") return "border-red-400/40 bg-red-500/10 text-red-200";
  if (lane === "user") return "border-cyan-300/40 bg-cyan-400/10 text-cyan-100";
  if (lane === "assistant") return "border-fuchsia-300/40 bg-fuchsia-400/10 text-fuchsia-100";
  if (event.kind === "tool_call" || event.kind === "tool_result" || event.kind === "tool") return "border-amber-300/40 bg-amber-400/10 text-amber-100";
  return "border-zinc-600 bg-zinc-800/70 text-zinc-200";
}

// Highlights important terminal tokens while preserving plain copied text elsewhere.
function highlightedText(text: string, baseClass = "") {
  return String(text || "").split(HIGHLIGHT_PATTERN).map((part, index) => {
    if (!part) return null;
    if (!HIGHLIGHT_PATTERN.test(part)) return <span key={`${part}-${index}`}>{part}</span>;
    const lower = part.toLowerCase();
    const color =
      lower.includes("erro") || lower.includes("falha") || lower.includes("failed")
        ? "text-red-200 font-black"
        : lower.includes("hana")
          ? "text-fuchsia-200 font-black"
          : lower.includes("nakamura")
            ? "text-cyan-200 font-black"
            : lower.includes("online") || lower.includes("success")
              ? "text-emerald-200 font-black"
              : "text-amber-100 font-bold";
    return <span key={`${part}-${index}`} className={`${baseClass} ${color}`}>{part}</span>;
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

interface AnimatedTerminalTextProps {
  text: string;
  active: boolean;
  onComplete: () => void;
}

// Reveals a newly arrived assistant event without changing the backend event log.
function AnimatedTerminalText({ text, active, onComplete }: AnimatedTerminalTextProps) {
  const [visibleLength, setVisibleLength] = useState(active ? 0 : text.length);
  const onCompleteRef = useRef(onComplete);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    if (!active) {
      setVisibleLength(text.length);
      return;
    }
    setVisibleLength(0);
    const timer = window.setInterval(() => {
      setVisibleLength((current) => {
        const remaining = text.length - current;
        const step = remaining > 300 ? 3 : remaining > 100 ? 2 : 1;
        const next = Math.min(text.length, current + step);
        if (next >= text.length) {
          window.clearInterval(timer);
          window.setTimeout(() => onCompleteRef.current(), 0);
        }
        return next;
      });
    }, 30);
    return () => window.clearInterval(timer);
  }, [active, text]);

  return <>{highlightedText(text.slice(0, visibleLength))}</>;
}

interface EventRowProps {
  event: TerminalAgentEvent;
  streaming: boolean;
  onStreamComplete: (id: string) => void;
  onCancelJob: (jobId: string) => void;
}

// One memoized event bubble. The 2s poll used to re-render ALL bubbles (each one
// re-running the highlight regex); with memo only NEW/changed events paint.
const EventRow = memo(function EventRow({ event, streaming, onStreamComplete, onCancelJob }: EventRowProps) {
  const lane = eventLane(event);
  const model = metadataText(event, "model");
  const emotion = metadataText(event, "emotion");
  const vision = metadataText(event, "vision");
  const operation = eventOperation(event);
  const jobId = eventJobId(event);
  const canCancelJob = canCancelEventJob(event);
  const isSystemLane = lane === "system";

  return (
    <div className={`group mb-2.5 flex ${lane === "user" ? "justify-end" : lane === "assistant" ? "justify-start" : "justify-center"}`}>
      <div className={`relative max-w-[min(760px,86%)] rounded-xl border px-4 py-2.5 ${isSystemLane ? "w-fit min-w-[300px]" : "min-w-[260px]"} ${eventBubbleClass(event)}`}>
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.18em] ${eventChipClass(event)}`}>
            {lane === "user" ? <Mic size={11} /> : lane === "assistant" ? <Bot size={11} /> : event.kind === "error" ? <AlertTriangle size={11} /> : <SquareTerminal size={11} />}
            {EVENT_LABELS[event.kind] || event.kind}
          </span>
          <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">{formatTime(event.createdAt)}</span>
          <span className="rounded bg-black/25 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-zinc-400">op={operation}</span>
          {event.kind === "tool_result" && <span className="inline-flex items-center gap-1 rounded bg-emerald-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-emerald-200"><CheckCircle2 size={11} /> result</span>}
          {event.kind === "error" && <span className="inline-flex items-center gap-1 rounded bg-red-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-red-200"><AlertTriangle size={11} /> alert</span>}
          <div className="ml-auto flex items-center gap-2">
            {canCancelJob && jobId && (
              <button className="opacity-0 transition-opacity group-hover:opacity-100 text-red-300 hover:text-red-100" onClick={() => onCancelJob(jobId)} title="Cancelar job">
                <Square size={14} />
              </button>
            )}
            <button className="opacity-0 transition-opacity group-hover:opacity-100 text-zinc-500 hover:text-white" onClick={() => void copyText(serializeEvent(event))} title="Copiar linha">
              <Copy size={14} />
            </button>
          </div>
        </div>

        {(model || emotion || vision || event.toolName) && (
          <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] uppercase tracking-widest text-zinc-500">
            {model && <span>model=<span className="text-indigo-200">{model}</span></span>}
            {emotion && <span className="inline-flex items-center gap-1"><BrainCircuit size={11} /> emotion=<span className="text-fuchsia-200">{emotion}</span></span>}
            {vision && <span className="inline-flex items-center gap-1"><Eye size={11} /> vision=<span className="text-cyan-200">{vision}</span></span>}
            {event.toolName && <span className="inline-flex items-center gap-1"><Wrench size={11} /> tool=<span className="text-amber-100">{event.toolName}</span></span>}
          </div>
        )}

        <pre className={`whitespace-pre-wrap break-words font-semibold leading-relaxed ${lane === "user" ? "text-right text-[13px] text-cyan-50" : lane === "assistant" ? "text-left text-[14px] text-fuchsia-50 md:text-[15px]" : "text-left text-[12px] text-zinc-200"}`}>
          {event.kind === "assistant_text" ? (
            <AnimatedTerminalText
              text={event.displayText}
              active={streaming}
              onComplete={() => onStreamComplete(event.id)}
            />
          ) : highlightedText(event.displayText)}
        </pre>
        {event.speechText && event.speechText !== event.displayText && (
          <pre className={`mt-2 whitespace-pre-wrap break-words border-t pt-2 font-semibold leading-relaxed ${lane === "user" ? "border-cyan-300/20 text-[11px] text-cyan-200" : lane === "assistant" ? "border-pink-300/20 text-[13px] text-pink-200" : "border-pink-300/20 text-[11px] text-pink-200"}`}>
            <span className="font-black text-pink-100">tts&gt;</span> {highlightedText(event.speechText)}
          </pre>
        )}
      </div>
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
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [streamingEventId, setStreamingEventId] = useState<string | null>(null);

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
  const eventIdsRef = useRef(new Set<string>());
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
    return collapsed.slice(-MAX_VISIBLE_EVENTS);
  }, [events]);
  const sttOptions = providerOptions(sttProviders, FALLBACK_STT_OPTIONS);
  const ttsOptions = providerOptions(ttsProviders, FALLBACK_TTS_OPTIONS);
  const activeSttProvider = sttOptions.find((item) => item.id === voiceConfig.sttProvider);
  const activeTtsProvider = ttsOptions.find((item) => item.id === voiceConfig.ttsProvider);
  const ttsUsesSpeed = voiceConfig.ttsProvider !== "gemini_tts";
  const ttsUsesPitch = !["gemini_tts", "cartesia", "elevenlabs", "fishaudio"].includes(voiceConfig.ttsProvider);
  const ttsCanStream = ["google_cloud_tts", "fishaudio"].includes(voiceConfig.ttsProvider);
  const ttsIsElevenLabs = voiceConfig.ttsProvider === "elevenlabs";
  const ttsIsFishAudio = voiceConfig.ttsProvider === "fishaudio";
  const [rememberedVoices, setRememberedVoices] = useState<string[]>([]);
  useEffect(() => {
    setRememberedVoices(readRememberedVoices(voiceConfig.ttsProvider || ""));
  }, [voiceConfig.ttsProvider]);
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
        badges: [{ label: "custom", tone: "purple" }],
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
        badges: [{ label: "custom", tone: "purple" }],
      });
    }
    return options;
  }, [activeTtsProvider, voiceConfig.ttsModel, voiceConfig.ttsProvider]);
  const ttsVoiceOptions = useMemo<CatalogPickerOption[]>(() => {
    const merged = new Map<string, CatalogPickerOption>();
    merged.set("", {
      value: "",
      label: "Padrao do provider",
      favoriteId: `${voiceConfig.ttsProvider}:default-voice`,
    });
    const fallback = FALLBACK_TTS_VOICES_BY_PROVIDER[voiceConfig.ttsProvider] || [];
    fallback.forEach((item) => merged.set(item.value, {
      ...item,
      favoriteId: `${voiceConfig.ttsProvider}:${item.value}`,
      secondary: item.value,
    }));
    activeTtsProvider?.voices?.forEach((voice) => merged.set(voice.id, {
      value: voice.id,
      label: voice.label || voice.id,
      favoriteId: `${voiceConfig.ttsProvider}:${voice.id}`,
      secondary: [voice.id, voice.locale].filter(Boolean).join(" - "),
    }));
    // Vozes que o usuario ja colou antes (persistidas), pra nao re-copiar do ElevenLabs.
    rememberedVoices.forEach((id) => {
      if (id && !merged.has(id)) {
        merged.set(id, {
          value: id,
          label: id,
          favoriteId: `${voiceConfig.ttsProvider}:${id}`,
          secondary: id,
          badges: [{ label: "salva", tone: "purple" }],
        });
      }
    });
    if (voiceConfig.ttsVoice && !merged.has(voiceConfig.ttsVoice)) {
      merged.set(voiceConfig.ttsVoice, {
        value: voiceConfig.ttsVoice,
        label: `${voiceConfig.ttsVoice} (custom)`,
        favoriteId: `${voiceConfig.ttsProvider}:${voiceConfig.ttsVoice}`,
        badges: [{ label: "custom", tone: "purple" }],
      });
    }
    return Array.from(merged.values());
  }, [activeTtsProvider, voiceConfig.ttsProvider, voiceConfig.ttsVoice, rememberedVoices]);

  const loadEvents = async () => {
    const data = await ApiController.getTerminalAgentEvents(MAX_VISIBLE_EVENTS);
    setBackendState(data.backendAvailable === false ? "offline" : "online");
    const nextEvents = data.events || [];
    // Nada mudou desde o último poll → não recria o array (evita re-render de
    // todas as bolhas a cada 2s, que era o que deixava a aba pesada).
    const signature = `${nextEvents.length}:${nextEvents[nextEvents.length - 1]?.id || ""}`;
    if (loadedEventsRef.current && signature === eventsSignatureRef.current) return;

    // Carga inicial (1º load, reload da página ou volta pra aba) NUNCA anima: a
    // resposta já é histórica. Só anima quando um assistant_text NOVO chega num
    // poll posterior, em tempo real. Snapshot dos ids ANTES de atualizar evita a
    // corrida que fazia a animação "re-tocar" sozinha no reload.
    const isInitialLoad = !loadedEventsRef.current;
    const previousIds = eventIdsRef.current;
    eventsSignatureRef.current = signature;
    eventIdsRef.current = new Set(nextEvents.map((event) => event.id));
    loadedEventsRef.current = true;

    if (!isInitialLoad) {
      const newestAssistant = [...nextEvents]
        .reverse()
        .find((event) => event.kind === "assistant_text" && !previousIds.has(event.id));
      if (newestAssistant) setStreamingEventId(newestAssistant.id);
    }
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
    Promise.all([ApiController.getVoiceConfig(), ApiController.getVoiceCatalog(), ApiController.getConnectionsConfig()])
      .then(([config, catalog, connectionsConfig]) => {
        setVoiceConfig(config);
        setSttProviders(catalog?.sttProviders || []);
        setTtsProviders(catalog?.ttsProviders || []);
        setConnections(connectionsConfig);
      })
      .catch(() => setStatus("Backend indisponivel. Usando cache local."));
    void loadEvents();
    void refreshAudioDevices();
    void refreshOutputDevices();
    void loadRuntimeStatus();

    const timer = window.setInterval(loadEvents, 2000);
    const configTimer = window.setInterval(() => {
      Promise.all([ApiController.getVoiceConfig(), ApiController.getConnectionsConfig(), loadRuntimeStatus()])
        .then(([config, connectionsConfig]) => {
          setVoiceConfig(config);
          setConnections(connectionsConfig);
        })
        .catch(() => undefined);
    }, 2000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(configTimer);
    };
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

  // Keeps provider-specific TTS defaults valid when switching between providers.
  const updateTtsProvider = (provider: string) => {
    if (provider === "gemini_tts") {
      void updateVoiceConfig({ ttsProvider: provider, ttsModel: "gemini-3.1-flash-tts-preview", ttsVoice: "Kore", ttsStreaming: false });
      return;
    }
    if (provider === "google_cloud_tts") {
      void updateVoiceConfig({ ttsProvider: provider, ttsModel: "", ttsVoice: "pt-BR-Neural2-C", ttsLanguage: "pt-BR", ttsSpeed: 1, ttsPitch: 0 });
      return;
    }
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
  const handleStreamComplete = useCallback((id: string) => {
    setStreamingEventId((current) => (current === id ? null : current));
  }, []);

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
        displayText: "Microfone aberto. Hana esta ouvindo Operador.",
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
    const text = sanitizedPreview || draft.trim() || "Oi Operador, teste de voz da Hana.";
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
    <div className="w-full h-full overflow-hidden bg-[#050608] shadow-2xl relative flex flex-col">
      {/* Cabeçalho + status FLUTUANTES: não reservam espaço, ficam por cima das
          mensagens (que ocupam a tela toda). pointer-events-none deixa o scroll
          passar por baixo; só os botões capturam clique. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 px-4 pt-3">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 font-mono text-lg font-black uppercase tracking-widest text-zinc-100">
              <SquareTerminal size={20} className="text-slate-300" /> Terminal Agente
            </h2>
          </div>

          <div className="pointer-events-auto flex flex-wrap items-center gap-2">
            <button onClick={loadEvents} className="inline-flex h-9 items-center gap-2 rounded-full bg-zinc-800/70 px-4 font-mono text-[11px] font-bold uppercase tracking-widest text-zinc-200 hover:bg-zinc-700/70">
              <RefreshCw size={14} /> Atualizar
            </button>
            <button onClick={stopTts} className="inline-flex h-9 items-center gap-2 rounded-full bg-pink-950/60 px-4 font-mono text-[11px] font-bold uppercase tracking-widest text-pink-100 hover:bg-pink-900/60">
              <Volume2 size={14} /> Parar fala
            </button>
            <button onClick={() => setSettingsOpen(true)} className="inline-flex h-9 items-center gap-2 rounded-full bg-zinc-800/70 px-4 font-mono text-[11px] font-bold uppercase tracking-widest text-zinc-200 hover:bg-zinc-700/70">
              <Settings size={14} /> Config
            </button>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center justify-end gap-1.5 font-mono text-[10px] text-zinc-400 opacity-80">
          {backendState === "offline" && <span className="rounded-full bg-red-950/60 px-2.5 py-1 text-red-300">offline</span>}
          {status && <span className="rounded-full bg-zinc-800/60 px-2.5 py-1 text-cyan-300">{status}</span>}
          <span className={`rounded-full bg-zinc-800/60 px-2.5 py-1 ${connections?.tts ? "text-pink-300" : "text-zinc-500"}`}>tts={connections?.tts ? "on" : "off"}</span>
          <span className={`rounded-full bg-zinc-800/60 px-2.5 py-1 ${connections?.visao ? "text-emerald-300" : "text-zinc-500"}`}>vision={connections?.visao ? "on" : "off"}</span>
          <button onClick={copyVisibleLog} className="pointer-events-auto inline-flex items-center gap-1 rounded-full bg-zinc-800/60 px-2.5 py-1 text-zinc-300 hover:text-white">
            <Copy size={13} /> copiar log
          </button>
          <button onClick={clearEvents} className="pointer-events-auto inline-flex items-center gap-1 rounded-full bg-zinc-800/60 px-2.5 py-1 text-red-300 hover:text-red-100">
            <Trash2 size={13} /> limpar
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={handleTerminalScroll}
        onWheel={handleTerminalWheel}
        onPointerDown={() => { manualScrollRef.current = true; }}
        onPointerUp={() => { manualScrollRef.current = false; }}
        onPointerCancel={() => { manualScrollRef.current = false; }}
        className="h-full overflow-y-auto custom-scrollbar bg-[#050608] p-4 font-mono text-[12px]"
      >
        <div ref={contentRef} className="mx-auto w-full max-w-5xl pt-16">
        {visibleEvents.length === 0 ? (
          <div className="flex h-full min-h-[320px] items-center justify-center text-zinc-500">
            <span className="border border-dashed border-zinc-700 px-4 py-2">terminal pronto: aguardando voz, tool calls e respostas</span>
          </div>
        ) : visibleEvents.map((event) => (
          <EventRow
            key={event.id}
            event={event}
            streaming={streamingEventId === event.id}
            onStreamComplete={handleStreamComplete}
            onCancelJob={handleCancelJob}
          />
        ))}
        </div>
      </div>
      {showScrollToBottom && (
        <button
          type="button"
          onClick={scrollTerminalToLatest}
          className="absolute bottom-5 right-5 z-40 flex h-11 items-center gap-2 rounded-full border border-cyan-300/40 bg-[#071217]/95 px-3 text-cyan-200 shadow-[0_0_22px_rgba(34,211,238,0.22)] backdrop-blur-md transition-all hover:scale-105 hover:bg-[#0b2028]"
          title="Ir para o evento mais recente"
          aria-label="Ir para o evento mais recente"
        >
          <ChevronDown size={18} />
          <span className="text-[10px] font-black uppercase tracking-widest">Mais recente</span>
        </button>
      )}
      </div>

      <div className="p-3">
        <div className="relative mx-auto w-full max-w-3xl">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) appendCommand();
            }}
            className="h-[76px] w-full resize-none rounded-2xl border border-zinc-700 bg-[#050608] py-3 pl-4 pr-14 font-mono text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-cyan-400/70"
            placeholder="nakamura> comando manual..."
          />
          <button
            onClick={appendCommand}
            disabled={!draft.trim()}
            title="Enviar"
            aria-label="Enviar"
            className="absolute bottom-3 right-3 flex h-10 w-10 items-center justify-center rounded-xl text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-30"
          >
            <Send size={18} />
          </button>
        </div>
      </div>

      {settingsOpen && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="flex h-full max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-zinc-700 bg-[#080a0e] shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
              <h3 className="font-mono text-sm font-black uppercase tracking-widest text-zinc-100">Configuracao do Terminal</h3>
              <button onClick={() => setSettingsOpen(false)} className="text-zinc-500 hover:text-white" title="Fechar">
                <X size={18} />
              </button>
            </div>

            <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 font-mono text-xs text-zinc-300 custom-scrollbar md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">STT provider</span>
                <select value={voiceConfig.sttProvider} onChange={(event) => updateVoiceConfig({ sttProvider: event.target.value })} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none">
                  {sttOptions.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.status})</option>)}
                </select>
              </label>

              <div className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">STT modelo</span>
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
                  <input value={voiceConfig.sttModel} onChange={(event) => updateVoiceConfig({ sttModel: event.target.value })} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none" placeholder="whisper-large-v3" />
                )}
              </div>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Idioma STT</span>
                <select value={voiceConfig.sttLanguage} onChange={(event) => updateVoiceConfig({ sttLanguage: event.target.value })} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none">
                  {LANGUAGE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Microfone</span>
                <select value={selectedAudioDeviceId} onChange={(event) => updateAudioDevice(event.target.value)} onFocus={refreshAudioDevices} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none">
                  <option value="">Dispositivo padrao do backend</option>
                  {audioDevices.map((device, index) => (
                    <option key={device.id || index} value={device.id}>{device.label || `Microfone ${index + 1}`} [{device.source}]</option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 flex items-center justify-between uppercase tracking-widest text-zinc-500">
                  Segunda saida de audio
                  <input
                    type="checkbox"
                    checked={!!voiceConfig.secondOutputEnabled}
                    onChange={(event) => updateSecondOutput({ secondOutputEnabled: event.target.checked })}
                    onFocus={refreshOutputDevices}
                    className="h-4 w-4 accent-cyan-500"
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
                  className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none disabled:opacity-40"
                >
                  <option value="">Selecione a saida (ex.: CABLE Input)</option>
                  {outputDevices.map((device, index) => (
                    <option key={device.id || index} value={device.id}>{device.label || `Saida ${index + 1}`}</option>
                  ))}
                </select>
                <span className="text-zinc-600">A voz toca no PC e tambem nesse dispositivo (cabo virtual p/ Discord, VTube etc.). Ligue so quando quiser.</span>
              </label>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Modo VAD</span>
                <select value={voiceConfig.vadMode || "silero"} onChange={(event) => updateVoiceConfig({ vadMode: event.target.value as "silero" | "rms" })} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none">
                  <option value="silero">Silero neural (ignora ruido)</option>
                  <option value="rms">Energia RMS (simples)</option>
                </select>
                <span className="text-zinc-600">{(voiceConfig.vadMode || "silero") === "silero" ? "Rede neural distingue voz de ruido. Cai pro RMS se o modelo faltar." : "So volume: dispara com qualquer barulho alto."}</span>
              </label>

              {(voiceConfig.vadMode || "silero") === "silero" && (
                <label className="block">
                  <span className="mb-1 block uppercase tracking-widest text-zinc-500">Sensibilidade Silero</span>
                  <input type="range" min="0.2" max="0.9" step="0.05" value={voiceConfig.vadProbThreshold ?? 0.5} onChange={(event) => updateVoiceConfig({ vadProbThreshold: Number(event.target.value) })} className="w-full accent-emerald-300" />
                  <span className="text-zinc-500">{Number(voiceConfig.vadProbThreshold ?? 0.5).toFixed(2)} — maior = exige mais certeza (menos falso gatilho)</span>
                </label>
              )}

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Threshold VAD (piso de volume)</span>
                <input type="range" min="0.005" max="0.12" step="0.001" value={voiceConfig.vadThreshold || 0.035} onChange={(event) => updateVoiceConfig({ vadThreshold: Number(event.target.value) })} className="w-full accent-emerald-300" />
                <span className="text-zinc-500">{Number(voiceConfig.vadThreshold || 0.035).toFixed(3)}</span>
              </label>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Limite de fala (TTS)</span>
                <input type="range" min="0" max="1200" step="50" value={voiceConfig.ttsMaxChars ?? 350} onChange={(event) => updateVoiceConfig({ ttsMaxChars: Number(event.target.value) })} className="w-full accent-pink-300" />
                <span className="text-zinc-500">{(voiceConfig.ttsMaxChars ?? 350) === 0 ? "sem limite" : `${voiceConfig.ttsMaxChars ?? 350} chars (corta fala longa pra economizar credito de TTS)`}</span>
              </label>

              <label className="flex items-center justify-between gap-3">
                <span className="block">
                  <span className="mb-1 block uppercase tracking-widest text-zinc-500">Barge-in (falar por cima)</span>
                  <span className="text-zinc-600">Interromper a fala da Hana falando por cima. Use de FONE (nas caixas pode cortar sozinha com o eco).</span>
                </span>
                <input type="checkbox" checked={!!voiceConfig.bargeInEnabled} onChange={(event) => updateVoiceConfig({ bargeInEnabled: event.target.checked })} className="h-5 w-5 accent-emerald-300" />
              </label>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Silencio final</span>
                <input type="range" min="300" max="1800" step="50" value={voiceConfig.silenceTimeoutMs || 900} onChange={(event) => updateVoiceConfig({ silenceTimeoutMs: Number(event.target.value) })} className="w-full accent-emerald-300" />
                <span className="text-zinc-500">{Number(voiceConfig.silenceTimeoutMs || 900)}ms</span>
              </label>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">TTS provider</span>
                <select value={voiceConfig.ttsProvider} onChange={(event) => updateTtsProvider(event.target.value)} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none">
                  {ttsOptions.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.status})</option>)}
                </select>
              </label>

              <div className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">TTS modelo</span>
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
                  <input value={voiceConfig.ttsModel} onChange={(event) => updateVoiceConfig({ ttsModel: event.target.value })} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none" placeholder="modelo do provider" />
                )}
                {ttsIsElevenLabs && (
                  <input
                    value={voiceConfig.ttsModel}
                    onChange={(event) => updateVoiceConfig({ ttsModel: event.target.value.trim() })}
                    className="mt-2 w-full rounded-md border border-cyan-400/20 bg-[#050608] px-3 py-2 font-mono text-zinc-100 outline-none focus:border-cyan-400/60"
                    placeholder="ID customizado do modelo ElevenLabs"
                  />
                )}
              </div>

              <div className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Voz</span>
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
                    onBlur={(event) => {
                      const id = event.target.value.trim();
                      if (id) setRememberedVoices(rememberVoice(voiceConfig.ttsProvider, id));
                    }}
                    className="mt-2 w-full rounded-md border border-pink-400/20 bg-[#050608] px-3 py-2 font-mono text-zinc-100 outline-none focus:border-pink-400/60"
                    placeholder={ttsIsFishAudio ? "Cole um reference_id do Fish Audio (vazio = voz padrao)" : "Cole qualquer Voice ID da sua biblioteca"}
                  />
                )}
              </div>

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Idioma TTS</span>
                <select value={voiceConfig.ttsLanguage} onChange={(event) => updateVoiceConfig({ ttsLanguage: event.target.value })} className="w-full rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none">
                  {LANGUAGE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </label>

              {ttsUsesSpeed && (
                <label className="block">
                  <span className="mb-1 block uppercase tracking-widest text-zinc-500">Velocidade TTS</span>
                  <input type="range" min="0.75" max="1.35" step="0.01" value={voiceConfig.ttsSpeed} onChange={(event) => updateVoiceConfig({ ttsSpeed: Number(event.target.value) })} className="w-full accent-cyan-300" />
                  <span className="text-zinc-500">{voiceConfig.ttsSpeed.toFixed(2)}x</span>
                </label>
              )}

              {ttsUsesPitch && (
                <label className="block">
                  <span className="mb-1 block uppercase tracking-widest text-zinc-500">Pitch TTS</span>
                  <input type="range" min="-20" max="20" step="1" value={voiceConfig.ttsPitch} onChange={(event) => updateVoiceConfig({ ttsPitch: Number(event.target.value) })} className="w-full accent-pink-300" />
                  <span className="text-zinc-500">{voiceConfig.ttsPitch.toFixed(0)} semitons</span>
                </label>
              )}

              <label className="block">
                <span className="mb-1 block uppercase tracking-widest text-zinc-500">Volume TTS</span>
                <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsVolume} onChange={(event) => updateVoiceConfig({ ttsVolume: Number(event.target.value) })} className="w-full accent-pink-300" />
                <span className="font-mono text-pink-200">{Math.round(voiceConfig.ttsVolume * 100)}%</span>
              </label>

              {ttsIsElevenLabs && (
                <div className="grid gap-4 rounded-md border border-pink-400/20 bg-[#050608] p-3 md:col-span-2 md:grid-cols-2">
                  <label className="block">
                    <span className="mb-1 block uppercase tracking-widest text-zinc-500">Estabilidade</span>
                    <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsStability} onChange={(event) => updateVoiceConfig({ ttsStability: Number(event.target.value) })} className="w-full accent-pink-300" />
                    <span className="font-mono text-pink-200">{voiceConfig.ttsStability.toFixed(2)}</span>
                  </label>
                  <label className="block">
                    <span className="mb-1 block uppercase tracking-widest text-zinc-500">Similaridade</span>
                    <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsSimilarity} onChange={(event) => updateVoiceConfig({ ttsSimilarity: Number(event.target.value) })} className="w-full accent-cyan-300" />
                    <span className="font-mono text-cyan-200">{voiceConfig.ttsSimilarity.toFixed(2)}</span>
                  </label>
                  <label className="block">
                    <span className="mb-1 block uppercase tracking-widest text-zinc-500">Estilo</span>
                    <input type="range" min="0" max="1" step="0.01" value={voiceConfig.ttsStyle} onChange={(event) => updateVoiceConfig({ ttsStyle: Number(event.target.value) })} className="w-full accent-purple-300" />
                    <span className="font-mono text-purple-200">{voiceConfig.ttsStyle.toFixed(2)}</span>
                  </label>
                  <label className="flex items-center justify-between gap-3 rounded-md border border-zinc-800 px-3 py-2">
                    <span className="uppercase tracking-widest text-zinc-500">Speaker boost</span>
                    <input type="checkbox" checked={voiceConfig.ttsSpeakerBoost} onChange={(event) => updateVoiceConfig({ ttsSpeakerBoost: event.target.checked })} className="h-4 w-4 accent-pink-300" />
                  </label>
                </div>
              )}

              <label className="flex items-center justify-between gap-3 rounded-md border border-fuchsia-500/30 bg-fuchsia-950/15 px-3 py-2 md:col-span-2">
                <span>
                  <span className="block uppercase tracking-widest text-fuchsia-300">Modo Call (ouvir o grupo)</span>
                  <span className="text-zinc-500">Para quando a Hana ouve a call (cabo virtual) com várias pessoas. Ela para de tratar todo mundo como Operador e age como participante do grupo.</span>
                </span>
                <input type="checkbox" checked={Boolean(voiceConfig.callMode)} onChange={(event) => updateVoiceConfig({ callMode: event.target.checked })} className="h-4 w-4 accent-fuchsia-300" />
              </label>

              {ttsCanStream && (
                <label className="flex items-center justify-between gap-3 rounded-md border border-zinc-800 bg-[#050608] px-3 py-2 md:col-span-2">
                  <span>
                    <span className="block uppercase tracking-widest text-zinc-500">Streaming Google Cloud TTS</span>
                    <span className="text-zinc-500">Requer ADC/service account e voz Chirp 3 HD; caso contrario usa REST MP3.</span>
                  </span>
                  <input type="checkbox" checked={Boolean(voiceConfig.ttsStreaming)} onChange={(event) => updateVoiceConfig({ ttsStreaming: event.target.checked })} className="h-4 w-4 accent-cyan-300" />
                </label>
              )}

              {voiceConfig.ttsProvider === "gemini_tts" && (
                <label className="block md:col-span-2">
                  <span className="mb-1 block uppercase tracking-widest text-zinc-500">Prompt de atuacao Gemini TTS</span>
                  <textarea
                    value={voiceConfig.ttsPrompt || ""}
                    onChange={(event) => updateVoiceConfig({ ttsPrompt: event.target.value })}
                    className="min-h-[120px] w-full resize-y rounded-md border border-zinc-700 bg-[#050608] px-3 py-2 text-zinc-100 outline-none"
                    placeholder="Tone, pace, accent and acting instructions. The backend adds the transcript separately."
                  />
                </label>
              )}



              <div className="rounded-md border border-zinc-800 bg-[#050608] p-3 md:col-span-2">
                <div className="mb-1 uppercase tracking-widest text-zinc-500">Runtime</div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-zinc-300">
                  <span>state={runtimeStatus?.state || "idle"}</span>
                  <span>running={runtimeStatus?.running ? "yes" : "no"}</span>
                  <span>stt={connections?.stt ? "on" : "off"}</span>
                  <span>tts={connections?.tts ? "on" : "off"}</span>
                </div>
                {runtimeStatus?.error && <div className="mt-2 text-red-300">error={runtimeStatus.error}</div>}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 border-t border-zinc-800 px-4 py-3 font-mono text-[11px] text-zinc-500">
              <div className="flex flex-wrap items-center gap-3">
                <button onClick={refreshAudioDevices} className="inline-flex items-center gap-2 text-zinc-300 hover:text-white">
                  <RefreshCw size={13} /> atualizar microfones
                </button>
                {recordingState === "recording" ? (
                  <button onClick={stopSttRecording} className="inline-flex items-center gap-2 rounded-md border border-red-400/50 bg-red-950/50 px-3 py-2 font-bold uppercase tracking-widest text-red-100 hover:bg-red-900/60">
                    <Square size={13} /> parar teste STT {recordingElapsedSeconds}s
                  </button>
                ) : (
                  <button
                    onClick={() => startSttRecording({ source: "manual" })}
                    disabled={recordingState === "processing"}
                    className="inline-flex items-center gap-2 rounded-md border border-emerald-400/40 bg-emerald-950/40 px-3 py-2 font-bold uppercase tracking-widest text-emerald-100 hover:bg-emerald-900/50 disabled:opacity-40"
                  >
                    {recordingState === "processing" ? <Loader2 size={13} className="animate-spin" /> : <Mic size={13} />} testar STT
                  </button>
                )}
                <button onClick={testTts} className="inline-flex items-center gap-2 rounded-md border border-pink-400/40 bg-pink-950/40 px-3 py-2 font-bold uppercase tracking-widest text-pink-100 hover:bg-pink-900/50">
                  <Volume2 size={13} /> testar TTS
                </button>

              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

