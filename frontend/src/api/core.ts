import { ConnectionsConfig } from "../models/types";

// URL do backend configuravel por variavel de ambiente (VITE_BACKEND_URL).
// O padrao aponta para o servidor local iniciado pelo Hana.cmd.
const RAW_BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8042";
export const BACKEND_URL = RAW_BACKEND_URL;
export const WS_URL = RAW_BACKEND_URL.replace(/^http/, "ws");
const DEFAULT_BACKEND_TIMEOUT_MS = 8000;

export const DEFAULT_CONNECTIONS_CONFIG: ConnectionsConfig = {
  tts: false,
  stt: false,
  vad: true,
  ptt: false,
  pttKey: "F2",
  stopHotkey: true,
  stopKey: "F4",
  discord: false,
  localHands: true,
  visao: false,
};

export class BackendRequestError extends Error {
  status?: number;
  backendUnavailable: boolean;

  constructor(message: string, options: { status?: number; backendUnavailable?: boolean } = {}) {
    super(message);
    this.name = "BackendRequestError";
    this.status = options.status;
    this.backendUnavailable = Boolean(options.backendUnavailable);
  }
}

// Adds a hard timeout so a stuck voice route cannot freeze the control panel.
export async function backendFetch(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      signal: init.signal || controller.signal,
    });
    return res;
  } catch (error) {
    if (error instanceof BackendRequestError) throw error;
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new BackendRequestError(aborted ? "Backend demorou para responder." : "Backend indisponivel.", {
      backendUnavailable: true,
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function readJson<T>(path: string, fallback: T, logMessage?: string): Promise<T> {
  try {
    const res = await backendFetch(path);
    if (res.ok) return await res.json();
    throw new BackendRequestError(`Falha na API: ${res.status}`, { status: res.status });
  } catch (error) {
    if (logMessage) console.error(logMessage, error);
    return fallback;
  }
}

export async function postJson(path: string, payload?: unknown): Promise<boolean> {
  try {
    const res = await backendFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function readLocalConnections(): ConnectionsConfig {
  const savedConfig = localStorage.getItem("hana_conexoes_config");
  if (!savedConfig) return DEFAULT_CONNECTIONS_CONFIG;
  return { ...DEFAULT_CONNECTIONS_CONFIG, ...JSON.parse(savedConfig) };
}
