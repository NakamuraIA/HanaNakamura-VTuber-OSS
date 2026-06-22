# Hana Agent OSS

Hana Agent OSS is a local multimodal agent framework built around Hana
Operador.

The project is no longer VTuber-first. The VTuber surface is now an optional
interface or subagent. The product is the Agent Core: one backend that can
coordinate tools, memory, channels, media modules, MCP
providers and specialized subagents.

## Active Architecture

```txt
main.py
  -> starts and supervises the local stack

!Hana_Agent_OSS/
  -> backend, Agent Core, API, tools, memory and capability registries

control_panel/
  -> React/Tauri frontend
```

The old backend tree is legacy and is not part of the runtime target. New
capabilities must be added to `!Hana_Agent_OSS/` as tools, modules,
integrations, subbrains, plugins, external processes or MCP providers.

## What Hana Can Become

| Form | Description |
| --- | --- |
| Desktop Agent | Local workflows, files and system tools with permission gates. |
| Coding Agent | Project navigation, edits, tests and review loops. |
| Media Agent | Image, music, audio, video and creative pipelines. |
| VTuber Interface | Optional avatar, voice and expression layer. |
| Game NPC | Specialized subbrain connected through game APIs. |
| Agent Orchestrator | Controller for MCP servers and external agents. |

## Runtime

Run the full local stack:

```powershell
python main.py
```

Other modes:

```powershell
python main.py backend-only
python main.py frontend-only
python main.py healthcheck
python main.py shutdown
```

The backend listens on `http://127.0.0.1:8042`. The Control Panel dev server
listens on `http://127.0.0.1:5173`. The default launcher reuses already-running
healthy services instead of starting duplicate processes, waits for both
healthchecks and opens the Control Panel in the browser unless
`HANA_OPEN_BROWSER=0` is set.

## Backend

The active backend is `!Hana_Agent_OSS/`.

It provides:

- `HanaAgentCore`;
- structured `AgentRequest`, `AgentResponse` and `AgentEvent`;
- `ToolCall`, `ToolResult` and `CapabilityManifest`;
- registries for tools, modules, integrations, subbrains, plugins and MCP
  providers;
- FastAPI routes for the Control Panel;
- WebSockets for chat, status and emotion streams;
- a lightweight memory system.
- MCP client support with disabled-by-default servers and per-tool allowlists.

The FastAPI surface is split by domain under
`!Hana_Agent_OSS/hana_agent_oss/api/routers/`, with small services under
`api/services/`. Root `main.py` remains a supervisor and must not regain route,
agent, memory or media logic.

Structured commands still use the deterministic Agent Core. Normal chat turns
run through the provider selector. Active LLM providers are Gemini API
(`gemini_api`), OpenRouter (`openrouter`) and Groq (`groq`). OpenRouter and
Groq use dynamic model catalogs and disable Gemini-only LLM features when
selected; STT and TTS providers remain separate.

Chat configuration is separate from the Terminal Agente runtime profile:

- `/api/config/llm` controls the main brain tab and the Chat do Controle TTS
  profile. The CÃ©rebro screen labels that voice block as "TTS do Chat"; it is
  persisted separately from Terminal Agente voice settings.
- `/api/config/chat` controls chat provider/model/native-search defaults.
- OpenRouter models remember preferred internal endpoints separately for
  Cerebro/voice/Terminal and Chat, with optional privacy and fallback controls.
- `/api/config/voice` controls Terminal Agente STT/TTS provider, model, voice
  and microphone settings.
- `/api/config/conexoes` controls whether STT/TTS/VAD/PTT/hotkeys are globally
  active and synchronizes the backend voice runtime immediately.
- `/api/voice/stt/transcribe` exposes the current Groq Whisper STT upload path.
- `/api/voice/tts/synthesize` exposes the current backend TTS synthesis path.
  Chat "Gerar voz" and auto-TTS call this endpoint with the persisted Chat TTS
  provider, model, voice, language, prompt, speed and pitch.
- `/api/voice/tts/speak` speaks text with the selected TTS provider when TTS is
  active in Conexoes.
- `/api/voice/runtime/start`, `/api/voice/runtime/stop`,
  `/api/voice/runtime/configure`, `/api/voice/runtime/status` and
  `/api/voice/runtime/interrupt` expose the backend-owned Terminal Agente
  runtime. Runtime start/configure reads the persisted `/api/config/voice` and
  `/api/config/conexoes` state; request payloads do not override activation.
- `/api/terminal-agent/tts/stop` and `/api/voice/tts/stop` expose the current
  "parar fala" contract.

