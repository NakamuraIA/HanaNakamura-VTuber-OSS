from __future__ import annotations

import os
from typing import Any

from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice.tts_fishaudio import FISHAUDIO_TTS_MODELS, DEFAULT_FISHAUDIO_MODEL
from hana_agent_oss.modules.voice.tts_elevenlabs import (
    DEFAULT_ELEVENLABS_MODEL,
    DEFAULT_ELEVENLABS_VOICE,
    ELEVENLABS_TTS_MODELS,
)
from hana_agent_oss.providers.provider_selector.deepseek.catalog import get_deepseek_catalog
from hana_agent_oss.providers.provider_selector.groq.catalog import GROQ_STATIC_MODELS, get_groq_catalog
from hana_agent_oss.providers.provider_selector.openrouter.catalog import get_openrouter_catalog
from hana_agent_oss.providers.provider_selector.qwen.catalog import get_qwen_catalog
from hana_agent_oss.providers.provider_selector.maritaca.catalog import get_maritaca_catalog


DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "llmProvider": "gemini_api",
    "llmModel": "gemini-3.1-pro-preview",
    "agentProvider": "",
    "agentModel": "",
    "agentToolRounds": 40,
    "llmFilter": "",
    "llmTemperature": 0.85,
    # Groq "pensar antes de falar": True = modelos de raciocínio (qwen3/gpt-oss) pensam
    # antes de responder; False = resposta direta e rápida (reasoning_effort=none).
    "groqThinking": True,
    # Qwen "pensar antes de falar" (so modelos qwen3.x): True = raciocina; False =
    # resposta direta (enable_thinking=false). Aliases genericos (qwen-plus/turbo/max)
    # nao sao afetados — ver _apply_thinking_control no provider.
    "qwenThinking": True,
    # DeepSeek so tem 2 niveis reais + desligado: "" (padrao deles = high),
    # "high" ou "max" (ver reasoning_effort na doc oficial), ou "off" (thinking.type=disabled).
    "deepseekReasoningEffort": "",
    # OpenRouter "pensar antes de falar": so afeta modelos cujo supportedParameters
    # inclui "reasoning" (ex.: Gemini 3.x, alguns Qwen/DeepSeek via OpenRouter).
    "openrouterThinking": True,
    # "Pensar" do MODELO DE AGENTE (loop de ferramentas), independente do chat.
    # agentThinking = on/off (groq/qwen); agentReasoningEffort = nivel (deepseek/openrouter).
    "agentThinking": True,
    "agentReasoningEffort": "",
    "openrouterRoutingByModel": {},
    "visionModel": "gemini-3-flash-preview",
    # Provider dono do visionModel. Vazio = inferir pelo id do modelo (catalog_provider_for_model).
    # Usado pra ROTEAR imagem quando o provider do chat nao ve (reaproveita o visionModel).
    "visionProvider": "",
    "ttsProvider": "edge",
    "ttsVoice": "",
    "ttsModel": "",
    "ttsLanguage": "pt-BR",
    "ttsPrompt": (
        "You are generating TTS audio in Brazilian Portuguese.\n"
        "Voice character: young adult AI assistant.\n"
        "Tone: warm, playful, slightly teasing, but not childish.\n"
        "Pace: medium, with natural pauses.\n"
        "Accent: neutral Brazilian Portuguese.\n"
        "Do not read these instructions aloud. Only synthesize the transcript."
    ),
    "ttsFilter": "",
    "ttsSpeed": 1.0,
    "ttsPitch": 0.0,
    "ttsVolume": 1.0,
    "ttsStreaming": True,  # fala frase-a-frase enquanto o modelo gera (corta o tempo até o 1º áudio)
    "ttsStability": 0.5,
    "ttsSimilarity": 0.75,
    "ttsStyle": 0.0,
    "ttsSpeakerBoost": True,
    # Last-used voice/controls per TTS provider, so switching providers and coming
    # back restores the custom voice instead of resetting to the hardcoded default.
    "ttsByProvider": {},
}

DEFAULT_CHAT_CONFIG: dict[str, Any] = {
    "provider": "gemini_api",
    "model": "gemini-3.1-pro-preview",
    "nativeSearchMode": "auto",
    "openrouterRoutingByModel": {},
}

