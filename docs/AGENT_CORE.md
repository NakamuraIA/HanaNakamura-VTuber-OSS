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
- `omni.bridge`

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
- `omni.delegate` and `omni.supervise` as background jobs through the local
  Omni-Agent OS HTTP bridge at `http://127.0.0.1:8060`;
- `agent.job.cancel` for explicit user-requested cancellation of active
  Omni jobs;
- contextual file references such as `abre ele` and `continua nele`.

The deterministic planner is only used when a caller explicitly selects the
Agent Core provider/mode. Normal chat and voice turns are not routed by matching
Nakamura's text or speech against command prefixes. In normal Gemini-backed
conversation, Hana decides tool use through provider tool-calling or assistant
output protocols; user text itself must not be treated as an action trigger.

Provider-backed LLM planning is still a future provider. MCP execution is wired
through the same tool/capability contract as a client provider.

## Gemini Provider Tools

The Gemini API provider exposes the supervised Omni bridge as the callable
function `omni_supervise`. Hana should use it only for local computer,
process, file-system, window, clipboard, OCR, or PC automation tasks. Normal
chat, STT, TTS, image generation and web search stay outside this bridge.

The callable is only exposed when the Connections config enables `omni`. The
endpoint is stored as `omniUrl`, defaults to `http://127.0.0.1:8060`, and can
be checked through `/api/config/omni/status`.

The Gemini callable keeps its schema intentionally simple: `acceptance` is a
plain string checklist instead of an array, because Gemini rejects array
parameters when the SDK-generated schema omits `items`.
Its exposed `mode` values are `inspect`, `execute` and `review`; the bridge
keeps `repair` only as a backward-compatible alias that normalizes to `review`.

When Omni is exposed as a Gemini callable, the provider must also send
`tool_config.functionCallingConfig` in `AUTO` mode. When Google Search or
another server-side Gemini tool is enabled, the same config must set
`includeServerSideToolInvocations=true`. If the installed Google SDK cannot
build that config, the provider drops only the Omni callable and keeps normal
Gemini chat/search online.

Gemini-triggered Omni calls are mirrored into the Terminal Agent log as
`omni.supervise` job events. The callable returns quickly with `job_id` and
`completion_status=running`; that only means the background job started. The
Terminal Agent receives the final report later as `job.done`, `job.failed` or
`job.cancelled`.
When the callable returns `ok=false`, the model must show the returned `error`
field instead of guessing a cause.

