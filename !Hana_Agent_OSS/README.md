# Hana Agent OSS Backend

> ⚠️ **Aviso de estrutura:** existe uma pasta `hana_agent_oss/` dentro de
> `!Hana_Agent_OSS/` — "Hana Agent" dentro de "Hana Agent". Isso foi um erro de
> estruturação cometido na hora de montar o backend, sem motivo técnico por
> trás. Hoje dá bastante trabalho desfazer com segurança (imports, paths,
> scripts e configs todos dependem do layout atual), então ficou assim por
> enquanto. O sistema funciona normalmente apesar disso — é só confuso de
> navegar. Se alguém quiser achatar os dois níveis em um só, fico muito grata. 🙏
> — Operador

This folder is the active backend for Hana.

It owns the Agent Core, FastAPI server, tool registry, capability manifests,
lightweight memory, integration slots, subbrain slots and future MCP provider
transport.

OpenRouter LLM requests support per-model endpoint preferences. The backend
caches the endpoint catalog and applies routing preferences to normal,
streaming and tool-loop requests. Voice and Terminal reuse the primary LLM
routing configuration, while Chat keeps an independent configuration.

## Structure

```txt
!Hana_Agent_OSS
|- config
|- models
|- runtime
|- tests
`- hana_agent_oss
   |- docs
   |- api
   |  |- routers
   |  `- services
   |- channels
   |- core
   |- integrations
   |- modules
   |- plugins
   `- subbrains
