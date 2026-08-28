/**
 * Nucleo de Memoria: as tres memorias da Hana, separadas.
 *
 *   curta  a conversa recente, por canal — entra no prompt em ordem
 *   longa  fatos que ela guarda sozinha — so o que combina com a pergunta
 *   fixa   regras que voce escreve — entram sempre, inteiras
 *
 * A tela anterior tinha 741 linhas porque falava com a API velha (20 rotas) e
 * renderizava campos que a memoria nova nao tem mais (categoria, importancia,
 * tags, score, compactacao). Cada memoria virou um componente proprio; esta
 * pagina so escolhe qual mostrar.
 */

import { useCallback, useEffect, useState } from "react";
import { Activity, Brain, Database, MessageSquare, Pin } from "lucide-react";

import { MemoriaApi } from "../../api/memoria";
import type { MemoriaStatus } from "../../models/types";
import { Button } from "../components/shared/Button";
import { MemoriaCurta } from "../components/memoria/MemoriaCurta";
import { MemoriaFixas } from "../components/memoria/MemoriaFixas";
import { MemoriaRag } from "../components/memoria/MemoriaRag";

type Aba = "curta" | "rag" | "fixas";

const ABAS: { id: Aba; icone: typeof Brain; label: string; dica: string }[] = [
  { id: "curta", icone: MessageSquare, label: "Curta", dica: "A conversa recente, por canal. Entra inteira no prompt." },
  { id: "rag", icone: Brain, label: "Longa (RAG)", dica: "Fatos que ela guarda sozinha. Só o que combina com a pergunta entra." },
  { id: "fixas", icone: Pin, label: "Fixas", dica: "Regras que valem sempre. Só você escreve — a Hana apenas lê." },
];

export function TabMemoria() {
  const [aba, setAba] = useState<Aba>("rag");
  const [status, setStatus] = useState<MemoriaStatus | null>(null);
  const [aviso, setAviso] = useState("");

  const carregarStatus = useCallback(async () => {
    const { status: s } = await MemoriaApi.status();
    setStatus(s);
  }, []);

  // Recarrega ao trocar de aba: criar/apagar em qualquer uma muda os numeros.
  useEffect(() => {
    void carregarStatus();
  }, [carregarStatus, aba]);

  const rodarSono = useCallback(async () => {
    setAviso("Rodando o sono da Hana…");
    const { ok } = await MemoriaApi.rodarSono();
    setAviso(ok ? "Sono executado — ela resumiu o dia." : "Não consegui rodar o sono.");
    void carregarStatus();
  }, [carregarStatus]);

  return (
    <div className="flex h-full flex-col">
      {/* ---- cabecalho ---- */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border-strong)] px-6 py-4">
        <div className="flex items-center gap-3">
          <Database size={22} className="text-[var(--purple-neon)]" />
          <div>
            <h2 className="text-lg font-bold text-white">Núcleo de Memória</h2>
            <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              três memórias · um banco SQLite
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status && (
            <div className="flex flex-wrap gap-1.5 font-mono text-[10px]">
              <Contador titulo="Falas guardadas na conversa" label="curta" valor={status.mensagens} />
              <Contador titulo="Fatos ativos, buscáveis por RAG" label="longa" valor={status.fatos.ativas} />
              <Contador titulo="Regras que entram em toda resposta" label="fixas" valor={status.fixas} />
              <Contador titulo="Só pra tela — nunca vai pra LLM" label="tela" valor={status.historicoFront} apagado />
            </div>
          )}
          <Button variant="secondary" size="sm" icon={<Activity size={13} />} onClick={() => void rodarSono()} title="Ela relê o dia e guarda um resumo">
            Sono
          </Button>
        </div>
      </div>

      {/* ---- abas ---- */}
      <div className="flex gap-1 border-b border-[var(--border-strong)] bg-black/20 px-6 py-3">
        {ABAS.map((a) => {
          const Icone = a.icone;
          return (
            <button
              key={a.id}
              onClick={() => setAba(a.id)}
              title={a.dica}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-wider transition-all ${
                aba === a.id
                  ? "border border-[var(--purple-neon)]/50 bg-[var(--purple-dark)] text-white shadow-lg"
                  : "text-[var(--text-muted)] hover:bg-white/5 hover:text-white"
              }`}
            >
              <Icone size={14} /> {a.label}
            </button>
          );
        })}
      </div>

      {aviso && <p className="px-6 pt-3 font-mono text-[11px] text-[var(--cyan-neon)]">{aviso}</p>}

      {/* ---- conteudo ---- */}
      <div className="custom-scrollbar flex-1 overflow-y-auto bg-gradient-to-b from-transparent to-black/40 p-6">
        {aba === "curta" ? <MemoriaCurta /> : aba === "rag" ? <MemoriaRag /> : <MemoriaFixas />}
      </div>
    </div>
  );
}

function Contador({ label, valor, titulo, apagado }: { label: string; valor: number; titulo: string; apagado?: boolean }) {
  return (
    <span
      title={titulo}
      className={`rounded-full px-2 py-0.5 ${apagado ? "bg-white/[0.03] text-[var(--text-muted)]/60" : "bg-white/5 text-[var(--text-muted)]"}`}
    >
      {label} <strong className="text-white">{valor}</strong>
    </span>
  );
}
