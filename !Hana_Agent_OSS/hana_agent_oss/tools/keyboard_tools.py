from __future__ import annotations

import time
import random
from typing import Any

from hana_agent_oss.core.protocol import ToolResult

# Co-piloto: Hana digita no lugar da Operador, no campo que ela deixou focado.
# Digitação letra-a-letra contínua (não em blocos de token) para parecer natural,
# com suporte total a acentos/pontuação via pynput (unicode-safe no Windows).

MAX_TEXT_CHARS = 8000
DEFAULT_CPS = 70.0          # caracteres por segundo (rápido e contínuo)
MIN_CPS = 5.0
MAX_CPS = 200.0
DEFAULT_START_DELAY = 0.35  # no modo agente a Hana ja clicou na caixa; respiro minimo


def _esc_pressed() -> bool:
    """ESC aborta a digitação na hora (botão de pânico)."""
    try:
        import keyboard  # type: ignore[import-not-found]

        return bool(keyboard.is_pressed("esc"))
    except Exception:
        return False


def keyboard_type(args: dict[str, Any]) -> ToolResult:
    """Type text into whatever control currently has keyboard focus."""
    text = str(args.get("text") or "")
    if not text.strip():
        return ToolResult(ok=False, tool="keyboard.type", error="text is required.")
    if len(text) > MAX_TEXT_CHARS:
        return ToolResult(ok=False, tool="keyboard.type", error=f"text too long (>{MAX_TEXT_CHARS} chars).")

    try:
        cps = float(args.get("cps") or DEFAULT_CPS)
    except (TypeError, ValueError):
        cps = DEFAULT_CPS
    cps = max(MIN_CPS, min(MAX_CPS, cps))
    try:
        start_delay = float(args.get("start_delay") or DEFAULT_START_DELAY)
    except (TypeError, ValueError):
        start_delay = DEFAULT_START_DELAY
    start_delay = max(0.0, min(10.0, start_delay))
    # Como digitar o \n: "space" (seguro, padrão), "shift_enter" (quebra linha SEM
    # enviar — Discord/WhatsApp/editores) ou "enter" (Enter real; envia formulários!).
    newline_mode = str(args.get("newline_mode") or "").strip().lower()
    if newline_mode not in {"space", "shift_enter", "enter"}:
        newline_mode = "enter" if bool(args.get("allow_enter", False)) else "space"

    try:
        from pynput.keyboard import Controller, Key
    except ImportError:
        return ToolResult(ok=False, tool="keyboard.type", error="pynput não instalado (pip install pynput).")

    controller = Controller()
    time.sleep(start_delay)

    base_interval = 1.0 / cps
    typed = 0
    aborted = False
    for char in text:
        if _esc_pressed():
            aborted = True
            break
        try:
            if char == "\n":
                if newline_mode == "space":
                    # vira espaço para nunca enviar um formulário sem querer
                    controller.type(" ")
                elif newline_mode == "shift_enter":
                    with controller.pressed(Key.shift):
                        controller.press(Key.enter)
                        controller.release(Key.enter)
                else:
                    controller.press(Key.enter)
                    controller.release(Key.enter)
            elif char == "\t":
                controller.type("    ")
            else:
                controller.type(char)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                tool="keyboard.type",
                error=f"falha ao digitar no caractere {typed}: {exc}",
                output={"typed_chars": typed},
            )
        typed += 1
        # jitter leve mantém o ritmo contínuo sem parecer metralhadora robótica
        time.sleep(base_interval * random.uniform(0.7, 1.3))

    return ToolResult(
        ok=True,
        tool="keyboard.type",
        output={
            "typed_chars": typed,
            "total_chars": len(text),
            "aborted_by_esc": aborted,
            "cps": cps,
            "newline_mode": newline_mode,
        },
    )
