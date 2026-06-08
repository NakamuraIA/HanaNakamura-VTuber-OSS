import { createPortal } from "react-dom";
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Check,
  ChevronDown,
  Coins,
  Eye,
  FileText,
  Gauge,
  Search,
  Sparkles,
  Star,
  Wrench,
  X,
} from "lucide-react";

const FAVORITES_STORAGE_KEY = "hana_catalog_favorites_v1";
const FAVORITES_EVENT = "hana:catalog-favorites";
const MAX_RENDERED_OPTIONS = 180;

type Accent = "purple" | "emerald" | "blue" | "pink" | "cyan" | "zinc";
type FilterId = "all" | "favorites" | "free" | "cheap" | "context" | "capable" | "vision" | "tools" | "docs" | "online" | "fast" | "quantized";

export interface CatalogPickerBadge {
  label: string;
  tone?: "neutral" | "green" | "blue" | "cyan" | "purple" | "amber" | "pink";
}

export interface CatalogPickerOption {
  value: string;
  label: string;
  favoriteId?: string;
  secondary?: string;
  description?: string;
  free?: boolean;
  priceScore?: number | null;
  priceLabel?: string;
  contextTokens?: number;
  capabilityScore?: number;
  performanceScore?: number | null;
  online?: boolean;
  quantized?: boolean;
  supportsVision?: boolean;
  supportsTools?: boolean;
  supportsDocuments?: boolean;
  badges?: CatalogPickerBadge[];
}

interface CatalogPickerProps {
  value: string;
  options: CatalogPickerOption[];
  onChange: (value: string) => void;
  favoriteNamespace: string;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  accent?: Accent;
  disabled?: boolean;
  showAdvancedFilters?: boolean;
  compact?: boolean;
  endpointFilters?: boolean;
}

interface FavoritesPayload {
  namespace: string;
  ids: string[];
}

const ACCENT_STYLES: Record<Accent, { border: string; text: string; ring: string; selected: string }> = {
  purple: {
    border: "hover:border-purple-400/60",
    text: "text-purple-300",
    ring: "focus-visible:ring-purple-400/50",
    selected: "border-purple-400/50 bg-purple-500/10",
  },
  emerald: {
    border: "hover:border-emerald-400/60",
    text: "text-emerald-300",
    ring: "focus-visible:ring-emerald-400/50",
    selected: "border-emerald-400/50 bg-emerald-500/10",
  },
  blue: {
    border: "hover:border-blue-400/60",
    text: "text-blue-300",
    ring: "focus-visible:ring-blue-400/50",
    selected: "border-blue-400/50 bg-blue-500/10",
  },
  pink: {
    border: "hover:border-pink-400/60",
    text: "text-pink-300",
    ring: "focus-visible:ring-pink-400/50",
    selected: "border-pink-400/50 bg-pink-500/10",
  },
  cyan: {
    border: "hover:border-cyan-400/60",
    text: "text-cyan-300",
    ring: "focus-visible:ring-cyan-400/50",
    selected: "border-cyan-400/50 bg-cyan-500/10",
  },
  zinc: {
    border: "hover:border-zinc-500",
    text: "text-zinc-200",
    ring: "focus-visible:ring-zinc-500/50",
    selected: "border-zinc-500 bg-zinc-800/80",
  },
};

const BADGE_STYLES: Record<NonNullable<CatalogPickerBadge["tone"]>, string> = {
  neutral: "border-white/10 bg-white/5 text-zinc-400",
  green: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200",
  blue: "border-blue-400/20 bg-blue-500/10 text-blue-200",
  cyan: "border-cyan-400/20 bg-cyan-500/10 text-cyan-200",
  purple: "border-purple-400/20 bg-purple-500/10 text-purple-200",
  amber: "border-amber-400/20 bg-amber-500/10 text-amber-200",
  pink: "border-pink-400/20 bg-pink-500/10 text-pink-200",
};

const FILTER_LABELS: Record<FilterId, { label: string; icon?: LucideIcon }> = {
  all: { label: "Todos" },
  favorites: { label: "Favoritos", icon: Star },
  free: { label: "Gratis", icon: Sparkles },
  cheap: { label: "Baratos", icon: Coins },
  context: { label: "Contexto +", icon: Gauge },
  capable: { label: "Recursos +", icon: Sparkles },
  vision: { label: "Visao", icon: Eye },
  tools: { label: "Tools", icon: Wrench },
  docs: { label: "Docs", icon: FileText },
  online: { label: "Online" },
  fast: { label: "Rápidos", icon: Gauge },
  quantized: { label: "Quantizados" },
};

function favoriteKey(option: CatalogPickerOption): string {
  /** Keep favorite identity stable when two providers publish the same model id. */
  return option.favoriteId || option.value;
}

