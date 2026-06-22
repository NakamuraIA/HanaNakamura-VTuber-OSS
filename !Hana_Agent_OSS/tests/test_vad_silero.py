from __future__ import annotations

import math
import struct

import pytest

from hana_agent_oss.modules.voice.runtime import BargeInGate, RmsVoiceGate
from hana_agent_oss.modules.voice.vad_silero import (
    SileroSpeechDetector,
    SileroVADConfig,
    _model_path,
)


def _pcm16(samples: list[float]) -> bytes:
    return struct.pack("<%dh" % len(samples), *[max(-32768, min(32767, int(s))) for s in samples])


def _tone(n: int, freq: float = 220.0, sr: int = 16000, amp: float = 8000.0) -> bytes:
    return _pcm16([amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)])


# --- Hybrid gate: neural prob + amplitude floor ---------------------------- #

def test_gate_rms_mode_unchanged() -> None:
    """Sem speech_prob, o gate se comporta como o gate de energia original."""
    gate = RmsVoiceGate(threshold=0.035, silence_timeout_ms=900)
    assert gate.push(0.01) == "idle"          # abaixo do limiar
    assert gate.push(0.20) == "start"         # passou -> grava
    assert gate.push(0.20) == "recording"


def test_gate_hybrid_rejects_loud_noise() -> None:
    """RMS alto mas probabilidade neural baixa NAO deve iniciar gravacao.

    Este e o ganho central do Silero: um barulho alto (rms alto) com baixa
    probabilidade de fala fica em 'idle' em vez de virar 'start'.
    """
    gate = RmsVoiceGate(threshold=0.035, silence_timeout_ms=900, prob_threshold=0.5, min_rms=0.01)
    assert gate.push(0.30, speech_prob=0.02) == "idle"   # ruido alto, nao-fala
    assert gate.push(0.30, speech_prob=0.90) == "start"  # fala de verdade


def test_gate_hybrid_requires_amplitude() -> None:
    """Probabilidade alta mas amplitude irrisoria nao inicia (anti-eco/ruido fantasma)."""
    gate = RmsVoiceGate(threshold=0.035, silence_timeout_ms=900, prob_threshold=0.5, min_rms=0.01)
    assert gate.push(0.001, speech_prob=0.95) == "idle"


# --- Barge-in (falar por cima interrompe o TTS) ---------------------------- #

def test_barge_in_fires_on_sustained_speech() -> None:
    gate = BargeInGate(prob_threshold=0.7, min_rms=0.05, min_speech_ms=400, frame_ms=64)
    fired = [gate.push(0.20, 0.95) for _ in range(7)]  # 7*64=448ms > 400
    assert fired[-1] is True
    assert fired[0] is False  # nao corta no primeiro frame


def test_barge_in_ignores_intermittent_echo() -> None:
    """Blips alternados (eco da propria voz) decaem e nunca atingem o limiar."""
    gate = BargeInGate(prob_threshold=0.7, min_rms=0.05, min_speech_ms=400, frame_ms=64)
    fired = False
    for i in range(40):
        fired = gate.push(0.20, 0.95) if i % 2 == 0 else gate.push(0.0, 0.0)
        if fired:
            break
    assert fired is False


def test_barge_in_requires_loudness() -> None:
    gate = BargeInGate(prob_threshold=0.7, min_rms=0.05, min_speech_ms=400, frame_ms=64)
    # prob alta mas volume baixo (eco fraco) -> nao acumula
    assert not any(gate.push(0.01, 0.95) for _ in range(20))


# --- Detector neural (usa o modelo onnx empacotado) ------------------------ #

def test_model_path_resolves_bundled() -> None:
    assert _model_path() is not None, "silero_vad.onnx deveria estar empacotado em models/"


def test_detector_loads_and_scores_silence_low() -> None:
    detector = SileroSpeechDetector.create(SileroVADConfig())
    if detector is None:
        pytest.skip("onnxruntime/numpy indisponivel neste ambiente")
    # silencio puro -> probabilidade baixa
    silence = b"\x00\x00" * 1024
    prob = detector.probability(silence)
    assert 0.0 <= prob < 0.3


def test_detector_handles_odd_and_empty_frames() -> None:
    detector = SileroSpeechDetector.create(SileroVADConfig())
    if detector is None:
        pytest.skip("onnxruntime/numpy indisponivel neste ambiente")
    assert detector.probability(b"") == 0.0
    # frame com numero impar de bytes nao deve estourar
    detector.probability(b"\x01\x02\x03")
    # leftover < 512 samples: nao roda inferencia ainda, sem erro
    detector.probability(_tone(300))
    detector.reset()


def test_detector_prepends_context_window() -> None:
    """Regressao: o input do modelo deve ter 64 de contexto + 512 = 576 amostras.

    Sem o contexto, o Silero v5 devolve ~0 para qualquer fala (bug que travou a
    STT inteira). Este teste falha se alguem voltar a mandar 512 cru.
    """
    np = pytest.importorskip("numpy")
    seen: list[int] = []

    class _FakeSession:
        def run(self, _outputs, feeds):
            seen.append(int(feeds["input"].shape[-1]))
            return [np.array([[0.0]], dtype=np.float32), feeds["state"]]

    det = SileroSpeechDetector(_FakeSession(), SileroVADConfig(smoothing_window=1))
    det.probability(b"\x10\x00" * 1024)  # 1024 samples -> 2 janelas
    assert seen == [576, 576]


def test_detector_smoothing_averages_window() -> None:
    detector = SileroSpeechDetector.create(SileroVADConfig(smoothing_window=3))
    if detector is None:
        pytest.skip("onnxruntime/numpy indisponivel neste ambiente")
    detector._recent.extend([0.0, 1.0, 0.5])
    assert abs(detector._smoothed() - 0.5) < 1e-6
