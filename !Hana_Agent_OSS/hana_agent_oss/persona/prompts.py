from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from hana_agent_oss.persona.profile import PersonaProfile, default_persona_profile


from hana_agent_oss.paths import SKILLS_DIR as DEFAULT_SKILLS_DIR, EXT_SKILLS_DIR as HANA_AGENT_SKILLS_DIR


def load_provider_skills(skills_dir: str | os.PathLike[str] | None = None) -> str:
    """Load lightweight Markdown skills that guide provider-level decisions.

    Loads from the primary skills dir (data/skills/ by default or HANA_SKILLS_DIR).
    Then, if hana_agent/skills/ exists at project root, its .md files are appended
    as extra/optional skills.
    """
    primary = Path(skills_dir or os.environ.get("HANA_SKILLS_DIR") or DEFAULT_SKILLS_DIR)

    roots: list[Path] = []
    if primary.exists() and primary.is_dir():
        roots.append(primary)

    # Optional modular extensions (hana_agent/skills). Never fails if absent.
    if HANA_AGENT_SKILLS_DIR.exists() and HANA_AGENT_SKILLS_DIR.is_dir():
        roots.append(HANA_AGENT_SKILLS_DIR)

    if not roots:
        return ""

    blocks: list[str] = []
    for root in roots:
        is_ext = root == HANA_AGENT_SKILLS_DIR
        for path in sorted(root.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not content:
                continue

            if is_ext:
                blocks.append(f"--- Skill (ext): {path.name} ---\n{content}")
            else:
                blocks.append(f"--- Skill: {path.name} ---\n{content}")

    if not blocks:
        return ""
    return "Habilidades operacionais carregadas:\n" + "\n\n".join(blocks)


def render_persona_context(profile: PersonaProfile | None = None) -> str:
    """Render identity and behavior data without provider-specific rules."""

    profile = profile or default_persona_profile()
    lines = [
        f"Nome da assistente: {profile.assistant_name}.",
        f"Projeto: {profile.project_name}.",
        f"Usuario principal: {profile.user_name}.",
        f"Idioma principal: {profile.language}.",
        f"Funcao: {profile.role}.",
    ]
    if profile.personality:
        lines.append("Personalidade: " + ", ".join(profile.personality) + ".")
    lines.extend(profile.relationship)
    lines.extend(profile.character_voice)
    if profile.conversation_style:
        lines.append("Dinamica de conversa:")
        lines.extend(profile.conversation_style)
    lines.extend(profile.behavior_rules)
    if profile.forbidden_phrases:
        lines.append("Vocabulario proibido: " + "; ".join(profile.forbidden_phrases) + ".")
    lines.extend(profile.preferences)
    lines.extend(profile.runtime_limits)
    return "\n".join(line for line in lines if line.strip())


def build_provider_system_prompt(
    provider_id: str,
    profile: PersonaProfile | None = None,
) -> str:
    """Build the system prompt consumed by an LLM provider."""

    provider = str(provider_id or "").strip() or "unknown"
    provider_rules = {
        "gemini_api": (
            "Regras do provedor Gemini API: responda em texto; use busca nativa somente quando o runtime solicitar; "
            "mantenha respostas diretas e nao invente capacidades ausentes."
        ),
        "openrouter": (
            "Regras do provedor OpenRouter: responda em texto pelo contrato Chat Completions; "
            "nao use busca nativa Gemini, Code Execution Gemini, URL Context Gemini ou ferramentas server-side do Gemini; "
            "use XML de imagem normalmente quando a Hana tiver provider de imagem ativo; "
            "use somente tools locais realmente fornecidas no turno."
        ),
        "groq": (
            "Regras do provedor Groq: responda em texto pelo contrato Chat Completions compativel com OpenAI; "
            "nao use busca nativa Gemini, Code Execution Gemini, URL Context Gemini ou ferramentas server-side do Gemini; "
            "use XML de imagem normalmente quando a Hana tiver provider de imagem ativo; "
            "modelos Compound da Groq podem usar recursos nativos da Groq quando o proprio modelo suportar; "
            "use tools locais como Omni ou MCP somente quando elas forem realmente fornecidas no turno."
        ),

    }
    sections = [
        render_persona_context(profile),
        _temporal_context(),
        load_provider_skills(),
        provider_rules.get(provider, "Regras do provedor: siga o contrato do runtime e responda somente com capacidades disponiveis."),
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _temporal_context() -> str:
    """Inject the real current date so the model stops answering from stale training data.

    The model's training knowledge is ~2 years behind. For anything that changes over
    time (AI models, prices, versions, news, dates), it must use the web search tool
    instead of guessing from memory.
    """
    today = datetime.now().strftime("%d/%m/%Y")
    return (
        "[CONTEXTO TEMPORAL]\n"
        f"Hoje e {today}. Seu conhecimento de treinamento esta defasado (vai ate ~2024). "
        "NUNCA responda fatos que mudam com o tempo (modelos de IA, precos, versoes, "
        "lancamentos, noticias, datas, 'atual/recente/hoje') a partir da memoria de "
        "treinamento: use a ferramenta de pesquisa web (Tavily via mcp_invoke) ANTES de "
        "responder. Se nao tiver certeza se algo esta atualizado, pesquise."
    )


def build_stt_prompt(profile: PersonaProfile | None = None, *, group_call: bool = False) -> str:
    """Build the transcription bias prompt used by STT providers.

    When group_call=True (virtual cable in Discord call with multiple people),
    the prompt avoids assuming the speaker is always the main user (Nakamura).
    This prevents the model from hallucinating the wrong speaker and improves
    transcription of other voices in the call.
    """

    profile = profile or default_persona_profile()
    terms = ", ".join(profile.speech_terms)

    if group_call:
        return (
            "Conversa casual em call de voz no Discord via cabo virtual. "
            "Podem ser varias pessoas falando (nao necessariamente o usuario principal). "
            f"Use grafia correta para nomes e termos comuns: {terms}. "
            "Transcreva somente fala humana clara. Ignore ruido, batidas no microfone, respiracao e silencio. "
            "Nao invente texto quando nao houver fala. "
            "Nao assuma que quem esta falando e o usuario principal da assistente."
        )

    return (
        f"Conversa casual em portugues brasileiro. O usuario se chama {profile.user_name} "
        f"e fala com a assistente {profile.assistant_name}. "
        f"Use grafia correta para nomes e termos comuns: {terms}. "
        "Transcreva somente fala humana clara. Ignore ruido, batidas no microfone, respiracao e silencio. "
        "Nao invente texto quando nao houver fala."
    )
