import { useState, useEffect } from "react";
import { Wrench, ChevronDown, BrainCircuit, Globe2 } from "lucide-react";
import { ChatMessage } from "../../../models/types";

// Cards colapsáveis exibidos na bolha da Hana no chat. São puramente apresentacionais
// (recebem dados por props, sem tocar no estado do TabChat). Extraídos do TabChat.tsx
// para enxugá-lo.

function hostFromUri(uri: string) {
  try {
    return new URL(uri).hostname.replace(/^www\./, "");
  } catch {
    return uri.replace(/^https?:\/\//, "").split("/")[0];
  }
}

// Collapsible "Atividade de ferramentas" card (amber, like the Terminal Agente tool events).
// Shows every tool Hana used this turn: which tool, ok/fail, query and a short return — so
// Operador can see if she tried a tool, if it failed, and what it returned.
export function ToolRunsRenderer({ toolRuns }: { toolRuns: NonNullable<NonNullable<ChatMessage["meta"]>["toolRuns"]> }) {
  const [expanded, setExpanded] = useState(false);
  const failed = toolRuns.filter((run) => !run.ok).length;

  return (
    <div className="mb-3 rounded-xl border border-amber-400/20 bg-amber-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-amber-200">
          <Wrench size={14} />
          Ferramentas
          <span className="font-mono text-[var(--text-muted)] normal-case tracking-normal">
            {toolRuns.length} {toolRuns.length === 1 ? "chamada" : "chamadas"}
            {failed ? ` · ${failed} falhou` : ""}
          </span>
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {!expanded && (
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2">
          {toolRuns.map((run, index) => (
            <span
              key={`${run.tool}-${index}`}
              className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-mono ${
                run.ok
                  ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                  : "border-red-400/20 bg-red-500/10 text-red-200"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${run.ok ? "bg-emerald-400" : "bg-red-400"}`} />
              {run.tool}
            </span>
          ))}
        </div>
      )}

      {expanded && (
        <div className="grid gap-2 px-3 pb-3">
          {toolRuns.map((run, index) => (
            <div key={`${run.tool}-${index}`} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${run.ok ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]" : "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.7)]"}`} />
                <span className="flex-1 truncate font-mono text-[11px] text-[var(--text-secondary)]">{run.tool}</span>
                <span className={`text-[9px] font-black uppercase tracking-widest ${run.ok ? "text-emerald-300" : "text-red-300"}`}>
                  {run.ok ? "ok" : "falhou"}
                </span>
              </div>
              {run.query && (
                <div className="mt-1 truncate text-[10px] font-mono text-[var(--text-muted)]">busca&gt; {run.query}</div>
              )}
              {run.summary && (
                <div className="mt-1 border-l border-amber-300/20 pl-2 text-[10px] leading-relaxed text-[var(--text-muted)] line-clamp-3">
                  {run.summary}
                </div>
              )}
              {run.sources && run.sources.length > 0 && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  {run.sources.slice(0, 5).map((source, sourceIndex) => (
                    <img
                      key={`${source.uri}-${sourceIndex}`}
                      src={`https://www.google.com/s2/favicons?domain=${hostFromUri(source.uri || "")}&sz=64`}
                      alt=""
                      className="h-3.5 w-3.5 rounded-sm bg-white/10"
                      loading="lazy"
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Collapsible "Memória usada" card: shows exactly which persistent memories were
// fed to the LLM this turn (proof against amnesia). Compact = count + token cost;
// expanded = the actual memory snippets, pinned ones flagged.
export function MemoryContextRenderer({ memoryContext }: { memoryContext: NonNullable<NonNullable<ChatMessage["meta"]>["memoryContext"]> }) {
  const [expanded, setExpanded] = useState(false);
  const memories = memoryContext.memories || [];
  if (!memories.length) return null;

  return (
    <div className="mb-3 rounded-xl border border-violet-400/20 bg-violet-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-violet-200">
          <BrainCircuit size={14} />
          Memória usada
          <span className="font-mono text-[var(--text-muted)] normal-case tracking-normal">
            {memoryContext.count} {memoryContext.count === 1 ? "lembrança" : "lembranças"}
            {memoryContext.approxTokens ? ` · ~${memoryContext.approxTokens} tokens` : ""}
          </span>
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="grid gap-1.5 px-3 pb-3">
          {memories.map((mem, index) => (
            <div key={mem.id || index} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
              <div className="flex items-center gap-2">
                {mem.pinned && <span className="text-[9px] font-black uppercase tracking-widest text-amber-300">fixada</span>}
                {mem.category && (
                  <span className="rounded-full border border-violet-400/20 bg-violet-500/10 px-1.5 py-0.5 text-[9px] font-mono text-violet-200">
                    {mem.category}
                  </span>
                )}
              </div>
              <div className="mt-1 text-[11px] leading-relaxed text-[var(--text-secondary)] line-clamp-3">{mem.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Collapsible "Pesquisa e fontes" card, ChatGPT/Gemini-style: a compact summary row that
// expands to show the search queries and the list of source links with favicons.
export function SearchSourcesRenderer({ grounding }: { grounding: NonNullable<NonNullable<ChatMessage["meta"]>["grounding"]> }) {
  const [expanded, setExpanded] = useState(false);
  const queries = grounding.queries || [];
  const sources = (grounding.sources || []).filter((source) => source.uri);

  return (
    <div className="mb-3 rounded-xl border border-emerald-400/20 bg-emerald-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-emerald-200">
          <Globe2 size={14} />
          Pesquisa na web
          <span className="font-mono text-[var(--text-muted)] normal-case tracking-normal">
            {sources.length ? `${sources.length} fontes` : "concluida"}
          </span>
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {!expanded && sources.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 pb-2">
          {sources.slice(0, 6).map((source, index) => (
            <img
              key={`${source.uri}-${index}`}
              src={`https://www.google.com/s2/favicons?domain=${hostFromUri(source.uri || "")}&sz=64`}
              alt=""
              className="h-4 w-4 rounded-sm bg-white/10"
              loading="lazy"
            />
          ))}
        </div>
      )}

      {expanded && (
        <div className="px-3 pb-3">
          {queries.map((query) => (
            <div key={query} className="mb-1 text-[10px] font-mono text-[var(--text-muted)]">
              busca&gt; {query}
            </div>
          ))}
          <div className="mt-2 grid gap-2">
            {sources.map((source, index) => (
              <a
                key={`${source.uri}-${index}`}
                href={source.uri}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 truncate rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-[11px] text-cyan-200 hover:border-cyan-300/30 hover:text-white"
              >
                <img
                  src={`https://www.google.com/s2/favicons?domain=${hostFromUri(source.uri || "")}&sz=64`}
                  alt=""
                  className="h-4 w-4 shrink-0 rounded-sm bg-white/10"
                  loading="lazy"
                />
                <span className="truncate">{source.title || source.uri}</span>
                <span className="ml-auto shrink-0 text-[9px] font-mono text-[var(--text-muted)]">{hostFromUri(source.uri || "")}</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentPlanRendererProps {
  plan: NonNullable<ChatMessage["agentPlan"]>;
  active?: boolean;
}

export function AgentPlanRenderer({ plan, active = false }: AgentPlanRendererProps) {
  const [expanded, setExpanded] = useState(active);
  const steps = plan.steps || [];
  const lastStep = steps[steps.length - 1];

  useEffect(() => {
    if (active) setExpanded(true);
  }, [active]);

  return (
    <div className="mb-4 rounded-xl border border-cyan-400/20 bg-cyan-500/5 p-3 shadow-[0_0_18px_rgba(34,211,238,0.06)]">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="w-full flex items-center justify-between gap-3 text-left"
      >
        <div className="flex items-center gap-2">
          <BrainCircuit size={15} className="text-[var(--cyan-neon)]" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--cyan-neon)]">Agent Mode</span>
          {lastStep && (
            <span className="max-w-[260px] truncate text-[10px] font-mono text-[var(--text-muted)]">
              {lastStep.tool} · {lastStep.status}
            </span>
          )}
        </div>
        <ChevronDown size={14} className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {!expanded && plan.project && (
        <div className="mt-2 truncate text-[10px] font-mono text-[var(--text-muted)]">Projeto: {plan.project}</div>
      )}

      {expanded && (
        <>
          {plan.project && (
            <div className="mt-3 text-[10px] font-mono text-[var(--text-muted)] truncate max-w-[320px]">
              Projeto: {plan.project}
            </div>
          )}

          <div className="grid gap-2">
            {steps.map((step, index) => {
              const ok = step.status === "success" || step.status === "ok" || step.status === "done";
              const running = ["planning", "executing", "verifying", "queued", "running"].includes(step.status);
              return (
                <div key={`${step.tool}-${index}`} className="rounded-xl bg-black/20 border border-white/5 px-3 py-2">
                  <div className="flex items-center gap-3">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${
                      ok
                        ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"
                        : running
                          ? "animate-pulse bg-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.8)]"
                          : "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.8)]"
                    }`} />
                    <span className="text-[11px] font-mono text-[var(--text-secondary)] flex-1 truncate">{step.tool}</span>
                    <span className={`text-[9px] font-black uppercase tracking-widest ${ok ? "text-emerald-300" : running ? "text-cyan-200" : "text-red-300"}`}>
                      {step.status}
                    </span>
                    <span className="text-[9px] font-bold uppercase text-[var(--text-muted)]">{step.risk}</span>
                  </div>
                  {step.summary && (
                    <div className="mt-2 border-l border-cyan-300/20 pl-3 text-[10px] leading-relaxed text-[var(--text-muted)]">
                      {step.summary}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
