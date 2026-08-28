/**
 * Cliente do catalogo de modelos (/api/modelos/*).
 *
 * Fala com a tabela `llm_models` — a MESMA que o chat le pra saber o que cada
 * modelo aceita. Nao existe lista paralela: cadastrar aqui e o modelo passar a
 * existir pra Hana.
 *
 * Diferente do resto do arquivo de config, aqui os erros SOBEM (throw) em vez
 * de virar valor padrao: salvar e apagar precisam falhar visivelmente, senao a
 * tela mostra "salvo" sem ter salvo nada.
 */

import { BACKEND_URL } from "./core";
import type { ModelSpec } from "../models/providerCatalog";

const BASE = `${BACKEND_URL}/api/modelos`;

export interface ModeloCatalogo extends ModelSpec {
  source?: string;
  status?: string;
}

async function pedirOuFalhar<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detalhe = await res.text().catch(() => "");
    throw new Error(detalhe || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const ModelosApi = {
  listar: async (provider = ""): Promise<{ itens: ModeloCatalogo[]; porProvider: Record<string, number> }> => {
    const query = provider ? `?provider=${encodeURIComponent(provider)}` : "";
    try {
      const data = await pedirOuFalhar<{ itens: ModeloCatalogo[]; porProvider: Record<string, number> }>(`${BASE}${query}`);
      return { itens: data.itens || [], porProvider: data.porProvider || {} };
    } catch (erro) {
      // Listar pode falhar sem quebrar a tela: mostra vazio e segue.
      console.error("modelos: falha ao listar", erro);
      return { itens: [], porProvider: {} };
    }
  },

  /** Cria ou sobrescreve. Uma rota so — do lado de quem usa, e o mesmo formulario. */
  salvar: (modelo: Partial<ModeloCatalogo> & { provider: string; id: string }): Promise<{ modelo: ModeloCatalogo }> =>
    pedirOuFalhar(BASE, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(modelo),
    }),

  apagar: (provider: string, id: string): Promise<{ ok: boolean }> =>
    // id pode ter barra (`qwen/qwen3-32b`); a rota usa :path e o encode preserva.
    pedirOuFalhar(`${BASE}/${encodeURIComponent(provider)}/${id.split("/").map(encodeURIComponent).join("/")}`, {
      method: "DELETE",
    }),
};