DEFAULT_VOICE_CONFIG: dict[str, Any] = {
    "sttProvider": "groq_whisper",
    "sttModel": "whisper-large-v3",
    "sttLanguage": "pt",
    "ttsProvider": "edge",
    "ttsModel": "",
    "ttsVoice": "pt-BR-FranciscaNeural",
    "ttsLanguage": "pt-BR",
    "ttsPrompt": (
        "You are generating TTS audio in Brazilian Portuguese.\n"
        "Voice character: young adult AI assistant.\n"
        "Tone: warm, playful, slightly teasing, but not childish.\n"
        "Pace: medium, with natural pauses.\n"
        "Accent: neutral Brazilian Portuguese.\n"
        "Do not read these instructions aloud. Only synthesize the transcript."
    ),
    "ttsSpeed": 1.0,
    "ttsPitch": 0.0,
    "ttsVolume": 1.0,
    "ttsStability": 0.5,
    "ttsSimilarity": 0.75,
    "ttsStyle": 0.0,
    "ttsSpeakerBoost": True,
    "ttsMaxChars": 350,
    "inputDeviceId": "",
    "inputDeviceLabel": "",
    "inputDeviceSource": "sounddevice",
    # Segunda saída de áudio (espelho): além do alto-falante do PC, manda a voz da Hana
    # para um device extra (ex.: CABLE Input do VB-Audio Virtual Cable) para rotear no
    # Discord/VTube. Liga/desliga sob demanda; quando off, nada muda.
    "secondOutputEnabled": False,
    "secondOutputDeviceId": "",
    "secondOutputDeviceLabel": "",
    "vadThreshold": 0.035,
    "vadMode": "silero",
    "vadProbThreshold": 0.5,
    "bargeInEnabled": False,
    "silenceTimeoutMs": 900,
    "speakTerminalEvents": True,
    "callMode": False,
}

DEFAULT_CONNECTIONS: dict[str, Any] = {
    "tts": False,
    "stt": False,
    "vad": True,
    "ptt": False,
    "pttKey": "F2",
    "stopHotkey": True,
    "stopKey": "F4",
    "discord": False,
    "localHands": True,
    "visao": False,
}

