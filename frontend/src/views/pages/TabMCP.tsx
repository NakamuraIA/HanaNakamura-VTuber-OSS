import { useEffect, useRef, useState } from "react";
import {
  Cable, CheckCircle2, Clock, Code2, Edit3, Globe2, Lock, Play,
  Plus, RefreshCcw, Save, Server, ShieldAlert, StopCircle, Terminal,
  X, Zap
} from "lucide-react";
import { ApiController } from "../../controllers/api";
import { McpServer, McpTool, McpToolsResponse } from "../../models/types";
import { TabHeader } from "../components/shared/TabHeader";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface LogEntry {
  id: number;
  timestamp: number;
  serverId: string;
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  result: unknown;
  error?: string;
  durationMs: number;
}

interface TestState {
  editing: boolean;
  argsJson: string;
  calling: boolean;
  result: unknown;
  error?: string;
}

type DetailTab = "tools" | "resources" | "prompts";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function timeSince(ts: number): string {
  const delta = Date.now() - ts;
  if (delta < 5_000) return "agora";
  if (delta < 60_000) return `${Math.round(delta / 1000)}s`;
  return `${Math.round(delta / 60_000)}m`;
}

function prettyJson(value: unknown): string {
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function runtimeStatusLabel(status: string): string {
  return ({
    disabled: "desligado",
    warming: "aquecendo",
    ready: "pronto",
    error: "erro",
  } as Record<string, string>)[status] || status;
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function TabMCP() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [toolsState, setToolsState] = useState<Record<string, McpToolsResponse>>({});
  const [loading, setLoading] = useState(false);

  /* Feature 1 — tool detail expansion */
  const [expandedName, setExpandedName] = useState("");

  /* Feature 2 — test runner per tool */
  const [testState, setTestState] = useState<Record<string, TestState>>({});

  /* Feature 3 — sub-tabs */
  const [detailTab, setDetailTab] = useState<DetailTab>("tools");

  /* Feature 4 — health timestamps */
  const [healthTimestamps, setHealthTimestamps] = useState<Record<string, number>>({});

  /* Feature 5 — execution log */
  const [execLog, setExecLog] = useState<LogEntry[]>([]);
  const logCounter = useRef(0);

  /* Feature 6 — inline editing */
  const [editingServerId, setEditingServerId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<{ command: string; args: string; env: string; cwd: string; timeout: number }>({
    command: "", args: "", env: "", cwd: "", timeout: 20,
  });
  const [editSaving, setEditSaving] = useState(false);

  /* Derived */
  const selected = servers.find((server) => server.id === selectedId) || servers[0];
  const tools = selected ? (toolsState[selected.id]?.tools || []) : [];
  const selectedStatus = selected ? toolsState[selected.id] : null;
  const hasTavily = servers.some((server) => server.id === "tavily");

  /* ---------------------------------------------------------------- */
  /*  Data loading                                                     */
  /* ---------------------------------------------------------------- */

  const loadServers = async () => {
    setLoading(true);
    const data = await ApiController.getMcpServers();
    const nextServers = Array.isArray(data.servers) ? data.servers : [];
    setServers(nextServers);
    setSelectedId((current) => current || nextServers[0]?.id || "");
    setLoading(false);
  };

  const discoverTools = async (serverId: string) => {
    const start = Date.now();
    setLoading(true);
    const data = await ApiController.getMcpServerTools(serverId);
    setToolsState((prev) => ({ ...prev, [serverId]: data }));
    setHealthTimestamps((prev) => ({ ...prev, [serverId]: Date.now() }));
    setLoading(false);
    /* Log discovery latency */
    addLog({
      serverId,
      tool: "__discover__",
      args: {},
      ok: data.status === "ok",
      result: `${data.tools?.length ?? 0} tools`,
      error: data.error,
      durationMs: Date.now() - start,
    });
  };

  const toggleServer = async (server: McpServer) => {
    setLoading(true);
    await ApiController.setMcpServerEnabled(server.id, !server.enabled);
    await loadServers();
    setToolsState((prev) => ({
      ...prev,
      [server.id]: { ...(prev[server.id] || server), tools: [], status: !server.enabled ? "pending_discovery" : "disabled" } as McpToolsResponse,
    }));
    setLoading(false);
  };

  const toggleTool = async (tool: McpTool) => {
    if (!selected) return;
    setLoading(true);
    await ApiController.setMcpToolAllowed(selected.id, tool.name, !tool.allowed);
    await loadServers();
    await discoverTools(selected.id);
    setLoading(false);
  };

  const installPreset = async (presetId: string) => {
    setLoading(true);
    await ApiController.installMcpPreset(presetId);
    await loadServers();
    setSelectedId(presetId);
    setLoading(false);
  };

  /* ---------------------------------------------------------------- */
  /*  Logging                                                         */
  /* ---------------------------------------------------------------- */

  const addLog = (entry: Omit<LogEntry, "id" | "timestamp">) => {
    logCounter.current += 1;
    setExecLog((prev) => [
      { ...entry, id: logCounter.current, timestamp: Date.now() },
      ...prev,
    ].slice(0, 50));
  };

  /* ---------------------------------------------------------------- */
  /*  Test runner (feature 2)                                         */
  /* ---------------------------------------------------------------- */

  const openTestEditor = (toolName: string) => {
    const tool = tools.find((t) => t.name === toolName);
    const schema = tool?.input_schema as Record<string, unknown> | undefined;
    const defaults: Record<string, unknown> = {};
    if (schema?.properties && typeof schema.properties === "object") {
      for (const [key, def] of Object.entries(schema.properties as Record<string, Record<string, unknown>>)) {
        if (def?.default !== undefined) defaults[key] = def.default;
      }
    }
    setTestState((prev) => ({
      ...prev,
      [toolName]: {
        editing: true,
        argsJson: prettyJson(Object.keys(defaults).length ? defaults : {}),
        calling: false,
        result: null,
      },
    }));
  };

  const updateTestArgs = (toolName: string, json: string) => {
    setTestState((prev) => ({
      ...prev,
      [toolName]: { ...(prev[toolName] || {} as TestState), editing: true, argsJson: json, calling: false, result: null },
    }));
  };

  const runTest = async (toolName: string) => {
    if (!selected) return;
    const state = testState[toolName];
    let args: Record<string, unknown> = {};
    try { args = JSON.parse(state?.argsJson || "{}"); } catch { /* keep empty */ }
    setTestState((prev) => ({
      ...prev,
      [toolName]: { ...(prev[toolName] || {} as TestState), editing: true, calling: true, result: null, error: undefined },
    }));
    const start = Date.now();
    const data = await ApiController.callMcpTool(selected.id, toolName, args);
    const ok = data?.ok === true;
    setTestState((prev) => ({
      ...prev,
      [toolName]: { ...(prev[toolName] || {} as TestState), editing: true, calling: false, result: data, error: ok ? undefined : (data?.error || "Erro desconhecido") },
    }));
    addLog({
      serverId: selected.id,
      tool: toolName,
      args,
      ok,
      result: data,
      error: ok ? undefined : (data?.error || "Erro desconhecido"),
      durationMs: Date.now() - start,
    });
  };

  const closeTestEditor = (toolName: string) => {
    setTestState((prev) => {
      const next = { ...prev };
      delete next[toolName];
      return next;
    });
  };

  /* ---------------------------------------------------------------- */
  /*  Inline editing (feature 6)                                      */
  /* ---------------------------------------------------------------- */

  const openServerEditor = (server: McpServer) => {
    setEditingServerId(server.id);
    setEditDraft({
      command: server.command || "",
      args: (server.args || []).join(" "),
      env: server.env ? Object.entries(server.env).map(([k, v]) => `${k}=${v}`).join("\n") : "",
      cwd: server.cwd || "",
      timeout: server.timeout || 20,
    });
  };

  const closeServerEditor = () => {
    setEditingServerId(null);
  };

  const saveServerEdit = async () => {
    if (!editingServerId) return;
    setEditSaving(true);
    const argsList = editDraft.args
      .split(" ")
      .map((s) => s.trim())
      .filter(Boolean);
    const envObj: Record<string, string> = {};
    if (editDraft.env.trim()) {
      for (const line of editDraft.env.split("\n")) {
        const eq = line.indexOf("=");
        if (eq > 0) {
          envObj[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
        }
      }
    }
    await ApiController.updateMcpServer(editingServerId, {
      command: editDraft.command,
      args: argsList,
      env: envObj,
      cwd: editDraft.cwd || null,
      timeout: editDraft.timeout,
    } as Partial<McpServer>);
    await loadServers();
    setEditSaving(false);
    setEditingServerId(null);
  };

  /* ---------------------------------------------------------------- */
  /*  Effects                                                         */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    void loadServers();
  }, []);

  /* ---------------------------------------------------------------- */
  /*  Render                                                          */
  /* ---------------------------------------------------------------- */

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] hana-glass p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-500 flex flex-col">
      <TabHeader
        icon={<Cable size={24} />}
        title="MCP Provider"
        subtitle="Servidores desligados por padrao; tools precisam entrar na allowlist"
        actions={
          <button
            onClick={() => void loadServers()}
            disabled={loading}
            className="px-4 py-2 rounded-[var(--radius-control)] bg-white/5 border border-white/10 text-xs font-black uppercase tracking-widest text-[var(--text-secondary)] hover:text-white hover:bg-white/10 disabled:opacity-50 flex items-center gap-2"
          >
            <RefreshCcw size={14} className={loading ? "animate-spin" : ""} /> Atualizar
          </button>
        }
      />

      {/* Server list + detail grid */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(280px,380px)_minmax(0,1fr)] gap-5 flex-1 min-h-0">
        {/* ============== LEFT COLUMN — server list ============== */}
        <section className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-4 overflow-y-auto custom-scrollbar">
          <div className="mb-3 text-[10px] font-black uppercase tracking-[0.22em] text-[var(--text-muted)]">
            Servidores configurados
          </div>
          <div className="grid gap-2">
            {!hasTavily && (
              <PresetCard loading={loading} onInstall={() => void installPreset("tavily")} />
            )}
            {servers.map((server) => {
              const active = selected?.id === server.id;
              const lastCheck = healthTimestamps[server.id];
              const status = toolsState[server.id]?.status || server.runtime_status;
              return (
                <button
                  key={server.id}
                  onClick={() => setSelectedId(server.id)}
                  className={`w-full min-w-0 overflow-hidden text-left rounded-xl border p-3 transition-all ${
                    active ? "border-cyan-400/40 bg-cyan-500/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <Server size={16} className={server.enabled ? "text-emerald-300" : "text-[var(--text-muted)]"} />
                      <span className="truncate text-sm font-black text-white">{server.name || server.id}</span>
                    </div>
                    <span
                      className={`rounded-full px-2 py-1 text-[9px] font-black uppercase ${
                        server.enabled ? "bg-emerald-500/15 text-emerald-200" : "bg-red-500/10 text-red-300"
                      }`}
                    >
                      {server.enabled ? "on" : "off"}
                    </span>
                  </div>
                  <div className="mt-2 truncate text-[10px] font-mono text-[var(--text-muted)]">
                    {server.command} {server.args?.join(" ")}
                  </div>

                  {/* --- Health badges (feature 4) --- */}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                      Allowlist: {server.allowed_tool_count ?? server.allowed_tools?.length ?? 0}
                    </span>
                    {status && (
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[8px] font-black uppercase ${
                          status === "ok" || status === "ready"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : status === "error"
                              ? "bg-red-500/15 text-red-300"
                              : "bg-yellow-500/15 text-yellow-300"
                        }`}
                      >
                        {runtimeStatusLabel(status)}
                      </span>
                    )}
                    {lastCheck && (
                      <span className="rounded-full px-1.5 py-0.5 text-[8px] font-black uppercase bg-white/5 text-[var(--text-muted)] flex items-center gap-1">
                        <Clock size={9} />
                        {timeSince(lastCheck)}
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
            {!servers.length && (
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-sm text-[var(--text-muted)]">
                Nenhum servidor MCP configurado. Use um preset acima para comecar sem editar JSON manualmente.
              </div>
            )}
          </div>
        </section>

        {/* ============== RIGHT COLUMN — server detail ============== */}
        <section className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-5 min-h-[420px] overflow-y-auto custom-scrollbar flex flex-col">
          {selected ? (
            <>
              {/* Server header + actions */}
              <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="min-w-0 truncate text-xl font-black text-white">{selected.name || selected.id}</h3>
                    <span
                      className={`rounded-full px-2 py-1 text-[9px] font-black uppercase ${
                        selected.enabled ? "bg-emerald-500/15 text-emerald-200" : "bg-red-500/10 text-red-300"
                      }`}
                    >
                      {selected.enabled ? "habilitado" : "desligado"}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--text-muted)] font-mono break-all">
                    {selected.command} {selected.args?.join(" ")}
                  </p>
                  {selectedStatus?.error && (
                    <p className="mt-2 text-xs text-red-300 flex items-center gap-2">
                      <ShieldAlert size={13} /> {selectedStatus.error}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  <button
                    onClick={() => void toggleServer(selected)}
                    disabled={loading}
                    className={`px-4 py-2 rounded-xl border text-xs font-black uppercase tracking-widest flex items-center gap-2 disabled:opacity-50 ${
                      selected.enabled
                        ? "border-red-400/25 bg-red-500/10 text-red-200"
                        : "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"
                    }`}
                  >
                    {selected.enabled ? <StopCircle size={14} /> : <Play size={14} />}{" "}
                    {selected.enabled ? "Desligar" : "Ativar"}
                  </button>
                  <button
                    onClick={() => void discoverTools(selected.id)}
                    disabled={loading || !selected.enabled}
                    className="px-4 py-2 rounded-xl border border-cyan-400/25 bg-cyan-500/10 text-cyan-200 text-xs font-black uppercase tracking-widest flex items-center gap-2 disabled:opacity-40"
                  >
                    <RefreshCcw size={14} className={loading ? "animate-spin" : ""} /> Descobrir tools
                  </button>
                  <button
                    onClick={() => openServerEditor(selected)}
                    className="px-4 py-2 rounded-xl border border-white/15 bg-white/5 text-xs font-black uppercase tracking-widest flex items-center gap-2 hover:bg-white/10"
                  >
                    <Edit3 size={14} /> Editar
                  </button>
                </div>
              </div>

              {/* --- Inline editing form (feature 6) --- */}
              {editingServerId === selected.id && (
                <div className="mb-4 rounded-xl border border-yellow-400/30 bg-yellow-500/5 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-black uppercase tracking-widest text-yellow-200 flex items-center gap-2">
                      <Edit3 size={13} /> Editando {selected.name || selected.id}
                    </span>
                    <button onClick={closeServerEditor} className="text-[var(--text-muted)] hover:text-white">
                      <X size={14} />
                    </button>
                  </div>
                  <div className="grid gap-3">
                    <div>
                      <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">Command</label>
                      <input
                        type="text"
                        value={editDraft.command}
                        onChange={(e) => setEditDraft((d) => ({ ...d, command: e.target.value }))}
                        className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-mono text-white"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">Args (separados por espaco)</label>
                      <input
                        type="text"
                        value={editDraft.args}
                        onChange={(e) => setEditDraft((d) => ({ ...d, args: e.target.value }))}
                        className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-mono text-white"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">Env (KEY=VAL por linha)</label>
                      <textarea
                        rows={3}
                        value={editDraft.env}
                        onChange={(e) => setEditDraft((d) => ({ ...d, env: e.target.value }))}
                        className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-mono text-white resize-none"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">CWD</label>
                        <input
                          type="text"
                          value={editDraft.cwd}
                          onChange={(e) => setEditDraft((d) => ({ ...d, cwd: e.target.value }))}
                          className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-mono text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">Timeout (s)</label>
                        <input
                          type="number"
                          value={editDraft.timeout}
                          onChange={(e) => setEditDraft((d) => ({ ...d, timeout: Number(e.target.value) || 20 }))}
                          className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-mono text-white"
                        />
                      </div>
                    </div>
                    <button
                      onClick={() => void saveServerEdit()}
                      disabled={editSaving}
                      className="self-start px-4 py-2 rounded-xl border border-emerald-400/30 bg-emerald-500/10 text-emerald-200 text-xs font-black uppercase tracking-widest flex items-center gap-2 disabled:opacity-40"
                    >
                      <Save size={14} /> {editSaving ? "Salvando..." : "Salvar"}
                    </button>
                  </div>
                </div>
              )}

              {/* --- Sub-tabs (feature 3) --- */}
              <div className="flex gap-1 mb-4 border-b border-white/10 pb-2">
                {(["tools", "resources", "prompts"] as DetailTab[]).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setDetailTab(tab)}
                    className={`px-4 py-1.5 rounded-t-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                      detailTab === tab
                        ? "bg-cyan-500/15 text-cyan-200 border-b-2 border-cyan-400"
                        : "text-[var(--text-muted)] hover:text-white"
                    }`}
                  >
                    {tab === "tools" ? "Tools" : tab === "resources" ? "Resources" : "Prompts"}
                  </button>
                ))}
              </div>

              {/* --- Tab content --- */}
              {detailTab === "tools" && (
                <div className="grid gap-3 flex-1 min-h-0 overflow-y-auto custom-scrollbar">
                  {tools.map((tool) => {
                    const expanded = expandedName === tool.name;
                    const test = testState[tool.name];
                    return (
                      <div key={tool.name}>
                        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                          <div className="flex items-start justify-between gap-4">
                            <div
                              className="min-w-0 flex-1 cursor-pointer"
                              onClick={() => setExpandedName(expanded ? "" : tool.name)}
                            >
                              <div className="flex items-center gap-2">
                                {tool.allowed ? (
                                  <CheckCircle2 size={15} className="text-emerald-300 shrink-0" />
                                ) : (
                                  <Lock size={15} className="text-[var(--text-muted)] shrink-0" />
                                )}
                                <h4 className="font-black text-white truncate">{tool.title || tool.name}</h4>
                              </div>
                              <p className="mt-1 text-xs text-[var(--text-muted)]">{tool.description || "Tool MCP sem descricao."}</p>
                              <div className="mt-2 text-[10px] font-mono text-[var(--text-muted)] truncate flex items-center gap-2">
                                {tool.name}
                                {tool.annotations?.readOnlyHint !== undefined && (
                                  <span className="text-[8px] bg-white/5 px-1 rounded">
                                    {tool.annotations.readOnlyHint ? "read-only" : "destructive"}
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <button
                                onClick={() => openTestEditor(tool.name)}
                                disabled={loading || !selected?.enabled}
                                className="px-3 py-1.5 rounded-lg border border-cyan-400/25 bg-cyan-500/10 text-cyan-200 text-[9px] font-black uppercase tracking-widest flex items-center gap-1 disabled:opacity-40"
                              >
                                <Zap size={11} /> Testar
                              </button>
                              <button
                                onClick={() => void toggleTool(tool)}
                                disabled={loading || !selected?.enabled}
                                className={`shrink-0 px-3 py-2 rounded-xl border text-[10px] font-black uppercase tracking-widest disabled:opacity-40 ${
                                  tool.allowed
                                    ? "border-red-400/25 bg-red-500/10 text-red-200"
                                    : "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"
                                }`}
                              >
                                {tool.allowed ? "Bloquear" : "Permitir"}
                              </button>
                            </div>
                          </div>

                          {/* --- Expanded: schema detail (feature 1) --- */}
                          {expanded && (
                            <div className="mt-4 pt-4 border-t border-white/10">
                              <SchemaCard tool={tool} />
                            </div>
                          )}
                        </div>

                        {/* --- Test panel (feature 2) --- */}
                        {test?.editing && <TestPanel toolName={tool.name} test={test} onArgsChange={updateTestArgs} onRun={() => void runTest(tool.name)} onClose={() => closeTestEditor(tool.name)} />}
                      </div>
                    );
                  })}
                  {!tools.length && (
                    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5 text-sm text-[var(--text-muted)]">
                      {selected.enabled
                        ? "Clique em descobrir tools para consultar o servidor MCP."
                        : "Ative o servidor para permitir discovery. Nenhuma conexao e feita enquanto ele estiver desligado."}
                    </div>
                  )}
                </div>
              )}

              {detailTab === "resources" && <PlaceholderTab title="Resources" icon={<Code2 size={40} />} message="Listagem de MCP resources ainda nao implementada no backend. Sera exibida aqui quando a API de resources estiver disponivel." />}

              {detailTab === "prompts" && <PlaceholderTab title="Prompts" icon={<Code2 size={40} />} message="Listagem de MCP prompts ainda nao implementada no backend. Sera exibida aqui quando a API de prompts estiver disponivel." />}
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-sm text-[var(--text-muted)]">
              Selecione um servidor MCP.
            </div>
          )}
        </section>
      </div>

      {/* ============== Execution Log (feature 5) ============== */}
      <ExecutionLog entries={execLog} />
    </div>
  );
}

/* ================================================================== */
/*  Sub-components                                                    */
/* ================================================================== */

/* --- Preset Card --- */
function PresetCard({ loading, onInstall }: { loading: boolean; onInstall: () => void }) {
  return (
    <div className="rounded-xl border border-cyan-400/20 bg-cyan-500/[0.07] p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Globe2 size={16} className="text-cyan-200" />
            <span className="truncate text-sm font-black text-white">Tavily Web Search</span>
          </div>
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            Primeiro MCP da Hana para pesquisa web atual. Usa{" "}
            <span className="font-mono text-cyan-200">TAVILY_API_KEY</span> do .env.
          </p>
          <p className="mt-2 text-[10px] font-bold uppercase tracking-widest text-cyan-200/80">
            Instala desligado com tavily-search permitido.
          </p>
        </div>
        <button
          onClick={onInstall}
          disabled={loading}
          className="shrink-0 px-3 py-2 rounded-xl border border-cyan-400/30 bg-cyan-500/10 text-cyan-100 text-[10px] font-black uppercase tracking-widest disabled:opacity-40 flex items-center gap-2"
        >
          <Plus size={13} /> Adicionar
        </button>
      </div>
    </div>
  );
}

/* --- Schema Card (feature 1) --- */
function SchemaCard({ tool }: { tool: McpTool }) {
  const schema = tool.input_schema as Record<string, unknown> | undefined;
  const properties = schema?.properties as Record<string, Record<string, unknown>> | undefined;
  const required = (schema?.required as string[]) || [];

  if (!properties || !Object.keys(properties).length) {
    return (
      <div className="text-[10px] text-[var(--text-muted)] italic">
        Sem schema de input definido para esta tool.
      </div>
    );
  }

  const params = Object.entries(properties);

  return (
    <div>
      <div className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] mb-2">
        Input Schema ({params.length} parametro{params.length !== 1 ? "s" : ""})
      </div>
      <div className="grid gap-2">
        {params.map(([name, def]) => {
          const isRequired = required.includes(name);
          const type = (def?.type as string) || "any";
          const desc = (def?.description as string) || "";
          const defVal = def?.default !== undefined ? String(def.default) : undefined;
          return (
            <div key={name} className="rounded-lg border border-white/10 bg-black/20 p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-xs font-bold text-cyan-200">{name}</span>
                <span className="text-[9px] rounded bg-white/5 px-1.5 py-0.5 font-mono text-[var(--text-muted)] uppercase">
                  {type}
                </span>
                {isRequired && (
                  <span className="text-[9px] rounded bg-red-500/15 px-1.5 py-0.5 font-black text-red-300 uppercase">
                    required
                  </span>
                )}
                {(def?.enum as unknown[])?.length > 0 && (
                  <span className="text-[9px] rounded bg-yellow-500/10 px-1.5 py-0.5 font-mono text-yellow-200">
                    enum: {(def.enum as string[]).join(", ")}
                  </span>
                )}
              </div>
              {desc && <p className="text-[10px] text-[var(--text-muted)]">{desc}</p>}
              {defVal && (
                <p className="mt-1 text-[9px] text-[var(--text-muted)]">
                  Default: <span className="font-mono text-emerald-200">{defVal}</span>
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* --- Test Panel (feature 2) --- */
function TestPanel({
  toolName,
  test,
  onArgsChange,
  onRun,
  onClose,
}: {
  toolName: string;
  test: TestState;
  onArgsChange: (toolName: string, json: string) => void;
  onRun: () => void;
  onClose: () => void;
}) {
  return (
    <div className="mt-2 rounded-xl border border-cyan-400/25 bg-cyan-500/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-black uppercase tracking-widest text-cyan-200 flex items-center gap-2">
          <Zap size={13} /> Testar: {toolName}
        </span>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white">
          <X size={14} />
        </button>
      </div>

      <div className="mb-3">
        <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">
          Argumentos (JSON)
        </label>
        <textarea
          rows={4}
          value={test.argsJson}
          onChange={(e) => onArgsChange(toolName, e.target.value)}
          className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs font-mono text-white resize-none"
          placeholder='{"query": "hello"}'
        />
      </div>

      <button
        onClick={onRun}
        disabled={test.calling}
        className="px-4 py-2 rounded-xl border border-cyan-400/30 bg-cyan-500/10 text-cyan-200 text-xs font-black uppercase tracking-widest flex items-center gap-2 disabled:opacity-40"
      >
        {test.calling ? (
          <>
            <RefreshCcw size={13} className="animate-spin" /> Executando...
          </>
        ) : (
          <>
            <Play size={13} /> Executar
          </>
        )}
      </button>

      {(test.result || test.error) && (
        <div className={`mt-3 rounded-lg border p-3 ${test.error ? "border-red-400/25 bg-red-500/5" : "border-emerald-400/25 bg-emerald-500/5"}`}>
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-[10px] font-black uppercase tracking-widest ${test.error ? "text-red-200" : "text-emerald-200"}`}>
              {test.error ? "Erro" : "Resultado"}
            </span>
          </div>
          <pre className="text-[11px] font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-all max-h-40 overflow-y-auto custom-scrollbar">
            {test.error ? test.error : prettyJson(test.result)}
          </pre>
        </div>
      )}
    </div>
  );
}

/* --- Placeholder Tab (feature 3) --- */
function PlaceholderTab({ title, icon, message }: { title: string; icon: React.ReactNode; message: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
      <div className="text-[var(--text-muted)] mb-4">{icon}</div>
      <h4 className="text-sm font-black text-white mb-2">{title}</h4>
      <p className="text-xs text-[var(--text-muted)] max-w-xs">{message}</p>
    </div>
  );
}

/* --- Execution Log (feature 5) --- */
function ExecutionLog({ entries }: { entries: LogEntry[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-4 rounded-2xl border border-white/10 bg-black/40 overflow-hidden shrink-0">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center justify-between px-4 py-2 bg-white/[0.03] hover:bg-white/[0.06] transition-colors"
      >
        <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] flex items-center gap-2">
          <Terminal size={13} /> Execution Log ({entries.length})
        </span>
        <span className="text-[10px] text-[var(--text-muted)]">{expanded ? "ocultar" : "expandir"}</span>
      </button>
      {expanded && (
        <div className="max-h-48 overflow-y-auto custom-scrollbar font-mono text-[11px] leading-relaxed">
          {entries.length === 0 ? (
            <div className="px-4 py-3 text-[var(--text-muted)] italic">Nenhuma execucao registrada ainda.</div>
          ) : (
            entries.map((entry) => (
              <div
                key={entry.id}
                className={`px-4 py-2 border-b border-white/5 ${
                  entry.tool === "__discover__" ? "opacity-60" : ""
                }`}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`text-[10px] font-black ${
                      entry.ok ? "text-emerald-300" : "text-red-300"
                    }`}
                  >
                    {entry.ok ? "OK" : "ERR"}
                  </span>
                  <span className="text-[var(--text-muted)]">
                    {entry.tool === "__discover__" ? "discover" : entry.tool}
                  </span>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {formatDuration(entry.durationMs)}
                  </span>
                  <span className="text-[9px] text-[var(--text-muted)] ml-auto">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                {entry.args && Object.keys(entry.args).length > 0 && (
                  <div className="mt-1 text-[10px] text-[var(--text-muted)] truncate">
                    args: {JSON.stringify(entry.args)}
                  </div>
                )}
                {entry.error && (
                  <div className="mt-1 text-[10px] text-red-300 truncate">{entry.error}</div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
