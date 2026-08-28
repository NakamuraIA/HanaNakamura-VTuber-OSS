from __future__ import annotations

import os
from typing import Any

from backend.catalog.repository import LlmModelRepository
from backend.catalog.tts_repository import TtsModelRepository
from backend.memory.store import MemoryStore
from backend.modules.vision.image_provider import IMPLEMENTED_IMAGE_PROVIDERS
from backend.providers.provider_aliases import PROVIDER_ALIASES
from backend.providers.provider_selector.openrouter.catalog import get_openrouter_catalog


TTS_STREAMING_MODES = {"off", "sentences", "audio"}


def normalize_tts_streaming_mode(value: Any, *, legacy_streaming: bool = False) -> str:
    """Preserva o booleano antigo enquanto a configuração migra para três modos."""
    mode = str(value or "").strip().lower()
    if mode in TTS_STREAMING_MODES:
        return mode
    return "sentences" if legacy_streaming else "off"


DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "llmProvider": "",
    "llmModel": "",
    "llmModelByProvider": {},
    "agentProvider": "",
    "agentModel": "",
    "agentModelByProvider": {},
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
    # A mesma integracao Qwen usa uma chave/endereco por regiao. Virginia preserva
    # o comportamento antigo; Singapura so entra quando a chave e o endpoint forem
    # configurados no ambiente.
    "qwenRegion": "virginia",
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
    "visionModel": "",
    "visionModelByProvider": {},
    # Provider dono do visionModel. Vazio = inferir pelo id do modelo (catalog_provider_for_model).
    # Usado pra ROTEAR imagem quando o provider do chat nao ve (reaproveita o visionModel).
    "visionProvider": "",
    "ttsProvider": "",
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
    "provider": "",
    "model": "",
    "nativeSearchMode": "auto",
    "openrouterRoutingByModel": {},
}

