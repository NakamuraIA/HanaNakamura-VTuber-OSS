# Hana Agent OSS Control Center

Tauri 2 + React desktop interface for Hana Agent OSS and Hana Nakamura.

The Control Center is the main GUI for chat, provider selection, memory, VTube Studio status and Agent Core traces.

## Main Features

- Visual chat with Markdown rendering.
- Local chat sessions to avoid loading huge histories into the UI. Empty
  auto-created sessions are not restored after reload, so refresh does not
  flood the selector with blank conversations.
- Message deletion and media deletion.
- Generated media preview and download without leaving the chat view.
- Chat message audio generation: `Ouvir/Gerar voz` creates a Hana-styled
  chat-local audio player with seek, pause, download and playback-speed
  controls instead of speaking immediately over the backend.
- Optional chat auto-TTS generates the same audio player after each Hana
  response, using the `TTS do Chat` profile saved in the `Cerebro & Voz` tab
  and the central TTS sanitizer.
- Chat microphone input records through browser MediaRecorder, sends the audio
  to the backend STT provider, and fills the text box with the transcript so
  the user can review before sending.
- Generic attachments: images, GIFs, audio, video, text files, JSON, Markdown and PDF.
- Collapsible chat configuration bar so provider/model/history controls do not
  occupy the reading area all the time.
- Provider-scoped model and voice catalogs use themed searchable pickers with
  local favorites. LLM catalogs also expose objective filters for free/cheap
  entries, context size and declared vision, document and tool capabilities.
- Chat provider/model config persists in `/api/config/chat`; Chat TTS provider,
  voice, model, language and prompt persist in `/api/config/llm` under the
  `TTS do Chat` block. Terminal Agente TTS remains separate in
  `/api/config/voice`.
- ElevenLabs TTS accepts manually pasted voice/model IDs in both voice profiles
  and exposes speed, stability, similarity, style and speaker boost controls.
- Chat and Terminal TTS profiles persist local playback volume. Generated Chat
  audio also exposes a per-message volume slider.
- Chat conversations reopen at the latest message after refresh, session
  changes or returning from another tab. A content resize observer keeps the
  active streamed response, Agent Mode steps, sources and media visible while
  they grow. Scrolling upward intentionally pauses follow mode and reveals a
  compact `Mais recente` button.
- `Web auto/on/off` toggle for Gemini Grounding with Google Search.
- Chat model selection reuses the searchable catalog from `Cerebro`, including
  provider-scoped favorites and free/cheap/context/capability filters.
- Agent Mode plan/status cards stay expanded during an active turn, preserve
  tool summaries after completion and render grounding queries/source links.
- The Chat visual streamer uses the operational WebSocket for every provider,
- The active Chat streamer bypasses deferred history rendering, reveals provider
  output through smooth character batches, and keeps a compact operational activity preview
  visible while OpenRouter models or tools are running.
- OpenRouter selectors in Cerebro and Chat include a searchable per-model
  endpoint router with favorites, fallback, parameter, data-collection and ZDR controls.
  so typewriter output no longer bypasses Agent Mode events on OpenRouter.
- `Terminal Agente` page with an operational console log, copy/clear controls,
  backend voice-runtime status lines and a top configuration panel for STT/TTS
  provider, model, voice, language, input device selection and optional RVC
  post-processing.
- Permission modal for tool approvals, denials and timeout countdowns.
- Safety mode selector: `Safe`, `Assisted`, `Trusted` and `Dev Unsafe`.
- Emergency stop button while `Dev Unsafe` is active.
- i18next base structure for future UI translations.

## Post-Big-Bang Cleanup State

- `TabConexoes` uses shared module toggle cards and the `useConnections` hook.
- `TabVTube` reads state through `ApiController` instead of direct `fetch`.
- `TabChat` keeps media rendering and permission modal in focused components.
- `TabChat` keeps provider/model/session controls hidden behind the `Config`
  toggle by default.
- `TabMCP` exposes MCP servers, discovery and per-tool allowlists.
- VTube, TTS, STT, vision, Discord and similar integrations are visible as
  optional slots. They may be toggled in UI, but real provider execution remains
  disabled until the backend capability is implemented.

