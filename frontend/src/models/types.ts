/**
 * Definições de Tipos e Modelos de Dados (Camada Model - MVC)
 */

export type SafetyMode = "safe" | "assisted" | "trusted" | "dev-unsafe";
export type AgentStage = "planning" | "waiting_permission" | "executing" | "verifying" | "success" | "failed" | "denied" | "expired";
export type NativeSearchMode = "auto" | "force" | "off";

export interface MenuOption {
  icon: React.ReactNode | string;
  label: string;
  id: string;
}

export interface ConnectionsConfig {
    tts: boolean;
    stt: boolean;
    vad: boolean;
    ptt: boolean;
  pttKey: string;
  stopHotkey: boolean;
  stopKey: string;
  discord: boolean;
  localHands: boolean;
  visao: boolean;
}

export interface SystemStatus {
  cpu: number;
  ramPercent: number;
  ramUsedStr: string;
  ramTotalStr: string;
  llmProvider: string;
  llmModel: string;
  ttsProvider: string;
  modules: {
    llm: boolean;
    tts: boolean;
    stt: boolean;
    visao: boolean;
    discord: boolean;
    localHands: boolean;
  };
}

export interface LlmConfig {
  llmProvider: string;
  llmModel: string;
  llmModelByProvider?: Record<string, string>;
  agentProvider: string;
  agentModel: string;
  agentModelByProvider?: Record<string, string>;
  agentToolRounds: number;
  llmFilter: string;
  llmTemperature: number;
  /** Groq "pensar antes de falar": true = raciocina; false = resposta direta/rápida. */
  groqThinking?: boolean;
  /** Qwen "pensar antes de falar" (modelos qwen3.x): true = raciocina; false = resposta direta/rápida. */
  qwenThinking?: boolean;
  /** Região da chave Alibaba Model Studio usada pelo provider Qwen. */
  qwenRegion?: "virginia" | "singapore";
  /** Nivel de esforco do DeepSeek: "off"/"high"/"max" (so 2 niveis reais + desligado). Vazio = padrao deles (high). */
  deepseekReasoningEffort?: string;
  /** OpenRouter "pensar antes de falar" (so pros modelos com reasoning no supportedParameters). */
  openrouterThinking?: boolean;
  /** Nivel exato de esforco no slider do OpenRouter: none/minimal/low/medium/high/max. Vazio = automatico (usa openrouterThinking). */
  openrouterReasoningEffort?: string;
  /** "Pensar" do MODELO DE AGENTE (loop de ferramentas), independente do chat. Toggle pra groq/qwen. */
  agentThinking?: boolean;
  /** Nivel de esforco do MODELO DE AGENTE (slider deepseek/openrouter). Vazio = automatico. */
  agentReasoningEffort?: string;
  openrouterRoutingByModel: Record<string, OpenRouterRoutingConfig>;
  visionModel: string;
  visionModelByProvider?: Record<string, string>;
  /** Provider dono do visionModel. Vazio = mesmo do chat. Usado pra rotear imagem quando o chat nao ve. */
  visionProvider?: string;
  ttsProvider: string;
  ttsVoice: string;
  ttsModel: string;
  ttsLanguage: string;
  ttsPrompt: string;
  ttsFilter: string;
  ttsSpeed: number;
  ttsPitch: number;
  ttsVolume: number;
  ttsStreaming: boolean;
  ttsStability: number;
  ttsSimilarity: number;
  ttsStyle: number;
  ttsSpeakerBoost: boolean;
  /** Última voz/controles usados por provider de TTS (restaurados ao voltar). */
  ttsByProvider?: Record<string, Partial<LlmConfig>>;
}

export interface ChatConfig {
  provider: string;
  model: string;
  nativeSearchMode: NativeSearchMode;
  openrouterRoutingByModel: Record<string, OpenRouterRoutingConfig>;
}

export type TtsVoiceAliases = Record<string, Record<string, string>>;
export type TtsStreamingMode = "off" | "sentences" | "audio";

