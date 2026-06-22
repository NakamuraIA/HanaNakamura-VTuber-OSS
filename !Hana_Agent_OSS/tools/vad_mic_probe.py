"""Diagnostico de captura: grava do fifine, mede rms e roda o Silero VAD.

Uso: rode com o STT DESLIGADO no painel (pra liberar o microfone) e fale sem
parar enquanto grava. Compara captura nativa (44.1k -> reamostrada p/ 16k) com
o que o runtime faz, pra separar problema de ganho (clipping) de problema de
taxa/API (MME 16k distorcido).
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from hana_agent_oss.modules.voice.vad_silero import SileroSpeechDetector, SileroVADConfig

DEVICE = int(sys.argv[1]) if len(sys.argv) > 1 else 3
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 9.0
OUT = Path("E:/Projeto_Hana_AI/runtime/_vad_probe")
OUT.mkdir(parents=True, exist_ok=True)


def rms_norm(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean((x.astype(np.float64) / 32768.0) ** 2)))


def peak_norm(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.max(np.abs(x.astype(np.float64))) / 32768.0)


def clip_ratio(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.mean(np.abs(x) >= 32000))


def downsample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x.astype(np.int16)
    n_out = int(len(x) * dst / src)
    idx = np.linspace(0, len(x) - 1, n_out)
    return np.interp(idx, np.arange(len(x)), x.astype(np.float64)).astype(np.int16)


def silero_scan(pcm16: np.ndarray, label: str) -> None:
    det = SileroSpeechDetector.create(SileroVADConfig(smoothing_window=1))
    if det is None:
        print(f"  [{label}] Silero indisponivel")
        return
    raw = pcm16.tobytes()
    probs = []
    step = 512 * 2  # bytes per window
    for i in range(0, len(raw) - step, step):
        p = det.probability(raw[i : i + step])
        probs.append(p)
    if probs:
        arr = np.array(probs)
        print(f"  [{label}] silero prob  max={arr.max():.2f}  mean={arr.mean():.2f}  janelas>0.5={int((arr>0.5).sum())}/{len(arr)}")
    else:
        print(f"  [{label}] sem janelas")


def save_wav(path: Path, pcm16: np.ndarray, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())


def main() -> None:
    info = sd.query_devices(DEVICE)
    native_sr = int(info["default_samplerate"])
    print(f"Device {DEVICE}: {info['name']} | taxa nativa {native_sr}Hz")
    print(f">>> FALANDO AGORA por {SECONDS:.0f}s (sem parar)...")
    frames = sd.rec(int(SECONDS * native_sr), samplerate=native_sr, channels=1, dtype="int16", device=DEVICE)
    sd.wait()
    x = frames.reshape(-1)
    print("Captura concluida.\n")

    print(f"NATIVO {native_sr}Hz: rms={rms_norm(x):.3f}  pico={peak_norm(x):.3f}  clip={clip_ratio(x)*100:.1f}%")
    x16 = downsample(x, native_sr, 16000)
    print(f"REAMOSTRADO 16kHz: rms={rms_norm(x16):.3f}  pico={peak_norm(x16):.3f}  clip={clip_ratio(x16)*100:.1f}%")
    silero_scan(x16, "16k limpo")

    save_wav(OUT / "native.wav", x, native_sr)
    save_wav(OUT / "resampled16k.wav", x16, 16000)
    print(f"\nWavs salvos em {OUT} (ouca pra confirmar se sai limpo ou distorcido).")
    print("Leitura: pico>=0.99 ou clip>1% = mic ESTOURANDO (baixe o volume).")
    print("         silero max>0.6 no 16k limpo = wrapper OK, problema e a captura do runtime.")


if __name__ == "__main__":
    main()
