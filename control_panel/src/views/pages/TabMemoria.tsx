import { useEffect, useMemo, useRef, useState } from "react";
import { ApiController } from "../../controllers/api";
import {
  Activity,
  Archive,
  BrainCircuit,
  CheckSquare,
  ChevronDown,
  ChevronUp,
  Database,
  FlaskConical,
  Network,
  Pencil,
  Pin,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Sparkles,
  Square,
  Star,
  Trash2,
  X,
} from "lucide-react";

import { GraphFact, MemoryAudit, MemoryStatus, RagMemory } from "../../models/types";
import { Button } from "../components/shared/Button";

const EMPTY_FACT: GraphFact = { subject: "", relation: "", object: "" };
const MEMORY_PREVIEW_LIMIT = 420;

// Friendly, child-readable category map (emoji + PT label) for the simple mode.
const CATEGORY_META: Record<string, { emoji: string; label: string }> = {
  general: { emoji: "🗂️", label: "Geral" },
  manual: { emoji: "✍️", label: "Manual" },
  person: { emoji: "👤", label: "Pessoas" },
  people: { emoji: "👤", label: "Pessoas" },
  projeto: { emoji: "🛠️", label: "Projeto" },
  project: { emoji: "🛠️", label: "Projeto" },
  reflection: { emoji: "💭", label: "Reflexões" },
  conversation_summary: { emoji: "💬", label: "Resumos de conversa" },
  attachment: { emoji: "📎", label: "Anexos" },
  game: { emoji: "🎮", label: "Jogos" },
  games: { emoji: "🎮", label: "Jogos" },
  event: { emoji: "📅", label: "Eventos" },
  events: { emoji: "📅", label: "Eventos" },
  preference: { emoji: "💜", label: "Preferências" },
};

function categoryMeta(category: string): { emoji: string; label: string } {
  /** Map a raw category to a friendly emoji + label, with a safe fallback. */
  const key = (category || "general").toLowerCase();
  return CATEGORY_META[key] || { emoji: "🗂️", label: category || "Geral" };
}

// Importance -> a single colored dot so the simple mode stays clean.
const IMPORTANCE_DOT: Record<string, string> = {
  low: "bg-slate-400",
  medium: "bg-amber-400",
  high: "bg-orange-400",
  critical: "bg-red-500",
};

function importanceDot(importance: string): string {
  return IMPORTANCE_DOT[(importance || "medium").toLowerCase()] || "bg-amber-400";
}

const MEMORY_FILTERS: { id: MemoryStatus; label: string }[] = [
  { id: "active", label: "Ativa" },
  { id: "archived", label: "Arquivada" },
  { id: "pinned", label: "Fixada" },
  { id: "long", label: "Longa" },
  { id: "deleted", label: "Lixeira" },
];

