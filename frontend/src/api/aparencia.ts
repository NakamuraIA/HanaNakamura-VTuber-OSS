/** Banco = fonte oficial; localStorage = abertura rápida e contingência visível. */

import { backendFetch } from "./core";

const API_PATH = "/api/config/aparencia";
const PENDING_KEY = "hana_ui_config_pending";
const UI_KEYS = ["theme", "identity", "accessibility"] as const;

export const APPEARANCE_SYNC_EVENT = "hana-appearance-sync";
export type Aparencia = {
  theme?: unknown;
  identity?: unknown;
  accessibility?: unknown;
};

function validPatch(value: unknown): Aparencia {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const source = value as Record<string, unknown>;
  return Object.fromEntries(
    UI_KEYS.filter((key) => source[key] && typeof source[key] === "object" && !Array.isArray(source[key]))
      .map((key) => [key, source[key]]),
  ) as Aparencia;
}

function readPending(): Aparencia {
  try {
    return validPatch(JSON.parse(localStorage.getItem(PENDING_KEY) || "{}"));
  } catch {
    return {};
  }
}

function writePending(value: Aparencia): void {
  if (Object.keys(value).length > 0) localStorage.setItem(PENDING_KEY, JSON.stringify(value));
  else localStorage.removeItem(PENDING_KEY);
}

function notifyPending(pending: boolean): void {
  window.dispatchEvent(new CustomEvent(APPEARANCE_SYNC_EVENT, { detail: { pending } }));
}

function clearSent(sent: Aparencia): void {
  const latest = readPending();
  for (const key of UI_KEYS) {
    if (JSON.stringify(latest[key]) === JSON.stringify(sent[key])) delete latest[key];
  }
  writePending(latest);
}

let flushing: Promise<Aparencia> | null = null;

async function flushPending(): Promise<Aparencia> {
  if (flushing) return flushing;
  flushing = (async () => {
    let ui: Aparencia = {};
    while (Object.keys(readPending()).length > 0) {
      const sent = readPending();
      const res = await backendFetch(API_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sent),
      });
      if (!res.ok) throw new Error("Falha ao sincronizar a personalização.");
      const body = await res.json() as { ui?: unknown };
      ui = validPatch(body.ui);
      clearSent(sent);
    }
    notifyPending(false);
    return ui;
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

export function hasPendingAppearance(): boolean {
  return Object.keys(readPending()).length > 0;
}

/** Salva uma alteração no banco; em falha, mantém a alteração local pendente. */
export async function salvarAparencia(patch: Aparencia): Promise<boolean> {
  const clean = validPatch(patch);
  if (Object.keys(clean).length === 0) return true;
  writePending({ ...readPending(), ...clean });
  notifyPending(true);
  try {
    await flushPending();
    return true;
  } catch {
    notifyPending(true);
    return false;
  }
}

/**
 * Entrega a configuração oficial. Campos ainda ausentes no banco recebem a
 * cópia local uma única vez; campos já existentes no banco sempre vencem.
 */
export async function sincronizarAparencia(local: Aparencia): Promise<Aparencia | null> {
  try {
    if (hasPendingAppearance()) await flushPending();
    const res = await backendFetch(API_PATH);
    if (!res.ok) throw new Error("Falha ao ler a personalização.");
    const stored = validPatch(await res.json());
    const missing = Object.fromEntries(
      UI_KEYS.filter((key) => stored[key] === undefined && local[key] !== undefined)
        .map((key) => [key, local[key]]),
    ) as Aparencia;
    if (Object.keys(missing).length > 0) await salvarAparencia(missing);
    return { ...local, ...stored };
  } catch {
    notifyPending(hasPendingAppearance());
    return null;
  }
}