# Catalogo unificado dos providers LLM/STT/TTS.
MODEL_CATALOG: dict[str, Any] = {
    "llmProviders": ["gemini_api", "openrouter", "groq", "deepseek", "qwen", "maritaca"],
    "imageProviders": ["gemini_api", "openrouter"],
    "models": [
        {
            "id": "gemini-3.1-pro-preview",
            "label": "Gemini 3.1 Pro Preview",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video", "pdf"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_536,
        },
        {
            "id": "gemini-3.5-flash",
            "label": "Gemini 3.5 Flash",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video", "pdf"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_536,
        },
        {
            "id": "gemini-2.5-pro",
            "label": "Gemini 2.5 Pro",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_535,
        },
        {
            "id": "gemini-3-flash-preview",
            "label": "Gemini 3 Flash Preview",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video", "pdf"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_536,
        },
        {
            "id": "gemini-2.5-flash",
            "label": "Gemini 2.5 Flash",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_535,
        },
        {
            "id": "gemini-3.1-flash-lite",
            "label": "Gemini 3.1 Flash Lite",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video", "pdf"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_535,
        },
        {
            "id": "gemini-2.5-flash-lite",
            "label": "Gemini 2.5 Flash Lite",
            "provider": "gemini_api",
            "supportsVision": True,
            "supportsNativeSearch": True,
            "inputModalities": ["text", "code", "image", "audio", "video"],
            "outputModalities": ["text"],
            "maxInputTokens": 1_048_576,
            "maxOutputTokens": 65_535,
        },
        *GROQ_STATIC_MODELS,
    ],
    "ttsProviders": ["edge", "gemini_tts", "google_cloud_tts", "azure", "cartesia", "minimax", "elevenlabs", "fishaudio"],
    "voices": [
        {"id": "pt-BR-FranciscaNeural", "label": "Edge Francisca", "provider": "edge"},
        {"id": "pt-BR-AntonioNeural", "label": "Edge Antonio", "provider": "edge"},
        {"id": "pt-BR-ThalitaNeural", "label": "Edge Thalita", "provider": "edge"},
        {"id": "ja-JP-NanamiNeural", "label": "Edge Nanami (ja-JP - sotaque japones)", "provider": "edge"},
        {"id": "ja-JP-AoiNeural", "label": "Edge Aoi (ja-JP - sotaque japones)", "provider": "edge"},
        {"id": "ja-JP-MayuNeural", "label": "Edge Mayu (ja-JP - sotaque japones)", "provider": "edge"},
        {"id": "ja-JP-ShioriNeural", "label": "Edge Shiori (ja-JP - sotaque japones)", "provider": "edge"},
        {"id": "pt-BR-Neural2-C", "label": "Google Cloud Neural2 C", "provider": "google_cloud_tts"},
        {"id": "pt-BR-Neural2-A", "label": "Google Cloud Neural2 A", "provider": "google_cloud_tts"},
        {"id": "pt-BR-Wavenet-A", "label": "Google Cloud Wavenet A", "provider": "google_cloud_tts"},
        {"id": "pt-BR-Standard-A", "label": "Google Cloud Standard A", "provider": "google_cloud_tts"},
        {"id": "700d1ee3-a641-4018-ba6e-899dcadc9e2b", "label": "Cartesia Luana (pt-BR female - public speaker, native Brazilian)", "provider": "cartesia"},
        {"id": "1cf751f6-8749-43ab-98bd-230dd633abdb", "label": "Cartesia Ana Paula (pt-BR female - marketer, native Brazilian)", "provider": "cartesia"},
        {"id": "d4b44b9a-82bc-4b65-b456-763fce4c52f9", "label": "Cartesia Beatriz (pt-BR female - support guide, native Brazilian)", "provider": "cartesia"},
        {"id": "c9611be8-aae9-4a93-bb1c-98dd6b7d52a4", "label": "Cartesia Isabella (pt-BR female - warm storyteller, native Brazilian)", "provider": "cartesia"},
        {"id": "f39bf583-3b3d-402f-9ffb-6179d9ec3e35", "label": "Cartesia Isabel (pt-BR female - confident woman, native Brazilian)", "provider": "cartesia"},
        {"id": "8d826d43-20ad-4c56-8d37-1048eccca1bf", "label": "Cartesia Larissa (pt-BR female - bright companion, native Brazilian)", "provider": "cartesia"},
        {"id": "2f4d204f-a5dc-4196-81bc-155986b76ab6", "label": "Cartesia Mirella (pt-BR female upbeat - native Brazilian)", "provider": "cartesia"},
        {"id": "pt-BR-FranciscaNeural", "label": "Azure Francisca (pt-BR female - excellent native Brazilian)", "provider": "azure"},
        {"id": "pt-BR-ThalitaNeural", "label": "Azure Thalita (pt-BR female - warm native Brazilian)", "provider": "azure"},
        {"id": "Portuguese_ConfidentWoman", "label": "Minimax Portuguese Confident Woman (pt-BR female)", "provider": "minimax"},
        {"id": DEFAULT_ELEVENLABS_VOICE, "label": "ElevenLabs documented sample voice", "provider": "elevenlabs"},
        {"id": "", "label": "Fish Audio voz padrao (sem reference_id)", "provider": "fishaudio"},
        {"id": "Portuguese_LovelyLady", "label": "Minimax Portuguese Lovely Lady (pt-BR female)", "provider": "minimax"},
        {"id": "Portuguese_PlayfulGirl", "label": "Minimax Portuguese Playful Girl (pt-BR female)", "provider": "minimax"},
        {"id": "Kore", "label": "Gemini Kore", "provider": "gemini_tts"},
        {"id": "Puck", "label": "Gemini Puck", "provider": "gemini_tts"},
        {"id": "Charon", "label": "Gemini Charon", "provider": "gemini_tts"},
        {"id": "Fenrir", "label": "Gemini Fenrir", "provider": "gemini_tts"},
        {"id": "Orus", "label": "Gemini Orus", "provider": "gemini_tts"},
        {"id": "Aoede", "label": "Gemini Aoede", "provider": "gemini_tts"},
        {"id": "Autonoe", "label": "Gemini Autonoe", "provider": "gemini_tts"},
        {"id": "Sulafat", "label": "Gemini Sulafat", "provider": "gemini_tts"},
        {"id": "Zephyr", "label": "Gemini Zephyr", "provider": "gemini_tts"},
        {"id": "Leda", "label": "Gemini Leda", "provider": "gemini_tts"},
        {"id": "Callirrhoe", "label": "Gemini Callirrhoe", "provider": "gemini_tts"},
        {"id": "Enceladus", "label": "Gemini Enceladus", "provider": "gemini_tts"},
        {"id": "Iapetus", "label": "Gemini Iapetus", "provider": "gemini_tts"},
        {"id": "Umbriel", "label": "Gemini Umbriel", "provider": "gemini_tts"},
        {"id": "Algieba", "label": "Gemini Algieba", "provider": "gemini_tts"},
        {"id": "Despina", "label": "Gemini Despina", "provider": "gemini_tts"},
        {"id": "Erinome", "label": "Gemini Erinome", "provider": "gemini_tts"},
        {"id": "Algenib", "label": "Gemini Algenib", "provider": "gemini_tts"},
        {"id": "Rasalgethi", "label": "Gemini Rasalgethi", "provider": "gemini_tts"},
        {"id": "Laomedeia", "label": "Gemini Laomedeia", "provider": "gemini_tts"},
        {"id": "Achernar", "label": "Gemini Achernar", "provider": "gemini_tts"},
        {"id": "Alnilam", "label": "Gemini Alnilam", "provider": "gemini_tts"},
        {"id": "Schedar", "label": "Gemini Schedar", "provider": "gemini_tts"},
        {"id": "Gacrux", "label": "Gemini Gacrux", "provider": "gemini_tts"},
        {"id": "Pulcherrima", "label": "Gemini Pulcherrima", "provider": "gemini_tts"},
        {"id": "Achird", "label": "Gemini Achird", "provider": "gemini_tts"},
        {"id": "Zubenelgenubi", "label": "Gemini Zubenelgenubi", "provider": "gemini_tts"},
        {"id": "Vindemiatrix", "label": "Gemini Vindemiatrix", "provider": "gemini_tts"},
        {"id": "Sadachbia", "label": "Gemini Sadachbia", "provider": "gemini_tts"},
        {"id": "Sadaltager", "label": "Gemini Sadaltager", "provider": "gemini_tts"},
    ],
}

