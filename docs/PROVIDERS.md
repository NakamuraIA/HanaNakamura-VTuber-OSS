# Providers

## Current Strategy

The backend uses a provider selector with separate LLM providers:

- `gemini_api` for Google AI Studio / Gemini API.
- `openrouter` for OpenRouter Chat Completions compatible models.
- `groq` for Groq OpenAI-compatible Chat Completions and Compound systems.

STT and TTS provider execution is connected through backend `VoiceRuntime`:
`groq_whisper` receives utterances captured by Python `sounddevice`, and the
active TTS providers are `edge`, `gemini_tts`, `google_cloud_tts`, `azure`, `cartesia`, `minimax` and `elevenlabs` (Minimax T2A for good quality multilingual with many pt-BR female voices; Cartesia for ultra-low latency + cheap; Elevenlabs for high-quality realistic speech; Azure/Edge/Google for excellent native Brazilian Portuguese female voices like Francisca, Luana, Thalita, Isabella - authentic accent, no American bleed).

## Active Provider

| Provider ID | Name | Status |
| --- | --- | --- |
| `gemini_api` | Gemini API (Google AI Studio) | Active |
| `openrouter` | OpenRouter | Active |
| `groq` | Groq | Active |

## Gemini Models (Main Multimodal LLMs)

All models below are multimodal for input and currently output text.

| Model ID | Input | Output | Max Input Tokens | Max Output Tokens |
| --- | --- | --- | ---: | ---: |
| `gemini-3.1-pro-preview` | text, code, image, audio, video, pdf | text | 1,048,576 | 65,536 |
| `gemini-2.5-pro` | text, code, image, audio, video | text | 1,048,576 | 65,535 |
| `gemini-3-flash-preview` | text, code, image, audio, video, pdf | text | 1,048,576 | 65,536 |
| `gemini-2.5-flash` | text, code, image, audio, video | text | 1,048,576 | 65,535 |
| `gemini-3.1-flash-lite` | text, code, image, audio, video, pdf | text | 1,048,576 | 65,535 |
| `gemini-2.5-flash-lite` | text, code, image, audio, video | text | 1,048,576 | 65,535 |

Provider selector source:

- `!Hana_Agent_OSS/hana_agent_oss/providers/provider_selector/selector.py`
- `!Hana_Agent_OSS/hana_agent_oss/providers/provider_selector/gemini_api/provider.py`
- `!Hana_Agent_OSS/hana_agent_oss/providers/provider_selector/openrouter/provider.py`
- `!Hana_Agent_OSS/hana_agent_oss/providers/provider_selector/groq/provider.py`
- `!Hana_Agent_OSS/hana_agent_oss/persona/prompts.py`

Provider modules do not own Hana's persona. They request a system prompt from
the central persona/prompt layer, which combines the provider-neutral identity
profile with provider-specific rules.

## OpenRouter Models

OpenRouter models are loaded dynamically from
`https://openrouter.ai/api/v1/models` and merged into the Control Panel catalog.
The backend maps model metadata into Hana capability flags:

- `input_modalities` containing `image` enables vision attachments.
- `input_modalities` containing `file` enables document/file attachments.
- `supported_parameters` containing `tools` or `tool_choice` enables local tool
  calls such as the terminal hands (`terminal_run`) and MCP.
- pricing, free status, context length and description are displayed when the
  OpenRouter catalog returns them.

Local tool schemas are normalized before submission so provider-specific
backends, including Gemini models routed through OpenRouter, do not receive
invalid blank enum values from optional tool arguments.

Selecting `openrouter` disables Gemini-only LLM behavior for that chat/voice
turn: Gemini native Google Search grounding, Gemini server-side tools and
Gemini image XML execution are not run. STT and TTS providers are unaffected.

## Groq Models

Groq models are loaded from `https://api.groq.com/openai/v1/models` and merged
with a small curated fallback catalog so the Control Panel can still show known
models if the API is unavailable. The starter catalog includes:

