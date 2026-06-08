import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { PlugZap, Mic, Eye, Video, MessageSquareText, ShieldAlert, Keyboard, Bot, RefreshCw, Square } from "lucide-react";
import { ApiController } from "../../controllers/api";
import { useConnections } from "../../hooks/useConnections";
import { AgentJob, ConnectionsConfig, OmniStatus } from "../../models/types";
import { ModuleToggleCard } from "../components/shared/ModuleToggleCard";
import { TabHeader } from "../components/shared/TabHeader";

const HOTKEYS = [
  "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
  "CapsLock", "ScrollLock", "Insert", "Home", "End", "PageUp", "PageDown",
];

type ModuleConfig = {
  id: keyof ConnectionsConfig;
  title: string;
  description: string;
  icon: ReactNode;
  neonColor: string;
  hotkey?: "pttKey" | "stopKey";
};

function isActiveAgentJob(job: AgentJob) {
  return job.status === "queued" || job.status === "running";
}

function ActiveAgentJobBanner({ job, tone, onCancel }: { job?: AgentJob; tone: "cyan" | "purple"; onCancel: (job: AgentJob) => void }) {
  if (!job) return null;
  const color = tone === "purple" ? "border-fuchsia-300/30 bg-fuchsia-300/10 text-fuchsia-100" : "border-cyan-300/30 bg-cyan-300/10 text-cyan-100";
  const task = job.task.length > 120 ? `${job.task.slice(0, 120)}...` : job.task;
  return (
    <div className={`rounded-xl border px-4 py-3 ${color}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-mono uppercase tracking-widest">Job ativo: {job.status}</p>
          <p className="mt-1 break-words text-sm text-white">{task || "Tarefa em background"}</p>
          <p className="mt-1 break-words font-mono text-[11px] text-[var(--text-muted)]">
            {job.job_id} · {job.mode || "mode"}{job.cwd ? ` · ${job.cwd}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onCancel(job)}
          className="inline-flex items-center gap-2 rounded-lg border border-red-300/40 bg-red-950/50 px-3 py-2 text-xs font-black uppercase tracking-wide text-red-100 transition-colors hover:border-red-200"
        >
          <Square size={13} /> Cancelar
        </button>
      </div>
    </div>
  );
}

const MODULES: ModuleConfig[] = [
  {
    id: "tts",
    title: "Sintese de Voz (TTS)",
    description: "Slot opcional de fala. Fica visivel no painel, mas so executa quando a integracao estiver instalada.",
    icon: <Mic size={24} />,
    neonColor: "blue",
  },
  {
    id: "stt",
    title: "Reconhecimento de Voz (STT)",
    description: "Entrada por microfone no backend. Quando ligado, o runtime aplica a configuracao em tempo real.",
    icon: <Mic size={24} />,
    neonColor: "purple",
  },
  {
    id: "vad",
    title: "Detector de Voz (VAD)",
    description: "Controla o sempre ouvindo. Se desligar, a fala entra apenas por PTT ou teste manual.",
    icon: <Mic size={24} />,
    neonColor: "cyan",
  },
  {
    id: "ptt",
    title: "Pressione para Falar (PTT)",
    description: "Hotkey global no backend para gravar somente enquanto a tecla estiver pressionada.",
    icon: <Keyboard size={24} />,
    neonColor: "cyan",
    hotkey: "pttKey",
  },
  {
    id: "stopHotkey",
    title: "Parar Resposta (Hotkey)",
    description: "Hotkey global de emergencia para interromper resposta ou midia quando a integracao estiver ativa.",
    icon: <ShieldAlert size={24} />,
    neonColor: "red",
    hotkey: "stopKey",
  },
  {
    id: "visao",
    title: "Visao sob demanda",
    description: "Slot de leitura de tela/imagem. Mantido como modulo opcional para evitar peso no runtime base.",
    icon: <Eye size={24} />,
    neonColor: "purple",
  },
  {
    id: "vts",
    title: "VTube Studio",
    description: "Interface opcional de avatar. A Hana nao depende mais disso como identidade base.",
    icon: <Video size={24} />,
    neonColor: "cyan",
  },
  {
    id: "discord",
    title: "Bot do Discord",
    description: "Transporte externo para texto e voz. O bot roda separado e usa o backend local da Hana.",
    icon: <MessageSquareText size={24} />,
    neonColor: "blue",
  },
  {
    id: "omni",
    title: "Omni Executor",
    description: "Ponte local para tarefas de computador. A Hana delega, supervisiona e registra o resultado no Terminal Agent.",
    icon: <Bot size={24} />,
    neonColor: "cyan",
  },
];

