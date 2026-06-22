# Hana Agent OSS Configuration

Configuration is moving to the Agent OSS backend and Control Panel settings.

## Runtime Environment

The backend loads `E:\Projeto_Hana_AI\.env` first, then optional backend-local
`.env` files. Keep real secrets in `.env`; it is ignored by git. Public
examples belong in `.env.example`.

Useful environment variables:

```env
HANA_BACKEND_HOST=127.0.0.1
HANA_BACKEND_PORT=8042
HANA_FRONTEND_PORT=5173
HANA_WS_MAX_SIZE=67108864
HANA_RUNTIME_DB=!Hana_Agent_OSS/runtime/hana_agent_oss.sqlite3
HANA_MEMORY_DB=!Hana_Agent_OSS/runtime/hana_memory.sqlite3
HANA_MEMORY_EVENTS=!Hana_Agent_OSS/runtime/hana_events.jsonl
```

## Dependencies

`requirements.txt` is the base runtime and test set. It intentionally stays
small: FastAPI/Uvicorn, psutil, httpx, websockets, pytest and the official MCP
Python SDK.

Optional voice, media, provider, vision and web-search packages are listed in
`requirements-optional.txt` and in the Agent OSS `integrations` extra. Install
them only when enabling the matching capability.

## LLM Providers

The Control Panel keeps provider/model preferences through the backend settings API:

- `/api/config/llm`: main "Cerebro & Voz" profile plus the Chat do Controle
  TTS profile.
- `/api/config/chat`: chat profile (provider/model/native-search mode).
- `/api/config/voice`: Terminal Agente STT/TTS provider, model, voice and
  microphone profile.
- `/api/config/voice-converter`: optional post-TTS RVC converter profile.
- `/api/config/voice/catalog`: planned STT/TTS provider metadata.
- `/api/config/voice/input-devices`: input-device listing contract.
- `/api/config/conexoes`: global feature activation, including STT/TTS on/off.

Free-form chat routes to the selected LLM provider. The active LLM providers
are `gemini_api`, `openrouter` and `groq`. STT and TTS providers stay separate
and are not changed when the LLM provider changes.
Structured commands such as `tools`, `capabilities`, `file.*`, `memory.*` and
`mcp.*` still route through the deterministic Agent Core.

Chat attachments are provider-owned in the backend. The Control Panel sends
base64 data URLs with file name, MIME type and size; the backend persists them
under `!Hana_Agent_OSS/runtime/attachments/` and stores searchable metadata in
memory. The Gemini provider turns supported image, PDF, audio, video and
text/code files into Gemini content parts. Small files are inline; larger files
use the Gemini Files API. Because WebSocket payloads include base64 overhead,
`HANA_WS_MAX_SIZE` defaults to 64 MiB.

Follow-up questions that reference a recent file or attachment can reload saved
attachments automatically, so the user does not need to upload the same PDF,
image, audio or video again for every question.

Persona and prompt text are centralized in the Agent OSS backend under
`!Hana_Agent_OSS/hana_agent_oss/persona/`. The persona profile defines who
Hana is, who the main user is and the stable speech terms. Provider modules only
consume prompt builders from that layer and may add provider-specific runtime
rules there.

Legacy local settings using `google_platform`, `google_cloud`, `google`,
`google_ai_studio` or `gemini` are normalized to `gemini_api` so old Control
Panel state does not hide the Gemini model catalog. Legacy `open_router` and
`openrouters` values are normalized to `openrouter`. Groq aliases
`groq_cloud`, `groqcloud` and the spoken shorthand `glock` are normalized to
`groq`.

Required environment variables:

```env
GOOGLE_API_KEY=...
# or
GEMINI_API_KEY=...

# OpenRouter LLM only
OPENROUTER_API_KEY=...
# Optional attribution headers sent to OpenRouter.
OPENROUTER_SITE_URL=
OPENROUTER_APP_NAME=Hana Agent OSS

# Groq LLM and Groq Whisper STT
GROQ_API_KEY=...

# Google Cloud Text-to-Speech only
GOOGLE_CLOUD_TTS_API_KEY=...
# Optional, only for Cloud TTS streaming through ADC/service account.
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
```

If the provider is missing credentials or optional SDKs, the chat returns a
visible `Provider ... nao conectado` message.