DEFAULT_VOICE_CONFIG: dict[str, Any] = {
    "sttProvider": "",
    "sttModel": "",
    "sttLanguage": "pt",
    "ttsProvider": "",
    "ttsModel": "",
    "ttsVoice": "",
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
    "ttsStreaming": False,
    "ttsStreamingMode": "off",
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

# Catalogo unificado — contem só dados que NAO sao modelos LLM (provedores, TTS/vozes).
# Modelos LLM agora vêm do banco (llm_models) + fetch dinamico. TTS/vozes
# vêm do banco (tts_models, ver catalog/tts_repository.py) — nao ficam mais
# hardcoded aqui, ver _tts_provider_ids()/_tts_flat_voices() mais abaixo.
MODEL_CATALOG: dict[str, Any] = {
    "llmProviders": ["gemini_api", "openrouter", "groq", "deepseek", "qwen", "maritaca"],
    "imageProviders": ["gemini_api", "openrouter"],
    "models": [],
}

VOICE_PROVIDER_CATALOG: dict[str, Any] = {
    # groq_whisper (banco) e openrouter (endpoint ao vivo) NAO ficam hardcoded
    # aqui — ver _stt_provider_catalog() logo abaixo. So os "planned" (sem
    # codigo nenhum ainda) continuam estaticos.
    "sttProviders": [
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
    # ttsProviders NAO fica hardcoded aqui — vem do banco (tts_models), ver
    # voice_provider_catalog() logo abaixo. sttProviders continua estatico
    # (fora do escopo desta migracao).
    "ttsReadable": {
        "displayTextMayDiffer": True,
        "sanitizesByDefault": ["markdown", "code_blocks", "links", "raw_punctuation"],
    },
}

# provider TTS -> a dimensao catalogavel dele e voz (Edge, que nao separa voz de
# motor) ou modelo (Fish Audio/ElevenLabs, onde a voz e um voice_id colado pelo
# usuario, nao catalogavel — ver bd/tts.py). So exibicao, nao muda capacidade.
_TTS_CATALOG_KIND: dict[str, str] = {"edge": "voices", "fishaudio": "models", "elevenlabs": "models"}
_TTS_PROVIDER_META: dict[str, dict[str, Any]] = {
    "edge": {"label": "Edge TTS", "requiresCredentials": False},
    "fishaudio": {"label": "Fish Audio TTS", "requiresCredentials": True},
    "elevenlabs": {"label": "ElevenLabs TTS", "requiresCredentials": True},
}


def _tts_provider_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa linhas de tts_models por provider no formato rico (voices/models + supportsX)."""
    rows_by_provider: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_provider.setdefault(row["provider"], []).append(row)

    providers: list[dict[str, Any]] = []
    for provider_id, provider_rows in rows_by_provider.items():
        meta = _TTS_PROVIDER_META.get(provider_id, {"label": provider_id, "requiresCredentials": True})
        entry: dict[str, Any] = {
            "id": provider_id,
            "label": meta["label"],
            "status": "active",
            "requiresCredentials": meta["requiresCredentials"],
            "inputModalities": ["text"],
            "outputModalities": ["audio"],
            "supportsRate": True,
            "supportsPitch": any(row["supportsPitch"] for row in provider_rows),
            "supportsStability": any(row["supportsStability"] for row in provider_rows),
            "supportsSimilarity": any(row["supportsSimilarity"] for row in provider_rows),
            "supportsStyle": any(row["supportsStyle"] for row in provider_rows),
            "supportsSpeakerBoost": any(row["supportsSpeakerBoost"] for row in provider_rows),
            "supportsStreaming": any(row["supportsStreaming"] for row in provider_rows),
        }
        if _TTS_CATALOG_KIND.get(provider_id) == "models":
            entry["models"] = [row["id"] for row in provider_rows]
            entry["defaultModel"] = provider_rows[0]["id"]
        else:
            entry["voices"] = [
                {"id": row["id"], "label": row["label"], "locale": row["language"]} for row in provider_rows
            ]
            entry["defaultVoice"] = provider_rows[0]["id"]
        providers.append(entry)
    providers.sort(key=lambda item: str(item["id"]))
    return providers


def _tts_flat_voices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Formato antigo e mais simples (id/label/provider), usado por /api/catalog."""
    return [{"id": row["id"], "label": row["label"], "provider": row["provider"]} for row in rows]


def _tts_provider_ids(rows: list[dict[str, Any]]) -> list[str]:
    """Lista plana de provider ids com pelo menos uma voz/modelo cadastrado."""
    return sorted({row["provider"] for row in rows})


def _stt_provider_catalog() -> list[dict[str, Any]]:
    """groq_whisper (banco) + openrouter (endpoint ao vivo) na frente; o resto
    da lista estatica (gemini_audio/openai/local — "planned", sem codigo) atras."""
    from backend.catalog.stt_repository import SttModelRepository
    from backend.providers.provider_selector.openrouter.catalog import get_openrouter_stt_catalog

    groq_rows = SttModelRepository().list_models("groq_whisper")
    groq_entry = {
        "id": "groq_whisper",
        "label": "Groq Whisper",
        "status": "active",
        "requiresCredentials": True,
        "inputModalities": ["audio"],
        "outputModalities": ["text"],
        "models": [row["id"] for row in groq_rows],
        "defaultModel": next((row["id"] for row in groq_rows), ""),
        "latencyProfile": "low",
    }

    openrouter_models, openrouter_error = get_openrouter_stt_catalog()
    openrouter_entry = {
        "id": "openrouter",
        "label": "OpenRouter STT",
        "status": "active" if openrouter_models else "degraded",
        "requiresCredentials": True,
        "inputModalities": ["audio"],
        "outputModalities": ["text"],
        "models": [model["id"] for model in openrouter_models],
        "defaultModel": "openai/whisper-1",
        "error": openrouter_error,
    }

    return [groq_entry, openrouter_entry, *VOICE_PROVIDER_CATALOG["sttProviders"]]


def voice_provider_catalog() -> dict[str, Any]:
    """sttProviders/ttsProviders lidos do banco/endpoint; ttsReadable estatico."""
    tts_rows = TtsModelRepository().list_models()
    return {
        **VOICE_PROVIDER_CATALOG,
        "sttProviders": _stt_provider_catalog(),
        "ttsProviders": _tts_provider_catalog(tts_rows),
    }


def normalize_catalog_provider(provider: Any) -> str:
    """Normalize provider IDs stored with catalog/custom models."""
    raw = str(provider or "").strip().lower()
    normalized = PROVIDER_ALIASES.get(raw, raw or "").strip().lower()
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
    mid = str(model_id or "").strip()
    if not p or not mid:
        return False

    # Capacidade pertence ao modelo. Um modelo manual local vence o catálogo
    # dinâmico; nenhum provider inteiro é marcado como multimodal por chute.
    try:
        local = LlmModelRepository().get_model(p, mid)
        if local:
            # Embedding/rerank/imagem podem declarar "vision", mas não são
            # conversa: nunca servem como alvo multimodal do chat.
            if str(local.get("modelDomain") or "chat") != "chat":
                return False
            return bool(local.get("supportsVision"))
    except Exception:
        pass

    if p == "openrouter":
        try:
            from backend.providers.provider_selector.openrouter.catalog import get_openrouter_model
            info = get_openrouter_model(mid)
            return bool(info and info.get("supportsVision"))
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
    try:
        local_provider = LlmModelRepository().find_provider_for_model(mid)
        if local_provider:
            return local_provider
    except Exception:
        pass

    import importlib
    for pid, module_path, fn in (
        ("openrouter", "backend.providers.provider_selector.openrouter.catalog", "get_openrouter_model"),
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


def _dominio_do_modelo(modelo: Any) -> str:
    """Domínio declarado do modelo; linhas sem o campo (OpenRouter dinâmico) são chat."""
    return str((modelo or {}).get("modelDomain") or "chat")


def erro_modelo_nao_conversa(provider: Any, model_id: str) -> str | None:
    """Mensagem amigável se o par (provider, modelo) existir com domínio != chat.

    Barreira central usada antes de qualquer chamada de conversa. Modelos que
    não estão no catálogo local (dinâmicos do OpenRouter, pseudo-modelos do
    Agent Core) seguem permitidos — a barreira só existe para quem DECLAROU
    um domínio especializado.
    """
    mid = str(model_id or "").strip()
    if not mid:
        return None
    try:
        local = LlmModelRepository().get_model(normalize_catalog_provider(provider), mid)
    except Exception:
        return None
    if not local:
        return None
    dominio = str(local.get("modelDomain") or "chat")
    if dominio == "chat":
        return None
    rotulos = {
        "embedding": "um modelo de embeddings",
        "rerank": "um modelo de reranking",
        "image": "um modelo de geração de imagem",
    }
    tipo = rotulos.get(dominio, "um modelo especializado")
    return (
        f"O modelo selecionado é {tipo}, não um modelo de conversa. "
        f"Escolha um modelo de chat nas configurações para eu responder normalmente."
    )


def catalog_payload() -> dict[str, Any]:
    local_models = LlmModelRepository().list_models()
    tts_rows = TtsModelRepository().list_models()

    data = {
        **MODEL_CATALOG,
        "llmProviders": list(MODEL_CATALOG["llmProviders"]),
        "models": list(local_models),
        "ttsProviders": _tts_provider_ids(tts_rows),
        "voices": _tts_flat_voices(tts_rows),
    }

    # Always fetch dynamic catalogs and status from live APIs
    openrouter_models, openrouter_error = get_openrouter_catalog()

    # Providers locais vêm todos da mesma leitura; esta divisão existe só para
    # o bloco de estado consumido pela interface.
    MIGRATED_PROVIDERS = ("qwen", "deepseek", "maritaca", "gemini_api", "groq")
    migrated_models = {
        provider_id: [model for model in local_models if model.get("provider") == provider_id]
        for provider_id in MIGRATED_PROVIDERS
    }
    migrated_errors: dict[str, str | None] = {provider_id: None for provider_id in MIGRATED_PROVIDERS}
    qwen_models, qwen_error = migrated_models["qwen"], migrated_errors["qwen"]
    deepseek_models, deepseek_error = migrated_models["deepseek"], migrated_errors["deepseek"]
    maritaca_models, maritaca_error = migrated_models["maritaca"], migrated_errors["maritaca"]
    gemini_models, gemini_error = migrated_models["gemini_api"], migrated_errors["gemini_api"]
    groq_models, groq_error = migrated_models["groq"], migrated_errors["groq"]

    # O OpenRouter continua dinâmico. Uma linha manual local com a mesma chave
    # pode complementar ou corrigir o endpoint e, por isso, vence na mesclagem.
    merged = {
        (str(model.get("provider") or ""), str(model.get("id") or "")): model
        for model in openrouter_models
        if isinstance(model, dict)
    }
    for model in local_models:
        merged[(str(model.get("provider") or ""), str(model.get("id") or ""))] = model

    # A lista de CONVERSA só expõe domínio chat. Especializados (embedding,
    # rerank, imagem) continuam no banco e em /api/modelos, mas não aparecem
    # nem são selecionáveis como LLM de chat/agente.
    data["models"] = [
        model for model in merged.values() if _dominio_do_modelo(model) == "chat"
    ]

    # Modelos de imagem: dinâmicos do OpenRouter + locais com domínio "image"
    # (linha local vence na mesclagem, mesmo critério da lista geral).
    implemented_image_providers = set(IMPLEMENTED_IMAGE_PROVIDERS)
    image_map = {
        (str(model.get("provider") or ""), str(model.get("id") or "")): model
        for model in openrouter_models
        if isinstance(model, dict)
        and str(model.get("provider") or "") in implemented_image_providers
        and "image" in (model.get("outputModalities") or [])
    }
    for model in local_models:
        if (
            _dominio_do_modelo(model) == "image"
            and str(model.get("provider") or "") in implemented_image_providers
        ):
            image_map[(str(model.get("provider") or ""), str(model.get("id") or ""))] = model
    data["imageModels"] = list(image_map.values())
    data["imageProviders"] = list(IMPLEMENTED_IMAGE_PROVIDERS)
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
        "gemini": {
            "ok": gemini_error is None,
            "error": gemini_error,
            "modelCount": len(gemini_models),
        },
    }
    data["voiceProviders"] = {**VOICE_PROVIDER_CATALOG, "ttsProviders": _tts_provider_catalog(tts_rows)}
    data["customModels"] = [model for model in local_models if model.get("custom")]
    return data


def upsert_custom_model(payload: dict[str, Any]) -> dict[str, Any]:
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
    return LlmModelRepository().save_model(model)


def delete_custom_model(payload: dict[str, Any]) -> bool:
    provider = normalize_catalog_provider(payload.get("provider"))
    model_id = str(payload.get("id") or "")
    current = LlmModelRepository().get_model(provider, model_id)
    if not current or not current.get("custom"):
        return False
    return LlmModelRepository().delete_model(provider, model_id)
