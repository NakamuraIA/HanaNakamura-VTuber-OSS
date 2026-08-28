"""Registro de ferramentas OpenAI-compatible por domínio."""

from __future__ import annotations

from typing import Any, Callable

from backend.providers.contracts import ProviderRequest
from .schema import tool_schema

_fn = tool_schema


def register_reminders(provider: Any, request: ProviderRequest, connections: dict[str, Any], tools: list[dict[str, Any]], runners: dict[str, Callable]) -> None:
    # === Reminders / alarms (in-process scheduler) ===
    from backend.tools.reminder_tools import (
        reminder_cancel as _reminder_cancel,
        reminder_create as _reminder_create,
        reminder_list as _reminder_list,
    )

    tools.append(_fn(
        "reminder_create",
        "Cria um lembrete/alarme. Informe 'at' (HH:MM), 'in_minutes' ou 'in_seconds'. "
        "repeat='daily' repete todo dia. discord=true também avisa no Discord (DM mencionando a dona). "
        "A Hana avisa por voz (se TTS ligado) e no painel quando chegar a hora.",
        params={
            "text": {"type": "string", "description": "O que lembrar"},
            "at": {"type": "string", "description": "Hora HH:MM (hoje, ou amanhã se já passou)"},
            "in_minutes": {"type": "number"},
            "in_seconds": {"type": "number"},
            "date": {"type": "string", "description": "Data opcional YYYY-MM-DD"},
            "repeat": {"type": "string", "enum": ["none", "daily"]},
            "discord": {"type": "boolean", "description": "Se true, também avisa no Discord quando disparar."},
        },
        required=["text"],
    ))
    tools.append(_fn(
        "reminder_list",
        "Lista os lembretes ativos.",
        params={"include_done": {"type": "boolean"}},
    ))
    tools.append(_fn(
        "reminder_cancel",
        "Cancela um lembrete pelo id.",
        params={"id": {"type": "string"}},
        required=["id"],
    ))
    runners["reminder_create"] = lambda args: _reminder_create(args).to_dict()
    runners["reminder_list"] = lambda args: _reminder_list(args).to_dict()
    runners["reminder_cancel"] = lambda args: _reminder_cancel(args).to_dict()

    # === Avisar a Nakamura no Discord (DM, mencionando ela) ===
    # Hana decide quando disparar (ex.: depois de criar um alarme). O bot do
    # Discord entrega a DM; aqui só enfileiramos na outbox.
    from backend.tools.discord_tools import discord_notify as _discord_notify

    tools.append(_fn(
        "discord_notify",
        "Envia uma mensagem direta (DM) pra Nakamura no Discord, mencionando ela. "
        "Use quando VOCE decidir avisa-la de algo importante por fora (ex.: confirmar "
        "que criou um alarme, lembrar de uma pendencia). Nao e automatico — voce escolhe a hora. "
        "Escreva a mensagem ja pronta, curta e em pt-BR.",
        params={"message": {"type": "string", "description": "A mensagem pra Nakamura"}},
        required=["message"],
    ))

    def run_discord_notify(args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        result = _discord_notify(request.memory, message)
        provider._append_terminal_event(
            request.memory,
            kind="tool_result",
            source="discord",
            status="success" if result.get("ok") else "failed",
            tool_name="discord.notify",
            display_text=(f"DM enfileirada pra Nakamura: {message[:160]}" if result.get("ok") else str(result.get("error"))),
            metadata={"toolResult": result},
        )
        return result

    runners["discord_notify"] = run_discord_notify

