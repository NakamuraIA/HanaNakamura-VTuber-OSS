export interface PriceTier {
  until: number | null;
  price: string;
}

/** Preco por token: valor fixo (string), ou faixas por tamanho de contexto. */
export type PriceValue = string | PriceTier[];

export interface ModelSpec {
  id: string;
  label: string;
  provider: string;
  /** Domínio do modelo: chat | image | embedding | rerank. Ausente = chat
   * (linhas dinâmicas do OpenRouter não mandam o campo e são conversa). */
  modelDomain?: string;
  supportsVision: boolean;
  supportsDocuments?: boolean;
  supportsTools?: boolean;
  supportsNativeSearch?: boolean;
  inputModalities?: string[];
  outputModalities?: string[];
  supportedParameters?: string[];
  maxInputTokens?: number;
  maxOutputTokens?: number;
  pricing?: Record<string, PriceValue>;
  free?: boolean;
  description?: string;
  custom?: boolean;
  /** Unix timestamp de entrada no catalogo do provider (so OpenRouter manda hoje). */
  createdAt?: number;
}

export interface VoiceSpec {
  id: string;
  label: string;
  provider: string;
  supportsRate?: boolean;
  supportsPitch?: boolean;
  pitchMode?: string;
}

// Fallback catalog — vazio de proposito.
// Modelos LLM sao servidos pelo backend (GET /api/catalog) que le do banco
// llm_models. Vozes TTS ficam no endpoint /api/config/voice/catalog.
// Se a API estiver offline, o front mostra lista vazia (dado errado e pior
// que dado nenhum).
export const LLM_PROVIDERS: string[] = [];
export const TTS_PROVIDERS: string[] = [];
export const STT_PROVIDERS: string[] = [];
export const TERMINAL_TTS_PROVIDERS: string[] = [];
export const MODEL_CATALOG: ModelSpec[] = [];
export const VOICE_CATALOG: VoiceSpec[] = [];

// Aliases historicos/falados -> id canonico usado pelo backend.
// Era triplicado em api/config.ts, TabChat e TabLLM; consolidado aqui.
export const PROVIDER_ALIASES: Record<string, string> = {
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

export function normalizeProvider(provider?: string): string {
  const value = String(provider || "").trim().toLowerCase();
  return PROVIDER_ALIASES[value] || value || "gemini_api";
}
