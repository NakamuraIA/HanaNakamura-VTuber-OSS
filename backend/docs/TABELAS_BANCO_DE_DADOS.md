# Tabelas do Banco de Dados

Status: levantamento de 2026-08-04. **Atualização 2026-08-05:** `facts`,
`facts_fts` e `graph_facts` (citadas abaixo) foram removidas — eram sistemas
paralelos/mortos, fundidos em `memory_items`, documentada na seção 2.
**Atualização 2026-08-06:** a seção 5 (TTS) foi reescrita — `bd/tts.py` deixou
de ser órfão, virou uma tabela única (`tts_models`) lida por
`catalog/tts_repository.py`. Ver `DECISOES_CATALOGO_FONTES.md` §12.
**Atualização 2026-08-22:** o Agent Core passou a usar tabelas com prefixo
`agent_core_` no banco principal. O antigo `hana_agent_oss.sqlite3` estava vazio
e foi preservado no disco, mas não possui mais chamadores.
Na fase 4, `provider_models`, `schema_info` e a lista `custom_models` de
`settings` foram migrados para `llm_models` e removidos.
O First Run registra a chave `setup.initial_catalog.v1` em `settings`; essa
marca impede que modelos apagados pelo usuário voltem numa execução posterior.

A Hana usa SQLite (via stdlib `sqlite3`, sem ORM). Os caminhos ficam em
`backend/paths.py`. Cada classe de "store" herda de `SQLiteStore`
(`backend/memory/sqlite.py`), que seta WAL, `timeout=15` e `row_factory=Row`.

## Arquivos de dados

| Caminho (runtime) | Papel | Definido em |
| --- | --- | --- |
| `runtime/hana_memory.sqlite3` | banco principal (memória + catálogo + Agent Core) | `paths.py` |
| `runtime/hana_events.jsonl` | log de eventos recentes por canal | `paths.py:40` |

---

## 1. `HanaMemory` — `backend/memory/core.py` (tabelas 46-159)

| Tabela | Colunas principais | Linha |
| --- | --- | --- |
| `messages` | id, role (CHECK user/assistant), author, content (1..8000), channel (CHECK chat/discord/terminal/voice), created_at | 46 |
| (índice `idx_messages_channel`) | | 54 |
| `facts` | id, text (1..2000), kind, source, status, use_count, last_used_at, created_at, updated_at | 57 |
| (`facts_fts` FTS5 + 3 triggers) | | 71-84 |
| `pinned` | id, text (1..1000), kind (regra/giria/tarefa/fato), position, enabled (0/1), created_at | 87 |
| `chat_log` | id, session_id, role, author, content, channel, meta_json, created_at | 98 |
| `settings` | key (PK), value_json, updated_at | 115 |
| `skills` | name (PK), title, content, notes, enabled, use_count, created_at, updated_at | 125 |

Documentada em `docs/MEMORIA.md` (mensagens/pinned/chat_log/settings). O catálogo
é um domínio separado, embora use o mesmo arquivo SQLite.

## 2. `MemoryStore` — `backend/memory/store.py` (tabelas 175-225)

| Tabela | Colunas |
| --- | --- |
| `memory_items` | id (TEXT PK), text, kind, source, metadata_json, created_at, updated_at (+ colunas v2 via `_ensure_memory_item_v2_columns`) |
| `memory_fts` | FTS5 virtual (id UNINDEXED, text) |
| `graph_facts` | id, subject, relation, object, created_at (UNIQUE subject/relation/object) |
| `settings` | key, value_json, updated_at |
| `memory_embeddings` | memory_id (PK, FK→memory_items CASCADE), provider, model, dimensions, vector_json, created_at, updated_at |
| `memory_links` | id, parent_id, child_id, relation, created_at, metadata_json |

As tabelas principais deste armazenamento são `memory_items`,
`memory_embeddings`, `memory_links` e `graph_facts`.

## 3. `RuntimeStore` — `backend/memory/storage.py` + `backend/bd/agent_core.py`

| Tabela | Colunas |
| --- | --- |
| `agent_core_messages` | id, role, content, channel, context_json, created_at |
| `agent_core_events` | id, type, message, payload_json, source, created_at |
| `agent_core_tool_runs` | id, tool, args_json, result_json, ok, error, created_at |
| `agent_core_working_context` | id (PK), state_json, updated_at |

As tabelas usam prefixo porque a memória curta já possui uma tabela `messages`
com contrato diferente (`author`, canais fechados e limite de conteúdo).

## 4. Catálogo — `backend/bd/` + `backend/catalog/`

| Tabela | Colunas |
| --- | --- |
| `llm_models` | provider, model_id (PK), label, capacidades por modelo, limites, preço, modalidades, origem, estado e marca `custom` |
| `model_overrides` | provider, model_id, field_name (PK triplo), value_json, updated_at |
| `tts_models` | provider, model_id (PK), idioma e capacidades de síntese de voz |
| `stt_models` | provider, model_id (PK), idioma e capacidades de transcrição |

`bd/` cria e migra as tabelas. Os três repositórios de `catalog/` são os únicos
leitores/escritores normais. O OpenRouter continua dinâmico e não é semeado.

## 5. TTS — `backend/bd/tts.py` + `backend/catalog/tts_repository.py`

| Tabela | Colunas |
| --- | --- |
| `tts_models` | provider, model_id (PK), label, language, supports_streaming/pitch/stability/similarity/style/speaker_boost, source, observed_at, fetched_at, lifecycle_status |

Uma linha por (provider, model_id) — o id é a voz (Edge, que não separa voz de
motor) ou o modelo (Fish Audio/ElevenLabs, onde a voz é um voice_id colado pelo
usuário, não catalogável). Escopo é só os 3 providers em uso (Edge, Fish Audio,
ElevenLabs); Google Cloud TTS foi removido do código (não só do banco).

Lido/escrito por `TtsModelRepository` (mesmo padrão do `LlmModelRepository`,
mas sem tabela de overrides — TTS não tem crawler, todo dado é manual). A carga
pública vem de `backend/setup/defaults/tts_models.json`. `catalog.py` projeta essas linhas
nos dois formatos que o front consome (`voice_provider_catalog()` e
`/api/catalog`) — nenhum dos dois tem mais provider/voz hardcoded em Python.

## 6. Carga pública inicial — `backend/setup/`

| Arquivo | Destino |
| --- | --- |
| `defaults/llm_models.json` | `llm_models` |
| `defaults/tts_models.json` | `tts_models` |
| `defaults/stt_models.json` | `stt_models` |

Os arquivos são lidos somente pelo First Run ou pela restauração manual. A
fonte de verdade depois da instalação é o banco. OpenRouter não entra nesses
JSONs porque consulta o catálogo dinâmico da própria API.

---

## Resumo de duplicação/risco

- Duas classes irmãs de memória (`HanaMemory` e `MemoryStore`) escrevem no
  mesmo arquivo `.sqlite3`, mas possuem responsabilidades e tabelas diferentes:
  a primeira cuida de memória curta, fixa, configuração e histórico visual; a
  segunda cuida da memória longa recuperada pelo RAG.
- ~~O catálogo tinha duas tabelas concorrentes e uma lista paralela em
  `settings`.~~ Corrigido na fase 4: a fonte local é `llm_models`.
- ~~`bd/tts.py` cria `tts_models`/`tts_voices`, mas ninguém chama `criar_tabelas_tts`.~~
  Corrigido 2026-08-06 — ver seção 5.
