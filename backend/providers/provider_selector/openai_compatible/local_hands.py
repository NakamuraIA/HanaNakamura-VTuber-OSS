"""Registro de ferramentas OpenAI-compatible por domínio."""

from __future__ import annotations

from typing import Any, Callable

from backend.providers.contracts import ProviderRequest
from .schema import tool_schema

_fn = tool_schema


def register_local_hands(provider: Any, request: ProviderRequest, connections: dict[str, Any], tools: list[dict[str, Any]], runners: dict[str, Callable]) -> None:
    # === Hana's local hands (lean in-process executor; replaces Omni) ===
    # Added last so it never disturbs the leading tool bundle order.
    if bool(connections.get("localHands", True)):
        from backend.tools.terminal_tools import (
            inspect_dir as _terminal_inspect_dir,
            run_command as _terminal_run_command,
        )

        tools.append(_fn(
            "terminal_run",
            "Roda um comando no PC da Nakamura (Windows). Tem timeout e limite de saída. "
            "Use shell='powershell' p/ PowerShell. ANTES de ações perigosas (deletar, formatar, "
            "admin, mexer em credenciais/.env): investigue, mostre o que vai fazer e confirme com a usuária.",
            params={
                "command": {"type": "string", "description": "Comando a executar"},
                "cwd": {"type": "string", "description": "Pasta de trabalho (opcional)"},
                "shell": {"type": "string", "enum": ["cmd", "powershell", "bash"]},
                "timeout": {"type": "integer", "description": "Segundos até interromper (padrão 60, máx 600)"},
            },
            required=["command"],
        ))
        tools.append(_fn(
            "terminal_inspect_dir",
            "Lista o conteúdo de uma pasta (um nível) para inspeção rápida.",
            params={"path": {"type": "string", "description": "Caminho da pasta"}},
            required=["path"],
        ))

        def run_terminal(args: dict[str, Any]) -> dict[str, Any]:
            command = str(args.get("command") or "").strip()
            provider._append_terminal_event(
                request.memory,
                kind="tool_call",
                source="local_hands",
                status="running",
                tool_name="terminal.run",
                display_text=f"Rodando: {command[:240]}",
                metadata={"shell": str(args.get("shell") or "")},
            )
            result = _terminal_run_command(args)
            result_dict = result.to_dict()
            provider._append_terminal_event(
                request.memory,
                kind="tool_result",
                source="local_hands",
                status="success" if result.ok else "failed",
                tool_name="terminal.run",
                display_text=str(result.output.get("stdout") or result.error or "Comando finalizado."),
                metadata={"toolResult": result_dict},
            )
            return result_dict

        def run_inspect(args: dict[str, Any]) -> dict[str, Any]:
            return _terminal_inspect_dir(args).to_dict()

        runners["terminal_run"] = run_terminal
        runners["terminal_inspect_dir"] = run_inspect

        # === File read/write (atomic, UTF-8) ===
        # Writing code/text via the terminal (PowerShell here-strings) corrupts content:
        # it eats $variables, turns backticks into escapes, mangles accents (mojibake) and
        # blows up on large files (WinError 206). These tools take the content as a plain
        # JSON argument, so there is no shell escaping at all — one clean write.
        from backend.tools.file_tools import (
            file_exists as _file_exists,
            file_read as _file_read,
            file_write as _file_write,
        )

        tools.append(_fn(
            "file_write",
            "Cria ou sobrescreve um arquivo de texto/código com o conteúdo EXATO informado "
            "(UTF-8, cria as pastas automaticamente). USE ISTO para escrever HTML/CSS/JS/Python/etc — "
            "NUNCA jogue código pelo terminal_run com here-string (@\"...\"@), pois isso corrompe "
            "variáveis $, crases e acentos. Para a Área de Trabalho use ~/Desktop/arquivo e nunca "
            "invente o nome da conta em C:\\Users. Só afirme que criou ou salvou depois que esta "
            "ferramenta retornar ok=true. Uma chamada basta por arquivo.",
            params={
                "path": {"type": "string", "description": "Caminho completo do arquivo"},
                "content": {"type": "string", "description": "Conteúdo completo do arquivo"},
            },
            required=["path", "content"],
        ))
        tools.append(_fn(
            "file_read",
            "Lê um arquivo de texto e retorna o conteúdo (UTF-8).",
            params={"path": {"type": "string", "description": "Caminho do arquivo"}},
            required=["path"],
        ))
        tools.append(_fn(
            "file_exists",
            "Verifica se um caminho existe (arquivo ou pasta).",
            params={"path": {"type": "string", "description": "Caminho a verificar"}},
            required=["path"],
        ))

        def run_file_write(args: dict[str, Any]) -> dict[str, Any]:
            path = str(args.get("path") or "").strip()
            provider._append_terminal_event(
                request.memory,
                kind="tool_call",
                source="local_hands",
                status="running",
                tool_name="file.write",
                display_text=f"Escrevendo arquivo: {path[:240]}",
                metadata={},
            )
            result = _file_write(args)
            result_dict = result.to_dict()
            provider._append_terminal_event(
                request.memory,
                kind="tool_result",
                source="local_hands",
                status="success" if result.ok else "failed",
                tool_name="file.write",
                display_text=(f"Arquivo salvo: {path}" if result.ok else (result.error or "Falha ao escrever.")),
                metadata={"toolResult": result_dict},
            )
            return result_dict

        runners["file_write"] = run_file_write
        runners["file_read"] = lambda args: _file_read(args).to_dict()
        runners["file_exists"] = lambda args: _file_exists(args).to_dict()

        # === Co-piloto: digitar pela Nakamura (teclado real) ===
        from backend.tools.keyboard_tools import keyboard_type as _keyboard_type

        tools.append(_fn(
            "keyboard_type",
            "Digita um texto NO TECLADO de verdade, letra por letra, dentro do campo que a "
            "Nakamura deixou focado/clicado na tela dela (caixa de resposta, formulário, editor). "
            "Use quando ela pedir 'digita pra mim', 'responde essa pergunta aí', 'escreve isso'. "
            "Suporta acentos e pontuação. Quebras de linha (\\n): newline_mode='space' (padrão, vira espaço), "
            "'shift_enter' (quebra linha SEM enviar — use para texto multilinha em chats/editores) ou "
            "'enter' (Enter real — ENVIA formulários, só se a Nakamura mandar enviar). "
            "Ela pode apertar ESC para abortar a digitação.",
            params={
                "text": {"type": "string", "description": "Texto exato a digitar"},
                "cps": {"type": "number", "description": "Velocidade em caracteres/segundo (padrão 40)"},
                "newline_mode": {"type": "string", "enum": ["space", "shift_enter", "enter"], "description": "Como digitar \\n (padrão space)"},
                "start_delay": {"type": "number", "description": "Segundos de espera antes de começar (padrão 1.2)"},
            },
            required=["text"],
        ))

        def run_keyboard_type(args: dict[str, Any]) -> dict[str, Any]:
            preview = str(args.get("text") or "")[:120]
            provider._append_terminal_event(
                request.memory,
                kind="tool_call",
                source="local_hands",
                status="running",
                tool_name="keyboard.type",
                display_text=f"Digitando pela Nakamura: {preview}...",
                metadata={},
            )
            result = _keyboard_type(args)
            result_dict = result.to_dict()
            typed = (result.output or {}).get("typed_chars", 0)
            provider._append_terminal_event(
                request.memory,
                kind="tool_result",
                source="local_hands",
                status="success" if result.ok else "failed",
                tool_name="keyboard.type",
                display_text=(f"Digitei {typed} caracteres." if result.ok else (result.error or "Falha ao digitar.")),
                metadata={"toolResult": result_dict},
            )
            return result_dict

        runners["keyboard_type"] = run_keyboard_type

        # === Co-piloto: mouse + olho (visão aponta, mouse clica) ===
        from backend.tools.mouse_tools import (
            mouse_click as _mouse_click,
            mouse_scroll as _mouse_scroll,
            screen_find as _screen_find,
        )

        tools.append(_fn(
            "screen_find",
            "OLHO do co-piloto: tira um print do monitor ativo e pergunta ao modelo de visão "
            "ONDE está um elemento (botão, X de fechar, campo, link). Retorna JSON com x/y "
            "normalizados 0-1000 prontos para usar em mouse_click. Use ANTES de clicar em "
            "qualquer coisa — nunca chute coordenadas. Funciona mesmo quando o seu próprio "
            "modelo não tem visão (a consulta vai para o modelo de visão configurado).",
            params={"query": {"type": "string", "description": "Descrição do elemento, ex: 'botão X de fechar da aba do Chrome'"}},
            required=["query"],
        ))
        tools.append(_fn(
            "mouse_click",
            "Clica na tela da Nakamura nas coordenadas x/y normalizadas 0-1000 do monitor ativo "
            "(as mesmas que screen_find retorna). O cursor teleporta e clica na hora. "
            "Obtenha as coordenadas via screen_find primeiro; após o clique, se for fazer outra "
            "ação dependente, chame screen_find de novo para conferir o novo estado da tela.",
            params={
                "x": {"type": "number", "description": "0-1000 (esquerda→direita)"},
                "y": {"type": "number", "description": "0-1000 (topo→baixo)"},
                "button": {"type": "string", "enum": ["left", "right", "middle"]},
                "double": {"type": "boolean", "description": "Clique duplo"},
            },
            required=["x", "y"],
        ))
        tools.append(_fn(
            "mouse_scroll",
            "Rola a tela (scroll). amount negativo = para baixo, positivo = para cima. Opcionalmente em x/y (0-1000).",
            params={
                "amount": {"type": "integer", "description": "Cliques de scroll, ex: -5 desce, 5 sobe"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
        ))

        def _copilot_runner(name: str, func) -> Callable[[dict[str, Any]], dict[str, Any]]:
            def run(args: dict[str, Any]) -> dict[str, Any]:
                detail = str(args.get("query") or f"x={args.get('x')} y={args.get('y')}")[:160]
                provider._append_terminal_event(
                    request.memory,
                    kind="tool_call",
                    source="local_hands",
                    status="running",
                    tool_name=name,
                    display_text=f"{name}: {detail}",
                    metadata={},
                )
                result = func(args, request.memory)
                result_dict = result.to_dict()
                provider._append_terminal_event(
                    request.memory,
                    kind="tool_result",
                    source="local_hands",
                    status="success" if result.ok else "failed",
                    tool_name=name,
                    display_text=(str((result.output or {}).get("answer") or "ok") if result.ok else (result.error or "falhou"))[:300],
                    metadata={"toolResult": result_dict},
                )
                return result_dict
            return run

        runners["screen_find"] = _copilot_runner("screen.find", _screen_find)
        runners["mouse_click"] = _copilot_runner("mouse.click", _mouse_click)
        runners["mouse_scroll"] = _copilot_runner("mouse.scroll", _mouse_scroll)

