/**
 * Gerenciador do catalogo de modelos (tabela `llm_models`).
 *
 * E a tela do banco de verdade: o que aparece aqui e exatamente o que a Hana
 * enxerga na hora de escolher modelo. Nao existe lista paralela.
 *
 * Preco: o banco guarda POR TOKEN (0.00000014), que e ilegivel e ainda vira
 * notacao cientifica ao ir e voltar. Aqui a pessoa digita em dolar por MILHAO,
 * como o provider anuncia, e a conversao acontece na borda.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";

import { ModelosApi, type ModeloCatalogo } from "../../../api/modelos";
import { Button } from "../shared/Button";

const CAPACIDADES = [
  { campo: "supportsVision", rotulo: "visão" },
  { campo: "supportsTools", rotulo: "tools" },
  { campo: "supportsDocuments", rotulo: "docs" },
  { campo: "supportsNativeSearch", rotulo: "busca web" },
  { campo: "supportsVideo", rotulo: "vídeo" },
  { campo: "free", rotulo: "grátis" },
] as const;

type Rascunho = {
  provider: string;
  id: string;
  label: string;
  maxInputTokens: string;
  maxOutputTokens: string;
  precoEntrada: string;
  precoSaida: string;
  supportsVision: boolean;
  supportsTools: boolean;
  supportsDocuments: boolean;
  supportsNativeSearch: boolean;
  supportsVideo: boolean;
  free: boolean;
};

const VAZIO: Rascunho = {
  provider: "",
  id: "",
  label: "",
  maxInputTokens: "",
  maxOutputTokens: "",
  precoEntrada: "",
  precoSaida: "",
  supportsVision: false,
  supportsTools: false,
  supportsDocuments: false,
  supportsNativeSearch: false,
  supportsVideo: false,
  free: false,
};

/** Preco pode ser string fixa ou faixas por contexto; pega a primeira faixa. */
function porToken(valor: unknown): number | null {
  if (Array.isArray(valor)) {
    const n = Number((valor[0] as { price?: unknown })?.price);
    return Number.isFinite(n) ? n : null;
  }
  const n = Number(valor);
  return Number.isFinite(n) ? n : null;
}

function paraMilhao(valor: unknown): string {
  const n = porToken(valor);
  if (n === null || n === 0) return "";
  return String(Number((n * 1_000_000).toFixed(4)));
}