VOICE_PROVIDER_CATALOG: dict[str, Any] = {
    "sttProviders": [
        {
            "id": "groq_whisper",
            "label": "Groq Whisper",
            "status": "active",
            "requiresCredentials": True,
            "inputModalities": ["audio"],
            "outputModalities": ["text"],
            "models": ["whisper-large-v3", "whisper-large-v3-turbo"],
            "defaultModel": "whisper-large-v3",
            "latencyProfile": "low",
        },
        {
            "id": "gemini_audio",
            "label": "Gemini Audio STT",
            "status": "planned",
            "requiresCredentials": True,
            "inputModalities": ["audio"],
            "outputModalities": ["text"],
        },
        {
            "id": "openai",
            "label": "OpenAI STT",
            "status": "planned",
            "requiresCredentials": True,
            "inputModalities": ["audio"],
            "outputModalities": ["text"],
        },
        {
            "id": "local",
            "label": "Local STT",
            "status": "planned",
            "requiresCredentials": False,
            "inputModalities": ["audio"],
            "outputModalities": ["text"],
        },
    ],
    "ttsProviders": [
        {
            "id": "edge",
            "label": "Edge TTS",
            "status": "active",
            "requiresCredentials": False,
            "inputModalities": ["text"],
            "outputModalities": ["audio"],
            "voices": [
                {"id": "pt-BR-FranciscaNeural", "label": "Francisca Neural", "locale": "pt-BR"},
                {"id": "pt-BR-AntonioNeural", "label": "Antonio Neural", "locale": "pt-BR"},
                {"id": "pt-BR-ThalitaNeural", "label": "Thalita Neural", "locale": "pt-BR"},
                {"id": "pt-PT-RaquelNeural", "label": "Raquel Neural", "locale": "pt-PT"},
                {"id": "pt-PT-DuarteNeural", "label": "Duarte Neural", "locale": "pt-PT"},
                {"id": "ja-JP-NanamiNeural", "label": "Nanami (sotaque japones)", "locale": "ja-JP"},
                {"id": "ja-JP-AoiNeural", "label": "Aoi (sotaque japones)", "locale": "ja-JP"},
                {"id": "ja-JP-MayuNeural", "label": "Mayu (sotaque japones)", "locale": "ja-JP"},
                {"id": "ja-JP-ShioriNeural", "label": "Shiori (sotaque japones)", "locale": "ja-JP"},
            ],
            "defaultVoice": "pt-BR-FranciscaNeural",
            "supportsRate": True,
            "supportsPitch": True,
        },
        {
            "id": "gemini_tts",
            "label": "Gemini API TTS",
            "status": "active",
            "requiresCredentials": True,
            "inputModalities": ["text"],
            "outputModalities": ["audio"],
            "models": ["gemini-3.1-flash-tts-preview"],
            "defaultModel": "gemini-3.1-flash-tts-preview",
            "voices": [
                {"id": "Zephyr", "label": "Zephyr - bright", "locale": "pt-BR"},
                {"id": "Puck", "label": "Puck - upbeat", "locale": "pt-BR"},
                {"id": "Charon", "label": "Charon - informative", "locale": "pt-BR"},
                {"id": "Kore", "label": "Kore - firm", "locale": "pt-BR"},
                {"id": "Fenrir", "label": "Fenrir - excitable", "locale": "pt-BR"},
                {"id": "Leda", "label": "Leda - youthful", "locale": "pt-BR"},
                {"id": "Orus", "label": "Orus - firm", "locale": "pt-BR"},
                {"id": "Aoede", "label": "Aoede - breezy", "locale": "pt-BR"},
                {"id": "Callirrhoe", "label": "Callirrhoe - easy-going", "locale": "pt-BR"},
                {"id": "Autonoe", "label": "Autonoe - bright", "locale": "pt-BR"},
                {"id": "Enceladus", "label": "Enceladus - breathy", "locale": "pt-BR"},
                {"id": "Iapetus", "label": "Iapetus - clear", "locale": "pt-BR"},
                {"id": "Umbriel", "label": "Umbriel - easy-going", "locale": "pt-BR"},
                {"id": "Algieba", "label": "Algieba - smooth", "locale": "pt-BR"},
                {"id": "Despina", "label": "Despina - smooth", "locale": "pt-BR"},
                {"id": "Erinome", "label": "Erinome - clear", "locale": "pt-BR"},
                {"id": "Algenib", "label": "Algenib - gravelly", "locale": "pt-BR"},
                {"id": "Rasalgethi", "label": "Rasalgethi - informative", "locale": "pt-BR"},
                {"id": "Laomedeia", "label": "Laomedeia - upbeat", "locale": "pt-BR"},
                {"id": "Achernar", "label": "Achernar - soft", "locale": "pt-BR"},
                {"id": "Alnilam", "label": "Alnilam - firm", "locale": "pt-BR"},
                {"id": "Schedar", "label": "Schedar - even", "locale": "pt-BR"},
                {"id": "Gacrux", "label": "Gacrux - mature", "locale": "pt-BR"},
                {"id": "Pulcherrima", "label": "Pulcherrima - forward", "locale": "pt-BR"},
                {"id": "Achird", "label": "Achird - friendly", "locale": "pt-BR"},
                {"id": "Zubenelgenubi", "label": "Zubenelgenubi - casual", "locale": "pt-BR"},
                {"id": "Vindemiatrix", "label": "Vindemiatrix - gentle", "locale": "pt-BR"},
                {"id": "Sadachbia", "label": "Sadachbia - lively", "locale": "pt-BR"},
                {"id": "Sadaltager", "label": "Sadaltager - knowledgeable", "locale": "pt-BR"},
                {"id": "Sulafat", "label": "Sulafat - warm", "locale": "pt-BR"},
            ],
            "defaultVoice": "Kore",
            "supportsRate": False,
            "supportsPitch": False,
            "supportsStylePrompt": True,
        },
        {
            "id": "google_cloud_tts",
            "label": "Google Cloud TTS",
            "status": "active",
            "requiresCredentials": True,
            "inputModalities": ["text"],
            "outputModalities": ["audio"],
            "voices": [
                {"id": "pt-BR-Neural2-C", "label": "Neural2 C", "locale": "pt-BR"},
                {"id": "pt-BR-Neural2-A", "label": "Neural2 A", "locale": "pt-BR"},
                {"id": "pt-BR-Wavenet-A", "label": "Wavenet A", "locale": "pt-BR"},
                {"id": "pt-BR-Standard-A", "label": "Standard A", "locale": "pt-BR"},
            ],
            "defaultVoice": "pt-BR-Neural2-C",
            "supportsRate": True,
            "supportsPitch": True,
            "supportsStreaming": True,
        },
        {
            "id": "cartesia",
            "label": "Cartesia (Sonic)",
            "status": "active",
            "requiresCredentials": True,
            "inputModalities": ["text"],
            "outputModalities": ["audio"],
            "models": ["sonic-3.5", "sonic-3.5-2026-05-04", "sonic-latest"],
            "defaultModel": "sonic-3.5",
            "voices": [
                # Real native Brazilian Portuguese (pt-BR) female voice IDs (authentic accent, good prosody).
                # Source: Cartesia catalog (filter Language=Portuguese (Brazil) + Female in playground).
                # Use language="pt" + sonic-3.5 for best native results. More voices available in playground.
                {"id": "700d1ee3-a641-4018-ba6e-899dcadc9e2b", "label": "Luana (pt-BR female public speaker - native Brazilian, clear & pleasant)", "locale": "pt-BR"},
                {"id": "1cf751f6-8749-43ab-98bd-230dd633abdb", "label": "Ana Paula (pt-BR female marketer - native Brazilian, warm & friendly)", "locale": "pt-BR"},
                {"id": "d4b44b9a-82bc-4b65-b456-763fce4c52f9", "label": "Beatriz (pt-BR female support guide - native Brazilian, natural conversation)", "locale": "pt-BR"},
                {"id": "c9611be8-aae9-4a93-bb1c-98dd6b7d52a4", "label": "Isabella (pt-BR female warm storyteller - native Brazilian, expressive narrative)", "locale": "pt-BR"},
                {"id": "f39bf583-3b3d-402f-9ffb-6179d9ec3e35", "label": "Isabel (pt-BR female confident woman - native Brazilian)", "locale": "pt-BR"},
                {"id": "8d826d43-20ad-4c56-8d37-1048eccca1bf", "label": "Larissa (pt-BR female bright companion - native Brazilian)", "locale": "pt-BR"},
                {"id": "2f4d204f-a5dc-4196-81bc-155986b76ab6", "label": "Mirella (pt-BR female upbeat speaker - native Brazilian)", "locale": "pt-BR"},
            ],
            "defaultVoice": "700d1ee3-a641-4018-ba6e-899dcadc9e2b",
            "supportsRate": True,
            "supportsPitch": False,
            "supportsStreaming": True,  # via SSE/WS in future; bytes endpoint now
        },
        {
            "id": "azure",
            "label": "Azure Neural TTS",
            "status": "active",
            "requiresCredentials": True,
            "inputModalities": ["text"],
            "outputModalities": ["audio"],
            "voices": [
                {"id": "pt-BR-FranciscaNeural", "label": "Francisca (pt-BR female, very natural Brazilian)", "locale": "pt-BR"},
                {"id": "pt-BR-ThalitaNeural", "label": "Thalita (pt-BR female, warm & clear Brazilian)", "locale": "pt-BR"},
                {"id": "pt-BR-AntonioNeural", "label": "Antonio (pt-BR male, for reference)", "locale": "pt-BR"},
            ],
            "defaultVoice": "pt-BR-FranciscaNeural",
            "supportsRate": True,
            "supportsPitch": True,
        },
    {
        "id": "minimax",
        "label": "Minimax TTS (T2A)",
        "status": "active",
        "requiresCredentials": True,
        "inputModalities": ["text"],
        "outputModalities": ["audio"],
        "models": ["speech-2.8-turbo", "speech-2.8-hd", "speech-2.6-turbo", "speech-2.6-hd"],
        "defaultModel": "speech-2.8-turbo",
        "voices": [
            # Many Portuguese female voices. Browse https://www.minimax.io/audio/voices or platform console.
            # Use with language_boost="Portuguese" for best pt-BR results.
            # Examples (native-sounding Brazilian Portuguese females):
            {"id": "Portuguese_ConfidentWoman", "label": "Portuguese Confident Woman (pt-BR female)", "locale": "pt-BR"},
            {"id": "Portuguese_SentimentalLady", "label": "Portuguese Sentimental Lady (pt-BR female)", "locale": "pt-BR"},
            {"id": "Portuguese_Wiselady", "label": "Portuguese Wise Lady (pt-BR female)", "locale": "pt-BR"},
            {"id": "Portuguese_PlayfulGirl", "label": "Portuguese Playful Girl (pt-BR female)", "locale": "pt-BR"},
            {"id": "Portuguese_LovelyLady", "label": "Portuguese Lovely Lady (pt-BR female)", "locale": "pt-BR"},
            {"id": "Portuguese_CharmingLady", "label": "Portuguese Charming Lady (pt-BR female)", "locale": "pt-BR"},
        ],
        "defaultVoice": "Portuguese_ConfidentWoman",
        "supportsRate": True,
        "supportsPitch": True,
    },
    {
        "id": "elevenlabs",
        "label": "ElevenLabs TTS",
        "status": "active",
        "requiresCredentials": True,
        "inputModalities": ["text"],
        "outputModalities": ["audio"],
        "models": list(ELEVENLABS_TTS_MODELS),
        "defaultModel": DEFAULT_ELEVENLABS_MODEL,
        "voices": [
            {"id": DEFAULT_ELEVENLABS_VOICE, "label": "Documented sample voice", "locale": "multilingual"},
        ],
        "defaultVoice": DEFAULT_ELEVENLABS_VOICE,
        "supportsRate": True,
        "supportsPitch": False,
        "supportsStability": True,
        "supportsSimilarity": True,
        "supportsStyle": True,
        "supportsSpeakerBoost": True,
    },
    {
        "id": "fishaudio",
        "label": "Fish Audio TTS",
        "status": "active",
        "requiresCredentials": True,
        "inputModalities": ["text"],
        "outputModalities": ["audio"],
        "models": list(FISHAUDIO_TTS_MODELS),
        "defaultModel": DEFAULT_FISHAUDIO_MODEL,
        # Sem reference_id = voz padrao da Fish Audio. Cole um reference_id proprio
        # (clonagem/voz publica escolhida no site) pra trocar de voz.
        "voices": [
            {"id": "", "label": "Voz padrao (sem reference_id)", "locale": "multilingual"},
        ],
        "defaultVoice": "",
        "supportsRate": True,
        "supportsPitch": False,
        "supportsStreaming": True,
        "notes": "s2.1-pro-free e gratuito (sem garantia de latencia); s2.1-pro/s2-pro/s1 sao pagos, mais baratos que ElevenLabs.",
    },
    ],
    "ttsReadable": {
        "displayTextMayDiffer": True,
        "sanitizesByDefault": ["markdown", "code_blocks", "links", "raw_punctuation"],
    },
}


