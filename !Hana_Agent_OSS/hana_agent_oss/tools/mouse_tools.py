from __future__ import annotations

import os
import time
from typing import Any

from hana_agent_oss.core.protocol import ToolResult

# Co-piloto: mouse da Hana.
#
# Coordenadas SEMPRE normalizadas 0-1000 relativas ao monitor ativo (o mesmo que a
# visão captura). Isso casa com o jeito que os modelos Gemini apontam elementos em
# imagem e torna tudo independente de resolução/redimensionamento do screenshot.
# O clique é "teleporte": o cursor pula para o alvo e clica em milissegundos, então
# dividir o mouse com a Operador não vira cabo de guerra.


def _active_monitor(memory: Any) -> dict[str, int]:
    """Geometry (left/top/width/height) of the configured active monitor."""
    import mss

    index = 1
    if memory is not None:
        try:
            config = memory.get_setting("portabilidade_config", {}) or {}
            index = int(config.get("activeMonitor", 1))
        except Exception:
            index = 1
    with mss.mss() as sct:
        monitors = sct.monitors
        if index < 1 or index >= len(monitors):
            index = 1 if len(monitors) > 1 else 0
        mon = monitors[index]
        return {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}


def _to_global(x_norm: float, y_norm: float, mon: dict[str, int]) -> tuple[int, int]:
    x = max(0.0, min(1000.0, float(x_norm)))
    y = max(0.0, min(1000.0, float(y_norm)))
    return (
        mon["left"] + round(x / 1000.0 * mon["width"]),
        mon["top"] + round(y / 1000.0 * mon["height"]),
    )


