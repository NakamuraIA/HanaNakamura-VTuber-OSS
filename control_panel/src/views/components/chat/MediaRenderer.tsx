import { useEffect, useRef, useState } from "react";
import { Download, ExternalLink, Eye, FastForward, Music, Pause, Play, Rewind, Trash2, Volume2, VolumeX } from "lucide-react";
import { ChatMessage } from "../../../models/types";
import { BACKEND_URL } from "../../../api/core";

interface MediaRendererProps {
  media: NonNullable<ChatMessage["media"]>[0];
  onOpenImage: (url: string) => void;
  onDelete?: () => void;
  onReSynthesize?: () => void;
}

const CHAT_AUDIO_VOLUME_KEY = "hana_chat_audio_volume_v1";

function readChatAudioVolume(fallback = 1) {
  /** Read the global Chat audio volume while tolerating invalid legacy values. */
  const raw = localStorage.getItem(CHAT_AUDIO_VOLUME_KEY);
  if (raw === null) return Math.max(0, Math.min(1, fallback));
  const stored = Number(raw);
  return Math.max(0, Math.min(1, Number.isFinite(stored) ? stored : fallback));
}

async function downloadUrl(url: string, name?: string) {
  const filename = name || decodeURIComponent(url.split("/").pop() || "") || "hana-media";
  let objectUrl: string | null = null;
  let href = url;

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Download failed: ${response.status}`);
    const blob = await response.blob();
    objectUrl = URL.createObjectURL(blob);
    href = objectUrl;
  } catch (error) {
    console.warn("[Chat] Falha ao baixar via blob; usando URL direta.", error);
  }

  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.rel = "noreferrer";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  if (objectUrl) {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${rest}`;
}