function deMilhao(texto: string): string | null {
  const n = Number(String(texto).replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return null;
  // toFixed(12) evita "5e-08" chegar no banco como texto em notacao cientifica.
  return (n / 1_000_000).toFixed(12).replace(/0+$/, "");
}

function compacto(tokens?: number): string {
  if (!tokens) return "—";
  if (tokens >= 1_000_000) return `${Number((tokens / 1_000_000).toFixed(1))}M`;
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
  return String(tokens);
}

export function GerenciadorModelos() {
  const [itens, setItens] = useState<ModeloCatalogo[]>([]);
  const [porProvider, setPorProvider] = useState<Record<string, number>>({});
  const [filtro, setFiltro] = useState("");
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [rascunho, setRascunho] = useState<Rascunho | null>(null);
  const [editando, setEditando] = useState<{ provider: string; id: string } | null>(null);
  const [aviso, setAviso] = useState("");
  const [confirmando, setConfirmando] = useState<string>("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    const dados = await ModelosApi.listar();
    setItens(dados.itens);
    setPorProvider(dados.porProvider);
    setCarregando(false);
  }, []);

  useEffect(() => { void carregar(); }, [carregar]);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return itens.filter((m) => {
      if (filtro && m.provider !== filtro) return false;
      if (!termo) return true;
      return `${m.id} ${m.label}`.toLowerCase().includes(termo);
    });
  }, [itens, filtro, busca]);

  const abrirNovo = () => {
    setEditando(null);
    setRascunho({ ...VAZIO, provider: filtro || "" });
    setAviso("");
  };

  const abrirEdicao = (m: ModeloCatalogo) => {
    setEditando({ provider: m.provider, id: m.id });
    setRascunho({
      provider: m.provider,
      id: m.id,
      label: m.label || "",
      maxInputTokens: m.maxInputTokens ? String(m.maxInputTokens) : "",
      maxOutputTokens: m.maxOutputTokens ? String(m.maxOutputTokens) : "",
      precoEntrada: paraMilhao(m.pricing?.prompt),
      precoSaida: paraMilhao(m.pricing?.completion),
      supportsVision: Boolean(m.supportsVision),
      supportsTools: Boolean(m.supportsTools),
      supportsDocuments: Boolean(m.supportsDocuments),
      supportsNativeSearch: Boolean(m.supportsNativeSearch),
      supportsVideo: Boolean((m as { supportsVideo?: boolean }).supportsVideo),
      free: Boolean(m.free),
    });
    setAviso("");
  };

  const salvar = async () => {
    if (!rascunho) return;
    const provider = rascunho.provider.trim().toLowerCase();
    const id = rascunho.id.trim();
    if (!provider || !id) {
      setAviso("Provider e ID são obrigatórios.");
      return;
    }
    const entrada = deMilhao(rascunho.precoEntrada);
    const saida = deMilhao(rascunho.precoSaida);
    const modalidades = ["text"];
    if (rascunho.supportsVision) modalidades.push("image");
    if (rascunho.supportsVideo) modalidades.push("video");
    if (rascunho.supportsDocuments) modalidades.push("pdf");

    try {
      await ModelosApi.salvar({
        provider,
        id,
        label: rascunho.label.trim() || id,
        maxInputTokens: Number(rascunho.maxInputTokens) || undefined,
        maxOutputTokens: Number(rascunho.maxOutputTokens) || undefined,
        pricing: entrada || saida ? { prompt: entrada || "0", completion: saida || "0" } : undefined,
        inputModalities: modalidades,
        outputModalities: ["text"],
        supportedParameters: rascunho.supportsTools ? ["tools", "tool_choice"] : [],
        supportsVision: rascunho.supportsVision,
        supportsTools: rascunho.supportsTools,
        supportsDocuments: rascunho.supportsDocuments,
        supportsNativeSearch: rascunho.supportsNativeSearch,
        supportsVideo: rascunho.supportsVideo,
        free: rascunho.free,
      } as Parameters<typeof ModelosApi.salvar>[0]);
      setRascunho(null);
      setEditando(null);
      await carregar();
    } catch (erro) {
      setAviso(`Não salvou: ${erro instanceof Error ? erro.message : String(erro)}`);
    }
  };

  const apagar = async (m: ModeloCatalogo) => {
    const chave = `${m.provider}:${m.id}`;
    // Duas etapas de propósito: apagar aqui some com o modelo pra Hana também.
    if (confirmando !== chave) {
      setConfirmando(chave);
      return;
    }
    try {
      await ModelosApi.apagar(m.provider, m.id);
      setConfirmando("");
      await carregar();
    } catch (erro) {
      setAviso(`Não apagou: ${erro instanceof Error ? erro.message : String(erro)}`);
    }
  };

  const campo = "bg-black/60 border border-white/10 focus:border-[var(--cyan-neon)]/50 text-white rounded-md px-2.5 py-1.5 outline-none font-mono text-xs w-full";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setFiltro("")}
          className={`rounded-md border px-2 py-1 font-mono text-[10px] ${filtro === "" ? "border-[var(--cyan-neon)]/50 bg-[var(--cyan-neon)]/10 text-[var(--cyan-neon)]" : "border-white/10 text-[var(--text-muted)] hover:text-white"}`}
        >
          todos ({itens.length})
        </button>
        {Object.entries(porProvider).map(([nome, quantos]) => (
          <button
            key={nome}
            type="button"
            onClick={() => setFiltro(nome)}
            className={`rounded-md border px-2 py-1 font-mono text-[10px] ${filtro === nome ? "border-[var(--cyan-neon)]/50 bg-[var(--cyan-neon)]/10 text-[var(--cyan-neon)]" : "border-white/10 text-[var(--text-muted)] hover:text-white"}`}
          >
            {nome} ({quantos})
          </button>
        ))}
        <input
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="buscar..."
          className={`${campo} ml-auto max-w-[180px]`}
        />
        <Button onClick={() => void carregar()} variant="ghost" size="sm" iconOnly icon={<RefreshCw size={13} />} title="Recarregar" />
        <Button onClick={abrirNovo} variant="primary" size="sm" icon={<Plus size={13} />}>Adicionar</Button>
      </div>

      {rascunho && (
        <div className="rounded-lg border border-[var(--cyan-neon)]/25 bg-[var(--cyan-neon)]/[0.03] p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[11px] text-[var(--cyan-neon)]">
              {editando ? `editando ${editando.provider}/${editando.id}` : "novo modelo"}
            </span>
            <button type="button" onClick={() => { setRascunho(null); setEditando(null); }} className="text-[var(--text-muted)] hover:text-white">
              <X size={14} />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[10px] text-[var(--text-muted)]">provider</span>
              <input className={campo} value={rascunho.provider} disabled={Boolean(editando)} placeholder="qwen"
                onChange={(e) => setRascunho({ ...rascunho, provider: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1 md:col-span-2">
              <span className="font-mono text-[10px] text-[var(--text-muted)]">id do modelo (exato, como a API espera)</span>
              <input className={campo} value={rascunho.id} disabled={Boolean(editando)} placeholder="qwen3.7-flash"
                onChange={(e) => setRascunho({ ...rascunho, id: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1 md:col-span-3">
              <span className="font-mono text-[10px] text-[var(--text-muted)]">nome visível (opcional)</span>
              <input className={campo} value={rascunho.label} placeholder="Qwen3.7 Flash"
                onChange={(e) => setRascunho({ ...rascunho, label: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[10px] text-[var(--text-muted)]">contexto de entrada</span>
              <input className={campo} value={rascunho.maxInputTokens} placeholder="1000000" inputMode="numeric"
                onChange={(e) => setRascunho({ ...rascunho, maxInputTokens: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[10px] text-[var(--text-muted)]">preço entrada ($/milhão)</span>
              <input className={campo} value={rascunho.precoEntrada} placeholder="0.03"
                onChange={(e) => setRascunho({ ...rascunho, precoEntrada: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[10px] text-[var(--text-muted)]">preço saída ($/milhão)</span>
              <input className={campo} value={rascunho.precoSaida} placeholder="0.13"
                onChange={(e) => setRascunho({ ...rascunho, precoSaida: e.target.value })} />
            </label>
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {CAPACIDADES.map(({ campo: chave, rotulo }) => {
              const ativo = rascunho[chave];
              return (
                <button
                  key={chave}
                  type="button"
                  onClick={() => setRascunho({ ...rascunho, [chave]: !ativo })}
                  aria-pressed={ativo}
                  className={`rounded-md border px-2 py-1 font-mono text-[10px] ${ativo ? "border-[var(--cyan-neon)]/50 bg-[var(--cyan-neon)]/10 text-[var(--cyan-neon)]" : "border-white/10 text-[var(--text-muted)] hover:text-white"}`}
                >
                  {ativo ? "✓ " : ""}{rotulo}
                </button>
              );
            })}
          </div>

          {aviso && <p className="mt-2 font-mono text-[11px] text-amber-300">{aviso}</p>}

          <div className="mt-3 flex justify-end">
            <Button onClick={() => void salvar()} variant="primary" size="sm" icon={<Check size={13} />}>
              {editando ? "Salvar alterações" : "Cadastrar"}
            </Button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-white/10">
        <table className="w-full min-w-[620px] text-left font-mono text-[11px]">
          <thead>
            <tr className="border-b border-white/10 text-[10px] text-[var(--text-muted)]">
              <th className="px-3 py-2 font-normal">modelo</th>
              <th className="px-3 py-2 font-normal">provider</th>
              <th className="px-3 py-2 font-normal">ctx</th>
              <th className="px-3 py-2 font-normal">$/M in · out</th>
              <th className="px-3 py-2 font-normal">capacidades</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {carregando && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-[var(--text-muted)]">carregando…</td></tr>
            )}
            {!carregando && visiveis.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-[var(--text-muted)]">nenhum modelo aqui.</td></tr>
            )}
            {visiveis.map((m) => {
              const chave = `${m.provider}:${m.id}`;
              const caps = [
                m.supportsVision && "visão",
                m.supportsTools && "tools",
                m.supportsDocuments && "docs",
                m.supportsNativeSearch && "web",
                m.free && "grátis",
              ].filter(Boolean).join(" · ");
              return (
                <tr key={chave} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                  <td className="px-3 py-1.5 text-white">
                    {m.label || m.id}
                    {m.label && m.label !== m.id && <span className="ml-2 text-[10px] text-[var(--text-muted)]">{m.id}</span>}
                  </td>
                  <td className="px-3 py-1.5 text-[var(--text-muted)]">{m.provider}</td>
                  <td className="px-3 py-1.5 text-[var(--text-muted)]">{compacto(m.maxInputTokens)}</td>
                  <td className="px-3 py-1.5 text-[var(--cyan-neon)]">
                    {m.free ? "grátis" : [paraMilhao(m.pricing?.prompt), paraMilhao(m.pricing?.completion)].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[var(--text-muted)]">{caps || "—"}</td>
                  <td className="px-3 py-1.5">
                    <div className="flex justify-end gap-1">
                      <button type="button" onClick={() => abrirEdicao(m)} title="Editar"
                        className="rounded p-1 text-[var(--text-muted)] hover:bg-white/5 hover:text-white">
                        <Pencil size={13} />
                      </button>
                      <button type="button" onClick={() => void apagar(m)}
                        title={confirmando === chave ? "Clique de novo pra confirmar" : "Apagar"}
                        className={`rounded p-1 hover:bg-white/5 ${confirmando === chave ? "text-red-400" : "text-[var(--text-muted)] hover:text-red-300"}`}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {confirmando && (
        <p className="font-mono text-[11px] text-red-300">
          Clique na lixeira de novo pra apagar de vez — some do banco e a Hana deixa de ver esse modelo.
        </p>
      )}
    </div>
  );
}
