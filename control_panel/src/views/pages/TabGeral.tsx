import { useEffect, useState } from "react";
import { ApiController } from "../../controllers/api";
import { SystemStatus, PortabilityConfig, VisionMonitor, VoiceInputDevice, VoiceConfig, VisionQualityProfile } from "../../models/types";
import { ConfigApi } from "../../api/config";
import { Card } from "../components/shared/Card";
import { TabHeader } from "../components/shared/TabHeader";
import { Button } from "../components/shared/Button";

import { MonitorDot, BrainCircuit, Mic, Video, Eye, MessageSquareText, PlugZap, Activity, TerminalSquare, Settings, Laptop, Cpu, FolderCog, Save, CheckCircle, Bot } from "lucide-react";

const VISION_QUALITY_OPTIONS: { id: VisionQualityProfile; label: string; description: string }[] = [
  { id: "full_hd_png", label: "Full HD PNG", description: "Maxima qualidade, comportamento atual." },
  { id: "readable_jpeg", label: "Leitura rapida", description: "Colorida e menor, boa para ler texto." },
  { id: "fast_jpeg", label: "Rapida", description: "Mais leve, texto pequeno pode perder definicao." },
  { id: "low_color_png", label: "Poucas cores", description: "Colorida com paleta reduzida para UI." },
  { id: "grayscale_readable", label: "Cinza legivel", description: "Sem cor, ainda focada em leitura." },
  { id: "grayscale_fast", label: "Cinza leve", description: "Modo mais leve para menor peso." },
];

// Componente auxiliar para Anel Circular Sci-Fi
function CircularGauge({ value, label, subLabel, colorClass, shadowClass }: { value: number, label: string, subLabel: string, colorClass: string, shadowClass: string }) {
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (value / 100) * circumference;

  return (
    <div className="relative flex flex-col items-center justify-center">
      <div className="relative w-32 h-32 flex items-center justify-center">
        {/* Fundo do Anel */}
        <svg className="absolute inset-0 w-full h-full transform -rotate-90">
          <circle 
            cx="64" cy="64" r={radius} 
            className="stroke-white/5 fill-transparent" 
            strokeWidth="8" 
          />
          {/* Anel de Progresso */}
          <circle 
            cx="64" cy="64" r={radius} 
            className={`fill-transparent transition-all duration-1000 ease-out ${colorClass} ${shadowClass}`}
            strokeWidth="8"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            stroke="currentColor"
          />
        </svg>
        <div className="absolute flex flex-col items-center justify-center animate-fade-in">
          <span className="text-xl font-black font-mono text-white tracking-tighter">
            {value.toFixed(0)}<span className="text-xs text-[var(--text-muted)]">%</span>
          </span>
        </div>
      </div>
      <div className="mt-2 text-center">
        <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-secondary)]">{label}</div>
        <div className="text-[9px] font-mono text-[var(--text-muted)]">{subLabel}</div>
      </div>
    </div>
  );
}

