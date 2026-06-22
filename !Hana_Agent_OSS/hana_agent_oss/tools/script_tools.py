"""Living scripts: let Hana write and reuse her own executable code.

A *skill* (``data/skills/*.md``) is the manual — when/how to do something. A
*script* (``data/scripts/*``) is the runnable code that actually does it, which
Hana executes via ``terminal.run`` (e.g. ``python data/scripts/youtube_download.py``).

This module gives Hana a dedicated way to CREATE and READ her own scripts. The
destination is ALWAYS ``SCRIPTS_DIR``; the name is sanitized to a bare stem plus
an allowed extension, so there is no path traversal and no way to write a script
into another bot's folder (the same bug that put a skill in Nyra's directory).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry
from hana_agent_oss.paths import SCRIPTS_DIR

MIN_SCRIPT_CHARS = 3
# Extensions Hana is allowed to create. Default to Python when none is given.
ALLOWED_EXTS = ("py", "js", "ts", "mjs", "cjs", "ps1", "sh", "bat")
DEFAULT_EXT = "py"

_STEM_RE = re.compile(r"[^a-z0-9_\-]")


def _normalize_script_name(name: str) -> str:
    """Reduce any input to ``<safe_stem>.<allowed_ext>`` inside SCRIPTS_DIR only.

    Strips path components (so an absolute path like another bot's folder collapses
    to just the filename), keeps an allowed extension or falls back to .py.
    """
    base = str(name or "").strip().lower()
    base = base.replace("\\", "/").split("/")[-1]  # drop any path component
    stem, _, ext = base.rpartition(".")
    if not stem:  # no dot at all -> whole thing is the stem
        stem, ext = base, ""
    safe_stem = _STEM_RE.sub("", stem)
    if not safe_stem:
        return ""
    safe_ext = _STEM_RE.sub("", ext)
    if safe_ext not in ALLOWED_EXTS:
        safe_ext = DEFAULT_EXT
    return f"{safe_stem}.{safe_ext}"


def create_script(name: str, content: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Create a NEW script inside Hana's OWN scripts dir (SCRIPTS_DIR)."""
    safe = _normalize_script_name(name)
    if not safe:
        return {"ok": False, "error": "invalid_name", "name": str(name)}

    body = str(content or "")
    if len(body.strip()) < MIN_SCRIPT_CHARS:
        return {"ok": False, "error": "content_too_short", "name": safe}

    try:
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"mkdir_failed: {exc}"}
    path = (SCRIPTS_DIR / safe).resolve()

    if path.exists() and not overwrite:
        return {"ok": False, "error": "script_already_exists", "name": safe, "path": str(path)}

    try:
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"write_failed: {exc}"}
    return {"ok": True, "script": safe, "path": str(path), "bytes": path.stat().st_size}


def list_scripts() -> list[dict[str, Any]]:
    """List Hana's existing scripts (name + size)."""
    out: list[dict[str, Any]] = []
    try:
        root = SCRIPTS_DIR.resolve()
        if not root.is_dir():
            return out
        for path in sorted(root.iterdir()):
            if path.is_file():
                out.append({"name": path.name, "bytes": path.stat().st_size})
    except OSError:
        return out
    return out


def read_script(name: str) -> dict[str, Any]:
    """Return the content of one script inside SCRIPTS_DIR."""
    safe = _normalize_script_name(name)
    if not safe:
        return {"ok": False, "error": "invalid_name", "name": str(name)}
    root = SCRIPTS_DIR.resolve()
    path = (root / safe).resolve()
    if root not in path.parents or not path.is_file():
        return {"ok": False, "error": "script_not_found", "name": safe}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"read_failed: {exc}"}
    return {"ok": True, "script": safe, "path": str(path), "content": content}


# --- Registry tools (agent path) ----------------------------------------- #

def _tool_create(args: dict[str, Any]) -> ToolResult:
    result = create_script(
        str(args.get("name") or args.get("nome") or ""),
        str(args.get("content") or args.get("conteudo") or args.get("body") or args.get("code") or ""),
        overwrite=bool(args.get("overwrite") or args.get("sobrescrever") or False),
    )
    return ToolResult(ok=bool(result.get("ok")), tool="script.create", output=result, error=None if result.get("ok") else str(result.get("error")))


def _tool_list(args: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, tool="script.list", output={"scripts": list_scripts()})


def _tool_read(args: dict[str, Any]) -> ToolResult:
    result = read_script(str(args.get("name") or args.get("nome") or ""))
    return ToolResult(ok=bool(result.get("ok")), tool="script.read", output=result, error=None if result.get("ok") else str(result.get("error")))


def register_script_tools(registry: ToolRegistry) -> None:
    """Register Hana's living-script tools for the local agent/terminal path."""
    registry.register(RegisteredTool(
        "script.create",
        "Create a NEW reusable script (py/js/ts/ps1/sh/bat) in Hana's own scripts folder (data/scripts/). "
        "Use this for code you will run more than once, then execute it with terminal.run "
        "(e.g. 'python data/scripts/<name>.py'). NEVER write the script with file.write to a guessed path.",
        _tool_create,
        {"type": "object", "required": ["name", "content"], "properties": {
            "name": {"type": "string", "description": "filename, e.g. youtube_download.py (extension optional, defaults to .py)"},
            "content": {"type": "string", "description": "the full source code"},
            "overwrite": {"type": "boolean", "description": "replace if a script with this name already exists"},
        }},
        {},
        "medium",
        "script.module",
    ))
    registry.register(RegisteredTool(
        "script.list",
        "List Hana's existing reusable scripts in data/scripts/.",
        _tool_list,
        {"type": "object"},
        {},
        "low",
        "script.module",
    ))
    registry.register(RegisteredTool(
        "script.read",
        "Read the source of one of Hana's scripts by name.",
        _tool_read,
        {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
        {},
        "low",
        "script.module",
    ))
