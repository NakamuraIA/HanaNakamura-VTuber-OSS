import { useEffect, useState } from "react";
import { ApiController } from "../../controllers/api";
import { SystemStatus } from "../../models/types";
import { Card } from "../components/shared/Card";
import { TabHeader } from "../components/shared/TabHeader";

import { MonitorDot, BrainCircuit, Mic, Eye, MessageSquareText, PlugZap, Activity, TerminalSquare, Bot, BellRing, X } from "lucide-react";
import type { Reminder } from "../../api/reminders";

/** Horizontal progress bar for CPU/RAM metrics. */
function MetricBar({ label, percent, detail, color }: { label: string; percent: number; detail: string; color: "purple" | "cyan" | "yellow" | "red" }) {
  const colorMap = {
    purple: { bar: "var(--purple-neon)", glow: "rgba(168,85,247,0.4)", text: "text-[var(--purple-neon)]", hex: "#a855f7" },
    cyan:   { bar: "var(--cyan-neon)",   glow: "rgba(34,211,238,0.4)",  text: "text-[var(--cyan-neon)]",   hex: "#22d3ee" },
    yellow: { bar: "#eab308",            glow: "rgba(234,179,8,0.4)",   text: "text-yellow-400",          hex: "#eab308" },
    red:    { bar: "#ef4444",            glow: "rgba(239,68,68,0.5)",   text: "text-red-400",             hex: "#ef4444" },
  };
  const c = colorMap[color];
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between items-center">
        <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">{label}</span>
        <span className={`text-xs font-mono font-bold ${c.text}`}>{percent.toFixed(1)}%</span>
      </div>
      <div className="w-full h-2.5 bg-black/60 rounded-full overflow-hidden border border-white/5">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{
            width: `${Math.min(100, percent)}%`,
            background: `linear-gradient(90deg, ${c.hex}, ${c.hex}88)`,
            boxShadow: `0 0 10px ${c.glow}`,
          }}
        />
      </div>
      <span className="text-[10px] text-[var(--text-muted)] font-mono">{detail}</span>
    </div>
  );
}

