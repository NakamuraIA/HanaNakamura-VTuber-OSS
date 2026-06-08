"""Single source of truth for filesystem paths used across Hana Agent OSS.

Every path is derived ONCE from this file's location, so changing the project
layout only requires touching this module (instead of scattered
``Path(__file__).resolve().parents[N]`` arithmetic in many files).

Layout anchors::

    PROJECT_ROOT/                 (e.g. Projeto_Hana_AI)
      !Hana_Agent_OSS/            -> AGENT_ROOT
        hana_agent_oss/           -> PACKAGE_DIR (this package)
          paths.py                (this file)

Note: there are intentionally TWO runtime directories preserved from the legacy
layout — the conversational memory lives under ``PROJECT_ROOT/runtime`` while the
agent runtime DB / MCP local config live under ``AGENT_ROOT/runtime``. They are
kept separate here to avoid moving any existing user data; unify later if desired.
"""
from __future__ import annotations

from pathlib import Path

# --- Anchors (computed once) --------------------------------------------- #
PACKAGE_DIR = Path(__file__).resolve().parent          # .../!Hana_Agent_OSS/hana_agent_oss
AGENT_ROOT = PACKAGE_DIR.parent                        # .../!Hana_Agent_OSS
PROJECT_ROOT = AGENT_ROOT.parent                       # .../<project root>

# --- Runtime directories (two distinct, see module docstring) ------------ #
PROJECT_RUNTIME_DIR = PROJECT_ROOT / "runtime"         # conversational memory + attachments
AGENT_RUNTIME_DIR = AGENT_ROOT / "runtime"             # agent runtime db + mcp local config

# --- Skills ------------------------------------------------------------- #
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
EXT_SKILLS_DIR = PROJECT_ROOT / "hana_agent" / "skills"

# --- Persistent memory (project runtime) -------------------------------- #
MEMORY_DB = PROJECT_RUNTIME_DIR / "hana_memory.sqlite3"
MEMORY_EVENTS = PROJECT_RUNTIME_DIR / "hana_events.jsonl"
ATTACHMENTS_DIR = PROJECT_RUNTIME_DIR / "attachments"

# --- Agent runtime store + MCP config (agent runtime) ------------------- #
RUNTIME_DB = AGENT_RUNTIME_DIR / "hana_agent_oss.sqlite3"
MCP_EXAMPLE_CONFIG = AGENT_ROOT / "config" / "mcp_servers.example.json"
MCP_LOCAL_CONFIG = AGENT_RUNTIME_DIR / "mcp_servers.local.json"
