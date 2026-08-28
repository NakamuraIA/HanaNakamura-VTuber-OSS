/**
 * Memoria fixa: as regras que entram em TODA resposta da Hana.
 *
 * Diferenca pras outras memorias:
 *   - so a Nakamura escreve aqui (a Hana nao tem ferramenta que grave)
 *   - nao passa por busca: entra inteira, sempre
 *   - e a continuacao do system prompt, mas em banco — da pra editar aqui sem
 *     tocar em codigo nenhum
 *
 * `position` define a ordem no prompt: menor primeiro, e o que vem antes pesa
 * mais pro modelo. `enabled` desliga sem apagar — util pra descobrir qual regra
 * esta causando algum comportamento estranho.
 */

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, Pin, Plus, RefreshCw, Trash2 } from "lucide-react";

import { MemoriaApi } from "../../../api/memoria";
import type { MemoriaFixa, TipoFixa } from "../../../models/types";
import { Button } from "../shared/Button";

const TIPOS: { id: TipoFixa; emoji: string; label: string; dica: string }[] = [
  { id: "regra", emoji: "📏", label: "Regra", dica: "Como ela deve se comportar. Ex: responda curto." },
  { id: "giria", emoji: "💬", label: "Gíria", dica: "Como ela deve falar. Ex: me chama de Naka." },
  { id: "tarefa", emoji: "✅", label: "Tarefa", dica: "Algo em andamento que ela deve lembrar." },
  { id: "fato", emoji: "📌", label: "Fato", dica: "Algo sobre você que nunca muda." },
];

function tipoMeta(kind: string) {
  return TIPOS.find((t) => t.id === kind) || TIPOS[0];
}

export function MemoriaFixas() {
  const [itens, setItens] = useState<MemoriaFixa[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [texto, setTexto] = useState("");
  const [tipo, setTipo] = useState<TipoFixa>("regra");

  const carregar = useCallback(async () => {
    setCarregando(true);
    // `todas` inclui as desligadas: quem edita precisa ver o que esta fora do
    // prompt, senao a regra desligada "some" e parece que foi apagada.
    const { itens: lista } = await MemoriaApi.listarFixas(true);
    setItens(lista);
    setCarregando(false);
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const criar = useCallback(async () => {
    const limpo = texto.trim();
    if (!limpo) return;
    // Entra no fim da fila; reordenar é uma edição depois.
    const posicao = itens.length ? Math.max(...itens.map((i) => i.position)) + 1 : 1;
    await MemoriaApi.criarFixa(limpo, tipo, posicao);
    setTexto("");
    void carregar();
  }, [texto, tipo, itens, carregar]);

  const alternar = useCallback(
    async (item: MemoriaFixa) => {
      await MemoriaApi.editarFixa(item.id, { enabled: !item.enabled });
      void carregar();
    },
    [carregar],
  );

  const apagar = useCallback(
    async (item: MemoriaFixa) => {
      await MemoriaApi.apagarFixa(item.id);
      void carregar();
    },
    [carregar],
  );

  const ligadas = itens.filter((i) => i.enabled).length;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Pin size={14} className="text-[var(--accent)]" />
            Memória fixa
          </h3>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Entra em <strong>toda</strong> resposta, sem passar por busca. Só você escreve aqui — a
            Hana apenas lê.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-white/5 px-2 py-0.5 font-mono text-[10px] text-[var(--text-muted)]">
            {ligadas} no prompt
          </span>
          <Button variant="ghost" size="sm" iconOnly icon={<RefreshCw size={13} />} onClick={() => void carregar()} title="Recarregar" />
        </div>
      </header>

      {/* ---- criar ---- */}
      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {TIPOS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTipo(t.id)}
              title={t.dica}
              className={`rounded-full px-2.5 py-1 text-[10px] transition ${
                tipo === t.id
                  ? "bg-[var(--accent)]/20 text-white ring-1 ring-[var(--accent)]/40"
                  : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10"
              }`}
            >
              {t.emoji} {t.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void criar();
              }
            }}
            placeholder={tipoMeta(tipo).dica}
            maxLength={1000}
            className="flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]/50"
          />
          <Button size="sm" icon={<Plus size={13} />} onClick={() => void criar()} disabled={!texto.trim()}>
            Fixar
          </Button>
        </div>
      </div>

      {/* ---- lista ---- */}
      {carregando ? (
        <p className="py-6 text-center text-[11px] text-[var(--text-muted)]">carregando…</p>
      ) : itens.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
          <p className="text-xs text-[var(--text-secondary)]">Nenhuma regra fixa ainda.</p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Comece com algo que você repete sempre — tipo <em>“responda curto”</em>.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {itens.map((item) => {
            const meta = tipoMeta(item.kind);
            return (
              <li
                key={item.id}
                className={`group flex items-center gap-3 rounded-lg border px-3 py-2 transition ${
                  item.enabled
                    ? "border-white/10 bg-white/[0.03]"
                    : "border-white/5 bg-transparent opacity-45"
                }`}
              >
                <span className="shrink-0 text-sm" title={meta.label}>
                  {meta.emoji}
                </span>
                <p className={`flex-1 text-xs ${item.enabled ? "text-white" : "text-[var(--text-muted)] line-through"}`}>
                  {item.text}
                </p>
                <span className="shrink-0 font-mono text-[10px] text-[var(--text-muted)]" title="Ordem no prompt (menor vem primeiro)">
                  #{item.position}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  iconOnly
                  icon={item.enabled ? <Eye size={13} /> : <EyeOff size={13} />}
                  onClick={() => void alternar(item)}
                  title={item.enabled ? "Tirar do prompt (sem apagar)" : "Voltar pro prompt"}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  iconOnly
                  icon={<Trash2 size={13} />}
                  onClick={() => void apagar(item)}
                  title="Apagar de vez"
                  className="opacity-0 transition group-hover:opacity-100"
                />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
