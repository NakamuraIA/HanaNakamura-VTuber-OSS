"""Living skills: let Hana read and annotate her own skill .md files.

Skills are Markdown files in ``data/skills/`` (and optional ``hana_agent/skills/``)
that are injected into the system prompt every turn. This module lets Hana append
short, dated notes/tips to a skill so she gets better at calling it next time —
exactly like ``<salvar_memoria>`` does for long-term memory, but for skills.

Two ways to use it:
1. XML tag (works in every channel, parsed after the response, like memory):
   ``<anotar_skill nome="tavily_mcp_research">use search_depth=advanced p/ noticias</anotar_skill>``
2. Registry tools (skill.list / skill.read / skill.note) for the agent path.

Safety: all file access is scoped to the known skills directories and the skill
name is sanitized, so there is no path traversal and no writing outside skills.
Notes are capped (count + length) so the prompt never bloats over time.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry
from hana_agent_oss.paths import EXT_SKILLS_DIR, SKILLS_DIR

# Header under which Hana's auto-learned notes live inside each skill file.
NOTES_HEADER = "## Notas da Hana (aprendidas em uso)"
# Hard caps so injected skills never grow unbounded in the prompt.
MAX_NOTES = 30
MAX_NOTE_CHARS = 600
MIN_NOTE_CHARS = 3

_SKILL_NAME_RE = re.compile(r"[^a-z0-9_\-]")
_NOTE_BULLET_RE = re.compile(r"^\s*-\s*\[")

# --- XML tag parsing (mirrors memory_xml) -------------------------------- #
_SKILL_TAG = r"anotar[_\s-]*skill"
SKILL_XML_BLOCK_RE = re.compile(
    rf"<\s*{_SKILL_TAG}\b[^>]*>.*?<\s*/\s*{_SKILL_TAG}\s*>",
    re.IGNORECASE | re.DOTALL,
)
SKILL_XML_EXTRACT_RE = re.compile(
    rf"<\s*{_SKILL_TAG}\b(?P<attrs>[^>]*)>(?P<body>.*?)<\s*/\s*{_SKILL_TAG}\s*>",
    re.IGNORECASE | re.DOTALL,
)


# --- Path scoping (no traversal) ----------------------------------------- #

def _allowed_roots() -> list[Path]:
    """Return existing skill directories, resolved, that writes are confined to."""
    roots: list[Path] = []
    for root in (SKILLS_DIR, EXT_SKILLS_DIR):
        try:
            if root.exists() and root.is_dir():
                roots.append(root.resolve())
        except OSError:
            continue
    return roots


def _normalize_name(name: str) -> str:
    """Reduce any input to a bare safe skill stem (strips path parts, dots, etc.)."""
    base = str(name or "").strip().lower()
    base = base.replace("\\", "/").split("/")[-1]  # drop any path component
    if base.endswith(".md"):
        base = base[:-3]
    return _SKILL_NAME_RE.sub("", base)


def _resolve_skill(name: str) -> Path | None:
    """Resolve a skill name to an existing .md file inside an allowed root only."""
    safe = _normalize_name(name)
    if not safe:
        return None
    for root in _allowed_roots():
        candidate = (root / f"{safe}.md").resolve()
        if root in candidate.parents and candidate.exists() and candidate.is_file():
            return candidate
    return None


# --- Core operations ----------------------------------------------------- #

def list_skills() -> list[dict[str, Any]]:
    """List available skills with a short title (first non-empty line)."""
    out: list[dict[str, Any]] = []
    ext_root = EXT_SKILLS_DIR.resolve() if EXT_SKILLS_DIR.exists() else None
    for root in _allowed_roots():
        for path in sorted(root.glob("*.md")):
            title = ""
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip().lstrip("#").strip()
                    if stripped:
                        title = stripped[:120]
                        break
            except OSError:
                continue
            out.append({"name": path.stem, "title": title, "ext": root == ext_root})
    return out


def read_skill(name: str) -> dict[str, Any]:
    """Return the full content of one skill .md file."""
    path = _resolve_skill(name)
    if path is None:
        return {"ok": False, "error": "skill_not_found", "name": _normalize_name(name)}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"read_failed: {exc}"}
    return {"ok": True, "name": path.stem, "path": str(path), "content": content}


def create_skill(name: str, content: str, *, title: str = "", overwrite: bool = False) -> dict[str, Any]:
    """Create a NEW skill .md inside Hana's OWN primary skills dir (SKILLS_DIR).

    This is the "skill that creates skills". The destination is ALWAYS SKILLS_DIR
    (``data/skills/``); the name is sanitized to a bare stem so there is no way to
    write outside it (no path traversal, no absolute paths, no other bot's folder).
    By default it refuses to clobber an existing skill — pass overwrite=True to
    replace it on purpose.
    """
    safe = _normalize_name(name)
    if not safe:
        return {"ok": False, "error": "invalid_name", "name": str(name)}

    body = str(content or "").strip()
    if len(body) < MIN_NOTE_CHARS:
        return {"ok": False, "error": "content_too_short", "name": safe}

    # Destination is hard-coded to Hana's own primary skills dir. No guessing paths.
    try:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"mkdir_failed: {exc}"}
    path = (SKILLS_DIR / f"{safe}.md").resolve()

    if path.exists() and not overwrite:
        return {"ok": False, "error": "skill_already_exists", "name": safe, "path": str(path)}

    # Ensure there is a markdown H1 title so list_skills() shows a clean title.
    clean_title = re.sub(r"\s+", " ", str(title or "").strip())
    if not body.lstrip().startswith("#"):
        heading = clean_title or safe.replace("_", " ").replace("-", " ").title()
        body = f"# {heading}\n\n{body}"

    try:
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"write_failed: {exc}"}
    return {"ok": True, "skill": safe, "path": str(path), "bytes": path.stat().st_size, "overwritten": path.exists() and overwrite}


def append_skill_note(name: str, note: str) -> dict[str, Any]:
    """Append one dated note under the Hana notes section, capped to MAX_NOTES.

    Idempotent-ish: identical note text already present is not duplicated.
    """
    clean = re.sub(r"\s+", " ", str(note or "").strip())
    if len(clean) < MIN_NOTE_CHARS:
        return {"ok": False, "error": "note_too_short"}
    if len(clean) > MAX_NOTE_CHARS:
        clean = clean[:MAX_NOTE_CHARS].rstrip() + "..."

    path = _resolve_skill(name)
    if path is None:
        return {"ok": False, "error": "skill_not_found", "name": _normalize_name(name)}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"read_failed: {exc}"}

    if NOTES_HEADER in text:
        head, _, notes_block = text.partition(NOTES_HEADER)
        existing = [line.rstrip() for line in notes_block.splitlines() if _NOTE_BULLET_RE.match(line)]
    else:
        head = text.rstrip() + "\n\n"
        existing = []

    bullet = f"- [{datetime.now().strftime('%Y-%m-%d')}] {clean}"
    # Skip exact-duplicate note text (ignore the date prefix when comparing).
    if any(line.split("] ", 1)[-1].strip() == clean for line in existing):
        return {"ok": True, "skill": path.stem, "path": str(path), "note": clean, "duplicate": True}

    existing.append(bullet)
    existing = existing[-MAX_NOTES:]
    new_text = head.rstrip() + "\n\n" + NOTES_HEADER + "\n" + "\n".join(existing) + "\n"
    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"write_failed: {exc}"}
    return {"ok": True, "skill": path.stem, "path": str(path), "note": clean, "noteCount": len(existing)}


# --- XML extraction / stripping ------------------------------------------ #

def extract_skill_notes(text: str) -> list[dict[str, str]]:
    """Extract <anotar_skill nome="..."> note </anotar_skill> blocks from a response.

    Supports a plain body with a ``nome``/``name``/``skill`` attribute, or a JSON
    body like {"skill": "...", "note": "..."}.
    """
    results: list[dict[str, str]] = []
    for match in SKILL_XML_EXTRACT_RE.finditer(str(text or "")):
        body = match.group("body").strip()
        attrs = match.group("attrs") or ""
        if not body:
            continue
        name = ""
        attr_match = re.search(r"\b(?:nome|name|skill)\s*=\s*(['\"])(.*?)\1", attrs, flags=re.IGNORECASE)
        if attr_match:
            name = attr_match.group(2).strip()
        note = body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                name = str(parsed.get("skill") or parsed.get("nome") or parsed.get("name") or name).strip()
                note = str(parsed.get("note") or parsed.get("nota") or parsed.get("text") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pass
        if name and note and len(note) >= MIN_NOTE_CHARS:
            results.append({"skill": name, "note": note})
    return results


def strip_skill_xml_tags(text: str) -> str:
    """Remove <anotar_skill> blocks so they never reach the user or TTS."""
    cleaned = SKILL_XML_BLOCK_RE.sub("", str(text or ""))
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def apply_skill_notes(text: str) -> list[dict[str, Any]]:
    """Parse and persist all skill notes found in a response. Never raises."""
    applied: list[dict[str, Any]] = []
    for entry in extract_skill_notes(text):
        try:
            result = append_skill_note(entry["skill"], entry["note"])
        except Exception as exc:  # noqa: BLE001 - never break a turn for a note
            result = {"ok": False, "error": str(exc), "skill": entry.get("skill")}
        applied.append(result)
    return applied


# --- Registry tools (agent path) ----------------------------------------- #

def _tool_list(args: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, tool="skill.list", output={"skills": list_skills()})


def _tool_read(args: dict[str, Any]) -> ToolResult:
    result = read_skill(str(args.get("name") or args.get("skill") or ""))
    return ToolResult(ok=bool(result.get("ok")), tool="skill.read", output=result, error=None if result.get("ok") else str(result.get("error")))


def _tool_create(args: dict[str, Any]) -> ToolResult:
    result = create_skill(
        str(args.get("name") or args.get("skill") or args.get("nome") or ""),
        str(args.get("content") or args.get("conteudo") or args.get("body") or args.get("text") or ""),
        title=str(args.get("title") or args.get("titulo") or ""),
        overwrite=bool(args.get("overwrite") or args.get("sobrescrever") or False),
    )
    return ToolResult(ok=bool(result.get("ok")), tool="skill.create", output=result, error=None if result.get("ok") else str(result.get("error")))


def _tool_note(args: dict[str, Any]) -> ToolResult:
    result = append_skill_note(
        str(args.get("name") or args.get("skill") or ""),
        str(args.get("note") or args.get("nota") or args.get("text") or ""),
    )
    return ToolResult(ok=bool(result.get("ok")), tool="skill.note", output=result, error=None if result.get("ok") else str(result.get("error")))


def register_skill_tools(registry: ToolRegistry) -> None:
    """Register living-skill tools for the local agent/terminal path."""
    registry.register(RegisteredTool("skill.list", "List Hana's available skills and titles.", _tool_list, {"type": "object"}, {}, "low", "skill.module"))
    registry.register(RegisteredTool(
        "skill.create",
        "Create a NEW skill for Hana herself. Writes a Markdown skill file into Hana's own skills folder (data/skills/). Use this to teach Hana a new reusable procedure — NEVER write the file manually with file.write to a guessed path.",
        _tool_create,
        {"type": "object", "required": ["name", "content"], "properties": {
            "name": {"type": "string", "description": "short skill id, e.g. youtube_music_download"},
            "content": {"type": "string", "description": "the full skill in Markdown (steps, tools, gotchas)"},
            "title": {"type": "string", "description": "optional human title for the H1"},
            "overwrite": {"type": "boolean", "description": "replace if a skill with this name already exists"},
        }},
        {},
        "medium",
        "skill.module",
    ))
    registry.register(RegisteredTool("skill.read", "Read the full content of one skill .md by name.", _tool_read, {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}, "low", "skill.module"))
    registry.register(RegisteredTool("skill.note", "Append a short dated tip to a skill so Hana improves next time.", _tool_note, {"type": "object", "required": ["name", "note"], "properties": {"name": {"type": "string"}, "note": {"type": "string"}}}, "low", "skill.module"))
