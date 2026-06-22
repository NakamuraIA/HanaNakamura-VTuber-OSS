from __future__ import annotations

from hana_agent_oss.persona import build_provider_system_prompt, build_stt_prompt, default_persona_profile


def test_provider_prompt_uses_central_persona_and_provider_rules() -> None:
    prompt = build_provider_system_prompt("gemini_api")

    assert "Nome da assistente: Hana." in prompt
    assert "Usuario principal: Operador." in prompt
    assert "Assistente de IA local com personalidade" in prompt
    assert "Dinamica de conversa:" in prompt
    assert "nao como central de atendimento" in prompt
    assert "Vocabulario proibido:" in prompt
    assert "Qual e a meta de hoje?" in prompt
    assert "Regras do provedor Gemini API:" in prompt
    assert "Nao finja ter executado ferramentas" in prompt


def test_stt_prompt_uses_central_speech_terms() -> None:
    profile = default_persona_profile()
    prompt = build_stt_prompt(profile)

    assert "usuario se chama Operador" in prompt
    assert "assistente Hana" in prompt
    assert "Groq" in prompt
    assert "Tavily" in prompt


def test_provider_prompt_loads_markdown_skills(monkeypatch, tmp_path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "exemplo.md").write_text("# Skill: Exemplo\nConteudo de exemplo de skill.", encoding="utf-8")
    monkeypatch.setenv("HANA_SKILLS_DIR", str(skills_dir))

    prompt = build_provider_system_prompt("gemini_api")

    # Lazy skills: only the index (name + title) is injected; the full body is read
    # on demand via skill.read, so the heavy content must NOT be in the prompt.
    assert "SKILLS DISPONIVEIS" in prompt
    assert "exemplo" in prompt
    assert "Skill: Exemplo" in prompt  # the title line survives in the index
    assert "Conteudo de exemplo de skill." not in prompt  # the body does not


def test_default_persona_has_generic_visual_identity() -> None:
    profile = default_persona_profile()

    # The OSS build ships a single generic "Hana" visual identity placeholder; users add
    # their own characters. Visual identities are kept out of the text system prompt.
    assert "Hana" in profile.visual_identities
    assert profile.visual_identities  # non-empty