export function TabGeral() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [portabilityConfig, setPortabilityConfig] = useState<PortabilityConfig | null>(null);
  const [monitors, setMonitors] = useState<VisionMonitor[]>([]);
  const [microphones, setMicrophones] = useState<VoiceInputDevice[]>([]);
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

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

    // Simulated Live Logs para dar ambiente sci-fi
    const logInterval = setInterval(() => {
      const messages = [
        "SISTEMA: Conexão neural estável...",
        "VTB: Parâmetros faciais atualizados.",
        "MEM: Indexação de vetores RAG concluída.",
        "LLM: Aguardando input do utilizador.",
        "SYS: Verificação térmica do CPU OK.",
        "HANA: Heartbeat sincronizado.",
        "NET: Latência < 12ms",
        "STT: Escuta ativa no microfone principal."
      ];
      setLogs(prev => {
        const newLogs = [...prev, `[${new Date().toLocaleTimeString()}] ${messages[Math.floor(Math.random() * messages.length)]}`];
        return newLogs.slice(-6); // Mantém os últimos 6
      });
    }, 4500);

    return () => {
      clearInterval(interval);
      clearInterval(logInterval);
      if (ws) ws.close();
    };
  }, []);

  useEffect(() => {
    // Load local PC environment and hardware configurations on mount
    ConfigApi.getPortabilityConfig().then(setPortabilityConfig).catch(console.error);
    ConfigApi.getVisionMonitors().then(setMonitors).catch(console.error);
    ConfigApi.getVoiceInputDevices().then(setMicrophones).catch(console.error);
    ConfigApi.getVoiceConfig().then(setVoiceConfig).catch(console.error);
  }, []);

  const handleSavePortability = async () => {
    if (!portabilityConfig) return;
    setSaving(true);
    try {
      // Save portability configs to the backend SQLite database
      await ConfigApi.updatePortabilityConfig(portabilityConfig);
      
      // Save updated voice configuration to persist the selected microphone
      if (voiceConfig) {
        await ConfigApi.updateVoiceConfig(voiceConfig);
      }
      
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to save environment configurations", error);
    } finally {
      setSaving(false);
    }
  };

  const selectedVisionQuality = VISION_QUALITY_OPTIONS.find(
    (option) => option.id === portabilityConfig?.visionQualityProfile
  ) ?? VISION_QUALITY_OPTIONS[0];

  const getCpuColor = (cpu: number) => {
    if (cpu > 80) return "text-red-500 shadow-[0_0_15px_rgba(239,68,68,0.5)]";
    if (cpu > 50) return "text-yellow-500 shadow-[0_0_15px_rgba(234,179,8,0.5)]";
    return "text-[var(--purple-neon)] drop-shadow-[0_0_8px_var(--purple-neon)]";
  };

  return (
    <div className="w-full h-full bg-[var(--bg-sidebar)] backdrop-blur-2xl p-8 overflow-y-auto custom-scrollbar shadow-2xl relative transition-all duration-500">
      {/* HEADER */}
      <TabHeader
        icon={<MonitorDot size={24} />}
        title="Monitor Geral"
        subtitle="Status em tempo real do ecossistema e hardware da Hana"
      />

      {/* CARDS GRID */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* CARD: RECURSOS DO SISTEMA (Com Anéis Sci-Fi) */}
        <Card hover className="flex flex-col justify-center">
          <div className="absolute top-[-50px] right-[-50px] w-40 h-40 bg-[var(--accent)] rounded-full blur-[80px] opacity-20 pointer-events-none group-hover:opacity-40 transition-opacity duration-1000"></div>

          <div className="flex items-center justify-between mb-6 relative z-10">
            <h3 className="font-bold text-[var(--text-primary)] text-lg flex items-center gap-2">
              <Activity size={20} className="text-[var(--purple-neon)]" /> Status de Hardware
            </h3>
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"></span>
              <span className="text-[9px] font-mono font-bold text-green-400 uppercase tracking-widest">Live</span>
            </div>
          </div>
          
          <div className="flex justify-around items-center relative z-10 py-4">
            <CircularGauge 
              value={status?.cpu || 0} 
              label="CPU" 
              subLabel="Processamento" 
              colorClass={status ? getCpuColor(status.cpu) : "text-[var(--purple-neon)]"}
              shadowClass=""
            />
            
            <div className="h-20 w-px bg-gradient-to-b from-transparent via-white/10 to-transparent"></div>

            <CircularGauge 
              value={status?.ramPercent || 0} 
              label="RAM" 
              subLabel={status ? `${status.ramUsedStr} / ${status.ramTotalStr} GB` : "Memória"}
              colorClass="text-[var(--cyan-neon)] drop-shadow-[0_0_8px_var(--cyan-neon)]"
              shadowClass=""
            />
          </div>
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

          <div className="flex-1 min-h-[100px] bg-black/60 border border-white/5 rounded-xl p-3 relative overflow-hidden flex flex-col font-mono text-[10px]">
            <div className="flex items-center gap-2 mb-2 text-[var(--text-muted)] border-b border-white/5 pb-1">
              <TerminalSquare size={12} />
              <span className="uppercase tracking-widest">System Log</span>
            </div>
            <div className="flex-1 flex flex-col justify-end gap-1">
              {logs.map((log, i) => (
                <div key={i} className="text-green-400/80 animate-fade-in break-all whitespace-pre-wrap">{log}</div>
              ))}
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
              { id: "visao", label: "Visão Computacional", icon: <Eye size={20} /> },
              { id: "vtube_studio", label: "VTube Studio", icon: <Video size={20} /> },
              { id: "discord", label: "Bot Discord", icon: <MessageSquareText size={20} /> },
              { id: "omni", label: "Omni Executor", icon: <Bot size={20} /> },
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

        {/* CARD: CONFIGURAÇÕES LOCAIS DE AMBIENTE (Portabilidade) */}
        <Card hover className="md:col-span-2">
          <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-2)] rounded-full blur-[80px] opacity-10 pointer-events-none"></div>
          
          <h3 className="font-bold text-[var(--text-primary)] mb-6 text-lg flex items-center gap-2 relative z-10">
            <Settings size={20} className="text-[var(--cyan-neon)]" /> Configurações de Ambiente (Portabilidade)
          </h3>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 relative z-10 mb-6">
            {/* Campo: Dispositivo de Entrada (Microfone) */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
                <Mic size={14} className="text-[var(--purple-neon)]" /> Microfone do Sistema
              </label>
              <select
                value={voiceConfig?.inputDeviceId || ""}
                onChange={(e) => {
                  const selectedId = e.target.value;
                  const mic = microphones.find(m => m.id === selectedId);
                  if (mic && voiceConfig) {
                    setVoiceConfig({
                      ...voiceConfig,
                      inputDeviceId: mic.id,
                      inputDeviceLabel: mic.label,
                      inputDeviceSource: mic.source
                    });
                  }
                }}
                className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 focus:border-[var(--purple-neon)] text-white rounded-xl px-4 py-3 text-sm font-mono transition-colors outline-none cursor-pointer"
              >
                {microphones.map((mic) => (
                  <option key={mic.id} value={mic.id} className="bg-neutral-900 text-white">
                    {mic.label} {mic.isDefault ? "(Padrão)" : ""}
                  </option>
                ))}
              </select>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                Detecta automaticamente o hardware de áudio do host local.
              </span>
            </div>

            {/* Campo: Monitor Ativo (Visão) */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
                <Laptop size={14} className="text-[var(--cyan-neon)]" /> Monitor para Gravação (Visão)
              </label>
              <select
                value={portabilityConfig?.activeMonitor ?? 1}
                onChange={(e) => {
                  if (portabilityConfig) {
                    setPortabilityConfig({
                      ...portabilityConfig,
                      activeMonitor: parseInt(e.target.value, 10)
                    });
                  }
                }}
                className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--cyan-neon)]/50 focus:border-[var(--cyan-neon)] text-white rounded-xl px-4 py-3 text-sm font-mono transition-colors outline-none cursor-pointer"
              >
                {monitors.map((mon) => (
                  <option key={mon.id} value={mon.id} className="bg-neutral-900 text-white">
                    {mon.label}
                  </option>
                ))}
              </select>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                Selecione qual tela a Hana irá analisar quando o módulo de Visão estiver ligado.
              </span>
            </div>

            {/* Field: Vision capture quality profile */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
                <Eye size={14} className="text-[var(--cyan-neon)]" /> Qualidade da Visao
              </label>
              <select
                value={portabilityConfig?.visionQualityProfile ?? "full_hd_png"}
                onChange={(e) => {
                  if (portabilityConfig) {
                    setPortabilityConfig({
                      ...portabilityConfig,
                      visionQualityProfile: e.target.value as VisionQualityProfile
                    });
                  }
                }}
                className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--cyan-neon)]/50 focus:border-[var(--cyan-neon)] text-white rounded-xl px-4 py-3 text-sm font-mono transition-colors outline-none cursor-pointer"
              >
                {VISION_QUALITY_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id} className="bg-neutral-900 text-white">
                    {option.label}
                  </option>
                ))}
              </select>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                {selectedVisionQuality.description}
              </span>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
                <Cpu size={14} className="text-[var(--purple-neon)]" /> Caminho do FFmpeg Executável
              </label>
              <input
                type="text"
                value={portabilityConfig?.ffmpegPath || ""}
                onChange={(e) => {
                  if (portabilityConfig) {
                    setPortabilityConfig({
                      ...portabilityConfig,
                      ffmpegPath: e.target.value
                    });
                  }
                }}
                placeholder="Ex: C:\ffmpeg\bin\ffmpeg.exe ou ffmpeg"
                className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 focus:border-[var(--purple-neon)] text-white font-mono rounded-xl px-4 py-3 text-sm transition-colors outline-none"
              />
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                Caminho absoluto ou variável global para decodificação de mídias por STT/TTS.
              </span>
            </div>

            {/* Campo: Pasta de Mídias de Saída */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
                <FolderCog size={14} className="text-[var(--cyan-neon)]" /> Diretório de Mídias de Saída
              </label>
              <input
                type="text"
                value={portabilityConfig?.mediaOutputPath || ""}
                onChange={(e) => {
                  if (portabilityConfig) {
                    setPortabilityConfig({
                      ...portabilityConfig,
                      mediaOutputPath: e.target.value
                    });
                  }
                }}
                placeholder="Ex: ./data ou D:\HanaData"
                className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--cyan-neon)]/50 focus:border-[var(--cyan-neon)] text-white font-mono rounded-xl px-4 py-3 text-sm transition-colors outline-none"
              />
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                Onde arquivos de fotos do VTube, logs de áudio ou capturas do sistema serão salvos.
              </span>
            </div>
          </div>

          {/* Botão Salvar com Micro-Animações */}
          <div className="flex items-center justify-between border-t border-white/5 pt-4 relative z-10">
            <span className="text-xs text-[var(--text-muted)] font-mono flex items-center gap-1">
              * Configurações salvas diretamente no SQLite local do host.
            </span>
            <Button
              onClick={handleSavePortability}
              disabled={!portabilityConfig}
              loading={saving}
              variant={success ? "success" : "primary"}
              icon={success ? <CheckCircle size={16} /> : <Save size={16} />}
            >
              {saving ? "Gravando..." : success ? "Salvo!" : "Persistir Alterações"}
            </Button>
          </div>
        </Card>

      </div>
    </div>
  );
}
