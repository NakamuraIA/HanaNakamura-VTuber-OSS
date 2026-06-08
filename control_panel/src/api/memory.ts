import { BACKEND_URL } from "./core";
import { MemoryAudit, MemorySemanticStatus, MemoryStatus, RagMemory } from "../models/types";

type GraphFactPayload = { subject: string; relation: string; object: string };
type MemoryListResponse = { memories: RagMemory[]; count?: number; semantic?: MemorySemanticStatus };
type MemoryAuditResponse = { audit: MemoryAudit | null };

interface MemoryListParams {
  query?: string;
  status?: MemoryStatus;
  limit?: number;
}

interface MemoryWritePayload {
  text: string;
  metadata?: Record<string, unknown>;
  category?: string;
  importance?: string;
  tags?: string[];
  pinned?: boolean;
  status?: string;
  kind?: string;
}

const EMPTY_MEMORY_LIST: MemoryListResponse = { memories: [] };

async function parseJson<T>(res: Response, fallback: T): Promise<T> {
  /** Parse JSON responses while keeping UI calls resilient to backend restarts. */
  if (!res.ok) return fallback;
  return (await res.json()) as T;
}

function memoryQuery(params?: MemoryListParams): string {
  /** Build URL query params for backend-ranked memory search/list calls. */
  const search = new URLSearchParams();
  if (params?.query) search.set("query", params.query);
  if (params?.status) search.set("status", params.status);
  if (params?.limit) search.set("limit", String(params.limit));
  const value = search.toString();
  return value ? `?${value}` : "";
}

export const MemoryApi = {
  getMemoryGraph: async (): Promise<{facts: GraphFactPayload[]}> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/graph`);
      return await parseJson(res, { facts: [] });
    } catch (error) {
      console.error("Erro ao carregar knowledge graph:", error);
      return { facts: [] };
    }
  },

  deleteMemoryGraph: async (subject: string, relation: string, object: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/graph`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject, relation, object })
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao deletar fato do grafo:", error);
      return false;
    }
  },

  createMemoryGraph: async (subject: string, relation: string, object: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject, relation, object })
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao criar fato do grafo:", error);
      return false;
    }
  },

  getMemoryRag: async (params?: MemoryListParams): Promise<MemoryListResponse> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag${memoryQuery(params)}`);
      return await parseJson(res, EMPTY_MEMORY_LIST);
    } catch (error) {
      console.error("Erro ao carregar memoria RAG:", error);
      return EMPTY_MEMORY_LIST;
    }
  },

  searchMemory: async (query: string, status: MemoryStatus = "active", limit = 80): Promise<MemoryListResponse> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, status, limit })
      });
      return await parseJson(res, EMPTY_MEMORY_LIST);
    } catch (error) {
      console.error("Erro ao buscar memoria RAG:", error);
      return EMPTY_MEMORY_LIST;
    }
  },

  createMemoryRag: async (text: string, metadata: Record<string, unknown> = {}): Promise<RagMemory | null> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, metadata })
      });
      const data = await parseJson<{ memory?: RagMemory }>(res, {});
      return data.memory || null;
    } catch (error) {
      console.error("Erro ao criar memoria RAG:", error);
      return null;
    }
  },

  updateMemoryRag: async (id: string, text: string, metadata: Record<string, unknown> = {}, payload: Partial<MemoryWritePayload> = {}): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, metadata, ...payload })
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao atualizar memoria RAG:", error);
      return false;
    }
  },

  deleteMemoryRag: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag/${id}`, { method: "DELETE" });
      return res.ok;
    } catch (error) {
      console.error("Erro ao deletar memoria RAG:", error);
      return false;
    }
  },

  hardDeleteMemoryRag: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag/${id}?hard=true`, { method: "DELETE" });
      return res.ok;
    } catch (error) {
      console.error("Erro ao apagar memoria RAG definitivamente:", error);
      return false;
    }
  },

  restoreMemoryRag: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag/${id}/restore`, { method: "POST" });
      return res.ok;
    } catch (error) {
      console.error("Erro ao restaurar memoria RAG:", error);
      return false;
    }
  },

  archiveMemoryRag: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag/${id}/archive`, { method: "POST" });
      return res.ok;
    } catch (error) {
      console.error("Erro ao arquivar memoria RAG:", error);
      return false;
    }
  },

  pinMemoryRag: async (id: string, pinned: boolean): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/rag/${id}/pin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned })
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao fixar memoria RAG:", error);
      return false;
    }
  },

  compactMemory: async (memoryIds: string[] = [], archiveOriginals = false): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/compact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memoryIds, archiveOriginals })
      });
      return res.ok;
    } catch (error) {
      console.error("Erro ao compactar memorias:", error);
      return false;
    }
  },

  runMemoryMaintenance: async (): Promise<boolean> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/maintenance/run`, { method: "POST" });
      return res.ok;
    } catch (error) {
      console.error("Erro ao rodar manutencao de memoria:", error);
      return false;
    }
  },

  getMemoryAudit: async (): Promise<MemoryAuditResponse> => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/memory/audit`);
      return await parseJson(res, { audit: null });
    } catch (error) {
      console.error("Erro ao auditar memoria:", error);
      return { audit: null };
    }
  }
};
