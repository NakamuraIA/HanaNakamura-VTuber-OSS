// Visual theme for the Control Panel (Personalização).
// Accent, secondary, gradient, background tone/opacity/blur, and global
// saturation/brightness live here and are applied as CSS variables on :root.
// Guardado no localStorage (leitura instantanea, tela nao pisca) E no banco
// (copia duravel, sobrevive a limpar o navegador). Ver api/aparencia.ts.

import { salvarAparencia } from "./api/aparencia";

export type ThemeConfig = {
  /** Primary accent (menus, buttons, highlights). */
  primary: string;
  /** Secondary surface color (cards, borders). */
  secondary: string;
  /** Gradient start for highlight elements. */
  gradientStart: string;
  /** Gradient end for highlight elements. */
  gradientEnd: string;
  /** Gradient angle in degrees (0–360). */
  gradientAngle: number;
  /** Base background RGB triplet string, e.g. "6, 6, 9". */
  bgTone: string;
  /** Background opacity 0.1–1 (lower = more see-through). */
  opacity: number;
  /** Backdrop blur in pixels for glass panels. */
  blur: number;
  /** Global color saturation multiplier 0–200 (%). */
  saturation: number;
  /** Global color brightness multiplier 0–200 (%). */
  brightness: number;
  /** Border radius preset: "sm" (8px), "md" (12px), "lg" (16px). */
  borderRadius: string;
};

export const DEFAULT_THEME: ThemeConfig = {
  primary: "#a855f7",
  secondary: "#1a1b22",
  gradientStart: "#a855f7",
  gradientEnd: "#22d3ee",
  gradientAngle: 135,
  bgTone: "6, 6, 9",
  opacity: 1.0,
  blur: 24,
  saturation: 100,
  brightness: 100,
  borderRadius: "md",
};

export const BG_TONES = [
  { name: "Preto", rgb: "6, 6, 9" },
  { name: "Grafite", rgb: "15, 16, 20" },
  { name: "Cinza escuro", rgb: "22, 24, 30" },
  { name: "Cinza", rgb: "31, 34, 42" },
] as const;

/** One-click full themes (accent + surfaces + glass + color balance). */
export type ThemePreset = {
  name: string;
  primary: string;
  secondary: string;
  gradientStart: string;
  gradientEnd: string;
  gradientAngle: number;
  tone: string;
  opacity: number;
  blur?: number;
  saturation?: number;
  brightness?: number;
};

