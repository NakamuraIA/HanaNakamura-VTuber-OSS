import { useEffect, useState } from "react";
import { Cable, CheckCircle2, Globe2, Lock, Play, Plus, RefreshCcw, Server, ShieldAlert, StopCircle } from "lucide-react";
import { ApiController } from "../../controllers/api";
import { McpServer, McpTool, McpToolsResponse } from "../../models/types";
import { TabHeader } from "../components/shared/TabHeader";

export function TabMCP() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [toolsState, setToolsState] = useState<Record<string, McpToolsResponse>>({});
  const [loading, setLoading] = useState(false);
  const selected = servers.find((server) => server.id === selectedId) || servers[0];
  const tools = selected ? toolsState[selected.id]?.tools || [] : [];
  const selectedStatus = selected ? toolsState[selected.id] : null;
  const hasTavily = servers.some((server) => server.id === "tavily");

  const loadServers = async () => {
    setLoading(true);
    const data = await ApiController.getMcpServers();
    const nextServers = Array.isArray(data.servers) ? data.servers : [];
    setServers(nextServers);
    setSelectedId((current) => current || nextServers[0]?.id || "");
    setLoading(false);
  };

  const discoverTools = async (serverId: string) => {
    setLoading(true);
    const data = await ApiController.getMcpServerTools(serverId);
    setToolsState((prev) => ({ ...prev, [serverId]: data }));
    setLoading(false);
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

  useEffect(() => {
    void loadServers();
  }, []);

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] backdrop-blur-2xl p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-500">
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

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(280px,380px)_minmax(0,1fr)] gap-5">
        <section className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-4 overflow-hidden">
          <div className="mb-3 text-[10px] font-black uppercase tracking-[0.22em] text-[var(--text-muted)]">Servidores configurados</div>
          <div className="grid gap-2">
            {!hasTavily && (
              <PresetCard loading={loading} onInstall={() => void installPreset("tavily")} />
            )}
            {servers.map((server) => {
              const active = selected?.id === server.id;
              return (
                <button
                  key={server.id}
                  onClick={() => setSelectedId(server.id)}
                  className={`w-full min-w-0 overflow-hidden text-left rounded-xl border p-3 transition-all ${active ? "border-cyan-400/40 bg-cyan-500/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <Server size={16} className={server.enabled ? "text-emerald-300" : "text-[var(--text-muted)]"} />
                      <span className="truncate text-sm font-black text-white">{server.name || server.id}</span>
                    </div>
                    <span className={`rounded-full px-2 py-1 text-[9px] font-black uppercase ${server.enabled ? "bg-emerald-500/15 text-emerald-200" : "bg-red-500/10 text-red-300"}`}>
                      {server.enabled ? "on" : "off"}
                    </span>
                  </div>
                  <div className="mt-2 truncate text-[10px] font-mono text-[var(--text-muted)]">{server.command} {server.args?.join(" ")}</div>
                  <div className="mt-2 text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    Allowlist: {server.allowed_tool_count ?? server.allowed_tools?.length ?? 0}
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

        <section className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-5 min-h-[420px] overflow-hidden">
          {selected ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="min-w-0 truncate text-xl font-black text-white">{selected.name || selected.id}</h3>
                    <span className={`rounded-full px-2 py-1 text-[9px] font-black uppercase ${selected.enabled ? "bg-emerald-500/15 text-emerald-200" : "bg-red-500/10 text-red-300"}`}>
                      {selected.enabled ? "habilitado" : "desligado"}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--text-muted)] font-mono break-all">{selected.command} {selected.args?.join(" ")}</p>
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
                    className={`px-4 py-2 rounded-xl border text-xs font-black uppercase tracking-widest flex items-center gap-2 disabled:opacity-50 ${selected.enabled ? "border-red-400/25 bg-red-500/10 text-red-200" : "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"}`}
                  >
                    {selected.enabled ? <StopCircle size={14} /> : <Play size={14} />} {selected.enabled ? "Desligar" : "Ativar"}
                  </button>
                  <button
                    onClick={() => void discoverTools(selected.id)}
                    disabled={loading || !selected.enabled}
                    className="px-4 py-2 rounded-xl border border-cyan-400/25 bg-cyan-500/10 text-cyan-200 text-xs font-black uppercase tracking-widest flex items-center gap-2 disabled:opacity-40"
                  >
                    <RefreshCcw size={14} className={loading ? "animate-spin" : ""} /> Descobrir tools
                  </button>
                </div>
              </div>

              <div className="grid gap-3">
                {tools.map((tool) => (
                  <ToolRow key={tool.name} tool={tool} onToggle={() => void toggleTool(tool)} disabled={loading || !selected.enabled} />
                ))}
                {!tools.length && (
                  <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5 text-sm text-[var(--text-muted)]">
                    {selected.enabled ? "Clique em descobrir tools para consultar o servidor MCP." : "Ative o servidor para permitir discovery. Nenhuma conexao e feita enquanto ele estiver desligado."}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-sm text-[var(--text-muted)]">Selecione um servidor MCP.</div>
          )}
        </section>
      </div>
    </div>
  );
}

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
            Primeiro MCP da Hana para pesquisa web atual. Usa <span className="font-mono text-cyan-200">TAVILY_API_KEY</span> do .env.
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

function ToolRow({ tool, onToggle, disabled }: { tool: McpTool; onToggle: () => void; disabled: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {tool.allowed ? <CheckCircle2 size={15} className="text-emerald-300" /> : <Lock size={15} className="text-[var(--text-muted)]" />}
          <h4 className="font-black text-white truncate">{tool.title || tool.name}</h4>
        </div>
        <p className="mt-1 text-xs text-[var(--text-muted)]">{tool.description || "Tool MCP sem descricao."}</p>
        <div className="mt-2 text-[10px] font-mono text-[var(--text-muted)] truncate">{tool.name}</div>
      </div>
      <button
        onClick={onToggle}
        disabled={disabled}
        className={`shrink-0 px-3 py-2 rounded-xl border text-[10px] font-black uppercase tracking-widest disabled:opacity-40 ${tool.allowed ? "border-red-400/25 bg-red-500/10 text-red-200" : "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"}`}
      >
        {tool.allowed ? "Bloquear" : "Permitir"}
      </button>
    </div>
  );
}
