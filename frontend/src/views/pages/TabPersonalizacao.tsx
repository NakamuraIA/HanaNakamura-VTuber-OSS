import { useState, useEffect, useCallback } from "react";
import {
  Paintbrush,
  Save,
  CheckCircle2,
  Palette,
  Accessibility,
  RotateCcw,
  ImagePlus,
  Sparkles,
  UserRound,
  Droplets,
  Contrast,
  ChevronDown,
  Eye,
  LayoutGrid,
  Radius,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { TabHeader } from "../components/shared/TabHeader";
import { Card } from "../components/shared/Card";
import { Button } from "../components/shared/Button";
import {
  APPEARANCE_SYNC_EVENT,
  hasPendingAppearance,
  sincronizarAparencia,
} from "../../api/aparencia";
import {
  ACCESSIBILITY_FONTS,
  AccessibilityConfig,
  applyAccessibility,
  loadAccessibility,
  saveAccessibility,
} from "../../accessibility";
import {
  DEFAULT_IDENTITY,
  HanaIdentity,
  fileToAvatarDataUrl,
  loadIdentity,
  saveIdentity,
} from "../../identity";
import {
  BG_TONES,
  DEFAULT_THEME,
  THEME_PRESETS,
  ThemeConfig,
  ThemePreset,
  applyTheme,
  isValidHex,
  isPresetActive,
  loadTheme,
  saveTheme,
} from "../../theme";

/* ── Internal components ─────────────────────────────────────── */

/** Compact labeled color field (native picker + hex text). */
function ColorField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (hex: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
      {hint ? <span className="text-[10px] text-[var(--text-muted)] -mt-0.5">{hint}</span> : null}
      <div className="flex gap-2 items-center">
        <input
          type="color"
          value={isValidHex(value) ? value : "#000000"}
          onChange={(e) => onChange(e.target.value)}
          title={label}
          className="h-10 w-12 shrink-0 cursor-pointer rounded-lg border border-[var(--border-strong)] bg-black/50 p-1"
        />
        <input
          type="text"
          value={draft}
          placeholder="#a855f7"
          onChange={(e) => {
            setDraft(e.target.value);
            if (isValidHex(e.target.value)) onChange(e.target.value.trim());
          }}
          onBlur={() => {
            if (isValidHex(draft)) onChange(draft.trim());
            else setDraft(value);
          }}
          className={`flex-1 min-w-0 bg-black/50 border text-[var(--text-primary)] rounded-lg px-2.5 py-2 outline-none font-mono text-sm focus:ring-2 focus:ring-[var(--accent)]/40 transition-all ${
            draft && !isValidHex(draft) ? "border-red-500/70" : "border-[var(--border-strong)]"
          }`}
        />
      </div>
    </div>
  );
}

/** Range row with label + live percent/unit badge. */
function SliderField({
  label,
  value,
  min,
  max,
  step,
  display,
  accent,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  accent: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">{label}</span>
      <div className="flex items-center gap-4">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          className="w-full h-2 bg-[rgba(0,0,0,0.5)] rounded-lg appearance-none cursor-pointer"
          style={{ accentColor: accent }}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
        />
        <span className="text-sm font-bold font-mono text-white bg-[rgba(255,255,255,0.1)] px-3 py-1 rounded-lg shrink-0 min-w-[3.5rem] text-center">
          {display}
        </span>
      </div>
    </div>
  );
}