- `llama-3.3-70b-versatile`
- `llama-3.1-8b-instant`
- `openai/gpt-oss-120b`
- `openai/gpt-oss-20b`
- `qwen/qwen3-32b`
- `meta-llama/llama-4-scout-17b-16e-instruct`
- `groq/compound`
- `groq/compound-mini`

`meta-llama/llama-4-scout-17b-16e-instruct` is marked as the Groq vision model
for image attachments. `groq/compound` and `groq/compound-mini` are marked as
native-search/code-execution systems because Groq runs their server-side tools
inside the model request. Selecting `groq` still disables Gemini-only behavior:
Gemini Google Search grounding, Gemini server-side tools and Gemini image XML
execution are not run. STT and TTS providers are unaffected.

## Environment Variables

Required for Gemini API:

```env
GOOGLE_API_KEY=...
# or
GEMINI_API_KEY=...
```

If no key is present, chat returns a provider setup error.

Required for OpenRouter LLM:

```env
OPENROUTER_API_KEY=...
# Optional attribution headers.
OPENROUTER_SITE_URL=
OPENROUTER_APP_NAME=Hana Agent OSS
```

`OPENROUTER_API_KEY` is used only by the `openrouter` LLM provider. It does not
replace Groq Whisper, Google Cloud TTS, Gemini TTS or Edge TTS credentials.

Required for Groq LLM and Groq Whisper STT:

```env
GROQ_API_KEY=...
```

The same environment variable is used by the Groq STT adapter and the `groq`
LLM provider, but the selected STT/TTS/LLM providers remain separate Control
Panel settings.

Required only for Google Cloud Text-to-Speech:

```env
GOOGLE_CLOUD_TTS_API_KEY=...
# Optional, only for Cloud TTS streaming through ADC/service account.
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
```

`GOOGLE_CLOUD_TTS_API_KEY` is not used by Gemini LLM, Gemini TTS, STT or tool
providers. Restrict it to Cloud Text-to-Speech in Google Cloud.

## Gemini Capability Profile

The selector stores Gemini capability metadata so future providers can expose
their own rules and limits.

Current Gemini profile includes:

- multimodal input (text/image/audio/video/pdf)
- native web search
- streaming
- structured output
- function calling
- code execution
- image generation
- video generation
- TTS and live voice slots
- memory embeddings and RAG slots

These flags represent provider profile metadata for orchestration. Individual
features still depend on runtime integration in their modules.

## Gemini Multimodal Attachments

The chat service persists attachments first, then the Gemini provider consumes
the saved attachment payload and maps supported files into Gemini content parts:

- `image/*`
- `audio/*`
- `video/*`
- `application/pdf`
- `text/*`
- `application/json`, `application/xml`, YAML

Files below the inline threshold are sent with inline bytes. Larger files use
the Gemini Files API and are referenced by URI after processing. This keeps the
frontend as a sender/preview layer while provider-specific media handling stays
in the backend. Follow-up file questions can reload recent saved attachments
from runtime storage and send them to the provider again.

## Voice Provider Foundations

The voice config endpoints are:

- `/api/config/voice`
- `/api/config/voice/catalog`
- `/api/config/voice/input-devices`
- `/api/config/conexoes`

`/api/config/voice` stores Terminal Agente provider/model/voice/microphone
preferences. It does not own global STT/TTS activation; Conexoes owns that
state through `stt` and `tts`. Input-device listing recommends backend
`sounddevice` for continuous capture and keeps browser `MediaRecorder` only as
a manual diagnostic fallback.

Provider IDs:

| Capability | Provider IDs | Status |
| --- | --- | --- |
| STT | `groq_whisper`, `gemini_audio`, `openai`, `local` | `groq_whisper` active through `/api/voice/runtime/start` and `/api/voice/stt/transcribe`; other providers are reserved |
| TTS | `edge`, `gemini_tts`, `google_cloud_tts`, `azure`, `cartesia`, `minimax`, `elevenlabs` | All listed providers are active through `/api/voice/tts/synthesize`, `/api/voice/tts/speak` and backend runtime playback. Minimax (good pt-BR females), Cartesia (low latency/cheap), Elevenlabs (high quality realistic) and Azure/Edge/Google Cloud (best native pt-BR female voices with authentic Brazilian accent) are recommended for quality BR Portuguese. |