When `openrouter` is selected, Gemini-only LLM features are disabled for that
turn: native Google Search grounding, Gemini server-side tools and Gemini image
XML execution do not run. OpenRouter model capabilities come from the dynamic
OpenRouter models catalog. Vision/file attachments are sent only to models that
advertise the matching modality; if a text-only model receives an image, the
backend returns a clear provider error instead of silently ignoring it. Local
tools such as the terminal hands (`terminal_run`, `terminal_inspect_dir`) and MCP
are exposed only when the selected OpenRouter model advertises tool-call support.

When `groq` is selected, Gemini-only LLM features are also disabled. Groq models
use the OpenAI-compatible Chat Completions endpoint at
`https://api.groq.com/openai/v1/chat/completions`. The model catalog is fetched
from `https://api.groq.com/openai/v1/models` with a fallback list for the known
production/preview models. `meta-llama/llama-4-scout-17b-16e-instruct` is the
Groq vision model in the starter catalog. `groq/compound` and
`groq/compound-mini` are Groq-managed Compound systems with native server-side
search/code execution; they do not use Gemini or Tavily MCP for those native
actions. Local tools are still exposed only when the selected Groq model is
marked as tool-call capable and the matching bridge is enabled.

The CÃ©rebro screen exposes the `/api/config/llm` TTS fields as `TTS do Chat`.
Those fields control the provider, model, voice, language, style prompt,
speed, pitch and streaming preference used by Chat "Gerar voz" and chat
auto-TTS. This is intentionally separate from the Terminal Agente voice
runtime.

Voice config is persistent, but it does not own global activation. The Terminal
Agente stores provider/model/voice/language/speed/pitch and selected microphone
there. The Conexoes config owns whether STT, TTS, VAD, PTT and stop hotkeys are
active through `stt`, `tts`, `vad`, `ptt` and `stopHotkey`. Saving Conexoes now
syncs the backend voice runtime immediately, so TTS and STT toggles do not wait
for a later chat turn. The current STT contract includes `groq_whisper` for the Terminal
Agente microphone test flow plus `gemini_audio`, `openai` and `local` as
reserved adapters. The default Groq Whisper prompt is built from the same
central persona speech context. Active TTS providers are `edge`, `gemini_tts`,
`google_cloud_tts`, `azure`, `cartesia`, `minimax` and `elevenlabs`. Edge is
the no-key local provider, Gemini TTS uses
Gemini API speech generation with prompt-based acting control, and Google Cloud
TTS uses a dedicated `GOOGLE_CLOUD_TTS_API_KEY` with classic rate/pitch
controls. ElevenLabs uses `ELEVENLABS_API_KEY`, accepts a custom voice ID and
persists model, speed, stability, similarity, style and speaker boost controls.
Both Chat TTS and Terminal TTS persist `ttsVolume` from `0.0` to `1.0`; this is
a local playback setting and is not forwarded to the synthesis provider.
TTS is still gated by Conexoes, so audio is generated/spoken only
when `tts=true`.

Runtime endpoints are not configuration owners. `POST /api/voice/runtime/start`
and `POST /api/voice/runtime/configure` re-read the persisted voice and
Conexoes settings before touching the live runtime. To change provider, speed,
voice, microphone, VAD or activation, save `/api/config/voice` or
`/api/config/conexoes` first, then call runtime start/configure if the UI needs
an immediate refresh.

Local PC actions are handled by Hana's in-process "hands" tools (`terminal_run`,
`terminal_inspect_dir`), gated by the `localHands` toggle in Conexoes. They run
commands/scripts with a timeout and output cap; destructive actions require user
confirmation (enforced by the persona rules). There is no separate executor
service to configure.

## Agent Jobs

The backend keeps a generic background-job system for long-running agent tasks,
retaining the last 50 finished jobs in the SQLite settings store. The endpoints
are:

- `GET /api/agent-jobs`
- `GET /api/agent-jobs/{job_id}`
- `POST /api/agent-jobs/{job_id}/cancel`
- `POST /api/agent-jobs/cancel-active`

Active process handles stay in memory only; after a backend restart, stale
running jobs are marked as `failed` with `backend_restarted`. Terminal Agent
receives `job.started`, progress, `job.done`, `job.failed` and `job.cancelled`
events.

Voice-converter config is separate from STT/TTS provider selection:

