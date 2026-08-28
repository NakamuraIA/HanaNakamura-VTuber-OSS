import { useEffect, useState } from "react";
import { ConfigApi } from "../../../api/config";
import { PortabilityConfig, VisionMonitor, VoiceInputDevice, VoiceConfig, VisionQualityProfile } from "../../../models/types";
import { Button } from "./Button";
import { Save, CheckCircle, Mic, Laptop, Eye, Cpu, FolderCog, Settings } from "lucide-react";

const VISION_QUALITY_OPTIONS: { id: VisionQualityProfile; label: string; description: string }[] = [
  { id: "full_hd_png", label: "Full HD PNG", description: "Máxima qualidade, comportamento atual." },
  { id: "readable_jpeg", label: "Leitura rápida", description: "Colorida e menor, boa para ler texto." },
  { id: "fast_jpeg", label: "Rápida", description: "Mais leve, texto pequeno pode perder definição." },
  { id: "low_color_png", label: "Poucas cores", description: "Colorida com paleta reduzida para UI." },
  { id: "grayscale_readable", label: "Cinza legível", description: "Sem cor, ainda focada em leitura." },
  { id: "grayscale_fast", label: "Cinza leve", description: "Modo mais leve para menor peso." },
];

export function PortabilityCard() {
  const [portabilityConfig, setPortabilityConfig] = useState<PortabilityConfig | null>(null);
  const [monitors, setMonitors] = useState<VisionMonitor[]>([]);
  const [microphones, setMicrophones] = useState<VoiceInputDevice[]>([]);
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    ConfigApi.getPortabilityConfig().then(setPortabilityConfig).catch(console.error);
    ConfigApi.getVisionMonitors().then(setMonitors).catch(console.error);
    ConfigApi.getVoiceInputDevices().then(setMicrophones).catch(console.error);
    ConfigApi.getVoiceConfig().then(setVoiceConfig).catch(console.error);
  }, []);

  const handleSave = async () => {
    if (!portabilityConfig) return;
    setSaving(true);
    try {
      const portabilitySaved = await ConfigApi.updatePortabilityConfig(portabilityConfig);
      const voiceSaved = voiceConfig ? await ConfigApi.updateVoiceConfig(voiceConfig) : true;
      if (!portabilitySaved || !voiceSaved) throw new Error("Backend indisponível");
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to save portability config", error);
    } finally {
      setSaving(false);
    }
  };

  const selectedVisionQuality = VISION_QUALITY_OPTIONS.find(
    (option) => option.id === portabilityConfig?.visionQualityProfile
  ) ?? VISION_QUALITY_OPTIONS.find((option) => option.id === "readable_jpeg")!;

  return (
    <div className="rounded-2xl bg-[var(--surface-1)] hana-glass border border-[var(--border-strong)] p-6 shadow-lg relative overflow-hidden group mt-5">
      <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-2)] rounded-full blur-[80px] opacity-10 pointer-events-none" />

      <div className="flex items-center gap-3 mb-5 relative z-10">
        <div className="w-10 h-10 rounded-xl bg-sky-500/20 border border-sky-400 flex items-center justify-center text-sky-200 shadow-[0_0_15px_rgba(56,189,248,0.3)]">
          <Settings size={20} />
        </div>
        <div>
          <h3 className="font-bold text-[var(--text-primary)] text-lg tracking-wide">Portabilidade</h3>
          <p className="text-xs text-[var(--text-muted)]">FFmpeg, microfone, monitor e saída de mídia.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 relative z-10 mb-5">
        {/* Microphone */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
            <Mic size={13} className="text-[var(--purple-neon)]" /> Microfone
          </label>
          <select
            value={voiceConfig?.inputDeviceId || ""}
            onChange={(e) => {
              const mic = microphones.find(m => m.id === e.target.value);
              if (mic && voiceConfig) {
                setVoiceConfig({ ...voiceConfig, inputDeviceId: mic.id, inputDeviceLabel: mic.label, inputDeviceSource: mic.source });
              }
            }}
            className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 focus:border-[var(--purple-neon)] text-white rounded-lg px-3 py-2.5 text-sm font-mono transition-colors outline-none cursor-pointer"
          >
            {microphones.map((mic) => (
              <option key={mic.id} value={mic.id} className="bg-neutral-900 text-white">
                {mic.label} {mic.isDefault ? "(padrão)" : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Monitor */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
            <Laptop size={13} className="text-[var(--cyan-neon)]" /> Monitor (Visão)
          </label>
          <select
            value={portabilityConfig?.activeMonitor ?? 1}
            onChange={(e) => {
              if (portabilityConfig) setPortabilityConfig({ ...portabilityConfig, activeMonitor: parseInt(e.target.value, 10) });
            }}
            className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--cyan-neon)]/50 focus:border-[var(--cyan-neon)] text-white rounded-lg px-3 py-2.5 text-sm font-mono transition-colors outline-none cursor-pointer"
          >
            {monitors.map((mon) => (
              <option key={mon.id} value={mon.id} className="bg-neutral-900 text-white">{mon.label}</option>
            ))}
          </select>
        </div>

        {/* Vision quality */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
            <Eye size={13} className="text-[var(--cyan-neon)]" /> Qualidade da Visão
          </label>
          <select
            value={portabilityConfig?.visionQualityProfile ?? "readable_jpeg"}
            onChange={(e) => {
              if (portabilityConfig) setPortabilityConfig({ ...portabilityConfig, visionQualityProfile: e.target.value as VisionQualityProfile });
            }}
            className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--cyan-neon)]/50 focus:border-[var(--cyan-neon)] text-white rounded-lg px-3 py-2.5 text-sm font-mono transition-colors outline-none cursor-pointer"
          >
            {VISION_QUALITY_OPTIONS.map((o) => (
              <option key={o.id} value={o.id} className="bg-neutral-900 text-white">{o.label}</option>
            ))}
          </select>
          <span className="text-[10px] text-[var(--text-muted)]">{selectedVisionQuality.description}</span>
        </div>

        {/* FFmpeg path */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
            <Cpu size={13} className="text-[var(--purple-neon)]" /> FFmpeg
          </label>
          <input
            type="text"
            value={portabilityConfig?.ffmpegPath || ""}
            onChange={(e) => {
              if (portabilityConfig) setPortabilityConfig({ ...portabilityConfig, ffmpegPath: e.target.value });
            }}
            placeholder="C:\Ffmpeg\ffmpeg.exe ou ffmpeg"
            className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--purple-neon)]/50 focus:border-[var(--purple-neon)] text-white font-mono rounded-lg px-3 py-2.5 text-sm transition-colors outline-none"
          />
        </div>

        {/* Media output path */}
        <div className="flex flex-col gap-1.5 md:col-span-2">
          <label className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
            <FolderCog size={13} className="text-[var(--cyan-neon)]" /> Diretório de Saída
          </label>
          <input
            type="text"
            value={portabilityConfig?.mediaOutputPath || ""}
            onChange={(e) => {
              if (portabilityConfig) setPortabilityConfig({ ...portabilityConfig, mediaOutputPath: e.target.value });
            }}
            placeholder="./data ou D:\HanaData"
            className="w-full bg-black/50 border border-[var(--border-strong)] hover:border-[var(--cyan-neon)]/50 focus:border-[var(--cyan-neon)] text-white font-mono rounded-lg px-3 py-2.5 text-sm transition-colors outline-none"
          />
          <span className="text-[10px] text-[var(--text-muted)]">
            Onde imagens geradas, logs de áudio e capturas do sistema são salvos.
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-white/5 pt-4 relative z-10">
        <span className="text-[10px] text-[var(--text-muted)] font-mono">Salvo no SQLite local do host.</span>
        <Button
          onClick={handleSave}
          disabled={!portabilityConfig}
          loading={saving}
          variant={success ? "success" : "primary"}
          icon={success ? <CheckCircle size={16} /> : <Save size={16} />}
        >
          {saving ? "Gravando..." : success ? "Salvo!" : "Persistir"}
        </Button>
      </div>
    </div>
  );
}
