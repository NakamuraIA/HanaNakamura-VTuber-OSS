# Hana Agent OSS Architecture

Status: active big-bang migration.

Hana is now a multimodal agent framework. The Agent Core is the product. VTuber
mode is only one optional interface.

## Runtime Boundary

```txt
main.py
  -> local supervisor only

!Hana_Agent_OSS/
  -> backend and Agent Core

control_panel/
  -> frontend
```

Root `main.py` must not contain agent logic. It starts, monitors and stops the
backend/frontend stack.

## Agent Core Flow

```txt
channel input
-> AgentRequest
-> context and memory lookup
-> planner
-> policy
-> ToolCall
-> executor/provider
-> ToolResult
-> verifier
-> AgentResponse
-> channel output
```

The structured planner is still deterministic for tool commands. Free-form chat
uses the provider selector and currently routes to `gemini_api`. MCP tool use
is implemented as a client-side capability provider behind this flow.

## Backend Package Shape

```txt
hana_agent_oss/
  api/
    routers/      # FastAPI routes grouped by domain
    services/     # small API-facing helpers
    server.py     # app factory and router registration
  core/           # protocol, runtime, registries, SQLite helpers
  modules/        # executable local modules
  integrations/   # external surfaces and optional adapters
    mcp/           # MCP client config, discovery and invocation
  providers/      # provider selector + provider implementations
  subbrains/      # specialized agents
```

Routes should stay thin. Business flow belongs in `core/`, capability code
belongs in `modules/` or `integrations/`, and persistence helpers belong near
the owning store.

## Capabilities

Every extension is represented by a manifest and registry entry.

Supported capability kinds:

- tool;
- module;
- integration;
- subbrain;
- plugin;
- external process;
- MCP provider;
- channel.

Examples:

- file module;
- memory module;
- Terminal Agente channel;
- Control Panel integration;
- VTuber interface;
- web search integration;
- MCP provider.

## MCP Boundary

MCP is a client integration in this version. The backend loads configured
stdio servers from local JSON, discovers tools only for enabled servers and
executes only tools present in each server allowlist. The root launcher does
not own MCP lifecycle.

## Memory

The active memory is reset and lightweight:

- SQLite for persistent items, facts and settings;
- SQLite FTS for RAG-like retrieval;
- JSONL for append-only recent runtime events;
- compacting from recent events into persistent summaries.

Old Chroma-based data and old conversations are quarantine only. They are not
read by the active runtime.

The Terminal Agente event stream reuses the JSONL event log with its own
`terminal_agent` channel. Clearing this stream removes only terminal-agent
events and leaves other channels intact.

## Legacy Policy

XML tags, old prompt tools and previous runtime branches are not the primary
protocol. If compatibility is needed during migration, it must be isolated
behind an adapter and removed after the matching capability exists in Agent OSS.
