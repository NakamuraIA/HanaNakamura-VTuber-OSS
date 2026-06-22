import { useEffect, useMemo, useState } from "react";
import { Gauge, Route } from "lucide-react";
import { ApiController } from "../../../controllers/api";
import { OpenRouterEndpoint, OpenRouterRoutingConfig } from "../../../models/types";
import { CatalogPicker, CatalogPickerOption } from "./CatalogPicker";

export const DEFAULT_OPENROUTER_ROUTING: OpenRouterRoutingConfig = {
  preferredEndpoint: "",
  allowFallbacks: true,
  requireParameters: false,
  dataCollection: "allow",
  zdr: false,
};

interface OpenRouterEndpointPickerProps {
  model: string;
  value?: OpenRouterRoutingConfig;
  onChange: (value: OpenRouterRoutingConfig) => void;
  compact?: boolean;
}

function endpointPrice(endpoint: OpenRouterEndpoint): number | null {
  /** Produce a stable endpoint price score for the shared cheap filter. */
  const values = [Number(endpoint.pricing?.prompt), Number(endpoint.pricing?.completion)]
    .filter((value) => Number.isFinite(value) && value >= 0);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function formatMetric(value: number | null | undefined, suffix: string): string {
  /** Format optional OpenRouter performance values without inventing missing data. */
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}${suffix}` : "";
}

function pricePerMillion(value: unknown): string {
  /** OpenRouter reporta preco POR TOKEN; humanos leem por 1M tokens. */
  const n = Number(value);
  if (!Number.isFinite(n)) return "?";
  const perM = n * 1_000_000;
  if (perM === 0) return "$0";
  if (perM >= 100) return `$${perM.toFixed(0)}`;
  if (perM < 0.01) return "<$0.01";
  return `$${perM.toFixed(2)}`;
}

function endpointPriceLabel(endpoint: OpenRouterEndpoint): string {
  const hasIn = endpoint.pricing?.prompt != null && endpoint.pricing?.prompt !== "";
  const hasOut = endpoint.pricing?.completion != null && endpoint.pricing?.completion !== "";
  if (!hasIn && !hasOut) return "";
  if (Number(endpoint.pricing?.prompt) === 0 && Number(endpoint.pricing?.completion) === 0) return "grátis";
  return `in ${pricePerMillion(endpoint.pricing?.prompt)} / out ${pricePerMillion(endpoint.pricing?.completion)} /M`;
}

export function OpenRouterEndpointPicker({ model, value, onChange, compact = false }: OpenRouterEndpointPickerProps) {
  const routing = { ...DEFAULT_OPENROUTER_ROUTING, ...(value || {}) };
  const [endpoints, setEndpoints] = useState<OpenRouterEndpoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    if (!model) {
      setEndpoints([]);
      return;
    }
    setLoading(true);
    ApiController.getOpenRouterEndpoints(model).then((result) => {
      if (!active) return;
      setEndpoints(result.endpoints || []);
      setError(result.error || "");
      setLoading(false);
    });
    return () => { active = false; };
  }, [model]);

  const options = useMemo<CatalogPickerOption[]>(() => [
    {
      value: "",
      label: "Automático pelo OpenRouter",
      favoriteId: "openrouter:auto",
      secondary: "Balanceamento e fallback padrão",
      badges: [{ label: "auto", tone: "cyan" }],
    },
    ...endpoints.map((endpoint) => ({
      value: endpoint.slug,
      label: endpoint.providerName || endpoint.name || endpoint.slug,
      favoriteId: `openrouter-endpoint:${endpoint.slug}`,
      secondary: endpoint.slug,
      description: [
        endpoint.quantization,
        formatMetric(endpoint.uptimeLast30m, "% uptime"),
        formatMetric(endpoint.latencyLast30m, "ms"),
        formatMetric(endpoint.throughputLast30m, " tok/s"),
      ].filter(Boolean).join(" · "),
      priceScore: endpointPrice(endpoint),
      priceLabel: endpointPriceLabel(endpoint),
      contextTokens: endpoint.contextLength || undefined,
      capabilityScore: endpoint.supportedParameters?.length || 0,
      performanceScore: endpoint.throughputLast30m ?? (
        typeof endpoint.latencyLast30m === "number" && endpoint.latencyLast30m > 0 ? 1 / endpoint.latencyLast30m : null
      ),
      online: endpoint.status === "online",
      quantized: Boolean(endpoint.quantization),
      supportsTools: endpoint.supportedParameters?.includes("tools"),
      badges: [
        { label: endpoint.status || "unknown", tone: endpoint.status === "online" ? "green" as const : "amber" as const },
        ...(endpoint.quantization ? [{ label: endpoint.quantization, tone: "purple" as const }] : []),
      ],
    })),
  ], [endpoints]);

  const update = <K extends keyof OpenRouterRoutingConfig>(field: K, next: OpenRouterRoutingConfig[K]) => {
    onChange({ ...routing, [field]: next });
  };

  return (
    <div className="rounded-lg border border-cyan-400/20 bg-cyan-500/[0.04] p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-cyan-200">
          <Route size={14} /> Endpoint OpenRouter
        </span>
        <span className="text-[9px] font-mono text-[var(--text-muted)]">
          {loading ? "consultando..." : error ? "catálogo indisponível" : `${endpoints.length} endpoints`}
        </span>
      </div>
      <CatalogPicker
        value={routing.preferredEndpoint}
        options={options}
        onChange={(selected) =>
          // Escolher um endpoint especifico FIXA nele (sem fallback). Voltar pro
          // "Automatico" religa o fallback padrao do OpenRouter.
          onChange({ ...routing, preferredEndpoint: selected, allowFallbacks: selected ? false : true })
        }
        favoriteNamespace={`openrouter-endpoints:${model}`}
        placeholder="Automático pelo OpenRouter"
        searchPlaceholder="Buscar endpoint, quantização ou provider..."
        emptyMessage="Nenhum endpoint corresponde aos filtros."
        accent="cyan"
        compact={compact}
        endpointFilters
      />
      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        <label className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]" title="Se ligado, o OpenRouter pode trocar pra outro provider. Desligue pra FIXAR no escolhido."><input type="checkbox" checked={routing.allowFallbacks} onChange={(e) => update("allowFallbacks", e.target.checked)} /> permitir trocar de provider</label>
        <label className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]"><input type="checkbox" checked={routing.requireParameters} onChange={(e) => update("requireParameters", e.target.checked)} /> exigir parâmetros</label>
        <label className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]"><input type="checkbox" checked={routing.dataCollection === "deny"} onChange={(e) => update("dataCollection", e.target.checked ? "deny" : "allow")} /> negar coleta</label>
        <label className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]"><input type="checkbox" checked={routing.zdr} onChange={(e) => update("zdr", e.target.checked)} /> <Gauge size={11} /> exigir ZDR</label>
      </div>
      {routing.preferredEndpoint && !loading && !endpoints.some((endpoint) => endpoint.slug === routing.preferredEndpoint) && (
        <p className="mt-2 text-[10px] font-bold text-amber-300">Endpoint salvo não aparece mais no catálogo atual.</p>
      )}
    </div>
  );
}
