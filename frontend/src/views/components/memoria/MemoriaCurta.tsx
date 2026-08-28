/**
 * Memoria curta: a conversa recente que entra no prompt, por canal.
 *
 * So leitura — ninguem edita a conversa na mao. O valor aqui e VER exatamente
 * o que a Hana enxerga naquele canal, que e como se descobre vazamento: se
 * aparecer no Discord algo que voce falou na call, o filtro quebrou de novo.
 */

import { useCallback, useEffect, useState } from "react";
import { MessageSquare, RefreshCw } from "lucide-react";

import { MemoriaApi } from "../../../api/memoria";
import type { CanalMemoria, MensagemCurta } from "../../../models/types";
import { Button } from "../shared/Button";

const CANAIS: { id: CanalMemoria; emoji: string; label: string }[] = [
  { id: "chat", emoji: "💬", label: "Chat" },
  { id: "discord", emoji: "🎮", label: "Discord" },
  { id: "terminal", emoji: "⌨️", label: "Terminal" },
  { id: "voice", emoji: "🎤", label: "Voz" },
];

function hora(iso: string): string {
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function MemoriaCurta() {
  const [canal, setCanal] = useState<CanalMemoria>("chat");
  const [itens, setItens] = useState<MensagemCurta[]>([]);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    const { itens: lista } = await MemoriaApi.conversa(canal);
    setItens(lista);
    setCarregando(false);
  }, [canal]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
            <MessageSquare size={14} className="text-[var(--cyan-neon)]" />
            Memória curta
          </h3>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            As últimas falas <strong>deste canal</strong>. É exatamente o que vai no prompt — cada
            canal é isolado dos outros.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-white/5 px-2 py-0.5 font-mono text-[10px] text-[var(--text-muted)]">
            {itens.length} falas
          </span>
          <Button variant="ghost" size="sm" iconOnly icon={<RefreshCw size={13} />} onClick={() => void carregar()} title="Recarregar" />
        </div>
      </header>

      <div className="flex flex-wrap gap-1.5">
        {CANAIS.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setCanal(c.id)}
            className={`rounded-full px-3 py-1 text-[11px] transition ${
              canal === c.id
                ? "bg-[var(--cyan-neon)]/15 text-[var(--cyan-neon)] ring-1 ring-[var(--cyan-neon)]/40"
                : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10"
            }`}
          >
            {c.emoji} {c.label}
          </button>
        ))}
      </div>

      {carregando ? (
        <p className="py-6 text-center text-[11px] text-[var(--text-muted)]">carregando…</p>
      ) : itens.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
          <p className="text-xs text-[var(--text-secondary)]">Nenhuma conversa neste canal ainda.</p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Fale com ela por aqui e as falas aparecem — em ordem, das mais antigas pras novas.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {itens.map((m) => (
            <li
              key={m.id}
              className={`rounded-lg border px-3 py-2 ${
                m.role === "user"
                  ? "border-white/10 bg-white/[0.04]"
                  : "border-[var(--purple-neon)]/15 bg-[var(--purple-dark)]/10"
              }`}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className={`text-[10px] font-bold uppercase tracking-wider ${
                  m.role === "user" ? "text-[var(--cyan-neon)]" : "text-[var(--purple-neon)]"
                }`}>
                  {m.author}
                </span>
                <span className="font-mono text-[10px] text-[var(--text-muted)]">{hora(m.created_at)}</span>
              </div>
              <p className="whitespace-pre-wrap text-xs text-[var(--text-secondary)]">{m.content}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
