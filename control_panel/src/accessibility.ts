// Acessibilidade (dislexia / TDAH) — aplicada como classes e variáveis CSS globais.
// Tudo usa fontes do sistema (nada para baixar) e persiste em localStorage,
// igual ao tema. Carregada no boot pelo App.tsx e controlada na Personalização.

export interface AccessibilityConfig {
  /** "default" | "verdana" | "comic" — fontes consideradas amigáveis para dislexia */
  font: string;
  /** Escala da fonte em % (100 = padrão) */
  fontScale: number;
  /** Mais espaço entre letras/linhas (leitura espaçada) */
  spacing: boolean;
  /** Desliga animações e partículas (foco / menos distração) */
  reduceMotion: boolean;
  /** Esconde brilhos/orbes decorativos (menos poluição visual) */
  focusMode: boolean;
}

export const DEFAULT_ACCESSIBILITY: AccessibilityConfig = {
  font: "default",
  fontScale: 100,
  spacing: false,
  reduceMotion: false,
  focusMode: false,
};

const STORAGE_KEY = "hana_accessibility";

export const ACCESSIBILITY_FONTS: { id: string; label: string; stack: string }[] = [
  { id: "default", label: "Padrão (Inter)", stack: "'Inter', 'Segoe UI', sans-serif" },
  { id: "verdana", label: "Verdana (dislexia)", stack: "Verdana, Geneva, Tahoma, sans-serif" },
  { id: "comic", label: "Comic Sans (dislexia)", stack: "'Comic Sans MS', 'Comic Sans', cursive, sans-serif" },
];

export function loadAccessibility(): AccessibilityConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_ACCESSIBILITY };
    return { ...DEFAULT_ACCESSIBILITY, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_ACCESSIBILITY };
  }
}

export function saveAccessibility(config: AccessibilityConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

export function applyAccessibility(config: AccessibilityConfig) {
  const root = document.documentElement;
  const font = ACCESSIBILITY_FONTS.find((f) => f.id === config.font) || ACCESSIBILITY_FONTS[0];
  root.style.setProperty("--acc-font", font.stack);
  const scale = Math.max(85, Math.min(140, config.fontScale || 100));
  root.style.setProperty("font-size", scale === 100 ? "" : `${scale}%`);
  root.classList.toggle("acc-spacing", config.spacing);
  root.classList.toggle("acc-reduce-motion", config.reduceMotion);
  root.classList.toggle("acc-focus", config.focusMode);
}
