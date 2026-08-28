// Acessibilidade (dislexia / TDAH) — aplicada como classes e variáveis CSS globais.
// Tudo usa fontes do sistema (nada para baixar). O navegador pinta primeiro e
// o banco mantém a cópia compartilhada entre interfaces da mesma Hana.

import { salvarAparencia } from "./api/aparencia";

export interface AccessibilityConfig {
  /** "default" | "verdana" | "comic" | "opendyslexic" — fontes amigáveis para dislexia */
  font: string;
  /** Escala da fonte em % (100 = padrão) */
  fontScale: number;
  /** Mais espaço entre letras/linhas (leitura espaçada) */
  spacing: boolean;
  /** Desliga animações e partículas (foco / menos distração) */
  reduceMotion: boolean;
  /** Esconde brilhos/orbes decorativos (menos poluição visual) */
  focusMode: boolean;
  /** Alto contraste: fundo preto puro + texto branco, sem transparências */
  highContrast: boolean;
  /** Cursor maior e mais visível */
  bigCursor: boolean;
  /** Destaca linha atual com fundo sutil (ajuda TDAH) */
  lineFocus: boolean;
  /** Limita largura de parágrafos (~65ch) */
  narrowText: boolean;
  /** Remove itálico (formato difícil para disléxicos) */
  noItalic: boolean;
}

export const DEFAULT_ACCESSIBILITY: AccessibilityConfig = {
  font: "default",
  fontScale: 100,
  spacing: false,
  reduceMotion: false,
  focusMode: false,
  highContrast: false,
  bigCursor: false,
  lineFocus: false,
  narrowText: false,
  noItalic: false,
};

const STORAGE_KEY = "hana_accessibility";

export const ACCESSIBILITY_FONTS: { id: string; label: string; stack: string }[] = [
  { id: "default", label: "Padrão (Inter)", stack: "'Inter', 'Segoe UI', sans-serif" },
  { id: "verdana", label: "Verdana (dislexia)", stack: "Verdana, Geneva, Tahoma, sans-serif" },
  { id: "comic", label: "Comic Sans (dislexia)", stack: "'Comic Sans MS', 'Comic Sans', cursive, sans-serif" },
  { id: "opendyslexic", label: "OpenDyslexic", stack: "'OpenDyslexic', 'OpenDyslexicAlta', Verdana, sans-serif" },
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

export function saveAccessibility(config: AccessibilityConfig, sync = true): Promise<boolean> {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  return sync ? salvarAparencia({ accessibility: config }) : Promise.resolve(true);
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
  root.classList.toggle("acc-high-contrast", config.highContrast);
  root.classList.toggle("acc-big-cursor", config.bigCursor);
  root.classList.toggle("acc-line-focus", config.lineFocus);
  root.classList.toggle("acc-narrow-text", config.narrowText);
  root.classList.toggle("acc-no-italic", config.noItalic);
}
