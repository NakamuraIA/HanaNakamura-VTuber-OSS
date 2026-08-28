/**
 * Recuperar conversa do BANCO (tabela `chat_log`).
 *
 * O chat guarda as sessoes no localStorage do navegador — some se voce limpar
 * os dados, e nao existe fora daquele PC. O backend, em paralelo, grava TODA
 * fala em `chat_log`.
 *
 * Este painel liga os dois: lista o que existe no banco e importa pra uma
 * sessao local nova. Nao mexe no localStorage existente de proposito — o erro
 * caro aqui seria sobrescrever a conversa que a Nakamura esta usando agora.
 *
 * `chat_log` NAO e memoria: nada dela vai pro prompt. E so pra tela.
 */

import { useCallback, useEffect, useState } from "react";
import { Database, Download, RefreshCw } from "lucide-react";

import { MemoriaApi } from "../../../api/memoria";
import type { ChatMessage, SessaoHistorico } from "../../../models/types";
import { Button } from "../shared/Button";

const CANAL_EMOJI: Record<string, string> = {
  chat: "💬",
  discord: "🎮",
  terminal: "⌨️",
  voice: "🎤",
};

/** "chat-2026-07-27" -> { emoji, label } */
function rotulo(sessionId: string): { emoji: string; label: string } {
  const [canal, ...resto] = sessionId.split("-");
  const data = resto.join("-");
  const [ano, mes, dia] = data.split("-");
  return {
    emoji: CANAL_EMOJI[canal] || "📁",
    label: dia ? `${canal} · ${dia}/${mes}/${ano}` : sessionId,
  };
}

type Props = {
  /** Recebe as mensagens importadas pra virarem uma sessao local nova. */
  onImportar: (titulo: string, mensagens: ChatMessage[]) => void;
};

export function HistoricoBanco({ onImportar }: Props) {
  const [sessoes, setSessoes] = useState<SessaoHistorico[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [importando, setImportando] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    const { sessoes: lista } = await MemoriaApi.sessoes();
    setSessoes(lista);
    setCarregando(false);
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const importar = useCallback(
    async (s: SessaoHistorico) => {
      setImportando(s.session_id);
      const { itens } = await MemoriaApi.historico(s.session_id);
      const mensagens: ChatMessage[] = itens
        // So conversa: evento de sistema/ferramenta fica de fora da tela do chat.
        .filter((i) => i.role === "user" || i.role === "hana" || i.role === "assistant")
        .map((i) => ({
          id: `db-${i.id}`,
          role: i.role === "user" ? "user" : "hana",
          content: i.content,
          timestamp: new Date(i.created_at.replace(" ", "T")).toLocaleTimeString("pt-BR", {
            hour: "2-digit",
            minute: "2-digit",
          }),
        }));
      onImportar(rotulo(s.session_id).label, mensagens);
      setImportando("");
    },
    [onImportar],
  );

  return (
    <div className="flex flex-col gap-2 border-t border-white/5 pt-2">
      <div className="flex items-center justify-between">
        <span
          className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]"
          title="O chat guarda as conversas no navegador. Isto aqui vem do banco — sobrevive a limpar o navegador."
        >
          <Database size={11} /> Do banco
        </span>
        <Button variant="ghost" size="sm" iconOnly icon={<RefreshCw size={12} />} onClick={() => void carregar()} title="Recarregar" />
      </div>

      {carregando ? (
        <p className="text-[10px] text-[var(--text-muted)]">carregando…</p>
      ) : sessoes.length === 0 ? (
        <p className="text-[10px] text-[var(--text-muted)]">
          Nada no banco ainda. Toda conversa daqui pra frente fica salva.
        </p>
      ) : (
        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto pr-1">
          {sessoes.map((s) => {
            const r = rotulo(s.session_id);
            return (
              <li key={s.session_id} className="flex items-center gap-2 rounded-lg bg-white/[0.03] px-2 py-1.5">
                <span className="text-xs">{r.emoji}</span>
                <span className="flex-1 truncate text-[11px] text-[var(--text-secondary)]">{r.label}</span>
                <span className="font-mono text-[10px] text-[var(--text-muted)]">{s.mensagens}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  iconOnly
                  icon={<Download size={12} />}
                  loading={importando === s.session_id}
                  onClick={() => void importar(s)}
                  title="Abrir numa conversa nova (não mexe nas suas atuais)"
                />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