/** Collapsible section wrapper. */
function AccordionSection({
  title,
  icon,
  defaultOpen = true,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.05)] rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
      >
        <span className="flex items-center gap-2 text-xs text-[var(--text-muted)] uppercase tracking-wider">
          {icon}
          {title}
        </span>
        <ChevronDown
          size={16}
          className={`text-[var(--text-muted)] transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

/* ── Live theme preview panel ────────────────────────────────── */

function ThemePreview({ theme }: { theme: ThemeConfig }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-[var(--border-strong)] bg-[rgba(0,0,0,0.4)] overflow-hidden shadow-lg">
      <div className="px-4 py-2.5 border-b border-[var(--border-strong)] bg-[rgba(255,255,255,0.03)] flex items-center gap-2">
        <Eye size={14} className="text-[var(--text-muted)]" />
        <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">
          {t("personalization.livePreview")}
        </span>
      </div>
      <div className="flex" style={{ minHeight: "200px" }}>
        {/* Mini sidebar */}
        <div
          className="w-[80px] shrink-0 flex flex-col items-center pt-4 pb-3 gap-3"
          style={{
            backgroundColor: `rgba(${theme.bgTone}, ${Math.min(1, theme.opacity * 0.92)})`,
            backdropFilter: `blur(${theme.blur}px)`,
            borderRight: `1px solid rgba(148,163,184,${0.14 + theme.opacity * 0.1})`,
          }}
        >
          <div
            className="w-8 h-8 rounded-full border-2 shrink-0"
            style={{ borderColor: theme.primary, backgroundColor: theme.primary + "22" }}
          />
          <div
            className="w-10 h-1 rounded-full opacity-60"
            style={{ background: `linear-gradient(${theme.gradientAngle}deg, ${theme.gradientStart}, ${theme.gradientEnd})` }}
          />
          <div className="flex flex-col gap-1.5 flex-1 w-full px-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-1.5 rounded-full"
                style={{
                  backgroundColor: i === 0 ? theme.primary + "44" : "rgba(255,255,255,0.1)",
                  width: i === 0 ? "100%" : `${60 + i * 15}%`,
                }}
              />
            ))}
          </div>
        </div>
        {/* Mini content */}
        <div
          className="flex-1 p-3 flex flex-col gap-2"
          style={{ backgroundColor: `rgba(${theme.bgTone}, ${theme.opacity})` }}
        >
          <div
            className="h-4 rounded w-3/4"
            style={{ backgroundColor: theme.primary + "44" }}
          />
          <div className="flex gap-2">
            <div
              className="h-8 flex-1 rounded border flex items-center justify-center"
              style={{
                borderColor: theme.primary + "55",
                background: `linear-gradient(${theme.gradientAngle}deg, ${theme.gradientStart}, ${theme.gradientEnd})`,
              }}
            >
              <span className="text-[8px] font-bold text-white/80">HANA</span>
            </div>
            <div
              className="h-8 w-12 rounded border"
              style={{
                borderColor: "rgba(148,163,184,0.2)",
                backgroundColor: `rgba(${theme.bgTone}, 0.6)`,
              }}
            />
          </div>
          <div
            className="flex-1 rounded border flex flex-col gap-1.5 p-2"
            style={{
              borderColor: "rgba(148,163,184,0.15)",
              backgroundColor: theme.secondary + "44",
            }}
          >
            <div className="h-1.5 rounded-full bg-white/10 w-2/3" />
            <div className="h-1.5 rounded-full bg-white/10 w-1/2" />
            <div className="h-1.5 rounded-full bg-white/10 w-3/4" />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Main page ───────────────────────────────────────────────── */

type SubTab = "appearance" | "identity" | "accessibility";

export function TabPersonalizacao() {
  const { t } = useTranslation();
  const [theme, setTheme] = useState<ThemeConfig>(() => loadTheme());
  const [acc, setAcc] = useState<AccessibilityConfig>(() => loadAccessibility());
  const [identity, setIdentity] = useState<HanaIdentity>(() => loadIdentity());
  const [avatarError, setAvatarError] = useState("");
  const [subTab, setSubTab] = useState<SubTab>("appearance");
  const [showToast, setShowToast] = useState(false);
  const [syncPending, setSyncPending] = useState(() => hasPendingAppearance());

  const pushTheme = useCallback((patch: Partial<ThemeConfig>) => {
    setTheme((prev) => {
      const next = { ...prev, ...patch };
      applyTheme(next);
      saveTheme(next);
      return next;
    });
  }, []);

  const updateIdentity = (patch: Partial<HanaIdentity>) => {
    setIdentity((prev) => {
      const next = { ...prev, ...patch };
      saveIdentity(next);
      return next;
    });
  };

  const handleAvatarUpload = async (file: File | undefined) => {
    if (!file) return;
    setAvatarError("");
    try {
      const dataUrl = await fileToAvatarDataUrl(file);
      updateIdentity({ avatar: dataUrl });
    } catch {
      setAvatarError(t("personalization.avatarError"));
    }
  };

  const updateAcc = (patch: Partial<AccessibilityConfig>) => {
    setAcc((prev) => {
      const next = { ...prev, ...patch };
      applyAccessibility(next);
      saveAccessibility(next);
      return next;
    });
  };

  useEffect(() => {
    let active = true;
    const handleSync = (event: Event) => {
      const detail = (event as CustomEvent<{ pending?: boolean }>).detail;
      setSyncPending(Boolean(detail?.pending));
    };
    window.addEventListener(APPEARANCE_SYNC_EVENT, handleSync);

    void sincronizarAparencia({ theme, identity, accessibility: acc }).then((ui) => {
      if (!active || !ui) return;
      if (ui.theme && typeof ui.theme === "object") {
        void saveTheme(ui.theme as ThemeConfig, false);
        const loaded = loadTheme();
        setTheme(loaded);
        applyTheme(loaded);
      }
      if (ui.identity && typeof ui.identity === "object") {
        void saveIdentity(ui.identity as HanaIdentity, false);
        setIdentity(loadIdentity());
      }
      if (ui.accessibility && typeof ui.accessibility === "object") {
        void saveAccessibility(ui.accessibility as AccessibilityConfig, false);
        const loaded = loadAccessibility();
        setAcc(loaded);
        applyAccessibility(loaded);
      }
    });

    return () => {
      active = false;
      window.removeEventListener(APPEARANCE_SYNC_EVENT, handleSync);
    };
    // A cópia local inicial é capturada uma vez; o banco passa a ser oficial.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSave = async () => {
    applyTheme(theme);
    setShowToast(await saveTheme(theme));
  };

  useEffect(() => {
    if (!showToast) return;
    const timer = setTimeout(() => setShowToast(false), 3000);
    return () => clearTimeout(timer);
  }, [showToast]);

  const applyPreset = (preset: ThemePreset) => {
    pushTheme({
      primary: preset.primary,
      secondary: preset.secondary,
      gradientStart: preset.gradientStart,
      gradientEnd: preset.gradientEnd,
      gradientAngle: preset.gradientAngle,
      bgTone: preset.tone,
      opacity: preset.opacity,
      blur: preset.blur ?? DEFAULT_THEME.blur,
      saturation: preset.saturation ?? 100,
      brightness: preset.brightness ?? 100,
    });
  };

  // Sub-tab definitions
  const subTabs: { id: SubTab; icon: React.ReactNode; label: string }[] = [
    { id: "appearance", icon: <Palette size={16} />, label: t("personalization.appearance") },
    { id: "identity", icon: <UserRound size={16} />, label: t("personalization.identity") },
    { id: "accessibility", icon: <Accessibility size={16} />, label: t("personalization.accessibility") },
  ];

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] hana-glass p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-300">
      <TabHeader
        icon={<Paintbrush size={24} />}
        title={t("personalization.title")}
        subtitle={t("personalization.subtitle")}
      />

      {/* Sub-tab navigation */}
      <div className="flex gap-1 mb-6 p-1 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.05)] rounded-xl w-fit">
        {subTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setSubTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
              subTab === tab.id
                ? "bg-[color-mix(in_srgb,var(--accent)_18%,transparent)] text-white shadow-sm"
                : "text-[var(--text-secondary)] hover:text-white hover:bg-white/5"
            }`}
          >
            <span className={subTab === tab.id ? "text-[var(--accent)]" : "text-[var(--text-muted)]"}>
              {tab.icon}
            </span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── APPEARANCE TAB ─────────────────────────────────── */}
      {subTab === "appearance" && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
          {/* Left column: settings */}
          <div className="flex flex-col gap-4">
            {/* Theme presets — grid of color swatches */}
            <div className="bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.05)] rounded-xl p-4">
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <Sparkles size={12} /> {t("personalization.presetsTitle")}
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                {THEME_PRESETS.map((preset) => {
                  const active = isPresetActive(theme, preset);
                  return (
                    <button
                      key={preset.name}
                      type="button"
                      onClick={() => applyPreset(preset)}
                      className={`flex flex-col items-center gap-1.5 rounded-lg border p-2.5 transition-all text-left ${
                        active
                          ? "border-[var(--accent)]/80 bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] scale-[1.02]"
                          : "border-white/10 hover:border-white/30 bg-black/30"
                      }`}
                    >
                      <span
                        className="h-6 w-full rounded-md border border-white/10"
                        style={{
                          background: `linear-gradient(${preset.gradientAngle}deg, ${preset.primary}, ${preset.gradientEnd})`,
                        }}
                      />
                      <div className="flex items-center gap-1.5 w-full">
                        <span
                          className="h-2.5 w-2.5 rounded-full shrink-0 border border-white/20"
                          style={{ backgroundColor: preset.primary }}
                        />
                        <span className="text-[11px] text-[var(--text-secondary)] font-medium truncate">
                          {preset.name}
                        </span>
                        {active && (
                          <span className="text-[9px] text-[var(--accent)] font-bold ml-auto shrink-0">
                            {t("personalization.activePreset")}
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Main colors */}
            <AccordionSection
              title={t("personalization.mainColors")}
              icon={<Droplets size={12} />}
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <ColorField
                  label={t("personalization.primaryColor")}
                  hint={t("personalization.primaryHint")}
                  value={theme.primary}
                  onChange={(hex) => pushTheme({ primary: hex, gradientStart: hex })}
                />
                <ColorField
                  label={t("personalization.secondaryColor")}
                  hint={t("personalization.secondaryHint")}
                  value={theme.secondary}
                  onChange={(hex) => pushTheme({ secondary: hex })}
                />
              </div>
            </AccordionSection>

            {/* Gradient */}
            <AccordionSection
              title={t("personalization.gradient")}
              icon={<Sparkles size={12} />}
            >
              <div
                className="h-10 w-full rounded-lg border border-white/10 mb-4 shadow-inner"
                style={{
                  background: `linear-gradient(${theme.gradientAngle}deg, ${theme.gradientStart}, ${theme.gradientEnd})`,
                }}
                title={t("personalization.gradientPreview")}
              />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                <ColorField
                  label={t("personalization.gradientStart")}
                  value={theme.gradientStart}
                  onChange={(hex) => pushTheme({ gradientStart: hex })}
                />
                <ColorField
                  label={t("personalization.gradientEnd")}
                  value={theme.gradientEnd}
                  onChange={(hex) => pushTheme({ gradientEnd: hex })}
                />
              </div>
              <SliderField
                label={t("personalization.gradientAngle")}
                value={theme.gradientAngle}
                min={0}
                max={360}
                step={5}
                display={`${theme.gradientAngle}°`}
                accent={theme.primary}
                onChange={(v) => pushTheme({ gradientAngle: v })}
              />
            </AccordionSection>

            {/* Color balance */}
            <AccordionSection
              title={t("personalization.colorBalance")}
              icon={<Contrast size={12} />}
            >
              <div className="flex flex-col gap-4">
                <SliderField
                  label={t("personalization.saturation")}
                  value={theme.saturation}
                  min={0}
                  max={200}
                  step={5}
                  display={`${theme.saturation}%`}
                  accent={theme.primary}
                  onChange={(v) => pushTheme({ saturation: v })}
                />
                <SliderField
                  label={t("personalization.brightness")}
                  value={theme.brightness}
                  min={40}
                  max={160}
                  step={5}
                  display={`${theme.brightness}%`}
                  accent={theme.primary}
                  onChange={(v) => pushTheme({ brightness: v })}
                />
              </div>
            </AccordionSection>

            {/* Background + transparency + blur */}
            <AccordionSection
              title={t("personalization.bgTone")}
              icon={<LayoutGrid size={12} />}
            >
              <div className="grid grid-cols-4 gap-2 mb-5">
                {BG_TONES.map((tone) => (
                  <button
                    key={tone.rgb}
                    type="button"
                    onClick={() => pushTheme({ bgTone: tone.rgb })}
                    className={`flex flex-col items-center gap-1.5 rounded-lg border p-2 transition-all ${
                      theme.bgTone === tone.rgb
                        ? "border-white/70 scale-[1.03]"
                        : "border-white/10 hover:border-white/30"
                    }`}
                  >
                    <span
                      className="h-8 w-full rounded-md border border-white/10"
                      style={{ backgroundColor: `rgb(${tone.rgb})` }}
                    />
                    <span className="text-[10px] text-[var(--text-secondary)] font-medium">{tone.name}</span>
                  </button>
                ))}
              </div>

              <div className="flex flex-col gap-5">
                <SliderField
                  label={t("personalization.bgTransparency")}
                  value={theme.opacity}
                  min={0.1}
                  max={1}
                  step={0.05}
                  display={`${Math.round(theme.opacity * 100)}%`}
                  accent={theme.primary}
                  onChange={(v) => pushTheme({ opacity: v })}
                />
                <SliderField
                  label={t("personalization.bgBlur")}
                  value={theme.blur}
                  min={0}
                  max={40}
                  step={1}
                  display={`${theme.blur}px`}
                  accent={theme.primary}
                  onChange={(v) => pushTheme({ blur: v })}
                />
              </div>
              <p className="mt-3 text-[10px] text-[var(--text-muted)] leading-relaxed">
                {t("personalization.bgBlurHint")}
              </p>
            </AccordionSection>

            {/* Border radius */}
            <AccordionSection
              title={t("personalization.borderRadius")}
              icon={<Radius size={12} />}
              defaultOpen={false}
            >
              <div className="flex gap-2">
                {([
                  { id: "sm", label: t("personalization.borderRadiusSm") },
                  { id: "md", label: t("personalization.borderRadiusMd") },
                  { id: "lg", label: t("personalization.borderRadiusLg") },
                ] as const).map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => pushTheme({ borderRadius: opt.id })}
                    className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                      theme.borderRadius === opt.id
                        ? "border-[var(--accent)]/70 bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-white"
                        : "border-[var(--border-strong)] bg-black/40 text-[var(--text-secondary)] hover:border-white/30"
                    }`}
                    style={{ borderRadius: opt.id === "sm" ? "6px" : opt.id === "md" ? "10px" : "16px" }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </AccordionSection>

            {/* Actions */}
            <div className="flex items-center justify-between gap-3 flex-wrap pt-2">
              <div
                className="px-6 py-3 rounded-xl font-bold font-mono text-white transition-all duration-500 shadow-inner"
                style={{ backgroundImage: "var(--accent-gradient)" }}
              >
                HANA_OS_ACTIVE
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={() => pushTheme({ ...DEFAULT_THEME })}
                  variant="secondary"
                  icon={<RotateCcw size={16} />}
                >
                  {t("personalization.resetDefault")}
                </Button>
                <Button onClick={handleSave} variant="secondary" icon={<Save size={16} />}>
                  {t("personalization.saveTheme")}
                </Button>
              </div>
            </div>
          </div>

          {/* Right column: live preview (sticky) */}
          <div className="hidden lg:block">
            <div className="sticky top-4">
              <ThemePreview theme={theme} />
            </div>
          </div>
        </div>
      )}

      {/* ── IDENTITY TAB ───────────────────────────────────── */}
      {subTab === "identity" && (
        <div className="max-w-lg">
          <Card className="flex flex-col overflow-hidden">
            {/* Full-bleed banner */}
            <div className="relative w-full h-[168px] shrink-0 overflow-hidden bg-black/40">
              <img
                src="/hana_foto_01.png"
                alt=""
                className="absolute inset-0 h-full w-full object-cover object-center transition-transform duration-700 group-hover:scale-105"
                draggable={false}
              />
              <div
                className="absolute inset-0 opacity-25 pointer-events-none"
                style={{
                  background: `linear-gradient(${theme.gradientAngle}deg, ${theme.gradientStart}, transparent 55%)`,
                }}
              />
              <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/70 to-transparent pointer-events-none" />
            </div>

            {/* Avatar + fields */}
            <div className="relative z-10 flex w-full flex-col items-center px-5 pb-6 pt-0">
              <label
                className="relative z-20 -mt-[4.5rem] mb-4 h-36 w-36 shrink-0 cursor-pointer overflow-hidden rounded-full border-4 border-[var(--surface-1)] bg-black shadow-[0_10px_28px_rgba(0,0,0,0.55)] ring-2 ring-white/20 transition-transform duration-300 hover:scale-[1.03]"
                title={t("personalization.avatarUpload")}
              >
                <img
                  src={identity.avatar}
                  alt="Avatar da assistente"
                  className="h-full w-full object-cover"
                />
                <span className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 transition-opacity hover:opacity-100">
                  <ImagePlus size={28} className="text-white" />
                </span>
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => void handleAvatarUpload(e.target.files?.[0])}
                />
              </label>

              {avatarError ? (
                <span className="mb-2 text-center text-[11px] text-red-400">{avatarError}</span>
              ) : null}

              <label className="mb-1.5 flex items-center justify-center gap-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                <UserRound size={11} /> {t("personalization.identityName")}
              </label>
              <input
                type="text"
                value={identity.name}
                maxLength={40}
                onChange={(e) => updateIdentity({ name: e.target.value })}
                className="mb-2 w-full max-w-[280px] rounded-lg border border-[var(--border-strong)] bg-black/45 px-3 py-2.5 text-center font-mono text-xl font-extrabold tracking-[0.18em] outline-none transition-all focus:ring-2"
                style={{ color: theme.primary, "--tw-ring-color": theme.primary } as React.CSSProperties}
              />
              <input
                type="text"
                value={identity.subtitle}
                maxLength={60}
                placeholder={t("personalization.identitySubtitle")}
                onChange={(e) => updateIdentity({ subtitle: e.target.value })}
                className="mb-3 w-full max-w-[280px] rounded-lg border border-[var(--border-strong)] bg-black/35 px-3 py-2 text-center text-sm uppercase tracking-widest text-[var(--text-secondary)] outline-none transition-all focus:ring-1"
              />

              <div className="mt-1 flex w-full max-w-[320px] flex-wrap items-center justify-center gap-2">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/35 px-4 py-1.5">
                  <span
                    className="h-2 w-2 animate-pulse rounded-full"
                    style={{ backgroundColor: theme.primary }}
                  />
                  <span className="font-mono text-xs text-[var(--text-muted)]">
                    {t("personalization.identityConnected")}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    updateIdentity({ ...DEFAULT_IDENTITY });
                    setAvatarError("");
                  }}
                  title="Restaurar identidade padrão"
                  aria-label="Restaurar identidade padrão da Hana"
                  className="group/reset inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/40 px-3 py-1.5 text-[11px] font-medium text-[var(--text-muted)] transition-all hover:border-white/30 hover:bg-black/60 hover:text-white"
                >
                  <RotateCcw
                    size={13}
                    className="shrink-0 transition-transform group-hover/reset:rotate-[-45deg]"
                  />
                  <span>{t("personalization.identityRestore")}</span>
                </button>
              </div>
              <p className="mt-3 max-w-[280px] text-center text-[10px] leading-relaxed text-[var(--text-muted)]">
                <strong className="text-[var(--text-secondary)]">{t("personalization.identityRestore")}</strong>{" "}
                {t("personalization.identityRestoreHint")}
              </p>
            </div>
          </Card>
        </div>
      )}

      {/* ── ACCESSIBILITY TAB ───────────────────────────────── */}
      {subTab === "accessibility" && (
        <Card className="max-w-2xl">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500 flex items-center justify-center text-emerald-300">
              <Accessibility size={20} />
            </div>
            <div>
              <h3 className="font-bold text-[var(--text-primary)] text-lg">{t("personalization.accessibilityTitle")}</h3>
              <p className="text-xs text-[var(--text-muted)]">{t("personalization.accessibilityDesc")}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
            {/* Font selector */}
            <div>
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">
                {t("personalization.readingFont")}
              </span>
              <div className="flex flex-wrap gap-2">
                {ACCESSIBILITY_FONTS.map((font) => {
                  const fontLabelKey =
                    font.id === "default"
                      ? "personalization.fontDefault"
                      : font.id === "verdana"
                        ? "personalization.fontVerdana"
                        : font.id === "opendyslexic"
                          ? "personalization.fontOpenDyslexic"
                          : "personalization.fontComic";
                  return (
                    <button
                      key={font.id}
                      type="button"
                      onClick={() => updateAcc({ font: font.id })}
                      className={`px-4 py-2 rounded-lg border text-sm transition-all ${
                        acc.font === font.id
                          ? "border-emerald-400 bg-emerald-500/15 text-emerald-200"
                          : "border-[var(--border-strong)] bg-black/40 text-[var(--text-secondary)] hover:border-white/30"
                      }`}
                      style={{ fontFamily: font.stack }}
                    >
                      {t(fontLabelKey)}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Font scale */}
            <div>
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2 block">
                {t("personalization.textSize")}:{" "}
                <b className="text-[var(--text-secondary)]">{acc.fontScale}%</b>
              </span>
              <input
                type="range"
                min="85"
                max="140"
                step="5"
                className="w-full h-2 bg-[rgba(0,0,0,0.5)] rounded-lg appearance-none cursor-pointer accent-emerald-400"
                value={acc.fontScale}
                onChange={(e) => updateAcc({ fontScale: parseInt(e.target.value, 10) })}
              />
            </div>

            {/* Toggle options */}
            {(
              [
                {
                  key: "spacing" as const,
                  label: t("personalization.spacing"),
                  hint: t("personalization.spacingHint"),
                },
                {
                  key: "reduceMotion" as const,
                  label: t("personalization.reduceMotion"),
                  hint: t("personalization.reduceMotionHint"),
                },
                {
                  key: "focusMode" as const,
                  label: t("personalization.focusMode"),
                  hint: t("personalization.focusModeHint"),
                },
                {
                  key: "highContrast" as const,
                  label: t("personalization.highContrast"),
                  hint: t("personalization.highContrastHint"),
                },
                {
                  key: "bigCursor" as const,
                  label: t("personalization.bigCursor"),
                  hint: t("personalization.bigCursorHint"),
                },
                {
                  key: "lineFocus" as const,
                  label: t("personalization.lineFocus"),
                  hint: t("personalization.lineFocusHint"),
                },
                {
                  key: "narrowText" as const,
                  label: t("personalization.narrowText"),
                  hint: t("personalization.narrowTextHint"),
                },
                {
                  key: "noItalic" as const,
                  label: t("personalization.noItalic"),
                  hint: t("personalization.noItalicHint"),
                },
              ]
            ).map((item) => (
              <label
                key={item.key}
                className="flex items-start gap-3 bg-black/30 border border-[var(--border-strong)] rounded-xl p-3 cursor-pointer hover:border-white/25 transition-all"
              >
                <input
                  type="checkbox"
                  checked={acc[item.key]}
                  onChange={(e) => updateAcc({ [item.key]: e.target.checked })}
                  className="mt-1 accent-emerald-400 w-4 h-4"
                />
                <span>
                  <span className="block text-sm font-bold text-[var(--text-primary)]">{item.label}</span>
                  <span className="block text-xs text-[var(--text-muted)]">{item.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </Card>
      )}

      {/* ── Toast ───────────────────────────────────────────── */}
      <div
        className={`fixed bottom-10 left-1/2 -translate-x-1/2 px-6 py-3 rounded-full font-bold backdrop-blur-md transition-all duration-300 z-50 flex items-center gap-2 pointer-events-none ${
          syncPending
            ? "bg-amber-500/20 border border-amber-500/50 text-amber-300 shadow-[0_0_20px_rgba(245,158,11,0.2)]"
            : "bg-green-500/20 border border-green-500/50 text-green-400 shadow-[0_0_20px_rgba(34,197,94,0.3)]"
        } ${
          showToast || syncPending ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4"
        }`}
      >
        {syncPending ? <Save size={20} /> : <CheckCircle2 size={20} />}
        {t(syncPending ? "personalization.syncPending" : "personalization.themeSaved")}
      </div>
    </div>
  );
}