export function TabGeral() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [logs, setLogs] = useState<{timestamp: string; level: string; message: string}[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);

  const refreshReminders = () => {
    ApiController.getReminders().then(setReminders).catch(() => setReminders([]));
  };

  useEffect(() => {
    refreshReminders();
    const timer = window.setInterval(refreshReminders, 20000);
    return () => window.clearInterval(timer);
  }, []);

  const cancelReminder = async (id: string) => {
    await ApiController.cancelReminder(id);
    refreshReminders();
  };

  useEffect(() => {
    // Tenta conectar via WebSocket
    let ws: WebSocket | null = null;
    try {
      ws = ApiController.connectStatusWebSocket((data) => {
        setStatus(data);
      });
    } catch (e) {
      console.debug("WebSocket de status indisponivel, usando fallback.", e);
    }

    // Loop fallback caso não tenha backend
    const interval = setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        ApiController.getSystemStatus().then(setStatus).catch(() => {});
      }
    }, 2000);

    // Real system logs via API polling
    const logInterval = setInterval(() => {
      ApiController.getSystemLogs(10).then((data) => {
        setLogs(data.logs || []);
      }).catch(() => {});
    }, 3000);
    // Initial fetch
    ApiController.getSystemLogs(10).then((data) => {
      setLogs(data.logs || []);
    }).catch(() => {});

    return () => {
      clearInterval(interval);
      clearInterval(logInterval);
      if (ws) ws.close();
    };
  }, []);

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] hana-glass p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-500">
      {/* HEADER */}
      <TabHeader
        icon={<MonitorDot size={24} />}
        title="Monitor Geral"
        subtitle="Status em tempo real do ecossistema e hardware da Hana"
      />

      {/* CARDS GRID */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* CARD: RECURSOS DO SISTEMA (Hardware Dashboard) */}
        <Card hover className="flex flex-col">
          <div className="absolute top-[-50px] right-[-50px] w-40 h-40 bg-[var(--accent)] rounded-full blur-[80px] opacity-20 pointer-events-none group-hover:opacity-40 transition-opacity duration-1000" />

          <div className="flex items-center justify-between mb-5 relative z-10">
            <h3 className="font-bold text-[var(--text-primary)] text-lg flex items-center gap-2">
              <Activity size={20} className="text-[var(--purple-neon)]" /> Status de Hardware
            </h3>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full animate-pulse ${!status ? 'bg-gray-500' : (status.cpu > 80 || status.ramPercent > 90) ? 'bg-red-500' : (status.cpu > 50 || status.ramPercent > 75) ? 'bg-yellow-500' : 'bg-green-400'}`} />
              <span className="text-[9px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-widest">Live</span>
            </div>
          </div>

          {status ? (
            <div className="relative z-10 flex flex-col gap-5">
              {/* Health score — big combined gauge */}
              <div className="flex items-center gap-4 bg-black/40 rounded-xl border border-white/5 p-4">
                <div className="relative w-[72px] h-[72px] shrink-0 flex items-center justify-center">
                  <svg className="absolute inset-0 w-full h-full -rotate-90">
                    <circle cx="36" cy="36" r="30" className="stroke-white/5 fill-transparent" strokeWidth="6" />
                    <circle
                      cx="36" cy="36" r="30"
                      className="fill-transparent transition-all duration-1000 ease-out"
                      strokeWidth="6"
                      strokeLinecap="round"
                      strokeDasharray={2 * Math.PI * 30}
                      strokeDashoffset={2 * Math.PI * 30 * (1 - Math.max(status.cpu, status.ramPercent) / 100)}
                      stroke="currentColor"
                      style={{
                        color: Math.max(status.cpu, status.ramPercent) > 80
                          ? "#ef4444" : Math.max(status.cpu, status.ramPercent) > 50
                            ? "#eab308" : "#a855f7",
                        filter: `drop-shadow(0 0 8px ${Math.max(status.cpu, status.ramPercent) > 80 ? "#ef444488" : Math.max(status.cpu, status.ramPercent) > 50 ? "#eab30888" : "#a855f788"})`,
                      }}
                    />
                  </svg>
                  <span className="text-lg font-black font-mono text-white">
                    {Math.max(status.cpu, status.ramPercent).toFixed(0)}
                    <span className="text-[10px] text-[var(--text-muted)]">%</span>
                  </span>
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="text-xs font-bold text-[var(--text-secondary)]">
                    {Math.max(status.cpu, status.ramPercent) > 80 ? "Sobrecarga" : Math.max(status.cpu, status.ramPercent) > 50 ? "Moderado" : "Saudável"}
                  </span>
                  <span className="text-[10px] text-[var(--text-muted)]">Pico de uso do sistema</span>
                </div>
              </div>

              {/* CPU bar */}
              <MetricBar
                label="CPU"
                percent={status.cpu}
                detail={`${status.cpu.toFixed(1)}%`}
                color={status.cpu > 80 ? "red" : status.cpu > 50 ? "yellow" : "purple"}
              />

              {/* RAM bar */}
              <MetricBar
                label="RAM"
                percent={status.ramPercent}
                detail={`${status.ramUsedStr} / ${status.ramTotalStr} GB`}
                color={status.ramPercent > 90 ? "red" : status.ramPercent > 75 ? "yellow" : "cyan"}
              />
            </div>
          ) : (
            <div className="relative z-10 flex flex-col items-center gap-2 py-8">
              <Activity size={28} className="text-[var(--text-muted)] animate-pulse" />
              <span className="text-xs text-[var(--text-muted)] font-mono">Aguardando telemetria...</span>
            </div>
          )}
        </Card>

        {/* CARD: MOTOR LLM ATIVO & TERMINAL */}
        <Card className="flex flex-col">
          <div className="absolute bottom-0 right-0 w-32 h-32 bg-[var(--accent-2)] rounded-full blur-[80px] opacity-10 pointer-events-none"></div>

          <h3 className="font-bold text-[var(--text-primary)] mb-4 text-lg flex items-center gap-2">
            <BrainCircuit size={20} className="text-[var(--cyan-neon)]" /> Inteligência Central
          </h3>
          
          <div className="grid grid-cols-2 gap-3 relative z-10 mb-4">
            <div className="flex flex-col bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.05)] rounded-xl p-3 hover:bg-[rgba(255,255,255,0.04)] transition-colors">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1 font-bold">LLM Engine</span>
              <span className="font-mono text-sm text-[var(--text-primary)] font-black">{status ? status.llmProvider.toUpperCase() : "—"}</span>
            </div>
            
            <div className="flex flex-col bg-gradient-to-br from-[var(--purple-dark)] to-transparent border border-[var(--purple-neon)]/30 rounded-xl p-3">
              <span className="text-[10px] text-[var(--purple-neon)] opacity-80 uppercase tracking-wider mb-1 font-bold">Modelo Core</span>
              <span className="font-mono text-sm text-white font-black truncate">{status ? status.llmModel : "—"}</span>
            </div>
          </div>

          <div className="flex-1 min-h-[100px] max-h-[200px] bg-black/60 border border-white/5 rounded-xl p-3 relative overflow-y-auto flex flex-col font-mono text-[10px] custom-scrollbar">
            <div className="flex items-center gap-2 mb-2 text-[var(--text-muted)] border-b border-white/5 pb-1">
              <TerminalSquare size={12} />
              <span className="uppercase tracking-widest">System Log</span>
            </div>
            <div className="flex-1 flex flex-col justify-end gap-1">
              {logs.map((log, i) => {
                const levelColor = log.level === "ERROR" ? "text-red-400" : log.level === "WARNING" ? "text-yellow-400" : "text-green-400/80";
                const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "";
                return (
                  <div key={i} className={`${levelColor} animate-fade-in break-all whitespace-pre-wrap font-mono text-[10px]`}>
                    [{time}] [{log.level}] {log.message}
                  </div>
                );
              })}
            </div>
            <div className="absolute top-0 left-0 w-1 h-full bg-gradient-to-b from-transparent via-green-500/50 to-transparent animate-pulse"></div>
          </div>
        </Card>

        {/* CARD: MÓDULOS ATIVOS (Ocupa 2 colunas) */}
        <Card hover className="md:col-span-2">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full h-full bg-gradient-to-r from-transparent via-[rgba(168,85,247,0.03)] to-transparent pointer-events-none"></div>

          <h3 className="font-bold text-[var(--text-primary)] mb-6 text-lg flex items-center gap-2 relative z-10">
            <PlugZap size={20} className="text-green-400" /> Conexões & Módulos
          </h3>
          
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 relative z-10">
            {[
              { id: "llm", label: "LLM Principal", icon: <BrainCircuit size={20} /> },
              { id: "tts", label: "Voz (TTS)", icon: <Mic size={20} /> },
              { id: "stt", label: "Ouvido (STT)", icon: <Mic size={20} /> },
              { id: "visao", label: "Visão / Multimodal", icon: <Eye size={20} /> },
              { id: "discord", label: "Bot Discord", icon: <MessageSquareText size={20} /> },
              { id: "localHands", label: "Mãos (Terminal)", icon: <Bot size={20} /> },
            ].map((mod) => {
              const isAtivo = status ? status.modules[mod.id as keyof SystemStatus["modules"]] : false;
              
              return (
                <div key={mod.id} className={`group bg-[rgba(0,0,0,0.4)] border ${isAtivo ? 'border-green-500/30 shadow-[inset_0_0_15px_rgba(34,197,94,0.1)]' : 'border-[rgba(255,255,255,0.05)]'} rounded-xl p-4 flex items-center gap-4 transition-all hover:scale-[1.02]`}>
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg ${isAtivo ? 'bg-green-500/20 text-green-400' : 'bg-white/5 text-gray-500'}`}>
                    {mod.icon}
                  </div>
                  <div className="flex flex-col">
                    <span className={`text-sm font-bold ${isAtivo ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}>
                      {mod.label}
                    </span>
                    <span className={`text-[10px] uppercase font-bold tracking-widest ${isAtivo ? 'text-green-400 drop-shadow-[0_0_5px_rgba(34,197,94,0.5)]' : 'text-red-500/70'}`}>
                      {isAtivo ? 'Online' : 'Offline'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* CARD: LEMBRETES ATIVOS */}
        <Card hover className="md:col-span-2">
          <h3 className="font-bold text-[var(--text-primary)] mb-4 text-lg flex items-center gap-2 relative z-10">
            <BellRing size={20} className="text-[var(--accent)]" /> Lembretes
            <span className="ml-auto text-xs font-mono text-[var(--text-muted)]">{reminders.length} ativo(s)</span>
          </h3>
          {reminders.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)] relative z-10">
              Nenhum lembrete ativo. Peça no chat: "Hana, me lembra de X às 16h".
            </p>
          ) : (
            <div className="flex flex-col gap-2 relative z-10">
              {reminders.map((item) => (
                <div key={item.id} className="flex items-center gap-3 rounded-lg border border-white/10 bg-black/30 px-3 py-2">
                  <BellRing size={14} className="shrink-0 text-[var(--accent)]" />
                  <span className="min-w-0 flex-1 truncate text-sm text-white">{item.text}</span>
                  <span className="shrink-0 font-mono text-[11px] text-[var(--text-muted)]">
                    {new Date(item.due_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    {item.repeat === "daily" ? " · diário" : ""}
                  </span>
                  <button
                    type="button"
                    onClick={() => cancelReminder(item.id)}
                    className="shrink-0 rounded p-1 text-[var(--text-muted)] transition-colors hover:text-red-400"
                    aria-label="Cancelar lembrete"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </Card>

      </div>
    </div>
  );
}
