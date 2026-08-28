"""Funções utilitárias puras do runtime de voz.

Extraído de ``runtime.py`` para enxugá-lo: aqui ficam helpers SEM estado nem
dependência da classe ``VoiceRuntime`` — RMS/WAV de PCM, resolução de dispositivos
de áudio (anti-drift de índice no Windows), abertura de stream de mic, validação de
captura PTT e preparação de texto para TTS.

As constantes de áudio (taxa, canais, etc.) são físicas e não mudam; ficam aqui como
fonte para estes helpers. O ``runtime.py`` mantém as suas para o resto da lógica.
"""

from __future__ import annotations

import io
import logging
import math
import re
import wave
from array import array
from typing import Any

logger = logging.getLogger(__name__)

# --- Constantes de áudio (PCM mono 16 kHz / 16-bit) ---------------------------
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2
BLOCK_SIZE = 1024
BLOCK_MS = int(BLOCK_SIZE / SAMPLE_RATE * 1000)

# --- Limiares de captura PTT --------------------------------------------------
PTT_MIN_ACTIVE_VOICE_MS = BLOCK_MS
PTT_MIN_RECORDING_MS = 80
PTT_MIN_PEAK_RMS = 0.012
PTT_THRESHOLD_SCALE = 0.60


def pcm16_rms(frame: bytes) -> float:
    """Return normalized RMS for little-endian 16-bit PCM bytes."""
    if not frame:
        return 0.0
    samples = array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % SAMPLE_WIDTH)])
    if not samples:
        return 0.0
    total = sum(int(sample) * int(sample) for sample in samples)
    return min(1.0, math.sqrt(total / len(samples)) / 32768.0)