export const THEME_PRESETS: ThemePreset[] = [
  {
    name: "🌸 Sakura",
    primary: "#f472b6",
    secondary: "#1c161c",
    gradientStart: "#f472b6",
    gradientEnd: "#fb7185",
    gradientAngle: 135,
    tone: "22, 24, 30",
    opacity: 1.0,
    blur: 24,
  },
  {
    name: "🖤 OLED",
    primary: "#a855f7",
    secondary: "#121218",
    gradientStart: "#a855f7",
    gradientEnd: "#22d3ee",
    gradientAngle: 135,
    tone: "6, 6, 9",
    opacity: 1.0,
    blur: 20,
  },
  {
    name: "🧪 Matrix",
    primary: "#4ade80",
    secondary: "#0c1410",
    gradientStart: "#4ade80",
    gradientEnd: "#22d3ee",
    gradientAngle: 120,
    tone: "6, 6, 9",
    opacity: 0.95,
    blur: 18,
  },
  {
    name: "🌆 Cyberpunk",
    primary: "#22d3ee",
    secondary: "#10141a",
    gradientStart: "#22d3ee",
    gradientEnd: "#a855f7",
    gradientAngle: 90,
    tone: "15, 16, 20",
    opacity: 0.9,
    blur: 28,
  },
  {
    name: "🍊 Sunset",
    primary: "#fb923c",
    secondary: "#1a1410",
    gradientStart: "#fb923c",
    gradientEnd: "#f43f5e",
    gradientAngle: 150,
    tone: "22, 24, 30",
    opacity: 0.95,
    blur: 22,
  },
  {
    name: "👑 Royal",
    primary: "#fbbf24",
    secondary: "#16140e",
    gradientStart: "#fbbf24",
    gradientEnd: "#a855f7",
    gradientAngle: 160,
    tone: "15, 16, 20",
    opacity: 1.0,
    blur: 24,
  },
  // Extra presets
  {
    name: "🌊 Ocean",
    primary: "#38bdf8",
    secondary: "#0c141c",
    gradientStart: "#38bdf8",
    gradientEnd: "#2dd4bf",
    gradientAngle: 120,
    tone: "10, 16, 24",
    opacity: 0.92,
    blur: 26,
  },
  {
    name: "🍵 Matcha",
    primary: "#86efac",
    secondary: "#121812",
    gradientStart: "#86efac",
    gradientEnd: "#a3e635",
    gradientAngle: 140,
    tone: "14, 18, 14",
    opacity: 0.96,
    blur: 20,
  },
  {
    name: "🍷 Wine",
    primary: "#e11d48",
    secondary: "#1a1014",
    gradientStart: "#e11d48",
    gradientEnd: "#fb7185",
    gradientAngle: 155,
    tone: "18, 12, 14",
    opacity: 0.97,
    blur: 24,
  },
  {
    name: "🧊 Ice",
    primary: "#e2e8f0",
    secondary: "#14181e",
    gradientStart: "#e2e8f0",
    gradientEnd: "#7dd3fc",
    gradientAngle: 100,
    tone: "12, 14, 18",
    opacity: 0.88,
    blur: 30,
  },
  {
    name: "🔥 Ember",
    primary: "#f97316",
    secondary: "#1a120e",
    gradientStart: "#f97316",
    gradientEnd: "#ef4444",
    gradientAngle: 145,
    tone: "18, 12, 10",
    opacity: 0.96,
    blur: 22,
  },
  {
    name: "💜 Lavender",
    primary: "#c4b5fd",
    secondary: "#16141c",
    gradientStart: "#c4b5fd",
    gradientEnd: "#f0abfc",
    gradientAngle: 130,
    tone: "16, 14, 22",
    opacity: 0.94,
    blur: 26,
  },
  {
    name: "🌲 Forest",
    primary: "#34d399",
    secondary: "#0e1412",
    gradientStart: "#34d399",
    gradientEnd: "#0d9488",
    gradientAngle: 160,
    tone: "8, 14, 12",
    opacity: 0.98,
    blur: 18,
  },
  {
    name: "📻 Mono",
    primary: "#a1a1aa",
    secondary: "#141416",
    gradientStart: "#d4d4d8",
    gradientEnd: "#71717a",
    gradientAngle: 180,
    tone: "10, 10, 12",
    opacity: 1.0,
    blur: 16,
    saturation: 40,
    brightness: 100,
  },
  {
    name: "🍑 Peach",
    primary: "#fdba74",
    secondary: "#1a1412",
    gradientStart: "#fdba74",
    gradientEnd: "#f9a8d4",
    gradientAngle: 125,
    tone: "20, 16, 14",
    opacity: 0.95,
    blur: 24,
  },
  {
    name: "🌌 Midnight",
    primary: "#818cf8",
    secondary: "#0c0e18",
    gradientStart: "#818cf8",
    gradientEnd: "#22d3ee",
    gradientAngle: 200,
    tone: "6, 8, 16",
    opacity: 0.9,
    blur: 32,
  },
];

const STORAGE_KEY = "hana_theme_v2";

// Legacy keys (pre-v2) — migrated on first load.
const LEGACY_ACCENT = "hana_accent_color";
const LEGACY_OPACITY = "hana_bg_opacity";
const LEGACY_TONE = "hana_bg_tone";

/** Valid #rgb or #rrggbb. */
export const isValidHex = (value: string) =>
  /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value.trim());

/** Expand #rgb → #rrggbb. */
export function normalizeHex(hex: string): string {
  const h = hex.trim();
  if (/^#[0-9a-fA-F]{3}$/.test(h)) {
    return `#${h[1]}${h[1]}${h[2]}${h[2]}${h[3]}${h[3]}`.toLowerCase();
  }
  return h.toLowerCase();
}

/** Parse #rrggbb into 0–255 RGB. */
export function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  if (!isValidHex(hex)) return null;
  const n = normalizeHex(hex).slice(1);
  return {
    r: parseInt(n.slice(0, 2), 16),
    g: parseInt(n.slice(2, 4), 16),
    b: parseInt(n.slice(4, 6), 16),
  };
}