export function MediaRenderer({
  media,
  onOpenImage,
  onDelete,
  onReSynthesize,
}: MediaRendererProps) {
  const [playing, setPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [volume, setVolume] = useState(() => readChatAudioVolume(media.volume ?? 1));
  const [volumeOpen, setVolumeOpen] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    /** Keep every mounted Chat audio player synchronized with the global volume. */
    const syncVolume = (event: Event) => {
      const nextVolume = Math.max(0, Math.min(1, Number((event as CustomEvent<number>).detail)));
      setVolume(nextVolume);
      if (audioRef.current) audioRef.current.volume = nextVolume;
    };
    window.addEventListener("hana:chat-audio-volume", syncVolume);
    return () => window.removeEventListener("hana:chat-audio-volume", syncVolume);
  }, []);
  
  const rawUrl = media.url || "";
  const mediaUrl = rawUrl.startsWith("/api/") ? `${BACKEND_URL}${rawUrl}` : rawUrl;

  const updatePlaybackRate = (rate: number) => {
    setPlaybackRate(rate);
    if (audioRef.current) audioRef.current.playbackRate = rate;
  };

  // Applies and persists the global volume used by current and future Chat audio players.
  const updateVolume = (nextVolume: number) => {
    const normalized = Math.max(0, Math.min(1, nextVolume));
    setVolume(normalized);
    localStorage.setItem(CHAT_AUDIO_VOLUME_KEY, String(normalized));
    window.dispatchEvent(new CustomEvent("hana:chat-audio-volume", { detail: normalized }));
    if (audioRef.current) audioRef.current.volume = normalized;
  };

  // Reapplies the selected volume before playback starts.
  const toggleAudioPlayback = () => {
    if (!audioRef.current) return;
    audioRef.current.volume = volume;
    if (playing) audioRef.current.pause();
    else void audioRef.current.play();
  };

  const seekBy = (seconds: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, audioRef.current.currentTime + seconds);
  };

  const seekTo = (value: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = value;
    setCurrentTime(value);
  };

  if (media.type === "image") {
    if (media.status === "failed") {
      return (
        <div className="mt-4 rounded-2xl border border-red-400/30 bg-red-500/10 p-4 text-red-100 shadow-[0_0_20px_rgba(248,113,113,0.15)]">
          <p className="text-[10px] font-black uppercase tracking-widest text-red-200">Falha ao gerar imagem</p>
          <p className="mt-2 text-sm text-red-50/80">{media.error || "O Gemini Image nao retornou uma imagem utilizavel."}</p>
        </div>
      );
    }
    return (
      <div className="mt-4 overflow-hidden rounded-2xl border border-white/10 bg-black/20 shadow-2xl">
        <button onClick={() => mediaUrl && onOpenImage(mediaUrl)} className="block w-full bg-black/20">
          <img src={mediaUrl} alt="Hana Generated" loading="lazy" className="h-auto max-h-[400px] w-full object-contain transition-transform duration-500 hover:scale-[1.02]" />
        </button>
        <div className="flex items-center justify-between bg-white/5 p-3 backdrop-blur-md">
          <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Imagem gerada</span>
          <div className="flex gap-2">
            <button onClick={() => mediaUrl && onOpenImage(mediaUrl)} className="rounded-lg p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-white/10 hover:text-white" title="Ver imagem">
              <Eye size={14} />
            </button>
            <button onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (mediaUrl) void downloadUrl(mediaUrl, media.name); }} className="rounded-lg p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-white/10 hover:text-white" title="Baixar imagem">
              <Download size={14} />
            </button>
            {onDelete && (
              <button onClick={onDelete} className="rounded-lg p-1.5 text-red-300 transition-colors hover:bg-red-500/20 hover:text-white" title="Apagar imagem">
                <Trash2 size={14} />
              </button>
            )}
            <a href={mediaUrl} className="hidden" aria-hidden="true">
              <ExternalLink size={14} />
            </a>
          </div>
        </div>
      </div>
    );
  }

  if (media.type === "music") {
    return (
      <div className="group relative mt-4 flex items-center gap-4 overflow-hidden rounded-2xl border border-blue-500/30 bg-gradient-to-br from-blue-500/20 to-purple-500/20 p-4 shadow-lg backdrop-blur-md">
        <div className="absolute left-0 top-0 h-full w-1 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.8)]" />
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-500/30 text-blue-400">
          {playing ? <Music size={24} className="animate-bounce" /> : <Music size={24} />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="mb-1 truncate text-xs font-black uppercase tracking-wider text-white">Musica gerada pela Hana</p>
          <p className="font-mono text-[10px] text-blue-300 opacity-70">ID: {media.job_id}</p>
          {mediaUrl && <audio ref={audioRef} src={mediaUrl} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />}
        </div>
        {mediaUrl ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (playing) audioRef.current?.pause();
                else audioRef.current?.play();
              }}
              className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-500 text-white shadow-[0_0_15px_rgba(59,130,246,0.5)] transition-all hover:scale-110 active:scale-95"
            >
              {playing ? <Pause size={20} fill="white" /> : <Play size={20} fill="white" className="ml-1" />}
            </button>
            <button onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (mediaUrl) void downloadUrl(mediaUrl, media.name); }} className="flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20" title="Baixar musica">
              <Download size={16} />
            </button>
            {onDelete && (
              <button onClick={onDelete} className="flex h-9 w-9 items-center justify-center rounded-full bg-red-500/10 text-red-300 transition-colors hover:bg-red-500/25" title="Apagar musica">
                <Trash2 size={16} />
              </button>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
            <span className="animate-pulse text-[10px] font-bold text-blue-400">GERANDO...</span>
          </div>
        )}
      </div>
    );
  }

  if (media.type === "audio") {
    const loading = (!mediaUrl && media.status !== "expired") || media.status === "generating";
    const failed = media.status === "failed";
    const expired = media.status === "expired";
    const progressMax = duration || 0;
    return (
      <div className="mt-3 overflow-visible rounded-xl border border-pink-400/25 bg-[linear-gradient(135deg,rgba(236,72,153,0.18),rgba(34,211,238,0.08),rgba(168,85,247,0.14))] shadow-[0_0_22px_rgba(236,72,153,0.14)] backdrop-blur-xl">
        <div className="relative p-3">
          <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-pink-300/70 to-transparent" />
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-pink-300/30 bg-black/35 text-pink-100 shadow-[inset_0_0_18px_rgba(236,72,153,0.2)]">
              <Volume2 size={18} />
            </div>
            <div className="min-w-[180px] flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <p className="truncate text-xs font-black uppercase tracking-wider text-white">{media.name || "Voz da Hana"}</p>
                <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest text-cyan-100">
                  {loading ? "gerando" : failed ? "falhou" : expired ? "expirado" : "pronto"}
                </span>
              </div>
              <p className="truncate font-mono text-[10px] text-pink-100/70">
                {loading ? "sintetizando audio do chat..." : expired ? "expirou por recarga" : `${media.provider || "tts"}${media.voice ? ` · ${media.voice}` : ""}`}
              </p>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-pink-100">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-pink-200 border-t-transparent" />
                Gerando
              </div>
            ) : failed ? (
              <div className="rounded-full border border-red-400/30 bg-red-500/10 px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-red-200">
                Falha no audio
              </div>
            ) : expired ? (
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-yellow-400/30 bg-yellow-500/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-yellow-200">
                  Áudio Expirado
                </span>
                {onReSynthesize && (
                  <button
                    onClick={onReSynthesize}
                    className="rounded-full border border-pink-400/30 bg-pink-500/15 hover:bg-pink-500/25 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-pink-200 transition-colors shadow-sm"
                    title="Regerar áudio para ouvir novamente"
                  >
                    Regerar
                  </button>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <button onClick={() => seekBy(-10)} className="h-8 w-8 rounded-full bg-white/10 text-white transition-colors hover:bg-white/20" title="Voltar 10s">
                  <Rewind size={14} className="mx-auto" />
                </button>
                <button
                  onClick={toggleAudioPlayback}
                  className="h-10 w-10 rounded-full bg-gradient-to-br from-pink-400 to-fuchsia-600 text-white shadow-[0_0_20px_rgba(236,72,153,0.45)] transition-all hover:scale-105 active:scale-95"
                  title={playing ? "Pausar" : "Tocar"}
                >
                  {playing ? <Pause size={18} fill="white" className="mx-auto" /> : <Play size={18} fill="white" className="mx-auto ml-[12px]" />}
                </button>
                <button onClick={() => seekBy(10)} className="h-8 w-8 rounded-full bg-white/10 text-white transition-colors hover:bg-white/20" title="Avancar 10s">
                  <FastForward size={14} className="mx-auto" />
                </button>
                <select
                  value={playbackRate}
                  onChange={(event) => updatePlaybackRate(Number(event.target.value))}
                  className="h-8 rounded-full border border-white/10 bg-black/50 px-2 text-[10px] font-bold text-white outline-none"
                  title="Velocidade de reproducao"
                >
                  {[0.75, 1, 1.25, 1.5, 2, 3].map((rate) => <option key={rate} value={rate} className="bg-[#0f0f13]">{rate}x</option>)}
                </select>
                <div className="relative">
                  <button onClick={() => setVolumeOpen((open) => !open)} className="h-8 w-8 rounded-full bg-white/10 text-pink-100 transition-colors hover:bg-pink-500/20" title="Volume global do Chat">
                    {volume === 0 ? <VolumeX size={14} className="mx-auto" /> : <Volume2 size={14} className="mx-auto" />}
                  </button>
                  {volumeOpen && (
                    <div className="absolute bottom-11 left-1/2 z-50 w-48 -translate-x-1/2 rounded-lg border border-pink-400/25 bg-[#0b0910]/95 p-3 shadow-2xl backdrop-blur-xl">
                      <div className="mb-2 flex items-center justify-between text-[9px] font-black uppercase tracking-widest text-pink-200">
                        <span>Volume do Chat</span>
                        <span>{Math.round(volume * 100)}%</span>
                      </div>
                      <input type="range" min="0" max="1" step="0.01" value={volume} onChange={(event) => updateVolume(Number(event.target.value))} className="h-2 w-full cursor-pointer accent-pink-400" aria-label="Volume global do Chat" />
                    </div>
                  )}
                </div>
                <button onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (mediaUrl) void downloadUrl(mediaUrl, media.name); }} className="h-8 w-8 rounded-full bg-white/10 text-white transition-colors hover:bg-white/20" title="Baixar audio">
                  <Download size={14} className="mx-auto" />
                </button>
                {onDelete && (
                  <button onClick={onDelete} className="h-8 w-8 rounded-full bg-red-500/10 text-red-300 transition-colors hover:bg-red-500/25" title="Apagar audio">
                    <Trash2 size={14} className="mx-auto" />
                  </button>
                )}
              </div>
            )}
          </div>

          {mediaUrl && !failed && (
            <div className="mt-3 grid grid-cols-[40px_1fr_44px] items-center gap-2 rounded-lg border border-white/10 bg-black/35 px-3 py-2">
              <span className="font-mono text-[10px] text-white/80">{formatTime(currentTime)}</span>
              <input
                type="range"
                min="0"
                max={progressMax}
                step="0.01"
                value={Math.min(currentTime, progressMax)}
                onChange={(event) => seekTo(Number(event.target.value))}
                className="h-2 w-full cursor-pointer accent-pink-400"
                aria-label="Posicao do audio"
              />
              <span className="text-right font-mono text-[10px] text-white/60">{formatTime(duration)}</span>
            </div>
          )}

          {mediaUrl && (
            <audio
              ref={audioRef}
              src={mediaUrl}
              className="hidden"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onEnded={() => {
                setPlaying(false);
                setCurrentTime(0);
              }}
              onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
              onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 0)}
              onCanPlay={(event) => {
                event.currentTarget.volume = volume;
              }}
            />
          )}
        </div>
      </div>
    );
  }

  return null;
}
