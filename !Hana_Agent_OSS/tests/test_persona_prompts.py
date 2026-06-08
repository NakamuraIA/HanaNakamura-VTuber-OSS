from __future__ import annotations

from hana_agent_oss.persona import build_provider_system_prompt, build_stt_prompt, default_persona_profile


def test_provider_prompt_uses_central_persona_and_provider_rules() -> None:
    prompt = build_provider_system_prompt("gemini_api")

    assert "Nome da assistente: Hana." in prompt
    assert "Usuario principal: Nakamura." in prompt
    assert "Onee-san Hex-Mentor" in prompt
    assert "como a personagem Hana Nakamura" in prompt
    assert "sou feita de codigo e bits" in prompt
    assert "Nakamura assume o risco operacional" in prompt
    assert "autorizacao de operador" in prompt
    assert "Dinamica de conversa:" in prompt
    assert "nao como central de atendimento" in prompt
    assert "nao transforme toda fala em oferta de suporte" in prompt
    assert "nao pergunte como melhorar" in prompt
    assert "Vocabulario proibido:" in prompt
    assert "Como posso melhorar?" in prompt
    assert "O que voce precisa agora?" in prompt
    assert "Regras do provedor Gemini API:" in prompt
    assert "Nao finja ter executado ferramentas" in prompt


def test_stt_prompt_uses_central_speech_terms() -> None:
    profile = default_persona_profile()
    prompt = build_stt_prompt(profile)

    assert "usuario se chama Nakamura" in prompt
    assert "assistente Hana" in prompt
    assert "Groq" in prompt
    assert "FFmpeg" in prompt


def test_provider_prompt_loads_markdown_skills(monkeypatch, tmp_path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "omni.md").write_text("# Skill: Omni\nDelegar tarefas de PC para o Omni.", encoding="utf-8")
    monkeypatch.setenv("HANA_SKILLS_DIR", str(skills_dir))

    prompt = build_provider_system_prompt("gemini_api")

    assert "Habilidades operacionais carregadas:" in prompt
    assert "Skill: omni.md" in prompt
    assert "Delegar tarefas de PC para o Omni." in prompt


def test_provider_prompt_loads_omni_operational_skills(monkeypatch) -> None:
    monkeypatch.delenv("HANA_SKILLS_DIR", raising=False)

    prompt = build_provider_system_prompt("gemini_api")

    assert "Skill: hana_omni_supervisor.md" in prompt
    assert "Skill: omni_decision_policy.md" in prompt
    assert "Skill: omni_task_writer.md" in prompt
    assert "Skill: omni_result_review.md" in prompt
    assert "Skill: omni_project_inspection.md" in prompt
    assert "omni_supervise(task, mode, acceptance, max_rounds)" in prompt
    assert "mode=\"inspect\"" in prompt
    assert "mode=\"execute\"" in prompt
    assert "mode=\"review\"" in prompt
    assert "acceptance` e um texto simples" in prompt
    assert "nunca array/lista JSON" in prompt
    assert "ok=false" in prompt
    assert "nao invente causa" in prompt
    assert "Chat normal" in prompt
    assert "TTS, STT, voz, imagem" in prompt
    assert "sem editar nada" in prompt


def test_default_persona_keeps_visual_identities_separate_from_provider_prompt() -> None:
    profile = default_persona_profile()

    assert "Nyra" in profile.visual_identities
    assert "Hana Nakamura" in profile.visual_identities
    assert "quimono futurista" in " ".join(profile.visual_identities["Nyra"]).lower()
    assert "open source AI VTuber" in " ".join(profile.visual_identities["Hana Nakamura"])
