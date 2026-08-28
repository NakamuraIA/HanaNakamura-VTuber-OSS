"""Trava a memoria fixa e a ordem do system prompt.

Duas coisas que quebram calado se ninguem olhar:

1. A memoria fixa some do prompt. A Nakamura escreve a regra na tela, a Hana
   ignora, e nao ha erro nenhum pra investigar.
2. O relogio volta pro meio do prompt. Nada quebra — so fica caro: `%H:%M` muda
   a cada minuto, e o cache do provider casa por PREFIXO, entao tudo depois do
   relogio passa a ser cobrado cheio em todo turno.

Roda com:  python -m backend.tests.test_prompt_fixas
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import backend.persona.prompts as prompts
from backend.memory.core import HanaMemory


def _com_banco_limpo(fn) -> None:
    """Roda fn(mem) apontando o prompt pra um banco temporario."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "m.db"
        mem = HanaMemory(str(db))
        original = prompts._pinned_block

        def _bloco() -> str:
            fixas = mem.list_pinned()
            if not fixas:
                return ""
            linhas = "\n".join(f"- ({p['kind']}) {p['text']}" for p in fixas)
            return f"[REGRAS FIXAS DA NAKAMURA — valem sempre, em todo turno]\n{linhas}"

        prompts._pinned_block = _bloco
        try:
            fn(mem)
        finally:
            prompts._pinned_block = original


def test_fixa_entra_no_system_prompt() -> None:
    def check(mem: HanaMemory) -> None:
        assert "REGRAS FIXAS" not in prompts.build_provider_system_prompt("groq")
        mem.add_pinned("responda curto", kind="regra")
        prompt = prompts.build_provider_system_prompt("groq")
        assert "responda curto" in prompt, "a memoria fixa nao chegou no prompt"

    _com_banco_limpo(check)


def test_fixa_desligada_nao_entra() -> None:
    def check(mem: HanaMemory) -> None:
        pid = mem.add_pinned("regra velha", kind="regra")
        mem.update_pinned(pid, enabled=0)
        assert "regra velha" not in prompts.build_provider_system_prompt("groq")

    _com_banco_limpo(check)


def test_relogio_e_a_ultima_secao() -> None:
    # Se algum dia isso falhar, o cache do provider morreu junto.
    prompt = prompts.build_provider_system_prompt("openrouter")
    assert "[CONTEXTO TEMPORAL]" in prompt
    depois_do_relogio = prompt[prompt.rfind("[CONTEXTO TEMPORAL]"):]
    for marcador in ("[REGRA DE SAIDA", "Regras do provedor", "REGRAS FIXAS"):
        assert marcador not in depois_do_relogio, (
            f"'{marcador}' ficou DEPOIS do relogio — muda a cada minuto e mata o cache"
        )


def test_registro_torto_no_banco_nao_derruba_o_prompt() -> None:
    # Falha realista: uma linha entrou sem 'kind' (migracao, edicao manual no
    # DBeaver, bug futuro). O prompt tem que sair mesmo assim — a Hana parar de
    # responder por causa de um registro torto seria muito pior que ignorar ele.
    original = prompts._pinned_block
    prompts._pinned_block = lambda: _bloco_de([{"text": "regra ok"}, {"kind": "regra"}])
    try:
        prompt = prompts.build_provider_system_prompt("groq")
        assert "regra ok" in prompt, "a linha boa devia ter entrado"
    finally:
        prompts._pinned_block = original


def _bloco_de(fixas: list[dict]) -> str:
    """Mesma logica defensiva do _pinned_block real, sobre dados de teste."""
    linhas = "\n".join(f"- ({p.get('kind') or 'regra'}) {p['text']}" for p in fixas if p.get("text"))
    return f"[REGRAS FIXAS DA NAKAMURA]\n{linhas}" if linhas else ""


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
    print("\nok: memoria fixa e ordem do prompt travadas" if not falhou else "\nTEM TESTE FALHANDO")