def normalize_catalog_provider(provider: Any) -> str:
    """Normalize provider IDs stored with catalog/custom models."""
    raw = str(provider or "").strip().lower()
    aliases = {
        "google_platform": "gemini_api",
        "google_cloud": "gemini_api",
        "google": "gemini_api",
        "google_ai_studio": "gemini_api",
        "gemini": "gemini_api",
        "open_router": "openrouter",
        "openrouters": "openrouter",
        "openrouter": "openrouter",
        "groq_cloud": "groq",
        "groqcloud": "groq",
        "glock": "groq",
        "groq": "groq",
        "deepseek": "deepseek",
        "deepseek_official": "deepseek",
        "deep_seek": "deepseek",
        "qwen": "qwen",
        "alibaba": "qwen",
        "dashscope": "qwen",
        "model_studio": "qwen",
        "modelstudio": "qwen",
        "maritaca": "maritaca",
        "sabia": "maritaca",
        "sabiá": "maritaca",
    }
    normalized = aliases.get(raw, raw or "").strip().lower()
    if not normalized:
        # Smart default favoring non-Gemini providers when Gemini quota is exhausted.
        if os.environ.get("OPENROUTER_API_KEY"):
            return "openrouter"
        if os.environ.get("GROQ_API_KEY"):
            return "groq"
        if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            return "gemini_api"
        return "gemini_api"
    return normalized


