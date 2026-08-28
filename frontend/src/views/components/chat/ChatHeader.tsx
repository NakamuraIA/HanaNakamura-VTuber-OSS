import { MessageSquareText, ChevronDown, StopCircle, Siren, Power } from "lucide-react";
import { SafetyMode } from "../../../models/types";

interface ChatHeaderProps {
  identity: { name: string; avatar?: string };
  provider: string;
  model: string;
  configOpen: boolean;
  onToggleConfig: () => void;
  isStreaming: boolean;
  onStop: () => void;
  safetyMode: SafetyMode;
  onEmergencyStop: () => void;
  onShutdown: () => void;
}

/** Floating toolbar with identity, provider/model, Config, Stop, Emergency, and Shutdown buttons. */
export function ChatHeader({
  identity,
  provider,
  model,
  configOpen,
  onToggleConfig,
  isStreaming,
  onStop,
  safetyMode,
  onEmergencyStop,
  onShutdown,
}: ChatHeaderProps) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-20 bg-[rgba(0,0,0,0.55)] p-3 backdrop-blur-md">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-[var(--purple-dark)] flex items-center justify-center border border-[var(--purple-neon)] shadow-[0_0_15px_var(--purple-dark)]">
            <MessageSquareText size={18} className="text-[var(--purple-neon)]" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-[var(--purple-neon)] to-[var(--cyan-neon)]">
              {identity.name} · Nexus Chat
            </h2>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest font-bold truncate">
              {provider} · {model}
            </p>
          </div>
        </div>

        <div className="pointer-events-auto flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={onToggleConfig}
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-[var(--text-secondary)] hover:text-white"
            title="Mostrar ou esconder configuracoes do chat"
          >
            Config
            <ChevronDown size={14} className={`transition-transform ${configOpen ? "rotate-180" : ""}`} />
          </button>
          {isStreaming && (
            <button
              onClick={onStop}
              className="bg-red-500/20 hover:bg-red-500/40 text-red-400 border border-red-500/30 transition-all p-2 rounded-xl animate-pulse"
              title="Parar Resposta"
            >
              <StopCircle size={18} />
            </button>
          )}
          {safetyMode === "dev-unsafe" && (
            <button
              onClick={onEmergencyStop}
              className="bg-red-600/30 hover:bg-red-600/50 text-red-100 border border-red-400/40 transition-all p-2 rounded-xl"
              title="Emergency stop"
            >
              <Siren size={18} />
            </button>
          )}
          <button
            type="button"
            onClick={onShutdown}
            className="bg-red-950/70 hover:bg-red-800/80 text-red-200 border border-red-400/30 transition-all p-2 rounded-xl"
            title="Desligar Hana"
          >
            <Power size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
