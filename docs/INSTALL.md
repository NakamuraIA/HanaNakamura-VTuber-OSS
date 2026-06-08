# Hana Agent OSS Installation

This setup targets Windows development.

## Requirements

- Python 3.11 or newer.
- Node.js LTS.
- Rust stable for the Tauri Control Panel.
- Git.

Provider API keys are optional for boot, but required for real chat responses
from the selected LLM provider.

## Install

```powershell
git clone <hana-agent-oss-repository-url>
cd <hana-agent-oss-repository-folder>
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cd control_panel
npm install
cd ..
```

Optional integrations:

```powershell
pip install -r requirements-optional.txt
```

Do this only when you are enabling voice, media, vision, provider SDKs or
external web-search tools. The base backend and Control Panel contract do not
require those packages.

Optional RVC voice conversion also needs a separate compatible RVC inference
environment that can be called through an external CLI wrapper. Configure its
Python executable, wrapper script and model files later in the Terminal Agente
settings panel; the base install does not bundle or train an RVC model.

MCP client support is part of the base backend. External MCP servers may also
require Node.js `npx` or Python `uvx`, depending on the server command in
`!Hana_Agent_OSS/runtime/mcp_servers.local.json`.

## Configure

```powershell
copy .env.example .env
```

Fill only the providers you intend to use. The current backend can boot without
old local memory files or Chroma data.

For real LLM chat in this phase, configure at least one LLM provider:

- `GOOGLE_API_KEY` or `GEMINI_API_KEY`.
- `OPENROUTER_API_KEY` if using OpenRouter.
- `GROQ_API_KEY` if using Groq LLM or Groq Whisper STT.

Optional OpenRouter attribution headers are `OPENROUTER_SITE_URL` and
`OPENROUTER_APP_NAME`. OpenRouter is an LLM provider only; it does not affect
Groq Whisper STT or the configured TTS provider.

Groq uses the OpenAI-compatible GroqCloud API for the `groq` LLM provider. The
same `GROQ_API_KEY` is also used by the separate `groq_whisper` STT provider;
selecting Groq as LLM does not change STT/TTS settings.

For Google Cloud Text-to-Speech only, configure:

- `GOOGLE_CLOUD_TTS_API_KEY`.

That key should be restricted to the Cloud Text-to-Speech API and is not used
for Gemini LLM, Gemini TTS, STT or tools. Optional Cloud TTS streaming also
needs `GOOGLE_APPLICATION_CREDENTIALS` pointing to a service-account JSON file.

## Start

Full local stack:

```powershell
python main.py
```

The launcher first checks whether backend/frontend are already healthy on their
default ports. If they are, it reuses those services instead of starting
duplicates. It then opens `http://127.0.0.1:5173` by default. Set
`HANA_OPEN_BROWSER=0` before starting if you do not want it to open a browser
window.

Backend only:

```powershell
python main.py backend-only
```

Frontend only:

```powershell
python main.py frontend-only
```

Healthcheck:

```powershell
python main.py healthcheck
```

## Validation

```powershell
python -m compileall main.py !Hana_Agent_OSS/src
pytest -q
cd control_panel
npm run build
cd src-tauri
cargo check
```
