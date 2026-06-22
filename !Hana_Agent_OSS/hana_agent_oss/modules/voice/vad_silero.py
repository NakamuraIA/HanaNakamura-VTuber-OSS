"""Neural voice-activity detection via Silero VAD (ONNX, no torch at runtime).

The energy/RMS gate in :mod:`runtime` triggers on *any* loud sound (keyboard,
fan, a slammed door). Silero is a tiny neural model (~2MB, runs on CPU in well
under a millisecond per window) that returns the *probability that a chunk is
speech*, so it rejects noise that the RMS gate would mistake for voice.

Design (borrowed from Open-LLM-VTuber's ``vad/silero.py``):

- run inference on fixed 512-sample windows @16kHz (Silero v5 requirement);
- carry the recurrent ``state`` across windows, reset it between utterances;
- smooth the probability over a short window so a single spike/dip does not
  flip the gate;
- combine the neural probability with an amplitude floor (hybrid) so faint
  background TV/music that scores high never starts a recording.

This module owns ONLY the neural probability. The start/stop timing (silence
timeout, min duration, pre-roll) stays in the existing gate in ``runtime`` so
both VAD modes share identical behaviour around the decision.
"""

from __future__ import annotations

import logging
import os
from array import array
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SILERO_SAMPLE_RATE = 16_000
SILERO_WINDOW_SAMPLES = 512  # Silero v5 advances 512 new samples per call @16k
SILERO_CONTEXT_SAMPLES = 64  # ...but the model input is 64 context + 512 new = 576
SAMPLE_WIDTH = 2  # int16


@dataclass(frozen=True)
class SileroVADConfig:
    """Tunable knobs for the neural gate (sensible defaults for a noisy room)."""

    prob_threshold: float = 0.5  # speech probability cutoff (0..1)
    min_rms: float = 0.006       # amplitude floor; below this never counts as speech
    smoothing_window: int = 3    # windows averaged to stabilise the probability


def _model_path() -> str | None:
    """Resolve the Silero ONNX model: env override first, then the bundled copy."""
    override = os.environ.get("HANA_SILERO_VAD_PATH")
    if override and os.path.isfile(override):
        return override
    try:
        from hana_agent_oss.paths import SILERO_VAD_MODEL
    except Exception:
        return None
    return str(SILERO_VAD_MODEL) if SILERO_VAD_MODEL.is_file() else None


class SileroSpeechDetector:
    """Stateful neural speech-probability estimator over streamed PCM frames."""

    def __init__(self, session, config: SileroVADConfig) -> None:
        import numpy as np  # local import keeps module import cheap

        self._np = np
        self._session = session
        self.config = config
        self._sr = np.array(SILERO_SAMPLE_RATE, dtype=np.int64)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((SILERO_CONTEXT_SAMPLES,), dtype=np.float32)
        self._leftover = np.zeros((0,), dtype=np.float32)
        self._recent: deque[float] = deque(maxlen=max(1, int(config.smoothing_window)))

    @classmethod
    def create(cls, config: SileroVADConfig | None = None) -> "SileroSpeechDetector | None":
        """Build a detector, or return None when onnxruntime/model are unavailable.

        Returning None lets the runtime fall back to the RMS gate transparently
        instead of crashing the voice loop on a machine without the model.
        """
        config = config or SileroVADConfig()
        path = _model_path()
        if not path:
            logger.warning("[VAD] Silero model not found; falling back to RMS gate.")
            return None
        try:
            import onnxruntime as ort  # noqa: F401
            import numpy as np  # noqa: F401
        except Exception as exc:
            logger.warning("[VAD] onnxruntime/numpy unavailable (%s); using RMS gate.", exc)
            return None
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        except Exception as exc:
            logger.warning("[VAD] Failed to load Silero model (%s); using RMS gate.", exc)
            return None
        logger.info("[VAD] Silero neural VAD active (%s).", path)
        return cls(session, config)

    def reset(self) -> None:
        """Clear recurrent state between utterances (call when the gate resets)."""
        self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)
        self._context = self._np.zeros((SILERO_CONTEXT_SAMPLES,), dtype=self._np.float32)
        self._leftover = self._np.zeros((0,), dtype=self._np.float32)
        self._recent.clear()

    def probability(self, frame: bytes) -> float:
        """Return the smoothed speech probability for a PCM16 mono frame.

        Frames are not required to be a multiple of 512 samples; leftover tail
        samples are carried to the next call so no audio is dropped.
        """
        np = self._np
        if not frame:
            return self._smoothed()
        usable = frame[: len(frame) - (len(frame) % SAMPLE_WIDTH)]
        pcm = array("h")
        pcm.frombytes(usable)
        if not pcm:
            return self._smoothed()
        samples = np.frombuffer(bytes(pcm), dtype=np.int16).astype(np.float32) / 32768.0
        if self._leftover.size:
            samples = np.concatenate((self._leftover, samples))

        offset = 0
        total = samples.shape[0]
        while total - offset >= SILERO_WINDOW_SAMPLES:
            window = samples[offset : offset + SILERO_WINDOW_SAMPLES]
            offset += SILERO_WINDOW_SAMPLES
            # Silero v5 expects 64 samples of prior context prepended to the 512
            # new samples (576 total). Without it the model returns ~0 for speech.
            model_input = np.concatenate((self._context, window)).reshape(1, -1).astype(np.float32)
            self._context = window[-SILERO_CONTEXT_SAMPLES:]
            try:
                out, self._state = self._session.run(
                    None,
                    {
                        "input": model_input,
                        "state": self._state,
                        "sr": self._sr,
                    },
                )
                self._recent.append(float(out[0][0]))
            except Exception as exc:  # pragma: no cover - inference guard
                logger.debug("[VAD] Silero inference error: %s", exc)
                self._recent.append(0.0)
        self._leftover = samples[offset:]
        return self._smoothed()

    def _smoothed(self) -> float:
        if not self._recent:
            return 0.0
        return sum(self._recent) / len(self._recent)