function readFavorites(namespace: string): Set<string> {
  /** Read one favorite namespace from versioned local storage. */
  try {
    const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) as Record<string, string[]> : {};
    return new Set(Array.isArray(parsed[namespace]) ? parsed[namespace] : []);
  } catch {
    return new Set();
  }
}

function writeFavorites(namespace: string, favorites: Set<string>): void {
  /** Persist favorites and notify other pickers in the same page. */
  try {
    const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) as Record<string, string[]> : {};
    parsed[namespace] = Array.from(favorites);
    localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(parsed));
    window.dispatchEvent(new CustomEvent<FavoritesPayload>(FAVORITES_EVENT, {
      detail: { namespace, ids: parsed[namespace] },
    }));
  } catch {
    // Favorites are a frontend convenience; storage failure must not block selection.
  }
}

function normalizeSearch(value: string): string {
  /** Normalize accents and casing for forgiving catalog searches. */
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function percentileCutoff(values: number[], fraction: number, fallback: number): number {
  /** Return a stable percentile cutoff without mutating source arrays. */
  if (values.length === 0) return fallback;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * fraction)))] ?? fallback;
}

function compactTokenCount(tokens?: number): string {
  /** Format context windows without widening model rows. */
  if (!tokens) return "";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(tokens % 1_000_000 === 0 ? 0 : 1)}M ctx`;
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K ctx`;
  return `${tokens} ctx`;
}