def model_supports_vision(provider: Any, model_id: str, memory: MemoryStore | None = None) -> bool:
    """Return whether the given provider+model can accept image inputs (vision)."""
    p = normalize_catalog_provider(provider)
    if p == "gemini_api":
        return True
    if p not in {"openrouter", "groq", "qwen", "maritaca"}:
        return False
    mid = str(model_id or "").strip()
    if not mid:
        return False

    # Custom models (user overrides in UI) take precedence
    if memory is not None:
        try:
            customs = memory.get_setting("custom_models", []) or []
            for item in customs:
                if isinstance(item, dict) and item.get("provider") == p and item.get("id") == mid:
                    return bool(item.get("supportsVision", False))
        except Exception:
            pass

    # Dynamic catalog from the selected OpenAI-compatible provider
    try:
        if p == "openrouter":
            from hana_agent_oss.providers.provider_selector.openrouter.catalog import get_openrouter_model
            info = get_openrouter_model(mid)
        elif p == "qwen":
            from hana_agent_oss.providers.provider_selector.qwen.catalog import get_qwen_model
            info = get_qwen_model(mid)
        elif p == "maritaca":
            from hana_agent_oss.providers.provider_selector.maritaca.catalog import get_maritaca_model
            info = get_maritaca_model(mid)
        else:
            from hana_agent_oss.providers.provider_selector.groq.catalog import get_groq_model
            info = get_groq_model(mid)
        if info:
            return bool(info.get("supportsVision"))
    except Exception:
        pass

    return False