export interface OpenRouterRoutingConfig {
  preferredEndpoint: string;
  allowFallbacks: boolean;
  requireParameters: boolean;
  dataCollection: "allow" | "deny";
  zdr: boolean;
}

export interface OpenRouterEndpoint {
  name: string;
  slug: string;
  providerName: string;
  status: string;
  pricing: Record<string, string>;
  contextLength?: number | null;
  maxPromptTokens?: number | null;
  maxCompletionTokens?: number | null;
  quantization: string;
  supportedParameters: string[];
  uptimeLast30m?: number | null;
  latencyLast30m?: number | null;
  throughputLast30m?: number | null;
}

export type TerminalAgentEventKind =
  | "listening"
  | "processing"
  | "speaking"
  | "transcription"
  | "response"
  | "tool"
  | "user_speech"
  | "user_text"
  | "assistant_thought"
  | "tool_call"
  | "tool_result"
  | "assistant_text"
  | "assistant_speech"
  | "error"
  | "system";

export interface TerminalAgentEvent {
  id: string;
  kind: TerminalAgentEventKind;
  source: string;
  displayText: string;
  speechText?: string;
  toolName?: string;
  status?: string;
  createdAt: string;
  metadata?: Record<string, unknown>;
}

export interface TerminalAgentEventsResponse {
  events: TerminalAgentEvent[];
  backendAvailable: boolean;
  message?: string;
}

export interface TerminalAgentStreamMessage {
  type: "delta" | "done";
  streamId: string;
  delta?: string;
}

export type AgentJobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface AgentJobProgressItem {
  at: string;
  type: string;
  message: string;
  detail?: string;
}

export interface AgentJob {
  job_id: string;
  agent: string;
  tool: string;
  mode: string;
  task: string;
  cwd?: string;
  status: AgentJobStatus;
  created_at: string;
  started_at?: string;
  updated_at?: string;
  finished_at?: string;
  duration_ms?: number | null;
  progress?: AgentJobProgressItem[];
  result?: Record<string, unknown> | null;
  error?: string | null;
  cancel_requested?: boolean;
  metadata?: Record<string, unknown>;
}

export interface AgentJobsResponse {
  ok: boolean;
  jobs: AgentJob[];
  active: AgentJob[];
}

export interface TerminalAgentTranscriptionResponse {
  text: string;
  assistantText?: string;
  responded?: boolean;
  provider?: string;
  model?: string;
  language?: string;
  durationMs?: number;
  raw?: unknown;
}

export interface TerminalAgentTextResponse {
  ok: boolean;
  text: string;
  assistantText: string;
  responded: boolean;
  assistant?: unknown;
}

export interface TerminalAgentSpeechResponse {
  ok: boolean;
  provider: string;
  voice: string;
  text: string;
  mimeType: string;
  audioBase64: string;
  durationMs?: number;
}

export interface VoiceRuntimeStatus {
  running: boolean;
  state: "idle" | "listening" | "recording" | "transcribing" | "thinking" | "speaking" | "error" | string;
  error?: string;
  startedAt?: number;
  updatedAt?: number;
  turns?: number;
  lastTranscript?: string;
  lastResponse?: string;
  config?: Record<string, unknown>;
}

export interface VoiceInputDevice {
  id: string;
  label: string;
  source: string;
  isDefault?: boolean;
  available?: boolean;
  channels?: number | null;
  sampleRate?: number | null;
}

export interface VoiceConfig {
  sttEnabled: boolean;
  sttProvider: string;
  sttModel: string;
  sttLanguage: string;
  inputDeviceId?: string;
  inputDeviceLabel?: string;
  inputDeviceSource?: string;
  secondOutputEnabled?: boolean;
  secondOutputDeviceId?: string;
  secondOutputDeviceLabel?: string;
  vadThreshold?: number;
  vadMode?: "silero" | "rms";
  vadProbThreshold?: number;
  bargeInEnabled?: boolean;
  silenceTimeoutMs?: number;
  ttsEnabled: boolean;
  ttsProvider: string;
  ttsModel: string;
  ttsVoice: string;
  ttsLanguage: string;
  ttsPrompt?: string;
  ttsSpeed: number;
  ttsPitch: number;
  ttsVolume: number;
  ttsStreaming?: boolean;
  ttsStreamingMode?: TtsStreamingMode;
  ttsStability: number;
  ttsSimilarity: number;
  ttsStyle: number;
  ttsSpeakerBoost: boolean;
  ttsMaxChars?: number;
  speakTerminalEvents: boolean;
  /** Modo call: ouvindo várias pessoas; a Hana não assume que quem fala é a Nakamura. */
  callMode?: boolean;
}