## MCP View

The MCP view talks to `/api/mcp/*`. It never creates arbitrary server commands;
it only reads the backend config, enables/disables known servers, discovers
tools and toggles allowlist entries.

## Terminal Agente View

The `Terminal Agente` sidebar page is a lightweight operational console for
voice-agent events. It renders a bounded visible log for Nakamura/Hana lines,
listening, processing, speaking, model, emotion, vision, tool calls, tool
results and errors.

- The page polls `/api/terminal-agent/events`. When the backend is restarting,
  it does not replay local fake events; the visible log is treated as backend
  state. The header/status strip now exposes `backend=online/offline/checking`
  so cached settings do not look like a confirmed live runtime state.
- `Display text` and `TTS speech text` are shown separately when they differ,
  so UI-friendly links/code do not have to be spoken verbatim.
- STT and TTS on/off controls remain in the `Conexoes` page. The terminal only
  exposes operational actions such as stop speech/TTS, copy and clear; manual
  microphone capture is kept inside settings as an STT test path.
- When STT is enabled in `Conexoes`, the frontend starts the backend
  `/api/voice/runtime/start` loop. The browser no longer owns continuous
  microphone capture.
- The backend runtime uses `sounddevice` plus RMS/VAD to discard silence and
  low-level noise before Groq Whisper, avoiding false replies from a muted mic.
- Backend listening pauses while Edge TTS is speaking, so Hana does not
  transcribe her own spoken response as a new user command.
- The top configuration button opens the terminal settings panel. It uses
  `/api/config/voice`, `/api/config/voice/catalog` and
  `/api/config/voice/input-devices` to choose STT provider, TTS provider,
  model, voice, language and microphone input.
- The same settings panel exposes the optional RVC post-TTS converter through
  `/api/config/voice-converter`, shows `rvc=on/off`, `rvc_backend`, keeps the
  last `rvc_result`, and provides `Testar RVC` through `/api/voice/rvc/test`.
- Voice/RVC settings are still cached locally for editing continuity, but a
  failed save marks the backend offline and shows an explicit status message.
- The settings STT test flow records the microphone with MediaRecorder, posts the audio
  to `/api/voice/stt/transcribe` with provider `groq_whisper`, and
  requests a text response from the backend.
- When TTS is enabled in `Conexoes`, the backend runtime requests Edge TTS and
  plays the returned MP3 locally with `pygame`.
- When RVC is enabled, Edge remains the base TTS provider; the backend tries the
  configured external RVC runtime after synthesis and falls back to the
  original Edge audio if conversion is unavailable or fails. The recommended
  local backend is `advanced_rvc_worker`; `external_cli` remains available as a
  slower compatibility option.
- Manual terminal input uses `/api/voice/text/respond`, so typing a command now
  routes through the same text-turn path as a transcript instead of only
  appending a local log row.
- The UI can copy one event, copy the visible log and clear the current
  terminal-agent event stream.
- The terminal opens at the newest event, follows new event height changes and
  exposes its own `Mais recente` button when the user scrolls upward. Newly
  received Hana text events use the same visible streamer treatment as Chat.

## Agent Mode Permissions

Risky actions are handled in the Control Center instead of relying on the optional Python/Tk popup:

- The backend exposes `/api/permissions/pending`, `/api/permissions/{id}/approve` and `/api/permissions/{id}/deny`.
- The modal shows tool name, risk, description, argument preview and countdown.
- The current Agent OSS backend returns an empty pending list until permissioned
  tools are wired into the new capability registry.
- `Dev Unsafe` disables permission polling/modal rendering. Chat, manual
  Terminal commands and the backend voice runtime reuse the persisted Agent
  Mode safety setting instead of silently falling back to `safe`.

## Development

```powershell
npm install
npm run dev
npm run build
```

For Tauri checks:

```powershell
cd src-tauri
cargo check
```

## Public Release Notes

Do not commit:

- `node_modules`
- `dist`
- `src-tauri/target`
- local screenshots with private data
- secrets or local config files
