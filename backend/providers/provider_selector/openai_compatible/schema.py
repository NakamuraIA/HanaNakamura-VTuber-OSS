"""Schema mínimo para function calling no formato OpenAI."""

from __future__ import annotations

from typing import Any


def tool_schema(
    name: str,
    description: str,
    params: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Schema OpenAI de function-calling sem boilerplate.

    Padrão trazido do estudo deepseek-tool-cli da Nakamura: cada tool declara
    nome/descrição/params em uma chamada, em vez de 20+ linhas de dict repetido.
    """
    parameters: dict[str, Any] = {"type": "object"}
    if required:
        parameters["required"] = list(required)
    parameters["properties"] = params or {}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