export interface VoiceProviderSpec {
  id: string;
  label: string;
  status: string;
  requiresCredentials: boolean;
  inputModalities: string[];
  outputModalities: string[];
  models?: string[];
  defaultModel?: string;
  voices?: { id: string; label: string; locale?: string }[];
  defaultVoice?: string;
  latencyProfile?: string;
  supportsRate?: boolean;
  supportsPitch?: boolean;
  supportsStreaming?: boolean;
  supportsStability?: boolean;
  supportsSimilarity?: boolean;
  supportsStyle?: boolean;
  supportsSpeakerBoost?: boolean;
  supportsStylePrompt?: boolean;
}

export type ThinkingItem =
  | { type: "text"; content: string }
  | { type: "tool_call" | "tool_result"; tool: string; args?: Record<string, unknown>; result?: Record<string, unknown> };

export interface ChatAttachment {
  name: string;
  data: string;
  type: string;
  size?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "hana" | "system";
  content: string;
  timestamp: string;
  meta?: {
    provider: string;
    model: string;
    tokens?: number;
    usage?: Record<string, unknown>;
    nativeSearch?: boolean;
    nativeSearchMode?: NativeSearchMode;
    browserContextEnabled?: boolean;
    agent?: string;
    safetyMode?: SafetyMode;
    providerError?: string;
    grounding?: {
      queries?: string[];
      sources?: Array<{
        title?: string;
        uri?: string;
      }>;
    };
    toolRuns?: Array<{
      tool: string;
      ok: boolean;
      summary?: string;
      query?: string;
      sources?: Array<{ title?: string; uri?: string }>;
    }>;
    /** Raciocinio vindo de provider que NAO streama (Gemini): chega pronto no meta
     *  em vez de token a token pelo on_reasoning. Mesma forma da timeline ao vivo. */
    thinking?: ThinkingItem[];
    memoryContext?: {
      count: number;
      approxTokens: number;
      memories: Array<{
        id?: string;
        text: string;
        category?: string;
        pinned?: boolean;
      }>;
    };
  };
  attachments?: Array<string | ChatAttachment>;
  images_b64?: string[];
  agentPlan?: {
    intent: string;
    project?: string;
    projectId?: number;
    memoryId?: number;
    browserSessionId?: number;
    assets?: ProjectAsset[];
    steps: {
      tool: string;
      status: string;
      risk: string;
      summary?: string;
    }[];
  };
  media?: {
    type: 'image' | 'music' | 'audio' | 'video' | 'file';
    url?: string;
    job_id?: string;
    name?: string;
    status?: "generating" | "ready" | "failed" | "expired";
    provider?: string;
    voice?: string;
    mimeType?: string;
    durationMs?: number;
    volume?: number;
    error?: string;
  }[];
  agentStatus?: {
    stage: AgentStage;
    tool_name?: string;
    action_id?: string;
    action_hash?: string;
    source?: string;
    risk?: string;
    detail?: string;
  };
  /** Timeline única de raciocínio: texto pensado e chamadas de ferramenta na
   * ordem em que aconteceram — uma só caixa "Pensando", sem cards duplicados. */
  thinking?: ThinkingItem[];
  thinkingElapsedMs?: number;
}

/** Sessao de chat que o front guarda em memoria/localStorage (nao e o banco). */
export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

