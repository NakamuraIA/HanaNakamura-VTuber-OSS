from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hana_agent_oss.modules.voice import audio_control
from hana_agent_oss.modules.voice.speech_state import set_speaking
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

DEFAULT_EDGE_VOICE = "pt-BR-FranciscaNeural"
DEFAULT_EDGE_RATE = "+0%"
DEFAULT_EDGE_PITCH = "+0Hz"
DEFAULT_EDGE_VOLUME = "+0%"
EDGE_AUDIO_MIME = "audio/mpeg"
DEFAULT_TTS_CHUNK_CHARS = 260
STREAM_SAMPLE_RATE = 24_000
STREAM_CHANNELS = 2
FFMPEG_CANDIDATES = ("FFMPEG_PATH", "HANA_FFMPEG_PATH")


class TTSConfigurationError(RuntimeError):
    """Raised when the selected TTS provider cannot run."""


@dataclass(frozen=True)
class EdgeTTSResult:
    provider: str
    voice: str
    rate: str
    pitch: str
    volume: str
    text: str
    audio: bytes
    mime_type: str = EDGE_AUDIO_MIME


def split_tts_text(text: str, *, max_chars: int = DEFAULT_TTS_CHUNK_CHARS) -> list[str]:
    """Split long speech text into natural chunks so playback can start sooner."""
    clean_text = sanitize_tts_text(text)
    if not clean_text:
        return []

    max_chars = max(80, int(max_chars or DEFAULT_TTS_CHUNK_CHARS))
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean_text) if part.strip()]
    chunks: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
            current = ""

    for sentence in sentences or [clean_text]:
        if len(sentence) > max_chars:
            flush_current()
            words = sentence.split()
            partial = ""
            for word in words:
                candidate = f"{partial} {word}".strip()
                if partial and len(candidate) > max_chars:
                    chunks.append(partial)
                    partial = word
                else:
                    partial = candidate
            if partial:
                chunks.append(partial)
            continue

        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            flush_current()
            current = sentence
        else:
            current = candidate

    flush_current()
    return chunks


def _command_exists(command: str) -> bool:
    """Return whether a command name or direct executable path is available."""
    value = str(command or "").strip()
    if not value:
        return False
    path = Path(value)
    if path.is_absolute() or any(separator in value for separator in ("/", "\\")):
        return path.exists()
    return shutil.which(value) is not None


def _ffmpeg_path() -> str:
    """Return the FFmpeg executable used for streaming MP3 decode."""
    # 1. Try to read from SQLite portabilidade_config
    from hana_agent_oss.paths import RUNTIME_DB as db_path
    if db_path.exists():
        try:
            import sqlite3
            import json
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT val FROM settings WHERE key = ?", ("portabilidade_config",))
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                config = json.loads(row[0])
                custom_path = config.get("ffmpegPath")
                if custom_path and Path(custom_path).exists():
                    return str(Path(custom_path))
        except Exception:
            pass

    # 2. Try environment variables
    for env_name in FFMPEG_CANDIDATES:
        value = os.environ.get(env_name)
        if value:
            return value
    # 3. Try standard local default
    default = Path("C:/Ffmpeg/ffmpeg.exe")
    return str(default) if default.exists() else "ffmpeg"


def _signed_percent(value: Any, *, default: str = DEFAULT_EDGE_RATE) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%") and text[:1] in {"+", "-"}:
            return text
        try:
            value = float(text)
        except ValueError:
            return default

    try:
        percent = round((float(value) - 1.0) * 100)
    except (TypeError, ValueError):
        return default
    percent = max(-90, min(100, percent))
    return f"{percent:+d}%"


def _signed_hertz(value: Any, *, default: str = DEFAULT_EDGE_PITCH) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Hz") and text[:1] in {"+", "-"}:
            return text
        try:
            value = float(text)
        except ValueError:
            return default

    try:
        hertz = round(float(value))
    except (TypeError, ValueError):
        return default
    hertz = max(-100, min(100, hertz))
    return f"{hertz:+d}Hz"


