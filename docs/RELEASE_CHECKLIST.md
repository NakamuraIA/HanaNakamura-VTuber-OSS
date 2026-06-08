# Hana Agent OSS Release Checklist

Use this checklist before making the repository public again or pushing the
big-bang refactor.

## Local Safety

- [ ] No commit or push was made before the local refactor reached a usable
      state.
- [ ] Snapshot exists outside the repository.
- [ ] `.env`, runtime databases, local memory, logs and generated media are
      ignored.
- [ ] Old local memory/vector data is quarantine only and not read by runtime.

## Architecture

- [ ] Root `main.py` is only a supervisor.
- [ ] Backend runs from `!Hana_Agent_OSS/`.
- [ ] FastAPI routes are grouped under `api/routers/`; `api/server.py` only
      creates the app and includes routers.
- [ ] Control Panel talks to `127.0.0.1:8042`.
- [ ] VTuber mode is optional and disabled by default.
- [ ] MCP exists as a client capability provider, not prompt glue.
- [ ] MCP servers are disabled by default and tools require allowlist entries.
- [ ] Base dependencies are in `requirements.txt`; provider/media/voice extras
      are optional.

## Validation

```powershell
python -m compileall main.py !Hana_Agent_OSS/src
pytest -q
cd control_panel
npm run build
cd src-tauri
cargo check
```

## Smoke

- [ ] `python main.py backend-only` starts the API.
- [ ] `python main.py healthcheck` returns `ok`.
- [ ] Control Panel opens.
- [ ] Chat WebSocket returns a response.
- [ ] Chat provider selector routes to `gemini_api` and fails clearly when key is missing.
- [ ] Memory tab can create, list, edit and delete SQLite/FTS memories.
- [ ] Terminal Agente shows `rvc=on/off`, saves `/api/config/voice-converter`
      settings and `Testar RVC` reports converted audio or a clear Edge fallback.