def pcm16_wav_bytes(frames: list[bytes]) -> bytes:
    """Wrap raw mono PCM frames as an in-memory 16 kHz WAV."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(frames))
    return buffer.getvalue()


def sounddevice_index(device_id: str) -> int | None:
    value = str(device_id or "").strip()
    if not value or value in {"default", "browser_default"}:
        return None
    if value.startswith("sounddevice:"):
        value = value.split(":", 1)[1]
    try:
        return int(value)
    except ValueError:
        return None


# Generic words that appear in almost every Windows mic name and carry no identity.
_DEVICE_STOPWORDS = {"microphone", "mic", "input", "audio", "device", "sound", "realtek", "default"}


def _device_name_tokens(label: str) -> set[str]:
    """Distinctive lowercased tokens from a device label (e.g. {'fifine'})."""
    raw = re.findall(r"[a-z0-9]+", str(label or "").lower())
    return {tok for tok in raw if len(tok) >= 3 and tok not in _DEVICE_STOPWORDS}


def resolve_input_device(device_id: str, label: str = "") -> int | None:
    """Resolve the mic to a sounddevice index, self-correcting a stale index by name.

    The stored device is a raw numeric index. On Windows that index DRIFTS when the
    device list reorders (host-API churn MME/WASAPI, plugging gear, toggling a
    modifier). A drifted index still opens *some* device without error and that device
    delivers pure silence (rms=0.0) — the mic looks "dead for no reason". So we verify
    the stored index still points at a device matching the saved label; if not, we hunt
    for an input-capable device whose name carries the same distinctive token (e.g.
    'fifine') and use that instead. Index stays authoritative when it's still valid.
    """
    idx = sounddevice_index(device_id)
    tokens = _device_name_tokens(label)
    if not tokens:
        return idx  # no name to match against — trust the stored index

    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        devices = sd.query_devices()
    except Exception:
        return idx  # can't enumerate — fall back to the stored index

    def is_input(dev: Any) -> bool:
        try:
            return int(dev.get("max_input_channels") or 0) > 0
        except Exception:
            return False

    # 1) Is the stored index still the right device? Then nothing changed — keep it.
    if idx is not None and 0 <= idx < len(devices):
        dev = devices[idx]
        if is_input(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            return idx

    # 2) Index drifted (or points at a silent device): find the mic by name.
    for i, dev in enumerate(devices):
        if is_input(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            logger.warning(
                "[VOICE RUNTIME] Indice de mic %s nao bate com '%s'; usando device %s ('%s') por nome.",
                idx, label, i, dev.get("name"),
            )
            return i

    return idx  # no name match anywhere — last resort, stored index


def resolve_output_device(device_id: str, label: str = "") -> int | None:
    """Resolve the second-output device index, self-correcting a stale index by name.

    Same drift problem as the mic (Windows reorders the device list), so the stored
    index for the virtual cable can point at the wrong endpoint. We verify it still
    matches the saved label and otherwise hunt for an output-capable device by name.
    """
    idx = sounddevice_index(device_id)
    tokens = _device_name_tokens(label)
    if not tokens:
        return idx

    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        devices = sd.query_devices()
    except Exception:
        return idx

    def is_output(dev: Any) -> bool:
        try:
            return int(dev.get("max_output_channels") or 0) > 0
        except Exception:
            return False

    if idx is not None and 0 <= idx < len(devices):
        dev = devices[idx]
        if is_output(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            return idx

    for i, dev in enumerate(devices):
        if is_output(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            logger.warning(
                "[VOICE RUNTIME] Indice da 2a saida %s nao bate com '%s'; usando device %s ('%s') por nome.",
                idx, label, i, dev.get("name"),
            )
            return i

    return idx


def open_input_stream(device: int | None):
    """Open a mic RawInputStream, falling back to the system default on PortAudio errors.

    The Windows device list has many duplicates of the same mic across host APIs
    (MME/WASAPI/DirectSound). A stored index can go stale ("device ID out of range",
    PaError -9999) or a given host variant may reject mono ("invalid number of
    channels", -9998). Instead of crashing the whole voice runtime, we retry with
    device=None so PortAudio negotiates a valid default — voice keeps working even
    when the exact selected endpoint is broken.
    """
    import sounddevice as sd

    try:
        return sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS, dtype="int16", device=device
        )
    except Exception as exc:
        if device is None:
            raise
        logger.warning(
            "[VOICE RUNTIME] Falha ao abrir mic device=%s (%s); caindo pro device padrao do sistema.",
            device, exc,
        )
        return sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS, dtype="int16", device=None
        )


def ptt_audio_is_usable(stats: dict[str, Any], *, vad_threshold: float) -> bool:
    """Return whether a PTT capture has intentional speech, including short words."""
    duration_ms = int(stats.get("durationMs") or 0)
    active_ms = int(stats.get("activeMs") or 0)
    try:
        max_rms = float(stats.get("maxRms") or 0.0)
    except (TypeError, ValueError):
        max_rms = 0.0
    min_peak_rms = max(PTT_MIN_PEAK_RMS, float(vad_threshold) * PTT_THRESHOLD_SCALE)
    return (
        duration_ms >= PTT_MIN_RECORDING_MS
        and active_ms >= PTT_MIN_ACTIVE_VOICE_MS
        and max_rms >= min_peak_rms
    )


_XML_BLOCK_RE = re.compile(
    r"<(gerar_imagem|editar_imagem|salvar_memoria)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_XML_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?…]+(?=\s|$)|\n+")


def clamp_tts_text(text: str, max_chars: int) -> str:
    """Trim spoken text to ~max_chars at a sentence boundary (protects TTS credit)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    window = text[:max_chars]
    # Prefer cutting at the last sentence end within the window.
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("\n"))
    if cut < max_chars * 0.5:
        cut = window.rfind(" ")  # senao corta na ultima palavra inteira
    if cut <= 0:
        cut = max_chars
    return text[: cut + 1].strip()


def strip_xml_for_tts(text: str) -> str:
    """Remove action/memory XML (e.g. <gerar_imagem>...) so it is never spoken."""
    text = _XML_BLOCK_RE.sub(" ", text)
    text = _XML_TAG_RE.sub(" ", text)
    return text


def extract_speakable_chunks(buffer: str, *, flush: bool = False) -> tuple[list[str], str]:
    """Split a growing LLM buffer into complete sentences ready to speak.

    Returns (chunks, remaining). XML-safe: while streaming, never emits past the
    first ``<`` (a tag may be opening) so action/memory blocks are not voiced;
    on ``flush`` the tail is emitted (with XML stripped by the caller).
    """
    if not flush:
        lt = buffer.find("<")
        safe, held = (buffer[:lt], buffer[lt:]) if lt != -1 else (buffer, "")
    else:
        safe, held = buffer, ""

    chunks: list[str] = []
    last = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(safe):
        end = match.end()
        sentence = safe[last:end].strip()
        if len(sentence) >= 2:
            chunks.append(sentence)
            last = end
    remaining = safe[last:] + held
    if flush:
        tail = remaining.strip()
        if tail:
            chunks.append(tail)
        remaining = ""
    return chunks, remaining
