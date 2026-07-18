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
  agentProvider: string;
  agentModel: string;
  agentToolRounds: number;
  llmFilter: string;
  llmTemperature: number;
  /** Groq "pensar antes de falar": true = raciocina; false = resposta direta/rápida. */
  groqThinking?: boolean;
  /** Qwen "pensar antes de falar" (modelos qwen3.x): true = raciocina; false = resposta direta/rápida. */
  qwenThinking?: boolean;
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
  ttsStability: number;
  ttsSimilarity: number;
  ttsStyle: number;
  ttsSpeakerBoost: boolean;
  ttsMaxChars?: number;
  speakTerminalEvents: boolean;
  /** Modo call: ouvindo várias pessoas; a Hana não assume que quem fala é a Operador. */
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
  reasoning?: {
    content: string;
    elapsedMs?: number;
  };
  toolActivity?: Array<{
    kind: "tool_call" | "tool_result";
    tool: string;
    args?: Record<string, unknown>;
    result?: Record<string, unknown>;
    timestamp: number;
  }>;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

export type MemoryStatus = "active" | "archived" | "deleted" | "all" | "long" | "pinned";
export type MemoryImportance = "low" | "medium" | "high" | "critical";

export interface MemorySemanticStatus {
  enabled: boolean;
  model: string;
  lazy: boolean;
  fastembedAvailable: boolean;
  sqliteVecAvailable: boolean;
  mode: "fts" | "hybrid_optional" | string;
}

export interface MemoryAudit {
  status: Record<string, number>;
  category: Record<string, number>;
  pinned: number;
  embeddingState: Record<string, number>;
  semantic: MemorySemanticStatus;
}

export interface RagMemory {
  id: string;
  text: string;
  kind?: string;
  source?: string;
  status?: "active" | "archived" | "deleted";
  category?: string;
  importance?: MemoryImportance | string;
  tags?: string[];
  pinned?: boolean;
  score?: number;
  metadata: Record<string, unknown>;
}

export interface GraphFact {
  subject: string;
  relation: string;
  object: string;
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

export interface PermissionRequest {
  id: string;
  action_id: string;
  tool_name: string;
  risk: string;
  description: string;
  args_preview: string;
  created_at: number;
  expires_at: number;
  timeout_seconds: number;
  remaining_seconds: number;
  status: string;
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

export interface EmotionEvent {
  timestamp: number;
  emotion: string;
  turno: number;
}

export interface EmotionState {
  mood: number;
  current_emotion: string;
  turno: number;
  last_thought: string;
  history: EmotionEvent[];
  updated_at: number;
}

export interface McpServer {
  id: string;
  name: string;
  enabled: boolean;
  command: string;
  args: string[];
  cwd?: string | null;
  timeout: number;
  allowed_tools: string[];
  allowed_tool_count?: number;
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
  openrouterImageModel: string;
  openrouterReasoning: string;
}
