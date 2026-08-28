"""Registro de ferramentas OpenAI-compatible por domínio."""

from __future__ import annotations

from typing import Any, Callable

from backend.providers.contracts import ProviderRequest
from .schema import tool_schema

_fn = tool_schema


def register_memory_skills(provider: Any, request: ProviderRequest, connections: dict[str, Any], tools: list[dict[str, Any]], runners: dict[str, Callable]) -> None:
    # === Mãos na memória (a Hana gerencia as próprias lembranças) ===
    # Sempre expostas (memória é núcleo, não módulo opcional). Operam na
    # MemoryStore viva da request; o painel Memória mostra tudo depois.
    if request.memory is not None:
        mem_store = request.memory

        tools.append(_fn(
            "memory_search",
            "Busca nas suas memórias persistentes (perfil, fatos, diários, anotações). "
            "Use quando a Nakamura perguntar 'o que você lembra de X', quando precisar "
            "conferir um fato antigo, ou ANTES de corrigir/apagar uma memória (para achar o id).",
            params={
                "query": {"type": "string", "description": "Termos de busca"},
                "limit": {"type": "integer", "description": "Máx. resultados (padrão 8)"},
            },
            required=["query"],
        ))
        tools.append(_fn(
            "memory_save",
            "Salva uma memória persistente nova (fato, preferência, decisão, contexto importante). "
            "category: preference_like, preference_dislike, personal_fact, ou general. "
            "Use para registrar na hora algo que a Nakamura pedir para você lembrar.",
            params={
                "text": {"type": "string", "description": "O fato, curto e específico"},
                "category": {"type": "string", "enum": ["preference_like", "preference_dislike", "personal_fact", "general"]},
                "importance": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            required=["text"],
        ))
        tools.append(_fn(
            "memory_update",
            "Corrige o texto de uma memória existente pelo id (use memory_search antes para achar). "
            "Use quando a Nakamura disser que uma lembrança sua está errada ou desatualizada.",
            params={
                "id": {"type": "string"},
                "text": {"type": "string", "description": "Novo texto corrigido"},
            },
            required=["id", "text"],
        ))
        tools.append(_fn(
            "memory_delete",
            "Apaga (soft-delete, recuperável) uma memória pelo id. Use memory_search antes. "
            "Confirme com a Nakamura antes de apagar, a não ser que ela já tenha mandado apagar.",
            params={"id": {"type": "string"}},
            required=["id"],
        ))
        tools.append(_fn(
            "memory_pin",
            "Fixa (pinned=true) ou desafixa uma memória. Fixadas nunca decaem e rankeiam mais alto — use para 'nunca esqueça isso'.",
            params={"id": {"type": "string"}, "pinned": {"type": "boolean"}},
            required=["id"],
        ))

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
                current = mem_store.get_memory(memory_id)
                if not current:
                    return {"ok": False, "error": "memória não encontrada"}
                updated = mem_store.add_memory(
                    text,
                    memory_id=memory_id,
                    kind=str(current.get("kind") or "long_term"),
                    source="hana_chat_tool",
                )
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

        tools.append(_fn(
            "memory_audit",
            "Panorama da sua memória: quantas ativas, arquivadas, na lixeira, fixadas, e "
            "se a busca semântica está ligada. Use quando a Nakamura perguntar como está "
            "sua memória, ou antes de compactar — pra saber se vale a pena.",
        ))
        tools.append(_fn(
            "memory_compact",
            "Junta memórias parecidas ou repetidas numa só, mais limpa. Use quando o audit "
            "mostrar muita coisa duplicada. Passe os ids (busque antes com memory_search); "
            "sem ids, ela compacta os eventos recentes da conversa.",
            params={
                "ids": {"type": "array", "items": {"type": "string"}, "description": "Ids das memórias a juntar (opcional)"},
                "archive_originals": {"type": "boolean", "description": "true arquiva as originais depois de juntar"},
            },
        ))

        def run_memory_audit(args: dict[str, Any]) -> dict[str, Any]:
            try:
                return {"ok": True, "audit": mem_store.audit_memories()}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        def run_memory_compact(args: dict[str, Any]) -> dict[str, Any]:
            ids = [str(i) for i in (args.get("ids") or []) if str(i).strip()]
            try:
                return {
                    "ok": True,
                    "result": mem_store.compact(
                        memory_ids=ids or None,
                        archive_originals=bool(args.get("archive_originals")),
                    ),
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        runners["memory_search"] = run_memory_search
        runners["memory_save"] = run_memory_save
        runners["memory_update"] = run_memory_update
        runners["memory_delete"] = run_memory_delete
        runners["memory_pin"] = run_memory_pin
        runners["memory_audit"] = run_memory_audit
        runners["memory_compact"] = run_memory_compact

    # === Skills e scripts (ela le, escreve e melhora as proprias ferramentas) ===
    #
    # Estas SEMPRE existiram no registry do backend, mas nunca chegaram na LLM —
    # e o system prompt mandava usar assim mesmo ("leia a completa com skill_read
    # ANTES de executar"). Resultado: ela via o indice das skills e nao conseguia
    # abrir nenhuma. Tudo que a Nakamura escreveu ali era decorativo.
    #
    # Sempre ligadas: skill e linha no banco, script e arquivo na pasta dela.
    # Nao dependem de config nem de modulo opcional.
    from backend.tools import script_tools as _script_tools
    from backend.tools import skill_tools as _skill_tools

    tools.append(_fn(
        "skill_list",
        "Lista suas skills (manuais) com o título de cada uma. "
        "Use quando não souber se existe skill pra uma tarefa.",
    ))
    tools.append(_fn(
        "skill_read",
        "Lê uma skill INTEIRA. Use SEMPRE antes de executar a tarefa correspondente — "
        "o índice no prompt só tem o título; os passos, os comandos e as pegadinhas "
        "estão aqui dentro, junto das dicas que você mesma anotou.",
        params={"name": {"type": "string", "description": "Nome da skill (ex: youtube_transcribe)"}},
        required=["name"],
    ))
    tools.append(_fn(
        "skill_create",
        "Cria uma skill NOVA (manual em Markdown). Use quando aprender um processo que "
        "vai repetir. A skill é o MANUAL; o código que executa vira um script separado. "
        "Passe overwrite=true só pra substituir uma que já existe.",
        params={
            "name": {"type": "string", "description": "Nome curto em snake_case (ex: converter_video)"},
            "content": {"type": "string", "description": "A skill inteira em Markdown: passos, tools, pegadinhas"},
            "title": {"type": "string", "description": "Título legível (opcional)"},
            "overwrite": {"type": "boolean", "description": "true pra substituir uma skill existente"},
        },
        required=["name", "content"],
    ))
    tools.append(_fn(
        "skill_note",
        "Anota uma dica curta numa skill que já existe. Use quando descobrir algo útil "
        "usando ela (um parâmetro que funcionou melhor, um erro a evitar). "
        "Só dica que ensina — não anote trivialidade.",
        params={
            "name": {"type": "string", "description": "Nome da skill"},
            "note": {"type": "string", "description": "Dica curta e prática"},
        },
        required=["name", "note"],
    ))
    tools.append(_fn(
        "script_create",
        "Cria um script reutilizável (py/js/ts/ps1/sh/bat) na sua pasta de scripts. "
        "Use quando a tarefa envolver código que você vai repetir, em vez de remontar "
        "o comando toda vez. Depois rode com terminal_run.",
        params={
            "name": {"type": "string", "description": "Nome do arquivo com extensão (ex: baixar_audio.py)"},
            "content": {"type": "string", "description": "Código completo do script"},
            "overwrite": {"type": "boolean", "description": "true pra sobrescrever um script existente"},
        },
        required=["name", "content"],
    ))
    tools.append(_fn("script_list", "Lista seus scripts reutilizáveis com o tamanho de cada um."))
    tools.append(_fn(
        "script_read",
        "Lê o código de um script seu. Use antes de editar ou pra conferir o que ele faz.",
        params={"name": {"type": "string", "description": "Nome do arquivo do script"}},
        required=["name"],
    ))

    runners["skill_list"] = lambda args: {"ok": True, "skills": _skill_tools.list_skills()}
    runners["skill_read"] = lambda args: _skill_tools.read_skill(str(args.get("name") or ""))
    runners["skill_create"] = lambda args: _skill_tools.create_skill(
        str(args.get("name") or ""),
        str(args.get("content") or ""),
        title=str(args.get("title") or ""),
        overwrite=bool(args.get("overwrite")),
    )
    runners["skill_note"] = lambda args: _skill_tools.append_skill_note(
        str(args.get("name") or ""), str(args.get("note") or "")
    )
    runners["script_create"] = lambda args: _script_tools.create_script(
        str(args.get("name") or ""), str(args.get("content") or ""), overwrite=bool(args.get("overwrite"))
    )
    runners["script_list"] = lambda args: {"ok": True, "scripts": _script_tools.list_scripts()}
    runners["script_read"] = lambda args: _script_tools.read_script(str(args.get("name") or ""))