def catalog_provider_for_model(model_id: str, memory: MemoryStore | None = None) -> str:
    """Best-effort: qual provider dono deste model id? "" quando nao acha.

    Usado pra inferir o provider de visao quando so o visionModel esta setado.
    Ordem barata primeiro (custom/estaticos), OpenRouter (rede, cacheado) por ultimo.
    """
    mid = str(model_id or "").strip()
    if not mid:
        return ""
    if memory is not None:
        try:
            for item in memory.get_setting("custom_models", []) or []:
                if isinstance(item, dict) and item.get("id") == mid and item.get("provider"):
                    return normalize_catalog_provider(item.get("provider"))
        except Exception:
            pass
    # Modelos estaticos do catalogo base (Gemini/Groq embutidos).
    for item in MODEL_CATALOG.get("models", []):
        if isinstance(item, dict) and item.get("id") == mid and item.get("provider"):
            return str(item.get("provider"))
    import importlib
    for pid, module_path, fn in (
        ("qwen", "hana_agent_oss.providers.provider_selector.qwen.catalog", "get_qwen_model"),
        ("maritaca", "hana_agent_oss.providers.provider_selector.maritaca.catalog", "get_maritaca_model"),
        ("groq", "hana_agent_oss.providers.provider_selector.groq.catalog", "get_groq_model"),
        ("openrouter", "hana_agent_oss.providers.provider_selector.openrouter.catalog", "get_openrouter_model"),
    ):
        try:
            getter = getattr(importlib.import_module(module_path), fn)
            if getter(mid):
                return pid
        except Exception:
            pass
    return ""


def resolve_vision_target(llm_config: dict[str, Any] | None, memory: MemoryStore | None = None) -> tuple[str, str]:
    """(provider, model) pra rotear imagem quando o provider do chat nao ve.

    Usa visionProvider explicito; se vazio, infere o provider pelo visionModel.
    Retorna ("","") quando nao ha visionModel configurado.
    """
    cfg = llm_config if isinstance(llm_config, dict) else {}
    vm = str(cfg.get("visionModel") or "").strip()
    if not vm:
        return "", ""
    raw_vp = str(cfg.get("visionProvider") or "").strip()
    vp = normalize_catalog_provider(raw_vp) if raw_vp else catalog_provider_for_model(vm, memory)
    if not vp:
        vp = "gemini_api"  # ultimo recurso (Gemini sempre aceita imagem)
    return vp, vm


