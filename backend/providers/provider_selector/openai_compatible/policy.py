"""Registro de ferramentas OpenAI-compatible por domínio."""

from __future__ import annotations

from typing import Any, Callable

from backend.providers.contracts import ProviderRequest
from .schema import tool_schema

_fn = tool_schema


def apply_tool_policy(provider: Any, request: ProviderRequest, connections: dict[str, Any], tools: list[dict[str, Any]], runners: dict[str, Callable]) -> None:
    # === Modo plano (ideia do Grok Build: enter/exit_plan_mode como tool) ===
    # Com o modo ativo, as tools com efeito colateral (terminal/arquivo/mouse/
    # teclado) NAO executam — devolvem "acao proposta" pro modelo descrever o
    # plano. O modelo so deve sair do modo com aprovacao explicita da usuaria.
    if request.memory is not None:
        tools.append(_fn(
            "enter_plan_mode",
            "Ativa o modo plano: ações com efeito colateral (terminal_run, file_write, "
            "mouse/teclado) ficam bloqueadas e viram propostas. Use quando a usuária pedir "
            "pra planejar antes de executar, ou antes de uma sequência arriscada.",
        ))
        tools.append(_fn(
            "exit_plan_mode",
            "Desativa o modo plano e volta a executar ações de verdade. SÓ chame depois "
            "que a usuária aprovar explicitamente o plano (ex: 'pode executar', 'aprovado').",
        ))
        runners["enter_plan_mode"] = lambda args: _set_plan_mode(request.memory, True)
        runners["exit_plan_mode"] = lambda args: _set_plan_mode(request.memory, False)
        for name in PLAN_GATED_TOOLS:
            runner = runners.get(name)
            if runner is not None:
                runners[name] = _plan_gate(name, runner, request.memory)



# Tools com efeito colateral real — bloqueadas quando o modo plano esta ativo.
# Leitura (file_read, screen_find, terminal_inspect_dir...) continua liberada.
PLAN_GATED_TOOLS = ("terminal_run", "file_write", "keyboard_type", "mouse_click", "mouse_scroll")


def plan_mode_active(memory: Any) -> bool:
    try:
        cfg = memory.get_setting("agent_settings", {}) or {}
        return bool(cfg.get("plan_mode"))
    except Exception:
        return False


def _set_plan_mode(memory: Any, active: bool) -> dict[str, Any]:
    try:
        cfg = memory.get_setting("agent_settings", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg["plan_mode"] = bool(active)
        memory.set_setting("agent_settings", cfg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"plan_mode_toggle_failed:{exc}"}
    if active:
        return {"ok": True, "message": "Modo plano ATIVO: ações com efeito colateral agora são só propostas. Descreva o plano pra usuária aprovar."}
    return {"ok": True, "message": "Modo plano desativado: ações voltam a executar de verdade."}


def _plan_gate(name: str, runner: Callable[[dict[str, Any]], dict[str, Any]], memory: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def gated(args: dict[str, Any]) -> dict[str, Any]:
        if plan_mode_active(memory):
            return {
                "ok": False,
                "error": "plan_mode_active",
                "message": (
                    f"Modo plano ativo: {name} NÃO foi executada, é só uma proposta. "
                    "Descreva o que essa ação faria e espere a aprovação da usuária; "
                    "aí chame exit_plan_mode e execute de verdade."
                ),
                "proposed_args": args,
            }
        return runner(args)

    return gated