function rgbToHex(r: number, g: number, b: number): string {
  const c = (n: number) =>
    Math.max(0, Math.min(255, Math.round(n)))
      .toString(16)
      .padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

function rgbToHsl(r: number, g: number, b: number): { h: number; s: number; l: number } {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = 0;
  if (max === rn) h = (gn - bn) / d + (gn < bn ? 6 : 0);
  else if (max === gn) h = (bn - rn) / d + 2;
  else h = (rn - gn) / d + 4;
  h /= 6;
  return { h, s, l };
}

function hslToRgb(h: number, s: number, l: number): { r: number; g: number; b: number } {
  if (s === 0) {
    const v = l * 255;
    return { r: v, g: v, b: v };
  }
  const hue2rgb = (p: number, q: number, t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return {
    r: hue2rgb(p, q, h + 1 / 3) * 255,
    g: hue2rgb(p, q, h) * 255,
    b: hue2rgb(p, q, h - 1 / 3) * 255,
  };
}

/**
 * Adjust a hex color by global saturation/brightness percentages (100 = neutral).
 * Keeps hue; scales S and L around mid-gray so 100% is identity.
 */
export function adjustColor(hex: string, saturationPct: number, brightnessPct: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const { h, s, l } = rgbToHsl(rgb.r, rgb.g, rgb.b);
  const satMul = Math.max(0, saturationPct) / 100;
  const briMul = Math.max(0, brightnessPct) / 100;
  const newS = Math.max(0, Math.min(1, s * satMul));
  // Brightness: scale lightness relative to 0.5 midpoint for more natural feel.
  const newL = Math.max(0, Math.min(1, 0.5 + (l - 0.5) * briMul + (briMul - 1) * 0.08));
  const out = hslToRgb(h, newS, newL);
  return rgbToHex(out.r, out.g, out.b);
}

function clampTheme(partial: Partial<ThemeConfig>): ThemeConfig {
  const base = { ...DEFAULT_THEME, ...partial };
  return {
    primary: isValidHex(base.primary) ? normalizeHex(base.primary) : DEFAULT_THEME.primary,
    secondary: isValidHex(base.secondary) ? normalizeHex(base.secondary) : DEFAULT_THEME.secondary,
    gradientStart: isValidHex(base.gradientStart)
      ? normalizeHex(base.gradientStart)
      : DEFAULT_THEME.gradientStart,
    gradientEnd: isValidHex(base.gradientEnd)
      ? normalizeHex(base.gradientEnd)
      : DEFAULT_THEME.gradientEnd,
    gradientAngle: Math.max(0, Math.min(360, Number(base.gradientAngle) || 135)),
    bgTone: base.bgTone || DEFAULT_THEME.bgTone,
    opacity: Math.max(0.1, Math.min(1, Number(base.opacity) || 1)),
    blur: Math.max(0, Math.min(48, Number(base.blur) || 0)),
    saturation: Math.max(0, Math.min(200, Number(base.saturation) || 100)),
    brightness: Math.max(0, Math.min(200, Number(base.brightness) || 100)),
    borderRadius: ["sm", "md", "lg"].includes(base.borderRadius) ? base.borderRadius : "md",
  };
}

/** Load theme from localStorage, migrating legacy single-accent keys if needed. */
export function loadTheme(): ThemeConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      return clampTheme(JSON.parse(raw) as Partial<ThemeConfig>);
    }
  } catch {
    /* ignore corrupt storage */
  }

  // Migrate pre-v2 keys once.
  const legacyPrimary = localStorage.getItem(LEGACY_ACCENT);
  const legacyOpacity = localStorage.getItem(LEGACY_OPACITY);
  const legacyTone = localStorage.getItem(LEGACY_TONE);
  if (legacyPrimary || legacyOpacity || legacyTone) {
    const migrated = clampTheme({
      primary: legacyPrimary || DEFAULT_THEME.primary,
      gradientStart: legacyPrimary || DEFAULT_THEME.gradientStart,
      opacity: legacyOpacity ? parseFloat(legacyOpacity) : DEFAULT_THEME.opacity,
      bgTone: legacyTone || DEFAULT_THEME.bgTone,
    });
    saveTheme(migrated);
    return migrated;
  }

  return { ...DEFAULT_THEME };
}

