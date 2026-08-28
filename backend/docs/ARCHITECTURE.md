# Hana Agent OSS Backend Architecture

Status: active backend.

The backend is responsible for the Agent Core, API, WebSockets, capability
registries, tools, memory and integration slots.

## Flow

```txt
Control Panel / terminal / browser / external agent
-> AgentRequest
-> HanaAgentCore
-> planner
-> policy slot
-> executor or provider
-> ToolResult
-> verifier
-> AgentResponse
```

## Current Runtime

- deterministic planner;
- file module;
- memory module;
- FastAPI compatibility API;
- Terminal Agente event API;
- Voice STT API using Groq Whisper as a separate audio-in/text-out provider;
- chat/status/emotion WebSockets;
- browser snapshot endpoint;
- Control Panel integration manifest;
- VTuber optional interface manifest;
- web search integration manifest;
- MCP provider manifest.

## Stores

```txt
runtime/hana_memory.sqlite3
runtime/hana_events.jsonl
```

The SQLite database is the single source for memory, configuration, catalogs
and Agent Core persistence. Agent Core tables use the `agent_core_` prefix so
they do not collide with canonical conversation tables. The JSONL file stores
recent channel events. Terminal Agente events use the `terminal_agent` channel
and are clearable without deleting Control Panel events.

## First Run

`Hana-First-Run.cmd` is the public entrypoint used once on a new installation.
It calls `backend/setup/database.py`, which validates the three public JSON
catalogs before creating a temporary SQLite database. The temporary file only
becomes `runtime/hana_memory.sqlite3` after schemas, catalogs and the setup
marker are complete. Normal Hana startup never reads those JSON files.

An existing database without the setup marker is treated as an older
installation and is preserved without automatic import.

## Memory

The active memory is clean and local to Agent OSS. Older memory/vector data may
remain on disk as quarantine, but it is not read by this backend.

## Migration Rule

Legacy behavior can only return as a module, integration, subbrain, plugin,
external process or MCP provider. Root launcher logic and prompt-tag protocols
are not valid homes for new behavior.

## Voice STT Contract

STT providers are separate from LLM and TTS providers. The current implemented
provider is `groq_whisper`, backed by `GROQ_API_KEY` and defaulting to
`whisper-large-v3` with language `pt`.

The public API entrypoint is `POST /api/voice/stt/transcribe`. It accepts audio
upload bytes and returns a structured payload with provider, model, language,
transcribed text, raw text and whether the result was filtered as a ghost
phrase/noise. With `respond=true`, the backend routes the transcript through
the main Cerebro & Voz LLM config and appends the text response to the Terminal
Agente channel without TTS. The backend does not reactivate legacy `src.*`
imports, keyboard hooks or local microphone capture for this path.
