"""Registro de ferramentas OpenAI-compatible por domínio."""

from __future__ import annotations

from typing import Any, Callable

from backend.providers.contracts import ProviderRequest
from .schema import tool_schema

_fn = tool_schema


def register_image_tools(provider: Any, request: ProviderRequest, connections: dict[str, Any], tools: list[dict[str, Any]], runners: dict[str, Callable]) -> None:
    # === Image generation tools (native function calling for providers that support tools) ===
    # When an image provider is active (check memory setting), these tools are registered
    # so function-calling LLMs (DeepSeek, OpenRouter, Groq, Qwen) can generate images via
    # native tool calls instead of relying solely on XML tag parsing.
    # XML extraction in chat.py remains as fallback for providers without function calling.
    image_service = getattr(request, "image_service", None)
    if image_service is not None:
        try:
            from backend.api.services.chat import _terminal_channels as _img_terminal_channels
        except ImportError:
            _img_terminal_channels = lambda: {"voice", "terminal_agent", "terminal"}  # fallback

        tools.append(_fn(
            "gerar_imagem",
            "Gera uma imagem a partir de um prompt em inglês. Use para criar imagens genéricas, "
            "cenas, paisagens, objetos, arte abstrata etc. O prompt deve ser descritivo, em inglês, "
            "com detalhes de estilo, iluminação, composição. Retorna o caminho da imagem gerada.",
            params={"prompt": {"type": "string", "description": "Prompt descritivo em inglês para a imagem"}},
            required=["prompt"],
        ))
        tools.append(_fn(
            "editar_imagem",
            "Edita uma imagem existente usando um prompt em inglês. Use quando a usuária pedir "
            "para modificar, retocar, ou transformar uma imagem que ela enviou como anexo. "
            "O prompt deve descrever a edição desejada em inglês.",
            params={"prompt": {"type": "string", "description": "Prompt descritivo em inglês para a edição"}},
            required=["prompt"],
        ))
        tools.append(_fn(
            "gerar_imagem_personagem",
            "Gera uma imagem de um personagem conhecido (Hana, Nyra, Shogun, etc.) ou da própria "
            "usuária. Use quando o pedido for específico para retratar uma pessoa/personagem. "
            "Envie um JSON com os campos: character (nome), mode (avatar/fullbody/scene/portrait), "
            "prompt (descrição em inglês), expression (opcional), outfit (opcional).",
            params={
                "character": {"type": "string", "description": "Nome do personagem: hana, nyra, shogun, ou nome da usuária"},
                "mode": {"type": "string", "enum": ["avatar", "fullbody", "scene", "portrait"], "description": "Modo/tipo da imagem"},
                "prompt": {"type": "string", "description": "Descrição detalhada em inglês"},
                "expression": {"type": "string", "description": "Expressão facial (opcional)"},
                "outfit": {"type": "string", "description": "Roupa/vestimenta (opcional)"},
            },
            required=["character", "mode", "prompt"],
        ))
        tools.append(_fn(
            "editar_imagem_personagem",
            "Edita uma imagem de personagem existente. Use quando a usuária pedir para modificar "
            "uma imagem de personagem que ela enviou. Envie um JSON similar ao gerar_imagem_personagem.",
            params={
                "character": {"type": "string", "description": "Nome do personagem"},
                "mode": {"type": "string", "enum": ["avatar", "fullbody", "scene", "portrait"]},
                "prompt": {"type": "string", "description": "Descrição da edição em inglês"},
                "expression": {"type": "string", "description": "Expressão facial (opcional)"},
                "outfit": {"type": "string", "description": "Roupa/vestimenta (opcional)"},
            },
            required=["character", "mode", "prompt"],
        ))

        def _run_generate(args: dict[str, Any]) -> dict[str, Any]:
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                return {"ok": False, "error": "prompt obrigatório"}
            result = image_service.generate(prompt)
            return {"ok": result.ok, "text": result.text, "error": result.error, "path": getattr(result, "saved_path", "") or ""}

        def _run_edit(args: dict[str, Any]) -> dict[str, Any]:
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                return {"ok": False, "error": "prompt obrigatório"}
            attachments = getattr(request, "attachments", [])
            result = image_service.edit(prompt, attachments=attachments)
            return {"ok": result.ok, "text": result.text, "error": result.error, "path": getattr(result, "saved_path", "") or ""}

        def _run_character_generate(args: dict[str, Any]) -> dict[str, Any]:
            import json as _json
            payload = {
                "character": str(args.get("character") or "hana").strip(),
                "mode": str(args.get("mode") or "portrait").strip(),
                "prompt": str(args.get("prompt") or "").strip(),
            }
            if args.get("expression"):
                payload["expression"] = str(args.get("expression")).strip()
            if args.get("outfit"):
                payload["outfit"] = str(args.get("outfit")).strip()
            content = _json.dumps(payload, ensure_ascii=False)
            result = image_service.generate_character(content)
            path = getattr(result, "saved_path", "") or ""
            _img_channel = str(getattr(request, "channel", "") or "")
            if _img_channel in _img_terminal_channels() and result.ok:
                try:
                    image_service.open_result(result, label="IMAGE GEN")
                except Exception:
                    pass
            return {"ok": result.ok, "text": result.text, "error": result.error, "path": path}

        def _run_character_edit(args: dict[str, Any]) -> dict[str, Any]:
            import json as _json
            payload = {
                "character": str(args.get("character") or "hana").strip(),
                "mode": str(args.get("mode") or "portrait").strip(),
                "prompt": str(args.get("prompt") or "").strip(),
            }
            if args.get("expression"):
                payload["expression"] = str(args.get("expression")).strip()
            if args.get("outfit"):
                payload["outfit"] = str(args.get("outfit")).strip()
            content = _json.dumps(payload, ensure_ascii=False)
            attachments = getattr(request, "attachments", [])
            result = image_service.edit_character(content, attachments=attachments)
            return {"ok": result.ok, "text": result.text, "error": result.error, "path": getattr(result, "saved_path", "") or ""}

        runners["gerar_imagem"] = _run_generate
        runners["editar_imagem"] = _run_edit
        runners["gerar_imagem_personagem"] = _run_character_generate
        runners["editar_imagem_personagem"] = _run_character_edit

