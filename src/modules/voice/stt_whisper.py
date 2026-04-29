import json
import logging
import os
import re
import tempfile
import wave

import keyboard
import pyaudio
from groq import Groq

from src.config.config_loader import CONFIG
from src.core.runtime_capabilities import get_ptt_settings
from src.utils.text import ui

logger = logging.getLogger(__name__)

DEFAULT_STT_PROMPT = (
    "Conversa casual em portugues brasileiro. O usuario se chama Nakamura e fala com a assistente Hana. "
    "Use grafia correta para nomes e termos comuns: Hana, Nakamura, Nyra, Mai, VTube Studio, Live2D, Cubism, "
    "Gemini, Groq, OpenRouter, ElevenLabs, Supabase, Playwright, FFmpeg, Brave. "
    "Transcreva somente fala humana clara. Ignore ruido, batidas no microfone, respiracao e silencio. "
    "Nao invente texto quando nao houver fala."
)
STT_PROMPT_MAX_WORDS = 160
FRASES_FANTASMAS_STT = {
    "",
    "obrigado.",
    "obrigada.",
    "obrigado",
    "obrigada",
    "tchau.",
    "tchau",
    "tchau tchau",
    "tchau, tchau.",
    "legendas pela comunidade amara.org",
    "mistura de idiomas.",
    "mistura de idiomas",
    "o usuario fala portugues e japones.",
    "portugues e japones.",
    "inscreva-se no canal",
    "deixe seu like",
    "legenda adriana zanotto",
    "e ai.",
    "e ai",
    "legenda por sonia ruberti",
    "legendas por sonia ruberti",
    "sonia ruberti",
    "subtitulos por tiago anderson",
    "subtitulo por tiago anderson",
    "legendas por tiago anderson",
    "legenda por tiago anderson",
    "ate a proxima",
    "ate a proxima!",
    "ate a proxima.",
    "ate a proxima.",
}
PADROES_FANTASMAS_STT = (
    re.compile(r"^(?:subtitulos?|legendas?|legenda|caption|captions|subtitle|subtitles)\s+(?:por|by)\s+[\w .'-]{2,60}\.?$", re.IGNORECASE),
    re.compile(r"^(?:transcricao|transcription)\s+(?:por|by)\s+[\w .'-]{2,60}\.?$", re.IGNORECASE),
    re.compile(r"^(?:traduzido|traducao|translation)\s+(?:por|by)\s+[\w .'-]{2,60}\.?$", re.IGNORECASE),
    re.compile(r"^(?:inscreva-se|deixe seu like|ative o sininho)(?:.+)?\.?$", re.IGNORECASE),
    re.compile(r"^.+(?:ative o sininho|notificacoes de novos videos).*$", re.IGNORECASE),
)

try:
    import audioop

    def audio_rms(data, width):
        return audioop.rms(data, width)
except Exception:
    def audio_rms(data, width):
        try:
            from array import array
            import math

            if width == 2:
                arr = array("h")
            elif width == 1:
                arr = array("b")
            else:
                arr = array("h")

            arr.frombytes(data)
            if not arr:
                return 0

            squared_mean = sum(x * x for x in arr) / len(arr)
            return int(math.sqrt(squared_mean))
        except Exception:
            return 0


