# Legacy Runtime Status

The previous runtime branch has been superseded by Hana Agent OSS.

Active runtime work now belongs in `!Hana_Agent_OSS/`:

- Agent Core;
- FastAPI backend;
- structured tool calls;
- capability manifests;
- SQLite/FTS/JSONL memory;
- Control Panel compatibility endpoints.

Do not add new behavior to the previous runtime path. If a legacy behavior is
still useful, rebuild it as a module, integration, subbrain or MCP provider in
the Agent OSS backend.