function metadataString(memory: RagMemory, key: string, fallback = ""): string {
  /** Read memory metadata values in a display-safe way. */
  const value = memory.metadata?.[key];
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function metadataNumber(memory: RagMemory, key: string, fallback = 0): number {
  /** Read numeric memory metadata without loose `any` casts. */
  const value = memory.metadata?.[key];
  return typeof value === "number" ? value : fallback;
}

function memoryStatus(memory: RagMemory): "active" | "archived" | "deleted" {
  /** Prefer v2 top-level status and fall back to metadata for migrated rows. */
  const status = memory.status || metadataString(memory, "status");
  return status === "archived" || status === "deleted" ? status : "active";
}

function memoryCategory(memory: RagMemory): string {
  /** Return the category badge value for one memory. */
  return memory.category || metadataString(memory, "category", "general");
}

function memoryImportance(memory: RagMemory): string {
  /** Return the importance badge value for one memory. */
  return memory.importance || metadataString(memory, "importance", "medium");
}

function isPinned(memory: RagMemory): boolean {
  /** Return pin state from top-level v2 data or migrated metadata. */
  const value = memory.pinned ?? memory.metadata?.pinned;
  return value === true;
}

function formatAccess(memory: RagMemory): string {
  /** Compact timestamp display for the memory cards. */
  const value = metadataString(memory, "lastAccessedAt") || metadataString(memory, "updatedAt");
  if (!value) return "sem acesso";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "sem acesso";
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function TabMemoria() {
  const [activeTab, setActiveTab] = useState<"graph" | "rag">("rag");
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  // Simple mode (default ON) hides technical badges and groups by category, so anyone
  // can read Hana's memory at a glance. Advanced mode keeps the full diagnostic view.
  const [simpleMode, setSimpleMode] = useState(true);
  // "Testar memória": focuses search and shows the relevance score so the user can
  // SEE exactly what Hana would recall for a given question.
  const [testMode, setTestMode] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [memoryFilter, setMemoryFilter] = useState<MemoryStatus>("active");
  const [audit, setAudit] = useState<MemoryAudit | null>(null);

  const [facts, setFacts] = useState<GraphFact[]>([]);
  const [memories, setMemories] = useState<RagMemory[]>([]);
  const [expandedMemories, setExpandedMemories] = useState<Set<string>>(() => new Set());
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<Set<string>>(() => new Set());

  const [factForm, setFactForm] = useState<GraphFact>(EMPTY_FACT);
  const [editingFact, setEditingFact] = useState<GraphFact | null>(null);
  const [memoryText, setMemoryText] = useState("");
  const [editingMemory, setEditingMemory] = useState<RagMemory | null>(null);

  const loadData = async () => {
    setIsLoading(true);
    setStatusMessage("");
    try {
      if (activeTab === "graph") {
        const { facts } = await ApiController.getMemoryGraph();
        setFacts(facts || []);
      } else {
        const query = searchTerm.trim();
        const response = await ApiController.getMemoryRag({ query, status: memoryFilter, limit: 160 });
        const auditResponse = await ApiController.getMemoryAudit();
        setMemories(response.memories || []);
        setAudit(auditResponse.audit);
        setSelectedMemoryIds(new Set());
      }
    } catch (e) {
      console.error("Erro ao carregar dados:", e);
      setStatusMessage("Falha ao carregar memorias.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    const delay = activeTab === "rag" ? 260 : 0;
    const timeout = window.setTimeout(() => {
      void loadData();
    }, delay);
    return () => window.clearTimeout(timeout);
  }, [activeTab, memoryFilter, searchTerm]);

  const resetFactEditor = () => {
    setFactForm(EMPTY_FACT);
    setEditingFact(null);
  };

  const resetMemoryEditor = () => {
    setMemoryText("");
    setEditingMemory(null);
  };

  const handleSaveFact = async () => {
    const subject = factForm.subject.trim();
    const relation = factForm.relation.trim();
    const object = factForm.object.trim();
    if (!subject || !relation || !object) {
      setStatusMessage("Preencha sujeito, relacao e objeto.");
      return;
    }

    if (editingFact) {
      await ApiController.deleteMemoryGraph(editingFact.subject, editingFact.relation, editingFact.object);
    }

    const ok = await ApiController.createMemoryGraph(subject, relation, object);
    if (!ok) {
      setStatusMessage("Nao foi possivel salvar o fato.");
      return;
    }

    resetFactEditor();
    setStatusMessage("Fato salvo.");
    await loadData();
  };

  const handleDeleteFact = async (fact: GraphFact) => {
    if (!confirm(`Remover o fato "${fact.subject} -> ${fact.relation} -> ${fact.object}" permanentemente?`)) return;
    const ok = await ApiController.deleteMemoryGraph(fact.subject, fact.relation, fact.object);
    if (ok) {
      setFacts(prev => prev.filter(item => item.subject !== fact.subject || item.relation !== fact.relation || item.object !== fact.object));
      if (editingFact && editingFact.subject === fact.subject && editingFact.relation === fact.relation && editingFact.object === fact.object) {
        resetFactEditor();
      }
    }
  };

  const handleSaveMemory = async () => {
    const text = memoryText.trim();
    if (text.length < 3) {
      setStatusMessage("Texto de memoria muito curto.");
      return;
    }

    const ok = editingMemory
      ? await ApiController.updateMemoryRag(editingMemory.id, text, editingMemory.metadata || {}, {
          category: memoryCategory(editingMemory),
          importance: memoryImportance(editingMemory),
          pinned: isPinned(editingMemory),
          status: memoryStatus(editingMemory),
          kind: editingMemory.kind || metadataString(editingMemory, "kind", "note"),
        })
      : Boolean(await ApiController.createMemoryRag(text, { category: "manual", importance: "medium" }));

    if (!ok) {
      setStatusMessage("Nao foi possivel salvar a memoria.");
      return;
    }

    resetMemoryEditor();
    setStatusMessage("Memoria salva.");
    await loadData();
  };

  const handleSoftDeleteMemory = async (memory: RagMemory) => {
    if (!confirm("Mover esta memoria para a lixeira?")) return;
    const ok = await ApiController.deleteMemoryRag(memory.id);
    if (ok) {
      setStatusMessage("Memoria movida para lixeira.");
      if (editingMemory?.id === memory.id) resetMemoryEditor();
      await loadData();
    }
  };

  const handleHardDeleteMemory = async (memory: RagMemory) => {
    if (!confirm("Apagar definitivamente esta memoria? Isso nao tem volta.")) return;
    const ok = await ApiController.hardDeleteMemoryRag(memory.id);
    if (ok) {
      setStatusMessage("Memoria apagada definitivamente.");
      if (editingMemory?.id === memory.id) resetMemoryEditor();
      await loadData();
    }
  };

  const handleArchiveMemory = async (memory: RagMemory) => {
    const ok = await ApiController.archiveMemoryRag(memory.id);
    if (ok) {
      setStatusMessage("Memoria arquivada.");
      await loadData();
    }
  };

  const handleRestoreMemory = async (memory: RagMemory) => {
    const ok = await ApiController.restoreMemoryRag(memory.id);
    if (ok) {
      setStatusMessage("Memoria restaurada.");
      await loadData();
    }
  };

  const handlePinMemory = async (memory: RagMemory) => {
    const nextPinned = !isPinned(memory);
    const ok = await ApiController.pinMemoryRag(memory.id, nextPinned);
    if (ok) {
      setStatusMessage(nextPinned ? "Memoria fixada." : "Memoria desafixada.");
      await loadData();
    }
  };

  const handleCompactSelected = async () => {
    const ids = Array.from(selectedMemoryIds);
    if (ids.length === 0) {
      setStatusMessage("Selecione memorias para compactar.");
      return;
    }
    const ok = await ApiController.compactMemory(ids, true);
    if (ok) {
      setStatusMessage("Memorias selecionadas compactadas e originais arquivadas.");
      await loadData();
    }
  };

  const handleMaintenance = async () => {
    const ok = await ApiController.runMemoryMaintenance();
    if (ok) {
      setStatusMessage("Sono da Hana executado.");
      await loadData();
    }
  };

  const toggleMemoryExpanded = (id: string) => {
    setExpandedMemories(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleMemorySelected = (id: string) => {
    setSelectedMemoryIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const filteredFacts = facts.filter(f =>
    f.subject.toLowerCase().includes(searchTerm.toLowerCase()) ||
    f.object.toLowerCase().includes(searchTerm.toLowerCase()) ||
    f.relation.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const selectedCount = selectedMemoryIds.size;
  const activeCount = audit?.status.active ?? 0;
  const archivedCount = audit?.status.archived ?? 0;
  const deletedCount = audit?.status.deleted ?? 0;
  const semanticLabel = audit?.semantic.enabled ? audit.semantic.mode : "fts";
  const visibleMemories = useMemo(() => memories, [memories]);

  // Group memories by friendly category for the simple-mode sections.
  const groupedMemories = useMemo(() => {
    const groups = new Map<string, RagMemory[]>();
    for (const mem of visibleMemories) {
      const key = memoryCategory(mem).toLowerCase();
      const list = groups.get(key) || [];
      list.push(mem);
      groups.set(key, list);
    }
    return Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [visibleMemories]);

  const startMemoryTest = () => {
    setTestMode(true);
    setSearchRefFocus();
  };
  const setSearchRefFocus = () => {
    window.setTimeout(() => searchRef.current?.focus(), 50);
  };

  const renderMemoryCard = (mem: RagMemory) => {
    const isExpanded = expandedMemories.has(mem.id);
    const isLong = mem.text.length > MEMORY_PREVIEW_LIMIT;
    const visibleText = isExpanded || !isLong ? mem.text : `${mem.text.slice(0, MEMORY_PREVIEW_LIMIT)}...`;
    const status = memoryStatus(mem);
    const selected = selectedMemoryIds.has(mem.id);
    const useCount = metadataNumber(mem, "useCount");
    const score = typeof mem.score === "number" ? mem.score : metadataNumber(mem, "score");
    const cat = categoryMeta(memoryCategory(mem));
    const pinned = isPinned(mem);

    const actionButtons = (
      <div className={`flex shrink-0 gap-1 ${simpleMode ? "" : "opacity-0 group-hover:opacity-100 transition-opacity"}`}>
        <button
          onClick={() => handlePinMemory(mem)}
          className={`p-2 hover:bg-white/10 rounded ${pinned ? "text-amber-300" : "text-[var(--text-muted)] hover:text-amber-300"}`}
          title={pinned ? "Desfixar memoria" : "Fixar memoria"}
        >
          {pinned ? <Star size={18} fill="currentColor" /> : <Pin size={18} />}
        </button>
        {status !== "deleted" && (
          <button
            onClick={() => {
              setEditingMemory(mem);
              setMemoryText(mem.text);
              setSearchRefFocus();
            }}
            className="text-[var(--text-muted)] hover:text-blue-400 p-2 hover:bg-white/10 rounded"
            title="Editar memoria"
          >
            <Pencil size={18} />
          </button>
        )}
        {status === "active" && (
          <button
            onClick={() => handleArchiveMemory(mem)}
            className="text-[var(--text-muted)] hover:text-emerald-300 p-2 hover:bg-white/10 rounded"
            title="Arquivar memoria"
          >
            <Archive size={18} />
          </button>
        )}
        {status !== "active" && (
          <button
            onClick={() => handleRestoreMemory(mem)}
            className="text-[var(--text-muted)] hover:text-cyan-300 p-2 hover:bg-white/10 rounded"
            title="Restaurar memoria"
          >
            <RotateCcw size={18} />
          </button>
        )}
        {status === "deleted" ? (
          <button
            onClick={() => handleHardDeleteMemory(mem)}
            className="text-[var(--text-muted)] hover:text-red-300 p-2 hover:bg-red-500/10 rounded"
            title="Apagar definitivamente"
          >
            <Trash2 size={18} />
          </button>
        ) : (
          <button
            onClick={() => handleSoftDeleteMemory(mem)}
            className="text-[var(--text-muted)] hover:text-red-400 p-2 hover:bg-red-500/10 rounded"
            title="Mover para lixeira"
          >
            <Trash2 size={18} />
          </button>
        )}
      </div>
    );

    const scoreBar = testMode && score > 0 ? (
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">Relevancia</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
          <div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-emerald-400" style={{ width: `${Math.min(100, Math.round(score * 100))}%` }} />
        </div>
        <span className="font-mono text-[10px] text-cyan-200">{score.toFixed(2)}</span>
      </div>
    ) : null;

    if (simpleMode) {
      return (
        <div
          key={mem.id}
          className="group flex flex-col gap-2 rounded-2xl border border-white/10 bg-black/40 p-4 shadow-lg transition-all hover:border-[var(--purple-neon)]/40"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5 rounded-full border border-[var(--purple-neon)]/20 bg-[var(--purple-neon)]/5 px-2.5 py-0.5 text-xs font-bold text-[var(--text-secondary)]">
                <span>{cat.emoji}</span> {cat.label}
              </span>
              {pinned && (
                <span className="flex items-center gap-1 text-[10px] font-black uppercase tracking-wider text-amber-300">
                  <Star size={11} fill="currentColor" /> fixada
                </span>
              )}
              <span className={`h-2.5 w-2.5 rounded-full ${importanceDot(memoryImportance(mem))}`} title={`Importancia: ${memoryImportance(mem)}`} />
            </div>
            {actionButtons}
          </div>

          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-gray-100">{visibleText}</p>

          {isLong && (
            <button
              onClick={() => toggleMemoryExpanded(mem.id)}
              className="flex items-center gap-1 self-start text-xs font-bold text-[var(--purple-neon)] hover:text-white"
            >
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {isExpanded ? "Ver menos" : "Ver mais"}
            </button>
          )}

          {scoreBar}
        </div>
      );
    }

    // Advanced (full diagnostic) card.
    return (
      <div key={mem.id} className={`bg-black/40 border hover:border-blue-500/50 rounded-xl p-5 transition-all group flex flex-col gap-2 shadow-lg ${selected ? "border-blue-400/70" : "border-white/10"}`}>
        <div className="flex items-start justify-between gap-4">
          <button
            onClick={() => toggleMemorySelected(mem.id)}
            className="mt-0.5 text-[var(--text-muted)] hover:text-blue-300"
            title={selected ? "Desselecionar" : "Selecionar"}
          >
            {selected ? <CheckSquare size={18} /> : <Square size={18} />}
          </button>
          <p className="text-sm text-gray-200 leading-relaxed flex-1 whitespace-pre-wrap">{visibleText}</p>
          {actionButtons}
        </div>

        {isLong && (
          <button
            onClick={() => toggleMemoryExpanded(mem.id)}
            className="self-start mt-1 text-xs font-bold text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {isExpanded ? "Ver menos" : "Ver mais"}
          </button>
        )}

        {scoreBar}

        <div className="mt-2 pt-3 border-t border-white/5 flex flex-wrap gap-2">
          <span className="text-[10px] font-mono text-blue-400 bg-blue-900/30 px-2 py-0.5 rounded border border-blue-500/20">
            ID: {mem.id.slice(0, 8)}...
          </span>
          <span className="text-[10px] font-mono text-gray-300 bg-white/5 px-2 py-0.5 rounded border border-white/10 uppercase">
            {status}
          </span>
          <span className="text-[10px] font-mono text-purple-200 bg-purple-900/30 px-2 py-0.5 rounded border border-purple-500/20">
            {memoryCategory(mem)}
          </span>
          <span className="text-[10px] font-mono text-amber-200 bg-amber-900/20 px-2 py-0.5 rounded border border-amber-500/20">
            {memoryImportance(mem)}
          </span>
          <span className="text-[10px] font-mono text-gray-400 bg-white/5 px-2 py-0.5 rounded border border-white/10">
            USO: {useCount}
          </span>
          {score > 0 && (
            <span className="text-[10px] font-mono text-cyan-200 bg-cyan-900/20 px-2 py-0.5 rounded border border-cyan-500/20">
              SCORE: {score.toFixed(2)}
            </span>
          )}
          <span className="text-[10px] font-mono text-gray-400 bg-white/5 px-2 py-0.5 rounded border border-white/10">
            ACESSO: {formatAccess(mem)}
          </span>
          {mem.tags?.slice(0, 4).map((tag) => (
            <span key={`${mem.id}-${tag}`} className="text-[10px] font-mono text-gray-400 bg-white/5 px-2 py-0.5 rounded border border-white/10">
              #{tag}
            </span>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="w-full h-full bg-[rgba(15,15,20,0.5)] backdrop-blur-2xl overflow-hidden shadow-2xl relative flex flex-col">
      <div className="bg-[rgba(10,10,15,0.85)] border-b border-[var(--border-strong)] p-6 z-10 shadow-lg backdrop-blur-md flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-[var(--purple-dark)] flex items-center justify-center border border-[var(--purple-neon)] shadow-[0_0_15px_var(--purple-dark)]">
            <BrainCircuit size={24} className="text-[var(--purple-neon)]" />
          </div>
          <div>
            <h2 className="text-2xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-[var(--purple-neon)] to-[var(--cyan-neon)]">
              Nucleo de Memoria
            </h2>
            <p className="text-[11px] text-[var(--text-muted)] uppercase tracking-widest font-bold">
              SQLite/FTS ativo · semantica opcional {semanticLabel}
            </p>
          </div>
        </div>

        <div className="flex bg-black/40 p-1.5 rounded-xl border border-white/5">
          <button
            onClick={() => setActiveTab("graph")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-wider transition-all ${
              activeTab === "graph"
                ? "bg-[var(--purple-dark)] text-white border border-[var(--purple-neon)]/50 shadow-lg"
                : "text-[var(--text-muted)] hover:text-white hover:bg-white/5"
            }`}
          >
            <Network size={14} /> Fatos
          </button>
          <button
            onClick={() => setActiveTab("rag")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-wider transition-all ${
              activeTab === "rag"
                ? "bg-blue-900/40 text-blue-400 border border-blue-500/50 shadow-lg"
                : "text-[var(--text-muted)] hover:text-white hover:bg-white/5"
            }`}
          >
            <Database size={14} /> SQLite FTS
          </button>
        </div>
      </div>

      <div className="px-6 py-4 border-b border-[var(--border-strong)] bg-black/20 flex flex-col gap-4">
        <div className="flex flex-col lg:flex-row gap-4">
          <div className="flex-1 relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              ref={searchRef}
              type="text"
              placeholder={
                activeTab === "graph"
                  ? "Buscar por entidade ou relacao..."
                  : testMode
                    ? "Pergunte algo (ex: nome da gata) e veja do que a Hana lembra..."
                    : "Buscar via backend SQLite/FTS..."
              }
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className={`w-full bg-black/40 border rounded-xl py-2 pl-9 pr-4 text-sm text-white placeholder:text-[var(--text-muted)] focus:outline-none transition-colors ${
                testMode ? "border-cyan-400/50 focus:border-cyan-300/70" : "border-white/5 focus:border-[var(--purple-neon)]/50"
              }`}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {activeTab === "rag" && (
              <button
                onClick={() => setSimpleMode((v) => !v)}
                className={`px-4 py-2 rounded-xl border flex items-center gap-2 text-xs font-bold uppercase tracking-wider transition-colors ${
                  simpleMode
                    ? "bg-[var(--purple-neon)]/15 border-[var(--purple-neon)]/40 text-[var(--purple-neon)]"
                    : "bg-white/5 border-white/10 text-[var(--text-muted)] hover:text-white"
                }`}
                title="Alternar entre visao simples (facil) e avancada (tecnica)"
              >
                <Sparkles size={16} /> {simpleMode ? "Modo simples" : "Modo avancado"}
              </button>
            )}
            {activeTab === "rag" && (
              <button
                onClick={() => (testMode ? setTestMode(false) : startMemoryTest())}
                className={`px-4 py-2 rounded-xl border flex items-center gap-2 text-xs font-bold uppercase tracking-wider transition-colors ${
                  testMode
                    ? "bg-cyan-500/15 border-cyan-400/40 text-cyan-200"
                    : "bg-white/5 border-white/10 text-[var(--text-muted)] hover:text-white"
                }`}
                title="Digite uma pergunta e veja exatamente do que a Hana lembraria"
              >
                <FlaskConical size={16} /> Testar memoria
              </button>
            )}
            {activeTab === "rag" && (
              <button
                onClick={handleMaintenance}
                className="px-4 py-2 bg-white/5 border border-white/10 rounded-xl hover:bg-white/10 transition-colors text-[var(--text-muted)] hover:text-white flex items-center gap-2 text-xs font-bold uppercase tracking-wider"
                title="Rodar manutencao"
              >
                <Activity size={16} /> Sono
              </button>
            )}
            <button
              onClick={loadData}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-xl hover:bg-white/10 transition-colors text-[var(--text-muted)] hover:text-white flex items-center justify-center"
              title="Recarregar"
            >
              <RefreshCw size={16} className={isLoading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {activeTab === "rag" && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              {MEMORY_FILTERS.map(filter => (
                <button
                  key={filter.id}
                  onClick={() => setMemoryFilter(filter.id)}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-bold uppercase tracking-wider transition-colors ${
                    memoryFilter === filter.id
                      ? "bg-blue-900/50 border-blue-500/60 text-blue-200"
                      : "bg-black/30 border-white/10 text-[var(--text-muted)] hover:text-white"
                  }`}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[10px] font-mono uppercase text-[var(--text-muted)]">
              <span className="bg-white/5 border border-white/10 px-2 py-1 rounded">ativas {activeCount}</span>
              <span className="bg-white/5 border border-white/10 px-2 py-1 rounded">arquivadas {archivedCount}</span>
              <span className="bg-white/5 border border-white/10 px-2 py-1 rounded">lixeira {deletedCount}</span>
              <span className="bg-white/5 border border-white/10 px-2 py-1 rounded">fixadas {audit?.pinned ?? 0}</span>
            </div>
          </div>
        )}

        {activeTab === "graph" ? (
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_1fr_auto] gap-3 bg-black/30 border border-white/5 rounded-xl p-3">
            <input className="bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-[var(--purple-neon)]/50" placeholder="Sujeito" value={factForm.subject} onChange={(e) => setFactForm(prev => ({ ...prev, subject: e.target.value }))} />
            <input className="bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-[var(--purple-neon)]/50" placeholder="Relacao" value={factForm.relation} onChange={(e) => setFactForm(prev => ({ ...prev, relation: e.target.value }))} />
            <input className="bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-[var(--purple-neon)]/50" placeholder="Objeto" value={factForm.object} onChange={(e) => setFactForm(prev => ({ ...prev, object: e.target.value }))} />
            <div className="flex gap-2">
              <Button onClick={handleSaveFact} variant="primary" icon={editingFact ? <Save size={15} /> : <Plus size={15} />}>
                {editingFact ? "Salvar" : "Criar"}
              </Button>
              {editingFact && (
                <Button onClick={resetFactEditor} variant="secondary" iconOnly icon={<X size={15} />} />
              )}
            </div>
          </div>
        ) : (
          <div className="bg-black/30 border border-white/5 rounded-xl p-3">
            <textarea
              className="w-full min-h-[100px] bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-blue-500/50 resize-y custom-scrollbar"
              placeholder="Escreva uma memoria persistente manual..."
              value={memoryText}
              onChange={(e) => setMemoryText(e.target.value)}
            />
            <div className="mt-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
              <span className="text-xs text-[var(--text-muted)]">
                {editingMemory ? `Editando ID ${editingMemory.id.slice(0, 8)}...` : "Nova memoria SQLite/FTS manual"}
              </span>
              <div className="flex flex-wrap gap-2">
                {selectedCount > 0 && (
                  <Button onClick={handleCompactSelected} variant="success" icon={<Archive size={15} />}>
                    Compactar {selectedCount}
                  </Button>
                )}
                {editingMemory && (
                  <Button onClick={resetMemoryEditor} variant="secondary">Cancelar</Button>
                )}
                <Button onClick={handleSaveMemory} variant="primary" icon={editingMemory ? <Save size={15} /> : <Plus size={15} />}>
                  {editingMemory ? "Salvar memoria" : "Criar memoria"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {statusMessage && (
          <div className="text-xs text-[var(--cyan-neon)] font-mono">{statusMessage}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar relative bg-gradient-to-b from-transparent to-black/40">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center flex-col gap-4">
            <div className="w-10 h-10 border-4 border-[var(--purple-neon)] border-t-transparent rounded-full animate-spin"></div>
            <p className="text-[var(--text-muted)] font-mono text-sm">Acessando redes neurais...</p>
          </div>
        ) : activeTab === "graph" ? (
          filteredFacts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)] opacity-50">
              <Network size={64} className="mb-4" />
              <p>Nenhum fato logico encontrado no Knowledge Graph.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredFacts.map((fact, i) => (
                <div key={`${fact.subject}-${fact.relation}-${fact.object}-${i}`} className="bg-black/40 border border-white/10 hover:border-[var(--purple-neon)]/50 rounded-xl p-4 transition-all group flex flex-col gap-3 shadow-lg">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-[var(--purple-neon)] bg-[var(--purple-dark)]/30 px-2 py-0.5 rounded border border-[var(--purple-neon)]/20 uppercase">Fato Logico</span>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => {
                          setEditingFact(fact);
                          setFactForm(fact);
                        }}
                        className="text-[var(--text-muted)] hover:text-[var(--cyan-neon)] p-1 hover:bg-white/10 rounded"
                        title="Editar memoria"
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        onClick={() => handleDeleteFact(fact)}
                        className="text-[var(--text-muted)] hover:text-red-400 p-1 hover:bg-red-500/10 rounded"
                        title="Apagar memoria"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-col gap-1.5 mt-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase text-[var(--text-muted)] w-16">Sujeito:</span>
                      <span className="text-white font-bold text-sm bg-white/5 px-2 py-1 rounded truncate">{fact.subject}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase text-[var(--text-muted)] w-16">Relacao:</span>
                      <span className="text-[var(--cyan-neon)] font-mono text-xs">{fact.relation}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase text-[var(--text-muted)] w-16">Objeto:</span>
                      <span className="text-white font-bold text-sm bg-white/5 px-2 py-1 rounded truncate">{fact.object}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          visibleMemories.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)] opacity-50">
              <Database size={64} className="mb-4" />
              <p>Nenhuma memoria persistente encontrada no SQLite/FTS.</p>
            </div>
          ) : simpleMode ? (
            <div className="flex flex-col gap-6">
              {groupedMemories.map(([key, list]) => {
                const meta = categoryMeta(key);
                return (
                  <div key={key} className="flex flex-col gap-3">
                    <div className="flex items-center gap-2 px-1">
                      <span className="text-lg">{meta.emoji}</span>
                      <h3 className="text-sm font-extrabold uppercase tracking-wider text-[var(--text-secondary)]">{meta.label}</h3>
                      <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-mono text-[var(--text-muted)]">{list.length}</span>
                      <div className="ml-2 h-px flex-1 bg-gradient-to-r from-white/10 to-transparent" />
                    </div>
                    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                      {list.map((mem) => renderMemoryCard(mem))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {visibleMemories.map((mem) => renderMemoryCard(mem))}
            </div>
          )
        )}
      </div>

    </div>
  );
}
