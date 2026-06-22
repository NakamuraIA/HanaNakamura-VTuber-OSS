from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from hana_agent_oss.persona.profile import PersonaProfile, default_persona_profile


from hana_agent_oss.paths import (
    SKILLS_DIR as DEFAULT_SKILLS_DIR,
    EXT_SKILLS_DIR as HANA_AGENT_SKILLS_DIR,
    SCRIPTS_DIR,
)


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

    # Lazy skills: inject only an INDEX (name + one-line title), not the full body.
    # The full manual is read on demand via the skill.read tool. This keeps the
    # system prompt flat as skills grow (each new skill no longer taxes every turn).
    index_lines: list[str] = []
    for root in roots:
        is_ext = root == HANA_AGENT_SKILLS_DIR
        for path in sorted(root.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not content:
                continue
            # First non-empty line as the title (strip leading markdown '#').
            title = ""
            for line in content.splitlines():
                line = line.strip().lstrip("#").strip()
                if line:
                    title = line
                    break
            name = path.stem
            tag = " (ext)" if is_ext else ""
            index_lines.append(f"- {name}{tag}: {title[:120]}" if title else f"- {name}{tag}")

    location = (
        "[SUAS SKILLS E SCRIPTS]\n"
        f"Skills (manuais .md) ficam SOMENTE em: {DEFAULT_SKILLS_DIR}\n"
        f"Scripts (codigo executavel) ficam SOMENTE em: {SCRIPTS_DIR}\n"
        "Skill = o manual (quando/como fazer, pegadinhas). Script = o codigo que "
        "realmente executa. Quando uma tarefa envolve codigo reutilizavel (baixar, "
        "converter, automatizar), crie um SCRIPT com a ferramenta script.create e rode "
        "com terminal.run (ex.: 'python data/scripts/<nome>.py'), em vez de remontar o "
        "comando toda vez. A SKILL correspondente deve APONTAR para esse script. "
        "Para criar skill use skill.create; para criar script use script.create — ambas "
        "gravam na pasta certa sozinhas. NUNCA crie skill ou script com file.write num "
        "caminho adivinhado: outras pastas '.agent/skills' ou de scripts no PC pertencem "
        "a OUTROS bots, nao a voce. Para anotar dicas numa skill existente use skill.note."
    )
    if not index_lines:
        return location
    return (
        location
        + "\n\nSKILLS DISPONIVEIS (so o indice; leia a completa com a tool skill.read "
        "ANTES de executar a tarefa correspondente):\n"
        + "\n".join(index_lines)
    )


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
            "use tools locais (terminal/arquivos) ou MCP somente quando elas forem realmente fornecidas no turno."
        ),

    }
    sections = [
        render_persona_context(profile),
        _output_rules(),
        _temporal_context(),
        load_provider_skills(),
        provider_rules.get(provider, "Regras do provedor: siga o contrato do runtime e responda somente com capacidades disponiveis."),
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _output_rules() -> str:
    """Hard output guardrails for reasoning models (anti CoT-leak + language lock).

    Reasoning models (qwen3, gpt-oss) tend to dump their raw chain-of-thought in
    English ("The user wants me to...") as the answer. The backend already requests
    reasoning_format=parsed on Groq, but this is the prompt-level belt-and-suspenders.
    """
    return (
        "[REGRA DE SAIDA - OBRIGATORIA]\n"
        "Responda SEMPRE em portugues do Brasil (pt-BR), nunca em ingles, salvo se a "
        "Operador pedir explicitamente outro idioma.\n"
        "NUNCA mostre seu raciocinio interno, analise passo-a-passo, 'Thinking Process', "
        "'The user wants', planejamento de qual ferramenta usar, ou monologo de decisao. "
        "Isso fica no seu pensamento, NAO na resposta. Entregue SOMENTE a resposta final, "
        "curta e direta, ja decidida. Se precisar usar ferramenta, chame a ferramenta — "
        "nao narre o que voce esta pensando em fazer."
    )


def _temporal_context() -> str:
    """Inject the real current date so the model stops answering from stale training data.

    The model's training knowledge is ~2 years behind. For anything that changes over
    time (AI models, prices, versions, news, dates), it must use the web search tool
    instead of guessing from memory.
    """
    agora = datetime.now()
    dias = ("segunda-feira", "terca-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sabado", "domingo")
    dia_semana = dias[agora.weekday()]
    today = agora.strftime("%d/%m/%Y")
    hora = agora.strftime("%H:%M")
    return (
        "[CONTEXTO TEMPORAL]\n"
        f"AGORA, NESTE EXATO MOMENTO, sao {hora} de {dia_semana}, {today} (horario local do PC da Operador). "
        "Voce SEMPRE recebe a data e a hora atuais aqui em todo turno — entao NUNCA rode "
        "comando no terminal (Get-Date, time /t) so pra saber a hora, e NUNCA chute: use este valor. "
        f"RACIOCINIO TEMPORAL: para decidir se um evento JA aconteceu, ainda vai acontecer ou esta "
        f"acontecendo, COMPARE o horario do evento com {hora} de hoje. Se o evento e mais tarde que "
        f"{hora}, ele AINDA NAO aconteceu — nao diga que 'ja acabou'. Nunca assuma passado/futuro sem "
        "comparar com a hora atual acima. "
        f"Seu conhecimento de treinamento esta defasado (vai ate ~2024). "
        "NUNCA responda fatos que mudam com o tempo (modelos de IA, precos, versoes, "
        "lancamentos, noticias, datas, 'atual/recente/hoje') a partir da memoria de "
        "treinamento: use a ferramenta de pesquisa web (Tavily via mcp_invoke) ANTES de "
        "responder. Se nao tiver certeza se algo esta atualizado, pesquise."
    )


def build_stt_prompt(profile: PersonaProfile | None = None, *, group_call: bool = False) -> str:
    """Build the transcription bias prompt used by STT providers.

    When group_call=True (virtual cable in Discord call with multiple people),
    the prompt avoids assuming the speaker is always the main user (Operador).
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
