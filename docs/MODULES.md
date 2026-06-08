# Modules, Integrations And Subbrains

Hana capabilities are added through manifests and registries, not root launcher
logic or prompt tags.

## Capability Types

- `tool`: one callable function.
- `module`: local package with multiple tools.
- `integration`: external service or UI surface.
- `subbrain`: specialized agent with its own model/context/tools.
- `plugin`: installable capability bundle.
- `external_process`: HTTP, stdio, WebSocket or other process.
- `channel`: user-facing or agent-facing communication surface.

## Active Modules

- File module: deterministic local file operations.
- Memory module: SQLite/FTS/JSONL memory.
- Provider selector: free-form chat routing with `gemini_api` as active
  provider in this phase.

## Active Integrations

- Control Panel: React/Tauri frontend.
- VTuber Interface: optional subagent/interface slot, disabled by default.
- TTS/STT/vision/media/PC control: visible optional slots, disabled until real
  providers are installed and wired.
- Web Search: configurable provider slot.
- MCP Provider: active client transport for external tools, disabled by default
  and guarded by per-tool allowlists.

## Runtime Weight Rule

Base runtime dependencies must stay small enough to boot the backend, tests and
Control Panel contract. Voice, media, vision, provider SDKs and Tavily-style web
search belong in optional requirements/extras unless they become mandatory for a
public feature.

MCP is part of the base Agent Core V1 and uses the official Python SDK.

## Implementation Rule

When adding a capability:

1. create or update its manifest;
2. register it in the Agent Core;
3. expose tools through the registry when executable;
4. add API/UI wiring only through the backend contract;
5. update public docs if user-facing behavior changed.