export function TabConexoes() {
  const { config, toggleField, updateKey, updateField, audioHover } = useConnections();
  const [omniStatus, setOmniStatus] = useState<OmniStatus | null>(null);
  const [agentJobs, setAgentJobs] = useState<AgentJob[]>([]);

  const refreshOmniStatus = () => {
    ApiController.getOmniStatus().then(setOmniStatus).catch(() => {
      setOmniStatus({
        enabled: Boolean(config?.omni),
        ok: false,
        online: false,
        baseUrl: config?.omniUrl || "http://127.0.0.1:8060",
        error: "backend_unavailable",
      });
    });
  };

  useEffect(() => {
    refreshOmniStatus();
  }, [config?.omni, config?.omniUrl]);

  const refreshAgentJobs = () => {
    ApiController.getAgentJobs().then((data) => setAgentJobs(data.jobs || [])).catch(() => setAgentJobs([]));
  };

  useEffect(() => {
    refreshAgentJobs();
    const timer = window.setInterval(refreshAgentJobs, 3000);
    return () => window.clearInterval(timer);
  }, []);

  const cancelAgentJob = async (job: AgentJob) => {
    await ApiController.cancelAgentJob(job.job_id, "connections_panel");
    refreshAgentJobs();
  };

  const activeOmniJob = agentJobs.find((job) => job.agent === "omni" && isActiveAgentJob(job));

  if (!config) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--cyan-neon)]" />
      </div>
    );
  }

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] backdrop-blur-2xl p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-500">
      <TabHeader
        icon={<PlugZap size={24} />}
        title="Conexoes & Modulos"
        subtitle="Sentidos e integracoes opcionais da Hana"
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 pb-10">
        {MODULES.map((item) => (
          <ModuleToggleCard
            key={String(item.id)}
            isActive={Boolean(config[item.id])}
            title={item.title}
            description={item.description}
            icon={item.icon}
            neonColor={item.neonColor}
            hasHotkey={Boolean(item.hotkey)}
            hotkeyValue={item.hotkey ? String(config[item.hotkey]) : undefined}
            hotkeysList={HOTKEYS}
            onToggle={() => toggleField(item.id)}
            onUpdateKey={item.hotkey ? (value) => updateKey(item.hotkey!, value) : undefined}
            onHover={audioHover}
          >
            {item.id === "discord" && (
              <div className="space-y-3">
                <p className="text-xs font-mono uppercase tracking-widest text-[var(--text-muted)]">
                  Execute separado: python -m hana_agent_oss.discord_bot
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {([
                    ["discordSpeak", "Falar na call", "TTS sai no canal de voz."],
                    ["discordListen", "Ouvir call", "STT recebe usuarios da call."],
                  ] as const).map(([field, label, detail]) => {
                    const active = Boolean(config[field]);
                    const disabled = !config.discord;
                    return (
                      <button
                        key={field}
                        type="button"
                        disabled={disabled}
                        onClick={() => toggleField(field)}
                        onMouseEnter={audioHover}
                        className={`rounded-xl border px-4 py-3 text-left transition-all ${disabled ? "opacity-35 cursor-not-allowed border-white/10" : active ? "border-cyan-300/70 bg-cyan-300/10 shadow-[0_0_18px_rgba(34,211,238,0.16)]" : "border-white/10 bg-black/30 hover:border-cyan-300/40"}`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-sm font-black uppercase tracking-wide text-white">{label}</span>
                          <span className={`h-2.5 w-2.5 rounded-full ${active && !disabled ? "bg-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.8)]" : "bg-zinc-600"}`} />
                        </div>
                        <p className="mt-1 text-xs text-[var(--text-muted)]">{detail}</p>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            {item.id === "omni" && (
              <div className="space-y-3">
                <div className="flex flex-col gap-2">
                  <label className="text-xs font-mono uppercase tracking-widest text-[var(--text-muted)]">
                    Endpoint local
                  </label>
                  <input
                    value={config.omniUrl || "http://127.0.0.1:8060"}
                    onChange={(event) => updateField("omniUrl", event.target.value)}
                    onMouseEnter={audioHover}
                    className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-3 font-mono text-sm text-white outline-none transition-colors focus:border-cyan-300/60"
                    placeholder="http://127.0.0.1:8060"
                  />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-300/20 bg-cyan-300/5 px-4 py-3">
                  <div>
                    <p className="text-xs font-mono uppercase tracking-widest text-cyan-200">
                      {omniStatus?.online ? "Omni online" : "Omni offline"}
                    </p>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">
                      {omniStatus?.online
                        ? `${omniStatus.baseUrl}${omniStatus.latencyMs ? ` · ${omniStatus.latencyMs}ms` : ""}`
                        : omniStatus?.error || "Aguardando verificacao."}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={refreshOmniStatus}
                    onMouseEnter={audioHover}
                    className="inline-flex items-center gap-2 rounded-lg border border-cyan-300/30 bg-black/40 px-3 py-2 text-xs font-black uppercase tracking-wide text-cyan-100 transition-colors hover:border-cyan-200"
                  >
                    <RefreshCw size={14} /> Testar
                  </button>
                </div>
                <ActiveAgentJobBanner job={activeOmniJob} tone="cyan" onCancel={cancelAgentJob} />
                <p className="text-xs font-mono uppercase tracking-widest text-[var(--text-muted)]">
                  Execute separado: Omni-Agent OS em 127.0.0.1:8060
                </p>
              </div>
            )}
          </ModuleToggleCard>
        ))}
      </div>
    </div>
  );
}