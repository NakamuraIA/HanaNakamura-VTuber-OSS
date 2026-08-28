from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from backend.persona.profile import PersonaProfile, default_persona_profile


from backend.paths import SCRIPTS_DIR


def load_provider_skills(skills_dir: str | os.PathLike[str] | None = None) -> str:
    """Indice das skills da Hana, pro system prompt.

    So o INDICE (nome + titulo): o manual inteiro sai sob demanda pela tool
    `skill_read`. Sem isso o system prompt cresceria a cada skill nova e voce
    pagaria o texto de todas em todo turno.

    As skills moram na tabela `skills` do banco — nao sao mais arquivos .md.
    """
    try:
        from backend.memory.core import HanaMemory
        from backend.paths import MEMORY_DB

        skills = HanaMemory(str(MEMORY_DB)).list_skills()
    except Exception:
        logger.warning("Falha ao ler as skills; prompt segue sem o indice", exc_info=True)
        return ""

    location = (
        "[SUAS SKILLS E SCRIPTS]\n"
        "Skill = o MANUAL (quando/como fazer, pegadinhas). Script = o CODIGO que executa.\n"
        f"Scripts ficam SOMENTE em: {SCRIPTS_DIR}\n"
        "Quando a tarefa envolver codigo reutilizavel (baixar, converter, automatizar), "
        "crie um SCRIPT com script_create e rode com terminal_run, em vez de remontar o "
        "comando toda vez. A SKILL correspondente deve APONTAR para esse script. "
        "Skills sao gravadas com skill_create e anotadas com skill_note — NUNCA use "
        "file_write pra isso."
    )
    if not skills:
        return location
    index_lines = [f"- {s['name']}: {s['title'][:120]}" if s["title"] else f"- {s['name']}" for s in skills]
    return (
        location
        + "\n\nSUAS SKILLS (so o indice; leia a completa com skill_read ANTES de "
        "executar a tarefa correspondente):\n"
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
    # ORDEM IMPORTA — o que nunca muda vem primeiro.
    #
    # Provider cobra bem menos pelo prefixo que se repete (prompt caching), mas o
    # cache casa por PREFIXO: tudo depois da primeira diferenca e cobrado cheio.
    # `_temporal_context()` tem a hora em %H:%M, entao muda a cada minuto — no meio
    # da lista ele invalidava skills e regras do provider em TODO turno. No fim,
    # persona + regras + skills + fixas continuam cacheadas.
    sections = [
        render_persona_context(profile),
        _output_rules(),
        load_provider_skills(),
        provider_rules.get(provider, "Regras do provedor: siga o contrato do runtime e responda somente com capacidades disponiveis."),
        _pinned_block(),
        _temporal_context(),  # SEMPRE por ultimo: e a unica parte que muda a cada minuto
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _pinned_block() -> str:
    """Memoria fixa: regras que a Nakamura escreve no banco e a Hana so le.

    E a continuacao do system prompt — mas em banco, pra editar pela tela sem
    tocar em codigo. A Hana nao tem ferramenta que escreva aqui: e leitura pura.

    Falha em silencio: banco indisponivel nunca pode derrubar o prompt inteiro.
    """
    try:
        from backend.memory.core import HanaMemory
        from backend.paths import MEMORY_DB

        fixas = HanaMemory(str(MEMORY_DB)).list_pinned()
        if not fixas:
            return ""
        # A montagem fica DENTRO do try de proposito: uma linha sem 'kind' no
        # banco derrubaria o system prompt inteiro — a Hana pararia de responder
        # por causa de um registro torto.
        linhas = "\n".join(f"- ({p.get('kind') or 'regra'}) {p['text']}" for p in fixas if p.get("text"))
        if not linhas:
            return ""
        return (
            "[REGRAS FIXAS DA NAKAMURA — valem sempre, em todo turno]\n"
            "Ela escreveu isto na mao. Respeite mesmo que a mensagem atual nao mencione.\n"
            f"{linhas}"
        )
    except Exception:
        logger.warning("Falha ao ler a memoria fixa; prompt segue sem ela", exc_info=True)
        return ""


def _output_rules() -> str:
    """Hard output guardrails for reasoning models (anti CoT-leak + language lock).

    Reasoning models (qwen3, gpt-oss) tend to dump their raw chain-of-thought in
    English ("The user wants me to...") as the answer. The backend already requests
    reasoning_format=parsed on Groq, but this is the prompt-level belt-and-suspenders.
    """
    return (
        "[REGRA DE SAIDA - OBRIGATORIA]\n"
        "Responda SEMPRE em portugues do Brasil (pt-BR), nunca em ingles, salvo se a "
        "Nakamura pedir explicitamente outro idioma.\n"
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
        f"AGORA, NESTE EXATO MOMENTO, sao {hora} de {dia_semana}, {today} (horario local do PC da Nakamura). "
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