def catalog_payload(memory: MemoryStore) -> dict[str, Any]:
    data = {
        **MODEL_CATALOG,
        "llmProviders": list(MODEL_CATALOG["llmProviders"]),
        "models": list(MODEL_CATALOG["models"]),
        "voices": list(MODEL_CATALOG["voices"]),
    }
    openrouter_models, openrouter_error = get_openrouter_catalog()
    groq_models, groq_error = get_groq_catalog()
    deepseek_models, deepseek_error = get_deepseek_catalog()
    qwen_models, qwen_error = get_qwen_catalog()
    maritaca_models, maritaca_error = get_maritaca_catalog()
    data["models"].extend(openrouter_models)
    data["models"] = [
        model
        for model in data["models"]
        if not (isinstance(model, dict) and model.get("provider") == "groq")
    ]
    data["models"].extend(groq_models)
    data["models"].extend(deepseek_models)
    data["models"].extend(qwen_models)
    data["models"].extend(maritaca_models)
    # Collect image-capable models from OpenRouter for the image provider selector.
    image_models = [
        model for model in openrouter_models
        if isinstance(model, dict) and "image" in (model.get("outputModalities") or [])
    ]
    data["imageModels"] = image_models
    data["imageProviders"] = list(MODEL_CATALOG.get("imageProviders", ["gemini_api", "openrouter"]))
    data["catalogStatus"] = {
        "openrouter": {
            "ok": openrouter_error is None,
            "error": openrouter_error,
            "modelCount": len(openrouter_models),
        },
        "groq": {
            "ok": groq_error is None,
            "error": groq_error,
            "modelCount": len(groq_models),
        },
        "deepseek": {
            "ok": deepseek_error is None,
            "error": deepseek_error,
            "modelCount": len(deepseek_models),
        },
        "qwen": {
            "ok": qwen_error is None,
            "error": qwen_error,
            "modelCount": len(qwen_models),
        },
        "maritaca": {
            "ok": maritaca_error is None,
            "error": maritaca_error,
            "modelCount": len(maritaca_models),
        },
    }
    data["voiceProviders"] = VOICE_PROVIDER_CATALOG
    custom_models = memory.get_setting("custom_models", [])
    data["customModels"] = custom_models
    if isinstance(custom_models, list):
        for item in custom_models:
            if not isinstance(item, dict):
                continue
            model = dict(item)
            model["custom"] = True
            if not model.get("provider") or not model.get("id"):
                continue
            data["models"] = [
                existing
                for existing in data["models"]
                if not (existing.get("provider") == model["provider"] and existing.get("id") == model["id"])
            ]
            data["models"].append(model)
    return data


def upsert_custom_model(memory: MemoryStore, payload: dict[str, Any]) -> dict[str, Any]:
    custom = list(memory.get_setting("custom_models", []))
    provider = normalize_catalog_provider(payload.get("provider"))
    model = {
        "provider": provider,
        "id": str(payload.get("id") or ""),
        "label": str(payload.get("label") or payload.get("id") or ""),
        "supportsVision": bool(payload.get("supportsVision")),
        "supportsDocuments": bool(payload.get("supportsDocuments", False)),
        "supportsTools": bool(payload.get("supportsTools", False)),
        "supportsNativeSearch": bool(payload.get("supportsNativeSearch", provider == "gemini_api")),
        "inputModalities": payload.get("inputModalities") if isinstance(payload.get("inputModalities"), list) else ["text"],
        "outputModalities": payload.get("outputModalities") if isinstance(payload.get("outputModalities"), list) else ["text"],
        "supportedParameters": payload.get("supportedParameters") if isinstance(payload.get("supportedParameters"), list) else [],
        "maxInputTokens": int(payload.get("maxInputTokens") or 0) or None,
        "maxOutputTokens": int(payload.get("maxOutputTokens") or 0) or None,
        "custom": True,
    }
    custom = [item for item in custom if not (item.get("provider") == model["provider"] and item.get("id") == model["id"])]
    custom.append(model)
    memory.set_setting("custom_models", custom)
    return model


def delete_custom_model(memory: MemoryStore, payload: dict[str, Any]) -> bool:
    custom = list(memory.get_setting("custom_models", []))
    provider = normalize_catalog_provider(payload.get("provider"))
    model_id = str(payload.get("id") or "")
    next_items = [item for item in custom if not (item.get("provider") == provider and item.get("id") == model_id)]
    memory.set_setting("custom_models", next_items)
    return len(next_items) != len(custom)