```json
{
  "enabled": false,
  "backend": "advanced_rvc_worker",
  "pythonPath": "",
  "scriptPath": "",
  "modelPath": "",
  "indexPath": "",
  "f0Method": "rmvpe",
  "pitch": 0,
  "indexRate": 0.6,
  "protect": 0.33,
  "timeoutSeconds": 45,
  "outputSampleRate": 0
}
```

RVC runs after Edge TTS synthesis. `enabled=true` requires a compatible external
runtime script plus a `.pth` model path; `.index` is optional but recommended
for matching a trained voice. The recommended local backend is
`advanced_rvc_worker`, which starts `hana_rvc_worker.py` in the external
Advanced-RVC environment and keeps the model loaded between phrases. If
`scriptPath` still points at the older `hana_rvc_wrapper.py`, the worker backend
uses the sibling `hana_rvc_worker.py` automatically. `external_cli` remains
available for compatibility, but it reloads the CLI for each phrase and is much
slower.

The Terminal Agente settings panel writes this contract through
`/api/config/voice-converter`, displays `rvc=on/off` and `rvc_backend=...`, and
can call `POST /api/voice/rvc/preflight` to verify whether the configured
backend is ready without running inference. `POST /api/voice/rvc/test` then
generates a sample and reports whether it was converted or used the Edge
fallback. On the current CPU-only Advanced-RVC setup, conversion can be several
seconds per short phrase even with the persistent worker; sub-second latency
will require a GPU-capable runtime, a faster sidecar or a cloud converter.

Input devices can be requested through `/api/config/voice/input-devices`.
Backend enumeration uses optional `sounddevice` when it is installed. The
response still includes a `browser_media_recorder` fallback for manual STT
diagnostics, but the preferred continuous capture path is now the backend voice
runtime.

When `stt=true` and `vad=true` in Conexoes with PTT disabled, the backend opens
the selected `sounddevice` input, detects start/end of speech with RMS/VAD,
writes a mono 16 kHz WAV in memory and calls Groq Whisper only after a real
utterance ends. Use `POST /api/voice/runtime/start` to start the runtime and
`POST /api/voice/runtime/configure` to re-apply the already-saved provider,
microphone, VAD and TTS settings without a full restart.
Use `GET /api/voice/runtime/status` to inspect `idle`, `listening`,
`standby`, `recording`, `transcribing`, `thinking`, `speaking` or `error`. Use
`POST /api/voice/runtime/stop` when `stt=false`, and
`POST /api/voice/runtime/interrupt` for stop-hotkey or "parar fala". If
`vad=false`, always-listening is disabled and audio input must come from PTT or
the manual STT diagnostic.

The Control Panel STT test sends microphone audio as `multipart/form-data` to
`/api/voice/stt/transcribe` and expects a JSON response with `text`.
When `respond=true` is sent, the backend routes the transcript through the main
`/api/config/llm` profile and returns `assistantText`. Transcripts and answers
are appended to the Terminal Agente event log. Browser audio formats such as
WebM/OGG/MP4 are converted to mono 16 kHz WAV before Groq when FFmpeg is
available. The default FFmpeg path is `C:\Ffmpeg\ffmpeg.exe`; use
`FFMPEG_PATH` or `HANA_FFMPEG_PATH` to override it. `pt-BR` is normalized to
`pt` before calling Groq because Groq's Whisper endpoint expects short language
codes.

The Chat do Controle microphone uses the same STT endpoint with
`respond=false`. The transcript is inserted into the chat text box, so Operador
can review or edit it before sending. This is a manual browser capture path and
does not replace the backend always-listening runtime.

PTT is controlled by the backend global hotkey listener through the optional
`keyboard` package. `ptt=true` and `pttKey` record while the key is held;
releasing the key closes the WAV and sends the utterance to the same STT/LLM
path. PTT uses a lighter backend gate than always-listening VAD: short
intentional words such as "oi" are accepted, while silence or accidental key
taps are still discarded before Groq. `stopHotkey=true` and `stopKey` interrupt
TTS even when the Control Panel is not focused; after interruption the runtime
returns to `listening` for VAD mode or `standby` for PTT mode. In VAD mode the
runtime does not stop a live backend capture thread during F8; it clears stale
stop state and starts a new capture only if the previous thread has already
exited. PTT also clears stale stop state before opening a recording, so an old
stop signal cannot make F2 start a dead capture. Manual typed terminal commands
use `/api/voice/text/respond` and are routed through the same LLM response path
as STT transcripts. The Terminal settings panel keeps a browser MediaRecorder
STT test button, but that is only a diagnostic upload path, not the continuous
listening loop.

