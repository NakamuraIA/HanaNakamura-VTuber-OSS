# Hana Agent Core

The Agent Core is the shared backend brain for every Hana channel.

It lives under `!Hana_Agent_OSS/hana_agent_oss/core` and exposes structured
requests, events, tool calls, tool results, verification and capability
registries.

## Core Contract

- `AgentRequest`: normalized user/channel request.
- `AgentResponse`: final response with events, planner result and optional tool
  result.
- `AgentEvent`: observable runtime event.
- `ToolCall`: structured action selected by the planner.
- `ToolResult`: structured result returned by a tool/provider.
- `CapabilityManifest`: metadata for tools, modules, integrations, subbrains,
  plugins, external processes and MCP providers.

## Built-In Capabilities

- `hana.agent_core`
- `file.module`
- `memory.module`
- `control_center.integration`
- `browser.integration`
- `vtuber.interface`
- `web_search.integration`
- `mcp.provider`
- `terminal.module`

## Channels

Built-in channel profiles:

| Channel | Purpose |
| --- | --- |
| `terminal` | Low-latency terminal/voice interaction. |
| `control_center` | Main desktop UI and chat. |
| `api_subagent` | Structured agent-to-agent calls. |

Channels are interfaces connected to the same core. They must not become
separate brains.

The Terminal Agente surface has a dedicated event API backed by the lightweight
JSONL memory log. Its event channel is `terminal_agent`, separate from
`control_center`, and supports low-latency voice/agent event kinds such as
`user_speech`, `assistant_thought`, `tool_call`, `tool_result` and
`assistant_speech`.

Text shown in terminal/chat can differ from text sent to TTS. Backend helpers
sanitize markdown, code blocks, links and raw punctuation by default before a
future TTS provider consumes the text.

## Current Planner

The current planner is deterministic and supports:

- `tools`;
- `capabilities`;
- file commands;
- memory commands;
- `mcp.discover` and `mcp.invoke`;
- `terminal.run` for local commands/scripts through Hana's in-process hands;
- contextual file references such as `abre ele` and `continua nele`.

The deterministic planner is only used when a caller explicitly selects the
Agent Core provider/mode. Normal chat and voice turns are not routed by matching
Operador's text or speech against command prefixes. In normal Gemini-backed
conversation, Hana decides tool use through provider tool-calling or assistant
output protocols; user text itself must not be treated as an action trigger.

Provider-backed LLM planning is still a future provider. MCP execution is wired
through the same tool/capability contract as a client provider.

## Provider Tools

Local PC actions use Hana's in-process "hands": `terminal_run` (run a shell
command with timeout + output cap; `shell` can be `cmd`, `powershell` or `bash`)
and `terminal_inspect_dir` (list a folder). They are exposed to tool-capable
OpenRouter models (gated by the `localHands` toggle in Conexoes) and run
directly in the backend — there is no separate executor service.

Safety is enforced by the persona rules: before destructive/irreversible actions
(delete, format, admin, credentials/.env) Hana must investigate, show what she
will do and confirm with the user. When a tool returns `ok=false`, the model
must show the returned `error` instead of guessing a cause.

The Gemini API provider exposes MCP callables (`mcp_discover`, `mcp_invoke`) when
configured. When server-side Gemini tools (e.g. Google Search) are enabled, the
provider sends `tool_config.functionCallingConfig` with
`includeServerSideToolInvocations=true`.

Tool activity is mirrored into the Terminal Agent log as `tool_call` /
`tool_result` events.

