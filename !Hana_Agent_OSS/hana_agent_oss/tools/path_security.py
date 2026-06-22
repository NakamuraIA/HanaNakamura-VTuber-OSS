"""Shared path validation helpers for tool implementations.

Adapted (refactored) from NousResearch/hermes-agent (tools/path_security.py),
which is MIT licensed (Copyright (c) 2025 Nous Research). Kept tiny and
dependency-free on purpose.
"""

from __future__ import annotations

from pathlib import Path


def validate_within_dir(path: Path, root: Path) -> str | None:
    """Ensure *path* resolves to a location within *root*.

    Returns an error message string if validation fails, or ``None`` if the
    path is safe. Uses ``Path.resolve()`` to follow symlinks and normalize
    ``..`` components.
    """
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (ValueError, OSError) as exc:
        return f"Path escapes allowed directory: {exc}"
    return None


def has_traversal_component(path_str: str) -> bool:
    """Return True if *path_str* contains ``..`` traversal components."""
    return ".." in Path(str(path_str or "")).parts