def mouse_click(args: dict[str, Any], memory: Any = None) -> ToolResult:
    """Teleport-click at normalized (0-1000) coordinates on the active monitor."""
    try:
        x_norm = float(args.get("x"))
        y_norm = float(args.get("y"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, tool="mouse.click", error="x and y (0-1000) are required.")

    button_name = str(args.get("button") or "left").strip().lower()
    if button_name not in {"left", "right", "middle"}:
        button_name = "left"
    clicks = 2 if bool(args.get("double", False)) else 1

    try:
        from pynput.mouse import Button, Controller
    except ImportError:
        return ToolResult(ok=False, tool="mouse.click", error="pynput não instalado (pip install pynput).")

    try:
        mon = _active_monitor(memory)
        gx, gy = _to_global(x_norm, y_norm, mon)
        controller = Controller()
        controller.position = (gx, gy)
        time.sleep(0.05)  # alguns apps precisam registrar o hover antes do clique
        controller.click(getattr(Button, button_name), clicks)
        return ToolResult(
            ok=True,
            tool="mouse.click",
            output={
                "screen_x": gx,
                "screen_y": gy,
                "monitor": mon,
                "button": button_name,
                "double": clicks == 2,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, tool="mouse.click", error=f"falha ao clicar: {exc}")


def mouse_scroll(args: dict[str, Any], memory: Any = None) -> ToolResult:
    """Scroll at the current cursor position (or at x/y when provided)."""
    try:
        amount = int(args.get("amount", -5))
    except (TypeError, ValueError):
        amount = -5
    amount = max(-50, min(50, amount))

    try:
        from pynput.mouse import Controller
    except ImportError:
        return ToolResult(ok=False, tool="mouse.scroll", error="pynput não instalado (pip install pynput).")

    try:
        controller = Controller()
        if args.get("x") is not None and args.get("y") is not None:
            mon = _active_monitor(memory)
            controller.position = _to_global(float(args["x"]), float(args["y"]), mon)
            time.sleep(0.05)
        controller.scroll(0, amount)
        return ToolResult(ok=True, tool="mouse.scroll", output={"amount": amount})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, tool="mouse.scroll", error=f"falha ao rolar: {exc}")


# --- Olho do co-piloto: localizar elementos com o modelo de visão ------------ #

SCREEN_FIND_PROMPT = (
    "Você é um localizador de elementos de interface em screenshots.\n"
    "Tarefa: encontre na imagem o elemento descrito e responda APENAS um JSON válido, "
    "sem markdown, sem texto extra, no formato:\n"
    '{"found": true|false, "x": <0-1000>, "y": <0-1000>, "description": "<o que há no ponto>"}\n'
    "x e y são o CENTRO do elemento, normalizados de 0 a 1000 (x: esquerda→direita, "
    "y: topo→baixo). Se houver vários candidatos, escolha o mais provável e mencione os "
    'outros em "description". Se não encontrar, found=false com a melhor dica em description.\n\n'
    "Elemento a localizar: "
)


import threading

_screen_find_guard = threading.local()


def screen_find(args: dict[str, Any], memory: Any = None) -> ToolResult:
    """Capture the active monitor and ask the vision model where an element is.

    This is the bridge that lets a no-vision chat model (e.g. DeepSeek) drive the
    mouse: it asks here, gets normalized coordinates back as text, then calls
    mouse_click. Uses the configured vision model (llm_config.visionModel).
    """
    # The vision sub-call may run through a provider that exposes tools; this guard
    # stops a confused model from calling screen_find inside screen_find.
    if getattr(_screen_find_guard, "active", False):
        return ToolResult(ok=False, tool="screen.find", error="screen_find reentrante bloqueado.")

    query = str(args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, tool="screen.find", error="query is required (o que procurar na tela).")

    # 1) Captura full-res do monitor ativo (sem resize: coordenadas mais precisas).
    try:
        import mss
        from PIL import Image

        mon = _active_monitor(memory)
        with mss.mss() as sct:
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        os.makedirs("temp", exist_ok=True)
        path = os.path.abspath(os.path.join("temp", "copilot_screen.png"))
        img.save(path, format="PNG", optimize=True)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, tool="screen.find", error=f"falha na captura: {exc}")

    # 2) Pergunta ao modelo de visão. O visionModel da config pertence ao provider
    #    principal: ids com "/" (ex: google/gemini-3.1-flash-lite-preview) são do
    #    OpenRouter; sem "/" são da API Gemini direta. Mandar um id do OpenRouter
    #    para a API Gemini dá 404 — então roteamos pelo formato, com fallback.
    vision_model = ""
    if memory is not None:
        try:
            cfg = memory.get_setting("llm_config", {}) or {}
            vision_model = str(cfg.get("visionModel") or "").strip()
        except Exception:
            vision_model = ""

    candidates: list[tuple[str, str]] = []
    if vision_model:
        if "/" in vision_model:
            if os.environ.get("OPENROUTER_API_KEY"):
                candidates.append(("openrouter", vision_model))
        elif os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            candidates.append(("gemini_api", vision_model))
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        fallback = ("gemini_api", "gemini-3-flash-preview")
        if fallback not in candidates:
            candidates.append(fallback)
    if not candidates:
        return ToolResult(
            ok=False,
            tool="screen.find",
            error="nenhum modelo de visão disponível (configure visionModel e a chave do provider).",
        )

    from hana_agent_oss.providers.contracts import ProviderRequest

    errors: list[str] = []
    _screen_find_guard.active = True
    try:
        return _query_vision_candidates(candidates, query, path, mon, memory, errors)
    finally:
        _screen_find_guard.active = False


def _query_vision_candidates(
    candidates: list[tuple[str, str]],
    query: str,
    path: str,
    mon: dict[str, int],
    memory: Any,
    errors: list[str],
) -> ToolResult:
    from hana_agent_oss.providers.contracts import ProviderRequest

    for provider_id, model in candidates:
        try:
            request = ProviderRequest(
                provider=provider_id,
                model=model,
                messages=[{"role": "user", "content": SCREEN_FIND_PROMPT + query}],
                temperature=0.1,
                native_search_mode="off",
                allow_tools=False,
                attachments=[{"type": "image/png", "name": "screen.png", "path": path}],
                memory=memory,
            )
            if provider_id == "openrouter":
                from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider

                response = OpenRouterProvider().generate(request)
            else:
                from hana_agent_oss.providers.provider_selector.gemini_api.provider import GeminiApiProvider

                response = GeminiApiProvider().generate(request)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider_id}:{model} -> {exc}")
            continue
        if not response.ok:
            errors.append(f"{provider_id}:{model} -> {response.error}")
            continue
        return ToolResult(
            ok=True,
            tool="screen.find",
            output={
                "query": query,
                "vision_model": f"{provider_id}:{model}",
                "answer": (response.text or "").strip(),
                "monitor": mon,
                "hint": "Use os x/y (0-1000) do answer em mouse_click. Se found=false, ajuste a query.",
            },
        )

    return ToolResult(ok=False, tool="screen.find", error="visão falhou: " + " | ".join(errors))