```

## Run

From the repository root:

```powershell
python main.py backend-only
```

From this folder:

```powershell
python main.py "capabilities"
python main.py "tools"
python -m hana_agent_oss.api.server
```

The API binds to `127.0.0.1:8042` by default.

## Current Foundation

- standalone `HanaAgentCore`;
- FastAPI backend for the Control Panel;
- native file module;
- SQLite/FTS/JSONL memory module with v2 CRUD, soft-delete, pinning and
  optional local semantic status;
- split FastAPI routers for status, chat, memory, config/catalog, MCP and
  optional system integrations;
- centralized persona/prompt module consumed by providers and voice modules;
- Terminal Agente event channel for low-latency terminal/voice logs;
- Groq Whisper STT upload endpoint with a separate audio-in/text-out contract;
- backend `VoiceRuntime` for always-listening microphone capture, STT, text
  response and local Edge TTS playback;
- Gemini chat attachments for image, PDF, audio, video and text/code inputs;
- MCP client provider with disabled-by-default servers and per-tool allowlists;
- deterministic structured planner;
- verification step before final tool answers;
- persisted working context for active files;
- capability manifests for Control Panel, VTuber interface, web search and MCP
  provider slots.

## Terminal Agente API

The backend exposes a lightweight persistent event channel for terminal and
voice-oriented surfaces:

- `GET /api/terminal-agent/events?limit=80`
- `POST /api/terminal-agent/events`
- `DELETE /api/terminal-agent/events`
- `POST /api/terminal-agent/tts-readable`
- `POST /api/terminal-agent/tts/stop`
- `POST /api/voice/runtime/start`
- `POST /api/voice/runtime/stop`
- `GET /api/voice/runtime/status`
- `POST /api/voice/runtime/interrupt`

Supported event kinds include runtime states (`listening`, `processing`,
`speaking`, `transcription`, `response`, `tool`, `error`) plus the existing
chat/tool forms (`user_speech`, `user_text`, `assistant_thought`, `tool_call`,
`tool_result`, `assistant_text`, `assistant_speech`, `system`). Portuguese
aliases such as `ouvindo`, `processando`, `falando`, `transcricao` and
`resposta` are normalized by the backend. Events are stored in the JSONL memory
event log under the `terminal_agent` channel.

`/api/terminal-agent/tts/stop` and `/api/voice/runtime/interrupt` are the
current stop contracts for "parar fala". They raise the shared audio stop
signal, stop local Edge playback, mark local speech state as stopped and log a
non-speakable `speaking/stopped` event.

## Terminal Agente Voice Config

Terminal Agente voice settings choose provider/model/voice/microphone, but do
not own global activation:

- `/api/config/voice`: STT/TTS provider, model, voice, language, speed, pitch
  and selected input device.
- `/api/config/voice/input-devices`: backend-visible input devices when
  optional `sounddevice` is installed, always including the
  `browser_media_recorder` fallback contract for manual diagnostics.
- `/api/config/conexoes`: global STT/TTS on/off state (`stt`, `tts`) plus PTT
  and stop hotkey toggles.

The recommended capture path is now backend `sounddevice`. Browser
`MediaRecorder` stays only as the Terminal Agente settings test path.

## Voice STT API

Groq Whisper STT is exposed as a backend-only provider contract. It receives
audio bytes and returns text without using the legacy `src/` runtime or local
microphone capture.

- `POST /api/voice/stt/transcribe`
- `POST /api/voice/text/respond`
- `POST /api/voice/tts/stop`
- provider ids accepted by the endpoint: `groq` and `groq_whisper`
- default model: `whisper-large-v3`
- default language: `pt`
- required environment variable: `GROQ_API_KEY`

The endpoint accepts either a raw audio request body or a multipart/form-data
upload using a `file`, `audio` or `upload` field. Optional `model`, `language`,
`prompt` and `respond` fields may be sent with multipart uploads. When
`respond=true`, the transcript is routed through the main LLM profile and the
response is written to the Terminal Agente log. In the always-listening
runtime, the backend can also speak the final answer with Edge TTS when
`tts=true` in Conexoes. The provider reuses
the centralized persona speech context, Portuguese STT prompt guard,
ghost-phrase filtering and basic correction pass from the previous Whisper
logic. Browser `webm`, `ogg`, `mp4` and `m4a` uploads are converted to mono
16 kHz WAV through FFmpeg when FFmpeg is available. The default local path is
`C:\Ffmpeg\ffmpeg.exe`, with `FFMPEG_PATH` or `HANA_FFMPEG_PATH` as overrides.
Language aliases such as `pt-BR` are normalized to Groq's accepted `pt`.
Internal memory tags such as `<salvar_memoria>` are stripped defensively from
both display payloads and TTS speech text, including malformed/verbalized tag
leaks, so private memory instructions are never spoken.

`/api/voice/text/respond` lets the Terminal Agente send manual text through the
same response path used after STT transcription, so the command line at the
bottom of the terminal is an operator input, not just a log append.

## Voice TTS API

Edge TTS is the first active no-key TTS provider:

- `POST /api/voice/tts/synthesize`
- provider id: `edge`
- default voice: `pt-BR-FranciscaNeural`
- output: JSON with `audioBase64`, `mimeType`, selected `voice`, `rate` and
  `pitch`

The endpoint sanitizes display text before synthesis, so markdown, links,
code blocks and noisy punctuation do not have to be spoken verbatim. The
always-listening runtime reuses the same provider and plays MP3 locally through
`pygame.mixer`, pausing microphone capture while Hana is speaking.

## Discord Voice Bridge

The Discord bot is an optional process that uses the local backend as the
source of truth for STT, LLM responses and TTS. It is started separately:

```powershell
python -m hana_agent_oss.discord_bot
```

Required environment:

- `DISCORD_TOKEN`: Discord bot token only.
- `HANA_BACKEND_URL`: backend URL, default `http://127.0.0.1:8042`.
- `GROQ_API_KEY`: required when Discord voice listening is enabled.
- `FFMPEG_PATH` or `HANA_FFMPEG_PATH`: optional playback override; defaults to
  `C:\Ffmpeg\ffmpeg.exe` or `ffmpeg`.

Optional packages for receive/playback are listed in the root
`requirements-optional.txt`: `discord.py[voice]` and
`discord-ext-voice-recv`.

Discord commands:

- `!entrar`: joins the caller's voice channel using the receive-capable client.
- `!sair`: leaves the voice channel and stops receive buffers.
- `!voz on` / `!voz off`: toggles Discord voice, speaking and listening
  together.
- `!voz falar on/off`: controls whether Hana plays TTS in the voice channel.
- `!voz ouvir on/off`: controls whether Hana transcribes users in the voice
  channel.
- `!voz status`: shows the persisted Discord voice toggles.
- `!hana <mensagem>`: sends a text message to the local backend and replies in
  Discord.