export function saveTheme(theme: ThemeConfig, sync = true): Promise<boolean> {
  const next = clampTheme(theme);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  // Keep legacy accent key in sync for any old readers.
  localStorage.setItem(LEGACY_ACCENT, next.primary);
  localStorage.setItem(LEGACY_OPACITY, String(next.opacity));
  localStorage.setItem(LEGACY_TONE, next.bgTone);
  // Copia duravel: o localStorage some quando se limpa o navegador.
  return sync ? salvarAparencia({ theme: next }) : Promise.resolve(true);
}

/**
 * Push theme into CSS variables on :root.
 * Opacity multiplies into --bg-sidebar / surfaces so panels actually go translucent.
 * Blur drives --bg-blur used by .hana-glass panels.
 */
export function applyTheme(theme: ThemeConfig): void {
  const t = clampTheme(theme);
  const root = document.documentElement;

  const primary = adjustColor(t.primary, t.saturation, t.brightness);
  const secondary = adjustColor(t.secondary, t.saturation, t.brightness);
  const gStart = adjustColor(t.gradientStart, t.saturation, t.brightness);
  const gEnd = adjustColor(t.gradientEnd, t.saturation, t.brightness);
  const secRgb = hexToRgb(secondary);

  root.style.setProperty("--purple-neon", primary);
  root.style.setProperty("--purple-glow", primary);
  root.style.setProperty("--purple-dark", `${primary}33`);
  root.style.setProperty("--accent", primary);
  root.style.setProperty("--accent-2", gEnd);

  root.style.setProperty("--secondary", secondary);
  if (secRgb) {
    root.style.setProperty("--secondary-rgb", `${secRgb.r}, ${secRgb.g}, ${secRgb.b}`);
  }

  root.style.setProperty("--gradient-start", gStart);
  root.style.setProperty("--gradient-end", gEnd);
  root.style.setProperty("--gradient-angle", `${t.gradientAngle}deg`);

  root.style.setProperty("--bg-darkest-rgb", t.bgTone);
  root.style.setProperty("--bg-opacity", String(t.opacity));
  root.style.setProperty("--bg-blur", `${t.blur}px`);

  // Surfaces must recompute from tone + opacity (never hardcode fixed alpha).
  // Sidebar/panels slightly less opaque than body so layering stays readable.
  root.style.setProperty(
    "--bg-darkest",
    `rgba(${t.bgTone}, ${t.opacity})`,
  );
  root.style.setProperty(
    "--bg-sidebar",
    `rgba(${t.bgTone}, ${Math.min(1, t.opacity * 0.92)})`,
  );
  // Keep cards readable: floor alpha so identity/forms never "vanish" into pure black.
  const surfaceAlpha = Math.min(1, Math.max(0.55, t.opacity * 0.88));
  root.style.setProperty(
    "--surface-1",
    secRgb
      ? `rgba(${secRgb.r}, ${secRgb.g}, ${secRgb.b}, ${surfaceAlpha})`
      : `rgba(${t.bgTone}, ${surfaceAlpha})`,
  );
  // Borders stay slate-tinted so dark secondary colors don't erase edges.
  root.style.setProperty(
    "--border-strong",
    `rgba(148, 163, 184, ${0.14 + t.opacity * 0.1})`,
  );

  root.style.setProperty("--theme-saturation", String(t.saturation / 100));
  root.style.setProperty("--theme-brightness", String(t.brightness / 100));

  // Border radius
  const radiusMap: Record<string, string> = { sm: "8px", md: "12px", lg: "16px" };
  root.style.setProperty("--theme-radius", radiusMap[t.borderRadius] || "12px");
}

/**
 * Check whether the current theme matches a preset's key visual properties.
 * Compares primary, gradient colors/angle, bg tone, opacity, blur, and color balance.
 */
export function isPresetActive(theme: ThemeConfig, preset: ThemePreset): boolean {
  const t = clampTheme(theme);
  const defaults = DEFAULT_THEME;
  return (
    t.primary === preset.primary &&
    t.gradientStart === preset.gradientStart &&
    t.gradientEnd === preset.gradientEnd &&
    t.gradientAngle === preset.gradientAngle &&
    t.opacity === preset.opacity &&
    t.blur === (preset.blur ?? defaults.blur) &&
    t.saturation === (preset.saturation ?? defaults.saturation) &&
    t.brightness === (preset.brightness ?? defaults.brightness) &&
    t.bgTone === preset.tone
  );
}