export function CatalogPicker({
  value,
  options,
  onChange,
  favoriteNamespace,
  placeholder = "Selecione",
  searchPlaceholder = "Buscar por nome ou ID...",
  emptyMessage = "Nenhuma opcao encontrada.",
  accent = "purple",
  disabled = false,
  showAdvancedFilters = true,
  compact = false,
  endpointFilters = false,
}: CatalogPickerProps) {
  /** Render a searchable provider-scoped picker with local favorites and objective filters. */
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterId>("all");
  const [favorites, setFavorites] = useState<Set<string>>(() => readFavorites(favoriteNamespace));
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({});
  const deferredQuery = useDeferredValue(query);
  const style = ACCENT_STYLES[accent];

  useEffect(() => {
    setFavorites(readFavorites(favoriteNamespace));
    setActiveFilter("all");
  }, [favoriteNamespace]);

  useEffect(() => {
    const syncFavorites = (event: Event) => {
      const detail = (event as CustomEvent<FavoritesPayload>).detail;
      if (detail?.namespace === favoriteNamespace) setFavorites(new Set(detail.ids));
    };
    window.addEventListener(FAVORITES_EVENT, syncFavorites);
    return () => window.removeEventListener(FAVORITES_EVENT, syncFavorites);
  }, [favoriteNamespace]);

  useEffect(() => {
    if (!open) return;

    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const viewportPadding = 12;
      const width = Math.min(Math.max(rect.width, 340), Math.max(280, window.innerWidth - viewportPadding * 2));
      const estimatedHeight = compact ? 390 : 480;
      const left = Math.min(
        Math.max(viewportPadding, rect.left),
        Math.max(viewportPadding, window.innerWidth - width - viewportPadding),
      );
      const opensAbove = window.innerHeight - rect.bottom < Math.min(estimatedHeight, rect.top);
      const top = opensAbove
        ? Math.max(viewportPadding, rect.top - estimatedHeight - 8)
        : Math.min(window.innerHeight - 120, rect.bottom + 8);
      setPanelStyle({ left, top, width });
    };

    const closeOnOutside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !panelRef.current?.contains(target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    window.addEventListener("pointerdown", closeOnOutside);
    window.addEventListener("keydown", closeOnEscape);
    window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      window.removeEventListener("pointerdown", closeOnOutside);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [compact, open]);

  const selected = options.find((option) => option.value === value);

  const filterAvailability = useMemo(() => {
    const priced = options.filter((option) => typeof option.priceScore === "number" && Number.isFinite(option.priceScore));
    return {
      favorites: favorites.size > 0,
      free: options.some((option) => option.free),
      cheap: priced.length > 1,
      context: options.some((option) => Boolean(option.contextTokens)),
      capable: options.some((option) => Boolean(option.capabilityScore)),
      vision: options.some((option) => option.supportsVision),
      tools: options.some((option) => option.supportsTools),
      docs: options.some((option) => option.supportsDocuments),
      online: options.some((option) => option.online),
      fast: options.some((option) => typeof option.performanceScore === "number"),
      quantized: options.some((option) => option.quantized),
    };
  }, [favorites.size, options]);

  const filteredOptions = useMemo(() => {
    const search = normalizeSearch(deferredQuery);
    const priceValues = options
      .map((option) => option.priceScore)
      .filter((price): price is number => typeof price === "number" && Number.isFinite(price) && price >= 0);
    const contextValues = options
      .map((option) => option.contextTokens)
      .filter((tokens): tokens is number => typeof tokens === "number" && tokens > 0);
    const capabilityValues = options
      .map((option) => option.capabilityScore)
      .filter((score): score is number => typeof score === "number" && score > 0);
    const cheapCutoff = percentileCutoff(priceValues, 0.25, Number.POSITIVE_INFINITY);
    const contextCutoff = percentileCutoff(contextValues, 0.75, 0);
    const capabilityCutoff = percentileCutoff(capabilityValues, 0.75, 0);
    const performanceValues = options
      .map((option) => option.performanceScore)
      .filter((score): score is number => typeof score === "number" && Number.isFinite(score) && score >= 0);
    const performanceCutoff = percentileCutoff(performanceValues, 0.75, 0);

    const matches = options.filter((option) => {
      const haystack = normalizeSearch([
        option.label,
        option.value,
        option.secondary,
        option.description,
        option.badges?.map((badge) => badge.label).join(" "),
      ].filter(Boolean).join(" "));
      if (search && !haystack.includes(search)) return false;

      const key = favoriteKey(option);
      if (activeFilter === "favorites") return favorites.has(key);
      if (activeFilter === "free") return Boolean(option.free);
      if (activeFilter === "cheap") {
        return Boolean(option.free) || (
          typeof option.priceScore === "number"
          && Number.isFinite(option.priceScore)
          && option.priceScore <= cheapCutoff
        );
      }
      if (activeFilter === "context") return Boolean(option.contextTokens && option.contextTokens >= contextCutoff);
      if (activeFilter === "capable") return Boolean(option.capabilityScore && option.capabilityScore >= capabilityCutoff);
      if (activeFilter === "vision") return Boolean(option.supportsVision);
      if (activeFilter === "tools") return Boolean(option.supportsTools);
      if (activeFilter === "docs") return Boolean(option.supportsDocuments);
      if (activeFilter === "online") return Boolean(option.online);
      if (activeFilter === "fast") return Boolean(typeof option.performanceScore === "number" && option.performanceScore >= performanceCutoff);
      if (activeFilter === "quantized") return Boolean(option.quantized);
      return true;
    });

    return matches.sort((left, right) => {
      const leftFavorite = favorites.has(favoriteKey(left)) ? 1 : 0;
      const rightFavorite = favorites.has(favoriteKey(right)) ? 1 : 0;
      if (leftFavorite !== rightFavorite) return rightFavorite - leftFavorite;
      if (activeFilter === "cheap") return (left.priceScore ?? Number.POSITIVE_INFINITY) - (right.priceScore ?? Number.POSITIVE_INFINITY);
      if (activeFilter === "context") return (right.contextTokens ?? 0) - (left.contextTokens ?? 0);
      if (activeFilter === "capable") return (right.capabilityScore ?? 0) - (left.capabilityScore ?? 0);
      if (activeFilter === "fast") return (right.performanceScore ?? 0) - (left.performanceScore ?? 0);
      return left.label.localeCompare(right.label, "pt-BR");
    });
  }, [activeFilter, deferredQuery, favorites, options]);

  const visibleOptions = filteredOptions.slice(0, MAX_RENDERED_OPTIONS);
  const availableFilters = (Object.keys(FILTER_LABELS) as FilterId[]).filter((filter) => {
    if (filter === "all") return true;
    if (["online", "fast", "quantized"].includes(filter)) return endpointFilters && filterAvailability[filter as keyof typeof filterAvailability];
    if (endpointFilters && ["free", "context", "capable", "vision", "tools", "docs"].includes(filter)) return false;
    if (!showAdvancedFilters && !["favorites"].includes(filter)) return false;
    return filterAvailability[filter as keyof typeof filterAvailability];
  });

  const toggleFavorite = (option: CatalogPickerOption) => {
    const key = favoriteKey(option);
    const next = new Set(favorites);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setFavorites(next);
    writeFavorites(favoriteNamespace, next);
  };

  const selectOption = (option: CatalogPickerOption) => {
    onChange(option.value);
    setOpen(false);
    setQuery("");
  };

  const panel = open && typeof document !== "undefined"
    ? createPortal(
      <div
        ref={panelRef}
        id={`${id}-panel`}
        style={panelStyle}
        className="fixed z-[120] overflow-hidden rounded-lg border border-zinc-700/90 bg-[#090b10]/98 shadow-[0_24px_80px_rgba(0,0,0,0.75)] backdrop-blur-xl"
      >
        <div className="border-b border-zinc-800 p-3">
          <div className="relative">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={searchPlaceholder}
              className={`h-10 w-full rounded-md border border-zinc-700 bg-black/40 pl-9 pr-9 font-mono text-xs text-zinc-100 outline-none placeholder:text-zinc-600 focus-visible:ring-2 ${style.ring}`}
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-zinc-500 hover:text-white"
                title="Limpar busca"
              >
                <X size={14} />
              </button>
            ) : null}
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {availableFilters.map((filter) => {
              const Icon = FILTER_LABELS[filter].icon;
              const active = activeFilter === filter;
              return (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setActiveFilter(filter)}
                  className={`inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 font-mono text-[10px] font-bold uppercase transition-colors ${
                    active
                      ? `${style.selected} ${style.text}`
                      : "border-zinc-800 bg-zinc-950/60 text-zinc-500 hover:border-zinc-600 hover:text-zinc-200"
                  }`}
                >
                  {Icon ? <Icon size={11} fill={filter === "favorites" && active ? "currentColor" : "none"} /> : null}
                  {FILTER_LABELS[filter].label}
                </button>
              );
            })}
          </div>
        </div>

        <div className={`${compact ? "max-h-[280px]" : "max-h-[360px]"} overflow-y-auto p-2 custom-scrollbar`}>
          {visibleOptions.length === 0 ? (
            <div className="px-4 py-10 text-center font-mono text-xs text-zinc-500">{emptyMessage}</div>
          ) : (
            visibleOptions.map((option) => {
              const optionFavorite = favorites.has(favoriteKey(option));
              const optionSelected = option.value === value;
              const contextLabel = compactTokenCount(option.contextTokens);
              return (
                <div
                  key={option.favoriteId || option.value}
                  className={`group/option mb-1 grid grid-cols-[minmax(0,1fr)_auto] gap-2 rounded-md border px-3 py-2.5 transition-colors ${
                    optionSelected
                      ? style.selected
                      : "border-transparent hover:border-zinc-700 hover:bg-zinc-900/80"
                  }`}
                  style={{ contentVisibility: "auto", containIntrinsicSize: "58px" }}
                >
                  <button
                    type="button"
                    onClick={() => selectOption(option)}
                    className="min-w-0 text-left"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {optionSelected ? <Check size={14} className={style.text} /> : null}
                      <span className="truncate text-sm font-semibold text-zinc-100">{option.label}</span>
                      {option.free ? (
                        <span className="shrink-0 rounded border border-emerald-400/20 bg-emerald-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase text-emerald-200">gratis</span>
                      ) : null}
                    </div>
                    {option.secondary ? (
                      <div className="mt-1 truncate font-mono text-[10px] text-zinc-500">{option.secondary}</div>
                    ) : null}
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {contextLabel ? (
                        <span className={BADGE_STYLES.neutral + " rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase"}>{contextLabel}</span>
                      ) : null}
                      {option.priceLabel ? (
                        <span className={BADGE_STYLES.pink + " rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase"}>{option.priceLabel}</span>
                      ) : null}
                      {option.badges?.map((badge) => (
                        <span
                          key={`${option.value}-${badge.label}`}
                          className={`${BADGE_STYLES[badge.tone || "neutral"]} rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase`}
                        >
                          {badge.label}
                        </span>
                      ))}
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => toggleFavorite(option)}
                    className={`self-start rounded p-1.5 transition-colors ${
                      optionFavorite ? "text-amber-300" : "text-zinc-700 hover:bg-zinc-800 hover:text-amber-200"
                    }`}
                    title={optionFavorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
                  >
                    <Star size={15} fill={optionFavorite ? "currentColor" : "none"} />
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="flex items-center justify-between border-t border-zinc-800 px-3 py-2 font-mono text-[10px] text-zinc-600">
          <span>{filteredOptions.length} resultado(s)</span>
          {filteredOptions.length > MAX_RENDERED_OPTIONS ? (
            <span>Mostrando {MAX_RENDERED_OPTIONS}. Refine a busca.</span>
          ) : (
            <span>{favorites.size} favorito(s)</span>
          )}
        </div>
      </div>,
      document.body,
    )
    : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => setOpen((current) => !current)}
        className={`flex min-h-10 w-full items-center justify-between gap-3 rounded-lg border border-zinc-700 bg-black/55 px-3 py-2 text-left shadow-inner outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${style.border} focus-visible:ring-2 ${style.ring}`}
      >
        <span className="min-w-0">
          <span className={`block truncate ${compact ? "text-xs" : "text-sm"} font-semibold text-zinc-100`}>
            {selected?.label || value || placeholder}
          </span>
          {selected?.secondary ? (
            <span className="mt-0.5 block truncate font-mono text-[9px] text-zinc-500">{selected.secondary}</span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {selected && favorites.has(favoriteKey(selected)) ? <Star size={13} className="text-amber-300" fill="currentColor" /> : null}
          <ChevronDown size={15} className={`${style.text} transition-transform ${open ? "rotate-180" : ""}`} />
        </span>
      </button>
      {panel}
    </>
  );
}