/* ============ Memoria nova (/api/memoria) ============================ *
 * Tres memorias que entram no prompt, mais o historico da tela, que NAO
 * entra. Ids aqui sao number (AUTOINCREMENT do SQLite); no contrato antigo
 * eram string (uuid) — por isso `RagMemory` continua separado, nao da pra
 * misturar os dois.
 * ==================================================================== */

export type CanalMemoria = "chat" | "discord" | "terminal" | "voice";
export type StatusFato = "ativa" | "arquivada" | "lixeira";
export type TipoFixa = "regra" | "giria" | "tarefa" | "fato";

/** Memoria longa: o que a Hana guardou sozinha. Buscada por RAG (memory_items). */
export interface Fato {
  id: string;
  text: string;
  kind: string;
  source: string;
  status?: StatusFato;
  use_count?: number;
  last_used_at?: string | null;
  created_at: string;
  updated_at?: string;
}

/** Memoria fixa: entra em TODA resposta. So a Nakamura escreve. */
export interface MemoriaFixa {
  id: number;
  text: string;
  kind: TipoFixa;
  position: number;
  /** 0 ou 1 — SQLite nao tem boolean. */
  enabled: number;
  created_at: string;
}

/** Memoria curta: uma fala da conversa, dentro de um canal. */
export interface MensagemCurta {
  id: number;
  role: "user" | "assistant";
  author: string;
  content: string;
  created_at: string;
}

/** Historico da TELA. Nunca vai pra LLM — por isso pode carregar meta pesada. */
export interface ChatLogItem {
  id: number;
  session_id: string;
  role: string;
  author: string;
  content: string;
  channel: string;
  created_at: string;
  meta: Record<string, unknown> | null;
}

export interface SessaoHistorico {
  session_id: string;
  mensagens: number;
  inicio: string;
  fim: string;
}

export interface MemoriaStatus {
  mensagens: number;
  mensagensPorCanal: Record<string, number>;
  fatos: { ativas: number; arquivadas: number; lixeira: number };
  fixas: number;
  historicoFront: number;
  configuracoes: number;
  modelosEmCache: number;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  goal?: string;
  status: string;
  priority: string;
  created_at: string;
  updated_at: string;
}

export interface BrowserSession {
  id: number;
  project_id: number;
  memory_id?: number;
  title: string;
  url: string;
  text_preview: string;
  text_length: number;
  links_count: number;
  images_count: number;
  truncated: number;
  captured_at: string;
  created_at: string;
}

export interface ProjectAsset {
  id: number;
  project_id: number;
  type: "link" | "image" | "note" | "file";
  title: string;
  url: string;
  source_url?: string;
  preview?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface McpServer {
  id: string;
  name: string;
  enabled: boolean;
  command: string;
  args: string[];
  env?: Record<string, string>;
  cwd?: string | null;
  timeout: number;
  allowed_tools: string[];
  allowed_tool_count?: number;
  runtime_status?: "disabled" | "warming" | "ready" | "error";
}

export interface McpTool {
  server_id: string;
  name: string;
  title?: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  annotations?: Record<string, unknown>;
  allowed?: boolean;
}

export interface McpToolsResponse extends McpServer {
  status: string;
  error?: string;
  tools: McpTool[];
}

/**
 * Configuration schema for local PC environments, enhancing portability.
 */
export interface PortabilityConfig {
  ffmpegPath: string;
  mediaOutputPath: string;
  activeMonitor: number;
  visionQualityProfile: VisionQualityProfile;
}

export type VisionQualityProfile =
  | "full_hd_png"
  | "readable_jpeg"
  | "fast_jpeg"
  | "low_color_png"
  | "grayscale_readable"
  | "grayscale_fast";

/**
 * Details of active displays detected on the host system.
 */
export interface VisionMonitor {
  id: number;
  label: string;
  width: number;
  height: number;
}

/**
 * Image generation provider configuration.
 * Separate from LLM provider — image generation can use a different backend.
 */
export interface ImageConfig {
  imageProvider: string;
  imageModel: string;
  /** Compatibilidade temporária com configurações antigas. */
  openrouterImageModel?: string;
  openrouterReasoning: string;
}
