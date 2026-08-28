"""Mapa unico de apelidos de provider (ex.: "google_cloud" -> "gemini_api").

Cada router mantinha sua propria copia deste mapa e elas iam divergindo
quando um provider novo entrava no catalogo. Consolidado aqui para que
selector, routers e servicos normalizem do mesmo jeito.
"""

PROVIDER_ALIASES: dict[str, str] = {
    # Familia Gemini / Google
    "google_platform": "gemini_api",
    "google_cloud": "gemini_api",
    "google": "gemini_api",
    "google_ai_studio": "gemini_api",
    "gemini": "gemini_api",
    # OpenRouter
    "open_router": "openrouter",
    "openrouters": "openrouter",
    # Groq
    "groq_cloud": "groq",
    "groqcloud": "groq",
    "glock": "groq",
    # DeepSeek
    "deepseek_official": "deepseek",
    "deep_seek": "deepseek",
    # Qwen / Alibaba (DashScope)
    "alibaba": "qwen",
    "dashscope": "qwen",
    "model_studio": "qwen",
    "modelstudio": "qwen",
    # Maritaca (Sabiá)
    "sabia": "maritaca",
    "sabiá": "maritaca",
}


def normalize_provider_id(value: object) -> str:
    """Normaliza apelidos para o id canonico; vazio/desconhecido -> gemini_api."""
    raw = str(value or "").strip().lower()
    return PROVIDER_ALIASES.get(raw, raw or "gemini_api")