Terminal/chat display text may differ from TTS text. Use
`/api/terminal-agent/tts-readable` to sanitize markdown, code blocks, links and
raw punctuation. The sanitizer also removes emoji before speech. Use
`/api/voice/tts/synthesize` to generate an audio payload from the sanitized
text, or `/api/voice/tts/speak` to speak text through the selected backend TTS
provider. Chat "Gerar voz" uses the synthesize endpoint with the CÃ©rebro
`TTS do Chat` config and attaches the result as an audio player to the Hana
message instead of forcing immediate backend playback. The chat can also enable
auto-TTS, which generates that audio player after each Hana response. `edge` can stream runtime playback with
`edge_tts.Communicate.stream()`, so long answers can start while audio is still
arriving. `gemini_tts` returns complete audio and is best for
expressive/prompt-directed acting, but it does not use numeric rate/pitch
controls. `google_cloud_tts` uses REST MP3 with
`GOOGLE_CLOUD_TTS_API_KEY`; `ttsSpeed` maps to `speakingRate` and `ttsPitch`
maps to Cloud TTS pitch. If `ttsStreaming=true`, the backend attempts Cloud TTS
client-library streaming only when `GOOGLE_APPLICATION_CREDENTIALS` is present
and the selected voice is streaming-compatible; otherwise it logs the fallback
and uses REST MP3. In the voice runtime, only Edge uses the chunk streaming
contract. ElevenLabs, Gemini TTS, Google Cloud TTS, Cartesia, Azure and Minimax
use their normal complete-audio `synthesize` contract before local playback.
TTS audio is played locally by the backend through `pygame.mixer`, respects
`ttsVolume`, and microphone capture is paused while speech is
active. ElevenLabs sends the selected `ttsVoice` directly as its voice ID,
normalizes `pt-BR` to API language code `pt`, and supports
`eleven_flash_v2_5`, `eleven_turbo_v2_5`, `eleven_multilingual_v2`,
`eleven_v3` or a manually entered model ID. The Edge streaming player owns a
local stop flag in addition to the
shared stop signal, which lets F8 halt playback without leaving the global
audio stop set for the next STT capture cycle. `/api/voice/tts/synthesize`
still returns one complete audio payload for diagnostic/download-style use.
Use `/api/terminal-agent/tts/stop` or `/api/voice/tts/stop` for the "parar
fala" contract. The endpoints raise the shared audio stop signal and append a
non-speakable Terminal Agente event.

To keep startup light, install provider SDKs only when needed:

```powershell
pip install -r requirements-optional.txt
```

The full launcher opens the Control Panel by default after the frontend
responds. Set `HANA_OPEN_BROWSER=0` to keep it terminal-only.

## MCP

MCP config is local JSON:

```env
HANA_MCP_CONFIG=!Hana_Agent_OSS/runtime/mcp_servers.local.json
```

When the variable is not set, the backend reads
`!Hana_Agent_OSS/runtime/mcp_servers.local.json` if it exists, otherwise it
falls back to `!Hana_Agent_OSS/config/mcp_servers.example.json`.

Servers stay disabled until explicitly enabled. Tools stay blocked until added
to `allowed_tools`.

## Memory

The active memory system is:

- SQLite persistent store;
- SQLite FTS retrieval;
- JSONL event log;
- compact summaries.

The Terminal Agente uses the same JSONL event log with the `terminal_agent`
channel. It can be listed, appended and cleared without clearing Control Panel
chat events. Event kinds support `listening`, `processing`, `speaking`,
`transcription`, `response`, `tool` and `error`, with Portuguese aliases such
as `ouvindo`, `processando`, `falando`, `transcricao` and `resposta`
normalized by the backend.

Old local memory databases and previous vector stores are not read by the new
runtime.

## Optional Interfaces

- VTuber: optional interface/subagent, disabled by default.
- TTS/STT/vision/media/PC control: optional capabilities, not root runtime
  requirements. STT now has backend continuous capture for `groq_whisper`;
  TTS has Edge synthesis plus backend playback when enabled.
- MCP: base client capability, but every external server remains disabled by
  default.

## Files That Must Stay Local

- `.env`
- runtime databases under `!Hana_Agent_OSS/runtime/`
- local memory quarantine
- generated media, logs and caches
- private docs under `docs/private/`
