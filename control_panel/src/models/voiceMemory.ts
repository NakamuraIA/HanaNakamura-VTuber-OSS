// Lembra os Voice IDs (TTS) que o usuario cola, por provider, no localStorage.
// Providers como ElevenLabs nao expoem catalogo de vozes no app, entao sem isso
// cada voz colada some da lista ao trocar — obrigando a re-copiar do ElevenLabs.

const STORAGE_KEY = "hana.rememberedVoices.v1";
const MAX_PER_PROVIDER = 30;

type Store = Record<string, string[]>;

function readStore(): Store {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {};
  }
}

function writeStore(store: Store): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // conveniencia de frontend; falha de storage nao deve travar a selecao
  }
}

export function readRememberedVoices(provider: string): string[] {
  const list = readStore()[provider];
  return Array.isArray(list) ? list : [];
}

/** Guarda um Voice ID e devolve a lista atualizada (mais recente primeiro). */
export function rememberVoice(provider: string, id: string): string[] {
  const voiceId = (id || "").trim();
  if (!provider || !voiceId) return readRememberedVoices(provider);
  const store = readStore();
  const current = Array.isArray(store[provider]) ? store[provider] : [];
  const next = [voiceId, ...current.filter((value) => value !== voiceId)].slice(0, MAX_PER_PROVIDER);
  store[provider] = next;
  writeStore(store);
  return next;
}

/** Remove um Voice ID lembrado e devolve a lista atualizada. */
export function forgetVoice(provider: string, id: string): string[] {
  const store = readStore();
  const current = Array.isArray(store[provider]) ? store[provider] : [];
  store[provider] = current.filter((value) => value !== id);
  writeStore(store);
  return store[provider];
}
