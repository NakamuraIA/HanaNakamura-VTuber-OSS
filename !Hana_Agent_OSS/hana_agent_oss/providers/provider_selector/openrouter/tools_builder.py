"""Montagem das ferramentas (tool schemas + runners) da Hana.

Extraído de ``provider.py`` para deixar o provider mais enxuto: aqui ficam TODAS
as definições de ferramentas locais (terminal, arquivos, teclado/mouse co-piloto,
lembretes, Discord, memória) além do bundle MCP.

A função recebe a instância ``provider`` para reusar os helpers dela
(``_append_terminal_event``, ``_safe_int``, ``_sanitize_tool_schema``). O
comportamento é idêntico ao que estava embutido no provider.
"""

from __future__ import annotations

from typing import Any, Callable

from hana_agent_oss.providers.contracts import ProviderRequest
from hana_agent_oss.tools.mcp_provider_tools import mcp_openai_runners, mcp_openai_schemas


def build_tool_schemas_and_runners(
    provider: Any,
    request: ProviderRequest,
    *,
    supports_tools: bool,
) -> tuple[list[dict[str, Any]], dict[str, Callable[[dict[str, Any]], dict[str, Any]]]]:
    """Expose MCP + local hands tools when model capabilities allow it.
    Tools are skipped entirely for models the catalog reports as not supporting tool calls.
    """
    connections = {}
    if request.memory is not None:
        try:
            raw = request.memory.get_setting("connections_config", {}) or {}
            from hana_agent_oss.api.routers.config import normalize_connections_config
            connections = normalize_connections_config(raw)
        except Exception:
            connections = {}

    if not getattr(request, "allow_tools", True):
        return [], {}

    tools: list[dict[str, Any]] = []
    runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
    tools.extend(mcp_openai_schemas())
    # tool_runs are captured centrally in _run_completion_loop (covers every tool),
    # so the MCP runner does not need its own collector here (avoids double-count).
    runners.update(mcp_openai_runners(request.memory))

    if not supports_tools:
        return [], {}

    # === Hana's local hands (lean in-process executor; replaces Omni) ===
    # Added last so it never disturbs the leading tool bundle order.
    if bool(connections.get("localHands", True)):
        from hana_agent_oss.tools.terminal_tools import (
            inspect_dir as _terminal_inspect_dir,
            run_command as _terminal_run_command,
        )

        tools.append({
            "type": "function",
            "function": {
                "name": "terminal_run",
                "description": (
                    "Roda um comando no PC da Operador (Windows). Tem timeout e limite de saída. "
                    "Use shell='powershell' p/ PowerShell. ANTES de ações perigosas (deletar, formatar, "
                    "admin, mexer em credenciais/.env): investigue, mostre o que vai fazer e confirme com a usuária."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {"type": "string", "description": "Comando a executar"},
                        "cwd": {"type": "string", "description": "Pasta de trabalho (opcional)"},
                        "shell": {"type": "string", "enum": ["cmd", "powershell", "bash"]},
                        "timeout": {"type": "integer", "description": "Segundos até interromper (padrão 60, máx 600)"},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "terminal_inspect_dir",
                "description": "Lista o conteúdo de uma pasta (um nível) para inspeção rápida.",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "description": "Caminho da pasta"}},
                },
            },
        })

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
        from hana_agent_oss.tools.file_tools import (
            file_exists as _file_exists,
            file_read as _file_read,
            file_write as _file_write,
        )

        tools.append({
            "type": "function",
            "function": {
                "name": "file_write",
                "description": (
                    "Cria ou sobrescreve um arquivo de texto/código com o conteúdo EXATO informado "
                    "(UTF-8, cria as pastas automaticamente). USE ISTO para escrever HTML/CSS/JS/Python/etc — "
                    "NUNCA jogue código pelo terminal_run com here-string (@\"...\"@), pois isso corrompe "
                    "variáveis $, crases e acentos. Uma chamada basta por arquivo."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string", "description": "Caminho completo do arquivo"},
                        "content": {"type": "string", "description": "Conteúdo completo do arquivo"},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "file_read",
                "description": "Lê um arquivo de texto e retorna o conteúdo (UTF-8).",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "description": "Caminho do arquivo"}},
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "file_exists",
                "description": "Verifica se um caminho existe (arquivo ou pasta).",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "description": "Caminho a verificar"}},
                },
            },
        })

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

        # === Co-piloto: digitar pela Operador (teclado real) ===
        from hana_agent_oss.tools.keyboard_tools import keyboard_type as _keyboard_type

        tools.append({
            "type": "function",
            "function": {
                "name": "keyboard_type",
                "description": (
                    "Digita um texto NO TECLADO de verdade, letra por letra, dentro do campo que a "
                    "Operador deixou focado/clicado na tela dela (caixa de resposta, formulário, editor). "
                    "Use quando ela pedir 'digita pra mim', 'responde essa pergunta aí', 'escreve isso'. "
                    "Suporta acentos e pontuação. Quebras de linha (\\n): newline_mode='space' (padrão, vira espaço), "
                    "'shift_enter' (quebra linha SEM enviar — use para texto multilinha em chats/editores) ou "
                    "'enter' (Enter real — ENVIA formulários, só se a Operador mandar enviar). "
                    "Ela pode apertar ESC para abortar a digitação."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "description": "Texto exato a digitar"},
                        "cps": {"type": "number", "description": "Velocidade em caracteres/segundo (padrão 40)"},
                        "newline_mode": {"type": "string", "enum": ["space", "shift_enter", "enter"], "description": "Como digitar \\n (padrão space)"},
                        "start_delay": {"type": "number", "description": "Segundos de espera antes de começar (padrão 1.2)"},
                    },
                },
            },
        })

        def run_keyboard_type(args: dict[str, Any]) -> dict[str, Any]:
            preview = str(args.get("text") or "")[:120]
            provider._append_terminal_event(
                request.memory,
                kind="tool_call",
                source="local_hands",
                status="running",
                tool_name="keyboard.type",
                display_text=f"Digitando pela Operador: {preview}...",
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
        from hana_agent_oss.tools.mouse_tools import (
            mouse_click as _mouse_click,
            mouse_scroll as _mouse_scroll,
            screen_find as _screen_find,
        )

        tools.append({
            "type": "function",
            "function": {
                "name": "screen_find",
                "description": (
                    "OLHO do co-piloto: tira um print do monitor ativo e pergunta ao modelo de visão "
                    "ONDE está um elemento (botão, X de fechar, campo, link). Retorna JSON com x/y "
                    "normalizados 0-1000 prontos para usar em mouse_click. Use ANTES de clicar em "
                    "qualquer coisa — nunca chute coordenadas. Funciona mesmo quando o seu próprio "
                    "modelo não tem visão (a consulta vai para o modelo de visão configurado)."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Descrição do elemento, ex: 'botão X de fechar da aba do Chrome'"},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "mouse_click",
                "description": (
                    "Clica na tela da Operador nas coordenadas x/y normalizadas 0-1000 do monitor ativo "
                    "(as mesmas que screen_find retorna). O cursor teleporta e clica na hora. "
                    "Obtenha as coordenadas via screen_find primeiro; após o clique, se for fazer outra "
                    "ação dependente, chame screen_find de novo para conferir o novo estado da tela."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["x", "y"],
                    "properties": {
                        "x": {"type": "number", "description": "0-1000 (esquerda→direita)"},
                        "y": {"type": "number", "description": "0-1000 (topo→baixo)"},
                        "button": {"type": "string", "enum": ["left", "right", "middle"]},
                        "double": {"type": "boolean", "description": "Clique duplo"},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "mouse_scroll",
                "description": "Rola a tela (scroll). amount negativo = para baixo, positivo = para cima. Opcionalmente em x/y (0-1000).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "integer", "description": "Cliques de scroll, ex: -5 desce, 5 sobe"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                },
            },
        })

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

    # === Reminders / alarms (in-process scheduler) ===
    from hana_agent_oss.tools.reminder_tools import (
        reminder_cancel as _reminder_cancel,
        reminder_create as _reminder_create,
        reminder_list as _reminder_list,
    )

    tools.append({
        "type": "function",
        "function": {
            "name": "reminder_create",
            "description": (
                "Cria um lembrete/alarme. Informe 'at' (HH:MM), 'in_minutes' ou 'in_seconds'. "
                "repeat='daily' repete todo dia. discord=true também avisa no Discord (DM mencionando a dona). "
                "A Hana avisa por voz (se TTS ligado) e no painel quando chegar a hora."
            ),
            "parameters": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "description": "O que lembrar"},
                    "at": {"type": "string", "description": "Hora HH:MM (hoje, ou amanhã se já passou)"},
                    "in_minutes": {"type": "number"},
                    "in_seconds": {"type": "number"},
                    "date": {"type": "string", "description": "Data opcional YYYY-MM-DD"},
                    "repeat": {"type": "string", "enum": ["none", "daily"]},
                    "discord": {"type": "boolean", "description": "Se true, também avisa no Discord quando disparar."},
                },
            },
        },
    })
    tools.append({
        "type": "function",
        "function": {
            "name": "reminder_list",
            "description": "Lista os lembretes ativos.",
            "parameters": {"type": "object", "properties": {"include_done": {"type": "boolean"}}},
        },
    })
    tools.append({
        "type": "function",
        "function": {
            "name": "reminder_cancel",
            "description": "Cancela um lembrete pelo id.",
            "parameters": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
        },
    })
    runners["reminder_create"] = lambda args: _reminder_create(args).to_dict()
    runners["reminder_list"] = lambda args: _reminder_list(args).to_dict()
    runners["reminder_cancel"] = lambda args: _reminder_cancel(args).to_dict()

    # === Avisar a Operador no Discord (DM, mencionando ela) ===
    # Hana decide quando disparar (ex.: depois de criar um alarme). O bot do
    # Discord entrega a DM; aqui só enfileiramos na outbox.
    from hana_agent_oss.tools.discord_tools import discord_notify as _discord_notify

    tools.append({
        "type": "function",
        "function": {
            "name": "discord_notify",
            "description": (
                "Envia uma mensagem direta (DM) pra Operador no Discord, mencionando ela. "
                "Use quando VOCE decidir avisa-la de algo importante por fora (ex.: confirmar "
                "que criou um alarme, lembrar de uma pendencia). Nao e automatico — voce escolhe a hora. "
                "Escreva a mensagem ja pronta, curta e em pt-BR."
            ),
            "parameters": {
                "type": "object",
                "required": ["message"],
                "properties": {"message": {"type": "string", "description": "A mensagem pra Operador"}},
            },
        },
    })

    def run_discord_notify(args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        result = _discord_notify(request.memory, message)
        provider._append_terminal_event(
            request.memory,
            kind="tool_result",
            source="discord",
            status="success" if result.get("ok") else "failed",
            tool_name="discord.notify",
            display_text=(f"DM enfileirada pra Operador: {message[:160]}" if result.get("ok") else str(result.get("error"))),
            metadata={"toolResult": result},
        )
        return result

    runners["discord_notify"] = run_discord_notify

    # === Mãos na memória (a Hana gerencia as próprias lembranças) ===
    # Sempre expostas (memória é núcleo, não módulo opcional). Operam na
    # MemoryStore viva da request; o painel Memória mostra tudo depois.
    if request.memory is not None:
        mem_store = request.memory

        tools.append({
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": (
                    "Busca nas suas memórias persistentes (perfil, fatos, diários, anotações). "
                    "Use quando a Operador perguntar 'o que você lembra de X', quando precisar "
                    "conferir um fato antigo, ou ANTES de corrigir/apagar uma memória (para achar o id)."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Termos de busca"},
                        "limit": {"type": "integer", "description": "Máx. resultados (padrão 8)"},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "memory_save",
                "description": (
                    "Salva uma memória persistente nova (fato, preferência, decisão, contexto importante). "
                    "category: preference_like, preference_dislike, personal_fact, ou general. "
                    "Use para registrar na hora algo que a Operador pedir para você lembrar."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "description": "O fato, curto e específico"},
                        "category": {"type": "string", "enum": ["preference_like", "preference_dislike", "personal_fact", "general"]},
                        "importance": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "memory_update",
                "description": (
                    "Corrige o texto de uma memória existente pelo id (use memory_search antes para achar). "
                    "Use quando a Operador disser que uma lembrança sua está errada ou desatualizada."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["id", "text"],
                    "properties": {
                        "id": {"type": "string"},
                        "text": {"type": "string", "description": "Novo texto corrigido"},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "memory_delete",
                "description": (
                    "Apaga (soft-delete, recuperável) uma memória pelo id. Use memory_search antes. "
                    "Confirme com a Operador antes de apagar, a não ser que ela já tenha mandado apagar."
                ),
                "parameters": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "memory_pin",
                "description": "Fixa (pinned=true) ou desafixa uma memória. Fixadas nunca decaem e rankeiam mais alto — use para 'nunca esqueça isso'.",
                "parameters": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}, "pinned": {"type": "boolean"}},
                },
            },
        })

        def _mem_compact(memory_item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": memory_item.get("id"),
                "text": memory_item.get("text"),
                "category": memory_item.get("category"),
                "importance": memory_item.get("importance"),
                "pinned": memory_item.get("pinned"),
                "updated_at": memory_item.get("updated_at"),
            }

        def run_memory_search(args: dict[str, Any]) -> dict[str, Any]:
            try:
                results = mem_store.search(str(args.get("query") or ""), limit=provider._safe_int(args.get("limit"), 8))
                return {"ok": True, "memories": [_mem_compact(m) for m in results]}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        def run_memory_save(args: dict[str, Any]) -> dict[str, Any]:
            text = str(args.get("text") or "").strip()
            if not text:
                return {"ok": False, "error": "text obrigatório"}
            try:
                saved = mem_store.add_memory(
                    text,
                    kind="long_term",
                    source="hana_chat_tool",
                    metadata={
                        "category": str(args.get("category") or "general"),
                        "importance": str(args.get("importance") or "medium"),
                    },
                )
                return {"ok": True, "memory": _mem_compact(saved)}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        def run_memory_update(args: dict[str, Any]) -> dict[str, Any]:
            memory_id = str(args.get("id") or "").strip()
            text = str(args.get("text") or "").strip()
            if not memory_id or not text:
                return {"ok": False, "error": "id e text obrigatórios"}
            try:
                updated = mem_store.add_memory(text, memory_id=memory_id, source="hana_chat_tool")
                return {"ok": True, "memory": _mem_compact(updated)}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        def run_memory_delete(args: dict[str, Any]) -> dict[str, Any]:
            memory_id = str(args.get("id") or "").strip()
            if not memory_id:
                return {"ok": False, "error": "id obrigatório"}
            deleted = mem_store.delete_memory(memory_id, hard=False)
            return {"ok": bool(deleted), "deleted": bool(deleted), "error": None if deleted else "memória não encontrada"}

        def run_memory_pin(args: dict[str, Any]) -> dict[str, Any]:
            memory_id = str(args.get("id") or "").strip()
            if not memory_id:
                return {"ok": False, "error": "id obrigatório"}
            pinned = bool(args.get("pinned", True))
            updated = mem_store.pin_memory(memory_id, pinned=pinned)
            return {"ok": bool(updated), "pinned": pinned, "error": None if updated else "memória não encontrada"}

        runners["memory_search"] = run_memory_search
        runners["memory_save"] = run_memory_save
        runners["memory_update"] = run_memory_update
        runners["memory_delete"] = run_memory_delete
        runners["memory_pin"] = run_memory_pin

    if not tools and not supports_tools:
        return [], {}

    return [provider._sanitize_tool_schema(schema) for schema in tools], runners
