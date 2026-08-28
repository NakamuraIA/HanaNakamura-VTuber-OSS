/**
 * Cliente da memoria nova (/api/memoria/*).
 *
 * Substitui api/memory.ts, que falava com as 20 rotas antigas. Aqui sao 12, e
 * o try/catch mora num helper so — o arquivo velho repetia o mesmo bloco de
 * erro 14 vezes.
 *
 * As tres memorias:
 *   curta  -> conversa recente, por canal (entra no prompt)
 *   longa  -> fatos que a Hana salva sozinha, buscados por RAG
 *   fixa   -> regras que SO a Nakamura escreve; a Hana apenas le
 *
 * `historico` nao e memoria: e o que a tela mostra. Nunca vai pra LLM.
 */

import { BACKEND_URL } from "./core";
import type {
  ChatLogItem,
  SessaoHistorico,
  Fato,
  MemoriaFixa,
  MemoriaStatus,
  MensagemCurta,
} from "../models/types";

const BASE = `${BACKEND_URL}/api/memoria`;

/**
 * Uma chamada HTTP com fallback.
 *
 * O painel nao pode quebrar quando o backend reinicia: toda falha vira o valor
 * padrao e um aviso no console, nunca uma tela branca.
 */
async function pedir<T>(url: string, fallback: T, init?: RequestInit): Promise<T> {
  try {
    const res = await fetch(url, init);
    if (!res.ok) {
      console.warn(`memoria: ${init?.method || "GET"} ${url} -> HTTP ${res.status}`);
      return fallback;
    }
    return (await res.json()) as T;
  } catch (erro) {
    console.error(`memoria: falha em ${url}`, erro);
    return fallback;
  }
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const jsonPut = (body: unknown): RequestInit => ({ ...json(body), method: "PUT" });

export const MemoriaApi = {
  // ---------------- panorama ---------------------------------------- //

  status: (): Promise<{ status: MemoriaStatus | null }> =>
    pedir(`${BASE}/status`, { status: null }),

  // ---------------- memoria longa (fatos / RAG) ---------------------- //

  /** Lista ou busca. Com `q` usa BM25 — a mesma busca que alimenta o prompt. */
  listarFatos: (q = "", status = "ativa", limit = 50): Promise<{ itens: Fato[]; total: number }> => {
    const p = new URLSearchParams({ status, limit: String(limit) });
    if (q.trim()) p.set("q", q.trim());
    return pedir(`${BASE}?${p}`, { itens: [], total: 0 });
  },

  criarFato: (text: string, kind = "fato"): Promise<{ ok?: boolean; id?: string }> =>
    pedir(BASE, {}, json({ text, kind, source: "manual" })),

  /**
   * Uma rota para tudo: editar texto, arquivar, restaurar, mandar pra lixeira.
   * Na API antiga isso eram quatro endpoints diferentes.
   */
  editarFato: (id: string, patch: { text?: string; status?: string }): Promise<{ ok?: boolean }> =>
    pedir(`${BASE}/${id}`, {}, jsonPut(patch)),

  apagarFato: (id: string): Promise<{ ok?: boolean }> =>
    pedir(`${BASE}/${id}`, {}, { method: "DELETE" }),

  // ---------------- memoria fixa (so a Nakamura escreve) ------------- //

  listarFixas: (todas = false): Promise<{ itens: MemoriaFixa[] }> =>
    pedir(`${BASE}/fixas?todas=${todas}`, { itens: [] }),

  criarFixa: (text: string, kind = "regra", position = 100): Promise<{ ok?: boolean; id?: number }> =>
    pedir(`${BASE}/fixas`, {}, json({ text, kind, position })),

  editarFixa: (
    id: number,
    patch: { text?: string; kind?: string; position?: number; enabled?: boolean },
  ): Promise<{ ok?: boolean }> => pedir(`${BASE}/fixas/${id}`, {}, jsonPut(patch)),

  apagarFixa: (id: number): Promise<{ ok?: boolean }> =>
    pedir(`${BASE}/fixas/${id}`, {}, { method: "DELETE" }),

  // ---------------- memoria curta (a conversa) ----------------------- //

  /** O que a Hana enxerga naquele canal. Canais sao isolados entre si. */
  conversa: (canal: string, limit = 80): Promise<{ itens: MensagemCurta[]; total: number }> =>
    pedir(`${BASE}/conversa/${canal}?limit=${limit}`, { itens: [], total: 0 }),

  // ---------------- historico do front (fora do prompt) -------------- //

  sessoes: (limit = 50): Promise<{ sessoes: SessaoHistorico[] }> =>
    pedir(`${BASE}/historico?limit=${limit}`, { sessoes: [] }),

  historico: (sessionId: string, limit = 500): Promise<{ itens: ChatLogItem[]; total: number }> =>
    pedir(`${BASE}/historico/${encodeURIComponent(sessionId)}?limit=${limit}`, { itens: [], total: 0 }),

  // ---------------- ciclo de sono ------------------------------------ //

  /** Faz a Hana reler o dia e guardar um resumo (o "diario"). */
  rodarSono: (): Promise<{ ok?: boolean }> =>
    pedir(`${BASE}/sono`, {}, { method: "POST" }),
};
