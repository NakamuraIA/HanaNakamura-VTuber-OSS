from __future__ import annotations

from pathlib import Path
from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry


def _path_from_args(args: dict[str, Any]) -> Path:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        raise ValueError("path is required.")
    return Path(raw_path).expanduser()


def file_exists(args: dict[str, Any]) -> ToolResult:
    path = _path_from_args(args)
    return ToolResult(
        ok=True,
        tool="file.exists",
        output={"path": str(path), "exists": path.exists(), "is_file": path.is_file(), "is_dir": path.is_dir()},
    )


def file_read(args: dict[str, Any]) -> ToolResult:
    path = _path_from_args(args)
    if not path.exists():
        return ToolResult(ok=False, tool="file.read", error=f"File does not exist: {path}")
    content = path.read_text(encoding=str(args.get("encoding") or "utf-8"))
    return ToolResult(ok=True, tool="file.read", output={"path": str(path), "content": content})


def file_write(args: dict[str, Any]) -> ToolResult:
    path = _path_from_args(args)
    content = str(args.get("content") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=str(args.get("encoding") or "utf-8"))
    return ToolResult(ok=True, tool="file.write", output={"path": str(path), "bytes": path.stat().st_size}, artifacts=[str(path)])


def file_append(args: dict[str, Any]) -> ToolResult:
    path = _path_from_args(args)
    content = str(args.get("content") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding=str(args.get("encoding") or "utf-8")) as handle:
        handle.write(content)
    return ToolResult(ok=True, tool="file.append", output={"path": str(path), "bytes": path.stat().st_size}, artifacts=[str(path)])


def file_verify_content(args: dict[str, Any]) -> ToolResult:
    path = _path_from_args(args)
    expected = str(args.get("contains") or "")
    if not path.exists():
        return ToolResult(ok=False, tool="file.verify_content", error=f"File does not exist: {path}")
    content = path.read_text(encoding=str(args.get("encoding") or "utf-8"))
    return ToolResult(
        ok=expected in content,
        tool="file.verify_content",
        output={"path": str(path), "contains": expected, "matched": expected in content},
        error=None if expected in content else "Expected content was not found.",
    )


def register_file_tools(registry: ToolRegistry) -> None:
    schema = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}
    registry.register(RegisteredTool("file.exists", "Check whether a path exists.", file_exists, schema, {}, "low", "file.module"))
    registry.register(RegisteredTool("file.read", "Read a text file.", file_read, schema, {}, "low", "file.module"))
    registry.register(RegisteredTool("file.write", "Write a text file.", file_write, schema, {}, "medium", "file.module"))
    registry.register(RegisteredTool("file.append", "Append to a text file.", file_append, schema, {}, "medium", "file.module"))
    registry.register(RegisteredTool("file.verify_content", "Verify text content in a file.", file_verify_content, schema, {}, "low", "file.module"))