The Control Panel `Conexoes` tab owns the same persisted toggles:
`discord`, `discordSpeak` and `discordListen`. Discord audio is logged under the
Terminal Agente event stream, but Discord TTS never plays through the local PC
speaker path.

## Multimodal Chat Attachments

The Control Panel chat can send attachments through the WebSocket chat payload.
The backend persists each attachment under `runtime/attachments/`, stores
metadata in memory and sends the saved file to the Gemini API provider as
Gemini content parts before calling `generate_content`.

Supported input groups:

- images: `image/*`
- audio: `audio/*`
- video: `video/*`
- documents: `application/pdf`
- text/code: `text/*`, `application/json`, `application/xml`, YAML

Small files are sent inline. Larger files are uploaded through the Gemini Files
API and then referenced in the model request. The backend WebSocket max payload
defaults to 64 MiB through `HANA_WS_MAX_SIZE` to account for base64 overhead.

Follow-up questions can reuse recent saved attachments. If the user asks about
"the PDF", "the attachment", "the image" or similar without sending a new file,
the chat service reloads recent saved attachments and sends them back to the
provider.

## Persona and Prompts

Hana's personality is not owned by a Gemini/OpenAI/STT provider. The central
profile lives under:

- `hana_agent_oss/persona/profile.py`
- `hana_agent_oss/persona/prompts.py`

Providers call prompt builders from this module. Provider-specific rules may be
added there, but the assistant identity, user relationship and speech terms stay
provider-neutral.

The central profile also owns conversation dynamics for weaker LLMs that need
more context than Gemini did. These rules push Hana to keep continuity, react
with her own presence, avoid support-bot closers such as generic "how can I
help" questions, and vary her rhythm without relying on canned example replies.

## Memory Rule

The active runtime does not use the old memory system or Chroma-based data.
Legacy local files may remain on disk as quarantine, but this backend starts
from the new lightweight memory store under `runtime/`.

## Hana Memory Fabric v1

Persistent memory stays local and lightweight:

- required fast path: SQLite + FTS5 + JSONL recent events;
- optional semantic path: `fastembed` + `sqlite-vec`, disabled by default;
- no ChromaDB server, no GPU requirement and no embedding model loaded during
  voice capture or TTS;
- `HANA_MEMORY_SEMANTIC=0` keeps the backend in pure FTS mode;
- `HANA_MEMORY_SEMANTIC=1` only reports/uses the semantic layer when optional
  dependencies are installed.

Memory APIs now support lifecycle and maintenance operations:

- `GET /api/memory/rag?query=&status=&limit=`
- `POST /api/memory/search`
- `POST /api/memory/rag`
- `PUT /api/memory/rag/{id}`
- `DELETE /api/memory/rag/{id}` for soft-delete;
- `DELETE /api/memory/rag/{id}?hard=true` for explicit permanent deletion;
- `POST /api/memory/rag/{id}/pin`
- `POST /api/memory/rag/{id}/archive`
- `POST /api/memory/rag/{id}/restore`
- `POST /api/memory/compact`
- `POST /api/memory/merge`
- `GET /api/memory/audit`
- `POST /api/memory/maintenance/run`

Hana's tool layer exposes `memory.save`, `memory.update`, `memory.delete`,
`memory.search`, `memory.compact`, `memory.merge`, `memory.pin`,
`memory.audit` and `memory.maintenance`. Normal conversation delete is
soft-delete only. `memory.clear_runtime` remains an admin reset and should not
be used in ordinary conversation.

Long-term memory is injected into provider prompts as a private block capped to
seven short text entries. IDs, tags, raw tool JSON and memory XML are not meant
for TTS or visible speech.

## Capability Rule

New behavior does not go into root `main.py`, old server monoliths or prompt
hacks. It enters as one of:

- tool;
- module;
- integration;
- subbrain;
- plugin;
- external process;
- MCP provider;
- channel.

## MCP Client

Config example lives in `config/mcp_servers.example.json`. Local runtime config
lives in `runtime/mcp_servers.local.json` or the path pointed to by
`HANA_MCP_CONFIG`.