class MotorSTTWhisper:
    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY") or CONFIG.get("GROQ_API_KEY")
        self.cliente = Groq(api_key=api_key)
        self.modelo_stt = CONFIG.get("STT_MODEL", "whisper-large-v3")
        self.idioma = CONFIG.get("STT_LANGUAGE", "pt")
        self.prompt_stt = self._normalizar_prompt_stt(CONFIG.get("STT_PROMPT", DEFAULT_STT_PROMPT))

        self.indice_mic = CONFIG.get("MIC_DEVICE_INDEX", None)
        self.formato = pyaudio.paInt16
        self.taxa_amostragem = CONFIG.get("TAXA_AMOSTRAGEM", 44100)
        self.canais = 1
        self.chunk = 1024
        self.audio = pyaudio.PyAudio()

        self.limiar_volume = 800
        self.limite_silencio = 1.6
        self.noise_guard_enabled = bool(CONFIG.get("STT_NOISE_GUARD_ENABLED", True))
        self.min_recording_seconds = float(CONFIG.get("STT_MIN_RECORDING_SECONDS", 0.45))
        self.min_active_seconds = float(CONFIG.get("STT_MIN_ACTIVE_SECONDS", 0.30))
        self.min_sustained_active_seconds = float(CONFIG.get("STT_MIN_SUSTAINED_ACTIVE_SECONDS", 0.12))
        self.min_active_ratio = float(CONFIG.get("STT_MIN_ACTIVE_RATIO", 0.08))

        ptt_cfg = get_ptt_settings()
        self.modo_ptt = bool(ptt_cfg["enabled"])
        self.tecla_ptt = str(ptt_cfg["key"]).lower()

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.caminho_dicionario = os.path.join(base_dir, "config", "dicionário.json")
        self._criar_dicionario_padrao()

    def _criar_dicionario_padrao(self):
        if not os.path.exists(self.caminho_dicionario):
            os.makedirs(os.path.dirname(self.caminho_dicionario), exist_ok=True)
            with open(self.caminho_dicionario, "w", encoding="utf-8") as f:
                json.dump({"hannah": "Hana"}, f, indent=4, ensure_ascii=False)

    def _corrigir_texto(self, texto: str) -> str:
        try:
            with open(self.caminho_dicionario, "r", encoding="utf-8") as f:
                dicionario = json.load(f)

            for errado, certo in dicionario.items():
                padrao = re.compile(rf"\b{re.escape(errado)}\b", re.IGNORECASE | re.UNICODE)
                texto = padrao.sub(certo, texto)
            return texto
        except Exception as e:
            logger.warning(f"[STT] Falha ao aplicar dicionario de correcao: {e}")
            return texto

    @staticmethod
    def _normalizar_prompt_stt(prompt: str) -> str:
        prompt = str(prompt or "").strip()
        if not prompt:
            return ""

        words = prompt.split()
        if len(words) <= STT_PROMPT_MAX_WORDS:
            return prompt

        return " ".join(words[:STT_PROMPT_MAX_WORDS])

    def _prompt_transcricao(self) -> str:
        prompt_config = CONFIG.get("STT_PROMPT", self.prompt_stt or DEFAULT_STT_PROMPT)
        return self._normalizar_prompt_stt(prompt_config)

    def _audio_passes_noise_guard(self, volumes: list[int]) -> bool:
        if not self.noise_guard_enabled:
            return True
        if not volumes:
            return False

        frame_seconds = self.chunk / float(self.taxa_amostragem)
        total_seconds = len(volumes) * frame_seconds
        active_flags = [volume > self.limiar_volume for volume in volumes]
        active_frames = sum(1 for active in active_flags if active)
        active_seconds = active_frames * frame_seconds
        active_ratio = active_frames / max(1, len(volumes))

        longest_run = 0
        current_run = 0
        for active in active_flags:
            if active:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 0
        sustained_seconds = longest_run * frame_seconds

        if total_seconds < self.min_recording_seconds:
            logger.info("[STT] Audio descartado: curto demais (%.2fs).", total_seconds)
            return False

        if active_seconds < self.min_active_seconds and active_ratio < self.min_active_ratio:
            logger.info(
                "[STT] Audio descartado: pouca voz ativa (active=%.2fs ratio=%.2f).",
                active_seconds,
                active_ratio,
            )
            return False

        if sustained_seconds < self.min_sustained_active_seconds:
            logger.info("[STT] Audio descartado: sem voz sustentada (%.2fs).", sustained_seconds)
            return False

        return True

    @staticmethod
    def _normalizar_texto_fantasma(texto: str) -> str:
        normalized = str(texto or "").lower().strip()
        replacements = str.maketrans(
            {
                "á": "a",
                "à": "a",
                "â": "a",
                "ã": "a",
                "é": "e",
                "ê": "e",
                "í": "i",
                "ó": "o",
                "ô": "o",
                "õ": "o",
                "ú": "u",
                "ç": "c",
            }
        )
        normalized = normalized.translate(replacements)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @classmethod
    def _eh_frase_fantasma(cls, texto: str) -> bool:
        normalized = cls._normalizar_texto_fantasma(texto)
        if normalized in FRASES_FANTASMAS_STT:
            return True
        return any(pattern.match(normalized) for pattern in PADROES_FANTASMAS_STT)

    def gravar_audio(self) -> str:
        if self.modo_ptt:
            return self._gravar_ptt()
        return self._gravar_buffer()

    def _gravar_ptt(self) -> str:
        try:
            stream = self.audio.open(
                format=self.formato,
                channels=self.canais,
                rate=self.taxa_amostragem,
                input=True,
                input_device_index=self.indice_mic,
                frames_per_buffer=self.chunk,
            )
        except Exception as e:
            logger.error(f"[STT] Falha ao abrir stream de audio no modo PTT: {e}")
            return None

        ui.print_ouvindo()
        frames = []
        try:
            while True:
                if keyboard.is_pressed(self.tecla_ptt):
                    data = stream.read(self.chunk, exception_on_overflow=False)
                    frames.append(data)
                elif frames:
                    break
        except KeyboardInterrupt:
            stream.stop_stream()
            stream.close()
            return None

        stream.stop_stream()
        stream.close()

        if not frames:
            return None

        arquivo_temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        caminho_wav = arquivo_temp.name
        with wave.open(caminho_wav, "wb") as wf:
            wf.setnchannels(self.canais)
            wf.setsampwidth(self.audio.get_sample_size(self.formato))
            wf.setframerate(self.taxa_amostragem)
            wf.writeframes(b"".join(frames))
        return caminho_wav

    def _gravar_buffer(self) -> str:
        try:
            stream = self.audio.open(
                format=self.formato,
                channels=self.canais,
                rate=self.taxa_amostragem,
                input=True,
                input_device_index=self.indice_mic,
                frames_per_buffer=self.chunk,
            )
        except Exception as e:
            logger.error(f"[STT] Falha ao abrir stream de audio no modo buffer: {e}")
            return None

        ui.print_ouvindo()

        frames = []
        volumes = []
        gravando = False
        silencio_frames = 0
        max_silencio_frames = int((self.taxa_amostragem / self.chunk) * self.limite_silencio)

        while True:
            try:
                data = stream.read(self.chunk, exception_on_overflow=False)
                width = self.audio.get_sample_size(self.formato)
                volume = audio_rms(data, width)

                if volume > self.limiar_volume:
                    gravando = True
                    silencio_frames = 0
                    frames.append(data)
                    volumes.append(volume)
                elif gravando:
                    silencio_frames += 1
                    frames.append(data)
                    volumes.append(volume)
                    if silencio_frames > max_silencio_frames:
                        break
            except KeyboardInterrupt:
                stream.stop_stream()
                stream.close()
                return None

        stream.stop_stream()
        stream.close()

        if not frames:
            return None
        if not self._audio_passes_noise_guard(volumes):
            return None

        arquivo_temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        caminho_wav = arquivo_temp.name
        with wave.open(caminho_wav, "wb") as wf:
            wf.setnchannels(self.canais)
            wf.setsampwidth(self.audio.get_sample_size(self.formato))
            wf.setframerate(self.taxa_amostragem)
            wf.writeframes(b"".join(frames))

        return caminho_wav

    def transcrever(self) -> str:
        caminho_wav = self.gravar_audio()
        if not caminho_wav:
            return ""

        ui.print_linha("PROCESSANDO", ui.C_STT, "WHISPER", "⚙️", "🎙️")

        texto_transcrito = ""
        try:
            with open(caminho_wav, "rb") as arquivo_audio:
                transcricao = self.cliente.audio.transcriptions.create(
                    file=(os.path.basename(caminho_wav), arquivo_audio),
                    model=self.modelo_stt,
                    language=self.idioma,
                    response_format="text",
                    prompt=self._prompt_transcricao(),
                    temperature=0.0,
                )
                texto_transcrito = transcricao.strip()
                texto_limpo = texto_transcrito.lower().strip()

                frases_fantasmas = [
                    "",
                    "obrigado.",
                    "obrigada.",
                    "obrigado",
                    "obrigada",
                    "tchau.",
                    "tchau",
                    "tchau tchau",
                    "tchau, tchau.",
                    "legendas pela comunidade amara.org",
                    "mistura de idiomas.",
                    "mistura de idiomas",
                    "o usuário fala português e japonês.",
                    "português e japonês.",
                    "inscreva-se no canal",
                    "deixe seu like",
                    "legenda adriana zanotto",
                    "e aí.",
                    "e aí",
                    "e ai.",
                    "e ai",
                    "legenda por sônia ruberti",
                    "legendas por sônia ruberti",
                    "sônia ruberti",
                ]

                if texto_limpo in frases_fantasmas or self._eh_frase_fantasma(texto_transcrito):
                    logger.info("[STT] Frase fantasma descartada: %s", texto_transcrito)
                    return ""

                palavras_curtas_validas = ["oi", "oi.", "ok", "ok.", "aí", "aí.", "lá", "lá."]
                if len(texto_limpo) < 3 and texto_limpo not in palavras_curtas_validas:
                    return ""

                texto_transcrito = self._corrigir_texto(texto_transcrito)
        except Exception as erro:
            logger.error(f"[STT] Erro durante transcricao Whisper: {erro}")
        finally:
            if os.path.exists(caminho_wav):
                os.remove(caminho_wav)

        return texto_transcrito