class EdgeTTSProvider:
    provider_id = "edge"

    def __init__(
        self,
        *,
        voice: str | None = None,
        speed: float | str | None = None,
        pitch: float | str | None = None,
        volume: str | None = None,
    ) -> None:
        self.voice = str(voice or DEFAULT_EDGE_VOICE).strip() or DEFAULT_EDGE_VOICE
        self.rate = _signed_percent(speed if speed is not None else 1.0)
        self.pitch = _signed_hertz(pitch if pitch is not None else 0)
        self.volume = str(volume or DEFAULT_EDGE_VOLUME).strip() or DEFAULT_EDGE_VOLUME

    async def synthesize(self, text: str) -> EdgeTTSResult:
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        try:
            import edge_tts
        except ImportError as exc:
            raise TTSConfigurationError("The edge-tts package is required for Edge TTS.") from exc

        audio_control.reset_stop_state()
        set_speaking(True)
        fd, raw_path = tempfile.mkstemp(prefix="hana-edge-tts-", suffix=".mp3")
        os.close(fd)
        output_path = Path(raw_path)
        try:
            communicate = edge_tts.Communicate(
                clean_text,
                self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch,
            )
            await communicate.save(str(output_path))
            if audio_control.stop_requested():
                return EdgeTTSResult(
                    provider=self.provider_id,
                    voice=self.voice,
                    rate=self.rate,
                    pitch=self.pitch,
                    volume=self.volume,
                    text=clean_text,
                    audio=b"",
                )
            return EdgeTTSResult(
                provider=self.provider_id,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch,
                volume=self.volume,
                text=clean_text,
                audio=output_path.read_bytes(),
            )
        finally:
            set_speaking(False)
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def stream_audio_chunks(self, text: str):
        """Yield Edge TTS MP3 chunks as soon as the service streams them."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        try:
            import edge_tts
        except ImportError as exc:
            raise TTSConfigurationError("The edge-tts package is required for Edge TTS.") from exc

        communicate = edge_tts.Communicate(
            clean_text,
            self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )
        async for chunk in communicate.stream():
            if audio_control.stop_requested():
                break
            if chunk.get("type") == "audio" and chunk.get("data"):
                yield chunk["data"]


MotorTTSEdge = EdgeTTSProvider


class EdgeTTSPlayer:
    """Blocking local MP3 player for backend-owned Edge TTS playback."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pygame: Any | None = None
        self._stream_stop_event = threading.Event()
        # Segunda saída (espelho): índice sounddevice de um device extra (ex.: CABLE
        # Input do VB-Audio) onde a voz também toca, além do alto-falante local. None =
        # desligado. Uma falha no espelho NUNCA derruba a saída principal.
        self._mirror_device: int | None = None
        audio_control.register_stop_callback("edge_tts_player", self.stop)

    def set_mirror(self, device_index: int | None, enabled: bool) -> None:
        """Set/clear the second output device the voice is mirrored to."""
        with self._lock:
            self._mirror_device = device_index if (enabled and device_index is not None) else None

    def _pygame_module(self):
        if self._pygame is not None:
            return self._pygame
        try:
            import pygame
        except ImportError as exc:
            raise TTSConfigurationError("The pygame package is required for backend Edge TTS playback.") from exc

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self._pygame = pygame
        return pygame

    @staticmethod
    def _normalize_volume(volume: float) -> float:
        """Clamp local playback volume to the mixer-supported range."""
        try:
            return max(0.0, min(1.0, float(volume)))
        except (TypeError, ValueError):
            return 1.0

    def _start_mirror_for_bytes(self, audio: bytes, volume: float) -> threading.Thread | None:
        """Decode a full TTS payload and play it on the second output device, in parallel.

        Best-effort mirror for the pygame (file) playback path: ffmpeg decodes the bytes
        to PCM and writes them to the chosen sounddevice output (e.g. CABLE Input) while
        pygame plays locally. Any failure is swallowed — it never affects the main voice.
        """
        mirror_device = self._mirror_device
        if mirror_device is None or not audio:
            return None
        ffmpeg = _ffmpeg_path()
        if not _command_exists(ffmpeg):
            return None

        def _run() -> None:
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",
                "-filter:a", f"volume={self._normalize_volume(volume):.3f}",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ac", str(STREAM_CHANNELS), "-ar", str(STREAM_SAMPLE_RATE), "pipe:1",
            ]
            process: Any = None
            try:
                import sounddevice as sd

                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if not process.stdin or not process.stdout:
                    return

                # Feed stdin from a separate thread so a full pipe buffer never deadlocks
                # against us reading stdout.
                def _feed() -> None:
                    with contextlib.suppress(Exception):
                        process.stdin.write(audio)
                    with contextlib.suppress(Exception):
                        process.stdin.close()

                feeder = threading.Thread(target=_feed, daemon=True)
                feeder.start()
                with sd.RawOutputStream(
                    samplerate=STREAM_SAMPLE_RATE, channels=STREAM_CHANNELS, dtype="int16", device=mirror_device
                ) as stream:
                    while True:
                        if self._stream_stop_event.is_set() or audio_control.stop_requested():
                            break
                        data = process.stdout.read(4096)
                        if not data:
                            break
                        stream.write(data)
            except Exception as exc:
                logger.warning("[VOICE TTS] Segunda saida (device %s) falhou no playback: %s", mirror_device, exc)
            finally:
                if process is not None and process.poll() is None:
                    with contextlib.suppress(Exception):
                        process.kill()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return thread

    def play_blocking(self, audio: bytes, *, mime_type: str = EDGE_AUDIO_MIME, volume: float = 1.0) -> None:
        """Play a complete TTS payload locally at the requested volume."""
        if not audio:
            return

        pygame = self._pygame_module()
        playback_volume = self._normalize_volume(volume)
        mirror_thread = self._start_mirror_for_bytes(audio, volume)
        suffix = ".wav" if mime_type in {"audio/wav", "audio/wave", "audio/x-wav"} or audio.startswith(b"RIFF") else ".mp3"
        fd, raw_path = tempfile.mkstemp(prefix="hana-edge-play-", suffix=suffix)
        os.close(fd)
        output_path = Path(raw_path)
        output_path.write_bytes(audio)
        try:
            audio_control.reset_stop_state()
            set_speaking(True)
            with self._lock:
                pygame.mixer.music.load(str(output_path))
                pygame.mixer.music.set_volume(playback_volume)
                pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if audio_control.stop_requested():
                    self.stop()
                    break
                time.sleep(0.05)
        finally:
            set_speaking(False)
            if mirror_thread is not None and mirror_thread.is_alive():
                # Let the mirror drain (it's ~the same length); bounded so we never hang.
                mirror_thread.join(timeout=2.0)
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass

    def stop(self, reason: str = "user_request") -> None:
        self._stream_stop_event.set()
        if self._pygame is None:
            set_speaking(False)
            return
        try:
            pygame = self._pygame_module()
            with self._lock:
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
        except Exception:
            pass
        set_speaking(False)

    async def play_edge_streaming(self, provider: EdgeTTSProvider, text: str, *, volume: float = 1.0) -> bool:
        """Play Edge TTS while audio chunks are still arriving from the service."""
        if not sanitize_tts_text(text):
            return False

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise TTSConfigurationError("The sounddevice package is required for streaming Edge TTS playback.") from exc

        ffmpeg = _ffmpeg_path()
        if not _command_exists(ffmpeg):
            raise TTSConfigurationError(f"FFmpeg indisponivel para streaming Edge TTS: {ffmpeg}.")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "mp3",
            "-i",
            "pipe:0",
            "-filter:a",
            f"volume={self._normalize_volume(volume):.3f}",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            str(STREAM_CHANNELS),
            "-ar",
            str(STREAM_SAMPLE_RATE),
            "pipe:1",
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not process.stdin or not process.stdout:
            raise TTSConfigurationError("FFmpeg streaming pipe nao abriu corretamente.")

        audio_control.reset_stop_state()
        self._stream_stop_event.clear()
        set_speaking(True)
        wrote_audio = False
        playback_error: list[BaseException] = []

        def _stop_requested() -> bool:
            return self._stream_stop_event.is_set() or audio_control.stop_requested()

        mirror_device = self._mirror_device

        def _decode_and_play() -> None:
            mirror_stream = None
            if mirror_device is not None:
                try:
                    mirror_stream = sd.RawOutputStream(
                        samplerate=STREAM_SAMPLE_RATE, channels=STREAM_CHANNELS, dtype="int16", device=mirror_device
                    )
                    mirror_stream.start()
                except Exception as exc:  # mirror is best-effort, never blocks the voice
                    logger.warning("[VOICE TTS] Segunda saida (device %s) falhou ao abrir: %s", mirror_device, exc)
                    mirror_stream = None
            try:
                with sd.RawOutputStream(samplerate=STREAM_SAMPLE_RATE, channels=STREAM_CHANNELS, dtype="int16") as stream:
                    while True:
                        if _stop_requested():
                            break
                        data = process.stdout.read(4096)
                        if not data:
                            break
                        stream.write(data)
                        if mirror_stream is not None:
                            try:
                                mirror_stream.write(data)
                            except Exception:
                                mirror_stream = None  # drop the mirror, keep the main voice
            except BaseException as exc:  # pragma: no cover - hardware dependent.
                playback_error.append(exc)
            finally:
                if mirror_stream is not None:
                    with contextlib.suppress(Exception):
                        mirror_stream.stop()
                        mirror_stream.close()

        playback_thread = threading.Thread(target=_decode_and_play, daemon=True)
        playback_thread.start()
        try:
            async for audio_chunk in provider.stream_audio_chunks(text):
                if _stop_requested():
                    break
                wrote_audio = True
                try:
                    await asyncio.to_thread(process.stdin.write, audio_chunk)
                    await asyncio.to_thread(process.stdin.flush)
                except (BrokenPipeError, OSError):
                    break
            with contextlib.suppress(Exception):
                process.stdin.close()
            while playback_thread.is_alive():
                if _stop_requested():
                    break
                await asyncio.sleep(0.03)
        finally:
            if _stop_requested() and process.poll() is None:
                with contextlib.suppress(Exception):
                    process.terminate()
            with contextlib.suppress(Exception):
                process.wait(timeout=1)
            if process.poll() is None:
                with contextlib.suppress(Exception):
                    process.kill()
            set_speaking(False)
            self._stream_stop_event.clear()

        if playback_error:
            raise TTSConfigurationError(f"Falha no playback streaming Edge TTS: {playback_error[0]}")
        return wrote_audio

    async def play_stream(self, provider: Any, text: str, *, volume: float = 1.0) -> bool:
        """Play any provider that exposes stream_audio_chunks() (MP3) as it arrives.

        The piping logic is provider-agnostic, so ElevenLabs streaming reuses the
        exact same ffmpeg→sounddevice pipeline as Edge.
        """
        return await self.play_edge_streaming(provider, text, volume=volume)