RVC is not a TTS provider. It is the first optional post-TTS voice converter:

| Capability | Backend | Status |
| --- | --- | --- |
| Voice conversion | `external_cli` | Optional RVC post-processing after Edge TTS through `/api/config/voice-converter` and `/api/voice/rvc/test` |

The frontend STT test contract sends `multipart/form-data` to
`/api/voice/stt/transcribe` with fields `audio`, `provider`, optional `model`,
optional `language`, optional `durationMs`, `respond=true` and `tts=false`.
The expected response includes `text`; when response generation is enabled it
also includes `assistantText` and `responded=true`.
Groq language values are normalized before execution; `pt-BR` becomes `pt`.
Manual terminal commands use `/api/voice/text/respond` and return the same
`assistantText` shape without requiring an audio upload.

TTS-readable text is prepared separately from display text through the
Terminal Agente contract. The sanitizer removes markdown/code blocks, converts
links to speakable placeholders and reduces raw punctuation before audio
generation. Edge TTS can stream local runtime playback and can also return MP3
audio as base64 JSON for diagnostics. Gemini TTS (`gemini_tts`) uses Gemini API
speech generation and prompt/style instructions; it is useful for acting
quality but does not use classic numeric rate/pitch controls. Google Cloud TTS
(`google_cloud_tts`) uses REST MP3 with `GOOGLE_CLOUD_TTS_API_KEY`, maps
`ttsSpeed` to `speakingRate`, maps `ttsPitch` to Cloud TTS pitch, and can try
Cloud client-library streaming when `ttsStreaming=true`,
`GOOGLE_APPLICATION_CREDENTIALS` is set and the selected voice supports the
streaming API. If streaming is unavailable, it falls back to REST MP3 instead
of breaking speech. Current Edge voices exposed in the catalog include
`pt-BR-FranciscaNeural`, `pt-BR-AntonioNeural`, `pt-BR-ThalitaNeural`,
`pt-PT-RaquelNeural` and `pt-PT-DuarteNeural`. Current Google Cloud starter
voices include `pt-BR-Neural2-C`, `pt-BR-Neural2-A`, `pt-BR-Wavenet-A` and
`pt-BR-Standard-A`.

ElevenLabs (`elevenlabs`) uses `ELEVENLABS_API_KEY` and the standard
text-to-speech REST endpoint. The Control Panel accepts any voice ID from the
user's ElevenLabs library. The curated model options are
`eleven_flash_v2_5`, `eleven_turbo_v2_5`, `eleven_multilingual_v2` and
`eleven_v3`, while a custom model ID can also be entered. Its provider-specific
controls are speed, stability, similarity boost, style exaggeration and speaker
boost. UI locales such as `pt-BR` are sent as the API language code `pt`.
Terminal runtime playback uses ElevenLabs' complete MP3 response and does not
route it through the Edge-only `stream_audio_chunks` path. `ttsVolume` is
applied locally after synthesis, so it does not consume a different provider
request or alter the selected voice.

The current stop contracts are `/api/terminal-agent/tts/stop`,
`/api/voice/tts/stop` and `/api/voice/runtime/interrupt`. They raise the shared
audio stop signal, mark local speech state as stopped and log a non-speakable
Terminal Agente event.

RVC accepts base audio generated by Edge, invokes a configured external CLI with
`pythonPath`, `scriptPath`, `modelPath`, optional `indexPath`, `f0Method`,
`pitch`, `indexRate`, `protect`, timeout and optional output sample rate, then
returns WAV audio when conversion succeeds. If RVC is disabled or conversion
fails, the runtime/test path keeps the original Edge audio and logs the fallback
instead of failing the whole spoken turn. Use `/api/voice/rvc/preflight` to
check whether the selected wrapper, model paths and FFmpeg dependency are ready
before running a real conversion.