The first active STT provider is `groq_whisper`, using `GROQ_API_KEY` and
`whisper-large-v3`. When STT is enabled in `Conexoes`, the backend captures the
selected microphone through `sounddevice`, uses a simple RMS/VAD gate, sends a
finished utterance to Groq Whisper, routes the transcript to the main LLM
profile and logs the whole flow in Terminal Agente. The settings panel keeps a
browser `MediaRecorder` STT test path only for diagnostics. WebM/OGG/MP4 audio
uploads are still converted to WAV with FFmpeg when available. The no-key TTS
provider is `edge`, which is spoken locally by the backend through `pygame` when
TTS is enabled in `Conexoes`. The active cloud TTS providers are
`gemini_tts`, `google_cloud_tts`, `azure`, `cartesia`, `minimax` and
`elevenlabs`. `gemini_tts` uses Gemini API speech
generation for higher acting quality and prompt-based tone control, but it is
not the low-latency streaming path. `google_cloud_tts` uses a dedicated
`GOOGLE_CLOUD_TTS_API_KEY` restricted to Cloud Text-to-Speech, supports classic
speaking-rate/pitch controls and falls back to REST MP3 when streaming
credentials or a streaming-compatible voice are unavailable. ElevenLabs accepts
any voice ID from the user's library and exposes Flash/Turbo/Multilingual/v3
model selection plus stability, similarity, style, speaker boost and speed.
`ttsVolume` controls local playback volume for the Terminal runtime and Chat
audio players without changing the provider synthesis request. If VAD is
disabled, the backend does not transcribe open-room audio; speech input must
come from PTT or a manual diagnostic test. PTT uses a lighter noise gate than
open-room VAD so short intentional phrases are accepted, while silence still
stays out of Groq.
Stop hotkeys interrupt current TTS and return the runtime to the correct
listening or standby mode; the Edge streaming player has its own stop signal so
F8 does not leave the microphone capture loop stalled. The runtime keeps a live
VAD capture thread alive during F8 and only starts a replacement if that thread
has already exited. Long Edge TTS responses use the Edge streaming path in the
voice runtime, so playback can begin while audio is still arriving instead of
waiting for one large MP3 file to finish generating.

The Control Center chat also has a manual browser microphone button. It records
with `MediaRecorder`, posts the audio to `/api/voice/stt/transcribe` using the
saved voice config and fills the chat input with the transcript for review. Chat
`Gerar voz` creates an audio player attached to the Hana message using
`/api/voice/tts/synthesize`; optional auto-TTS does the same after every Hana
response. This chat audio path does not force immediate backend playback, so
the user can pause, seek, download or change local playback speed per message.

## Memory

The active memory system starts clean.

- SQLite stores persistent notes, facts and settings.
- SQLite FTS provides lightweight RAG-style search.
- JSONL stores recent runtime events.
- The compact command turns recent events into persistent summaries.

Old local memory and previous Chroma-based data are quarantine only. They are
not read by the new runtime and are not migrated automatically.

## MCP

Hana can connect to external MCP servers as a client. Servers are configured in
`!Hana_Agent_OSS/runtime/mcp_servers.local.json` or through `HANA_MCP_CONFIG`.
No server is enabled by default and no tool runs until it is allowlisted.

See [MCP Client](docs/MCP.md).

## VTuber Boundary

Hana is a multimodal agent. VTuber mode is optional.

If enabled later, the VTuber layer should be implemented as a subagent or
interface capability that connects voice, expressions and VTube Studio to the
same Agent Core.

## Development Checks

Install the base runtime first:

```powershell
pip install -r requirements.txt
```

Optional providers and media/voice integrations live in
`requirements-optional.txt` and the Agent OSS `integrations` extra. They are not
required for the base backend to boot.

```powershell
python -m compileall main.py !Hana_Agent_OSS/src
pytest -q
cd control_panel
npm run build
cd src-tauri
cargo check
```

## Public Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Agent Core](docs/AGENT_CORE.md)
- [Modules and Capabilities](docs/MODULES.md)
- [MCP Client](docs/MCP.md)
- [Installation](docs/INSTALL.md)
- [Configuration](docs/CONFIG.md)
- [Providers](docs/PROVIDERS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)
- [Control Panel](control_panel/README.md)

Private planning and status docs live under `docs/private/` and are not public
usage documentation.

## License and Brand

Source code is licensed under **AGPL-3.0-only**. See [LICENSE](LICENSE).

The Hana Operador identity, official brand, official character assets and
official promotional media are protected separately by project brand policy.
See [NOTICE](NOTICE), [TRADEMARK.md](TRADEMARK.md) and
[assets/LICENSE.md](assets/LICENSE.md).
