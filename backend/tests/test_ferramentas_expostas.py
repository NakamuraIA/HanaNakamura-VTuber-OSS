"""Trava o bug das "ferramentas fantasma".

O system prompt mandava a Hana usar skill_read, skill_create, skill_note,
script_create, memory_audit e memory_compact. Nenhuma das seis chegava na LLM —
elas existiam so no registry interno do backend. Ela via o indice das skills e
nao conseguia abrir nenhuma; tudo que a Nakamura escreveu ali era decorativo.

Nao da erro em lugar nenhum: a Hana simplesmente responde sem usar, ou inventa
que usou. Por isso precisa de teste.

Roda com:  python -m backend.tests.test_ferramentas_expostas
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.persona.prompts import build_provider_system_prompt

TOOLS_PACKAGE = Path("backend/providers/provider_selector/openai_compatible")


def _builder_source() -> str:
    """Código dos registradores por domínio que formam o builder agregado."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TOOLS_PACKAGE.glob("*.py"))
    )


def _expostas() -> set[str]:
    """Nomes que o builder declara pra LLM (function calling)."""
    return set(re.findall(r"_fn\(\s*\n?\s*\"([a-zA-Z0-9_.]+)\"", _builder_source()))


def _runners() -> set[str]:
    """Nomes que o builder sabe EXECUTAR quando a LLM chama."""
    return set(re.findall(r'runners\[\s*"([a-zA-Z0-9_.]+)"\s*\]', _builder_source()))


def test_prompt_nao_promete_ferramenta_que_nao_existe() -> None:
    prompt = build_provider_system_prompt("deepseek")
    citadas = set(re.findall(r"\b((?:file|memory|script|skill|terminal|reminder)[._][a-z_]+)\b", prompt))
    expostas = _expostas()
    fantasma = sorted(c for c in citadas if c.replace(".", "_") not in expostas)
    assert not fantasma, (
        f"o prompt manda usar {fantasma}, mas a LLM nao recebe essas ferramentas — "
        "ou exponha no tools_builder, ou tire do prompt"
    )


def test_toda_ferramenta_declarada_tem_quem_execute() -> None:
    # Declarar sem runner e pior que nao declarar: a LLM chama, o sistema nao
    # sabe rodar, e o turno morre num erro generico.
    expostas, runners = _expostas(), _runners()
    # MCP entra dinamico (nome montado em runtime), fica de fora da checagem.
    sem_runner = sorted(n for n in expostas if n not in runners and not n.startswith("mcp"))
    assert not sem_runner, f"declaradas sem runner: {sem_runner}"


def test_skills_e_scripts_chegam_na_llm() -> None:
    # As seis do incidente + as vizinhas que vieram junto.
    esperadas = {
        "skill_list", "skill_read", "skill_create", "skill_note",
        "script_create", "script_list", "script_read",
        "memory_audit", "memory_compact",
    }
    faltando = sorted(esperadas - _expostas())
    assert not faltando, f"voltaram a sumir da LLM: {faltando}"


def test_skill_read_devolve_o_manual_inteiro() -> None:
    # O indice no prompt so tem o titulo. Se o read parar de funcionar, a Hana
    # fica sabendo que a skill existe e nao consegue seguir os passos.
    from backend.tools.skill_tools import list_skills, read_skill

    skills = list_skills()
    if not skills:
        return  # banco novo, sem skills — nada a checar
    r = read_skill(skills[0]["name"])
    assert r["ok"] and len(r["content"]) > len(skills[0]["title"]), "skill_read devolveu so o titulo"


if __name__ == "__main__":
    falhou = False
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok  {nome}")
            except AssertionError as exc:
                falhou = True
                print(f"FALHOU  {nome}: {exc}")
    print("\nok: nenhuma ferramenta fantasma" if not falhou else "\nTEM TESTE FALHANDO")
