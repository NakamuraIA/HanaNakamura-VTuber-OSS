/**
 * Memoria longa: os fatos que a Hana guarda sozinha, buscados por RAG.
 *
 * RAG = antes de responder, ela busca aqui e cola no prompt o que combinou com
 * a pergunta. So o que combinou — nao a lista inteira.
 *
 * O "modo teste" existe pra tirar a duvida mais comum: *do que ela lembraria se
 * eu perguntasse isso?* Digite a pergunta e a lista mostra exatamente o que
 * entraria no prompt, na mesma ordem.
 */

import { useCallback, useEffect, useState } from "react";
import { Archive, Brain, FlaskConical, Plus, RefreshCw, RotateCcw, Search, Trash2 } from "lucide-react";

import { MemoriaApi } from "../../../api/memoria";
import type { Fato, StatusFato } from "../../../models/types";
import { Button } from "../shared/Button";

const FILTROS: { id: StatusFato; label: string }[] = [
  { id: "ativa", label: "Ativas" },
  { id: "arquivada", label: "Arquivadas" },
  { id: "lixeira", label: "Lixeira" },
];

export function MemoriaRag() {
  const [itens, setItens] = useState<Fato[]>([]);
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<StatusFato>("ativa");
  const [modoTeste, setModoTeste] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [novo, setNovo] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    const { itens: lista } = await MemoriaApi.listarFatos(busca, filtro);
    setItens(lista);
    setCarregando(false);
  }, [busca, filtro]);

  // Debounce: sem isso cada tecla dispara uma busca no banco.
  useEffect(() => {
    const t = window.setTimeout(() => void carregar(), busca ? 280 : 0);
    return () => window.clearTimeout(t);
  }, [carregar, busca]);

  const criar = useCallback(async () => {
    const limpo = novo.trim();
    if (!limpo) return;
    await MemoriaApi.criarFato(limpo);
    setNovo("");
    void carregar();
  }, [novo, carregar]);

  const mudarStatus = useCallback(
    async (fato: Fato, status: StatusFato) => {
      await MemoriaApi.editarFato(fato.id, { status });
      void carregar();
    },
    [carregar],
  );

  const apagar = useCallback(
    async (fato: Fato) => {
      if (!confirm("Apagar de vez? Pra apagar com volta, use a lixeira.")) return;
      await MemoriaApi.apagarFato(fato.id);
      void carregar();
    },
    [carregar],
  );

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Brain size={14} className="text-blue-400" />
            Memória longa (RAG)
          </h3>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Fatos que ela guardou sozinha. Só o que combina com a pergunta entra no prompt.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-white/5 px-2 py-0.5 font-mono text-[10px] text-[var(--text-muted)]">
            {itens.length}
          </span>
          <Button variant="ghost" size="sm" iconOnly icon={<RefreshCw size={13} />} onClick={() => void carregar()} title="Recarregar" />
        </div>
      </header>

      {/* ---- busca ---- */}
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder={modoTeste ? "Pergunte algo e veja do que ela lembraria…" : "Buscar nas memórias…"}
            className={`w-full rounded-lg border bg-black/30 py-2 pl-9 pr-3 text-xs text-white outline-none placeholder:text-[var(--text-muted)] ${
              modoTeste ? "border-cyan-400/50" : "border-white/10 focus:border-blue-500/50"
            }`}
          />
        </div>
        <Button
          size="sm"
          variant={modoTeste ? "success" : "secondary"}
          icon={<FlaskConical size={13} />}
          onClick={() => setModoTeste((v) => !v)}
          title="Digite uma pergunta e veja exatamente do que a Hana lembraria"
        >
          Testar
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFiltro(f.id)}
            disabled={!!busca.trim()}
            className={`rounded-full px-3 py-1 text-[10px] transition disabled:opacity-30 ${
              filtro === f.id
                ? "bg-blue-500/15 text-blue-300 ring-1 ring-blue-400/40"
                : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10"
            }`}
          >
            {f.label}
          </button>
        ))}
        {busca.trim() && (
          <span className="self-center text-[10px] text-[var(--text-muted)]">
            buscando em todas as ativas
          </span>
        )}
      </div>

      {/* ---- criar ---- */}
      <div className="flex gap-2">
        <input
          value={novo}
          onChange={(e) => setNovo(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void criar();
            }
          }}
          placeholder="Escrever uma memória na mão…"
          maxLength={2000}
          className="flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white outline-none placeholder:text-[var(--text-muted)] focus:border-blue-500/50"
        />
        <Button size="sm" icon={<Plus size={13} />} onClick={() => void criar()} disabled={!novo.trim()}>
          Criar
        </Button>
      </div>

      {/* ---- lista ---- */}
      {carregando ? (
        <p className="py-6 text-center text-[11px] text-[var(--text-muted)]">carregando…</p>
      ) : itens.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
          <p className="text-xs text-[var(--text-secondary)]">
            {busca.trim() ? "Ela não lembraria de nada com essa pergunta." : "Nenhuma memória aqui."}
          </p>
          {!busca.trim() && (
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              Ela guarda sozinha durante a conversa. Você também pode escrever acima.
            </p>
          )}
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {itens.map((f) => (
            <li key={f.id} className="group flex items-start gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="whitespace-pre-wrap text-xs text-white">{f.text}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-[var(--text-muted)]">
                  <span className="rounded bg-white/5 px-1.5 py-0.5">{f.kind}</span>
                  <span title="Quem salvou">{f.source}</span>
                  {typeof f.use_count === "number" && f.use_count > 0 && (
                    <span title="Quantas vezes já entrou numa resposta">usada {f.use_count}x</span>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 gap-1 opacity-0 transition group-hover:opacity-100">
                {filtro === "ativa" ? (
                  <Button variant="ghost" size="sm" iconOnly icon={<Archive size={13} />} onClick={() => void mudarStatus(f, "arquivada")} title="Arquivar" />
                ) : (
                  <Button variant="ghost" size="sm" iconOnly icon={<RotateCcw size={13} />} onClick={() => void mudarStatus(f, "ativa")} title="Restaurar" />
                )}
                <Button variant="ghost" size="sm" iconOnly icon={<Trash2 size={13} />} onClick={() => void apagar(f)} title="Apagar de vez" />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
