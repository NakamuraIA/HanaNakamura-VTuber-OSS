"""Hana's hands: run shell commands and inspect the local machine safely.

This is the lean, in-process replacement for the external Omni executor. It does
NOT spawn a separate service: Hana runs commands directly via subprocess with
guardrails (timeout, output cap, chosen shell). Cross-platform, Windows-first.

Safety model (defense in depth, the rest lives in the persona rules):
- Every command has a TIMEOUT (kills runaway processes).
- Output is CAPPED (never floods the prompt / token budget).
- Dangerous actions (delete, format, admin, credentials) are gated by the
  persona behavior rules: Hana must investigate + confirm with the user first.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry

_IS_WINDOWS = platform.system() == "Windows"

# Guardrails (tunable via env without code changes).
DEFAULT_TIMEOUT = int(os.environ.get("HANA_TERMINAL_TIMEOUT", "60"))      # seconds
MAX_TIMEOUT = int(os.environ.get("HANA_TERMINAL_MAX_TIMEOUT", "600"))     # hard ceiling
MAX_OUTPUT_CHARS = int(os.environ.get("HANA_TERMINAL_MAX_OUTPUT", "20000"))


def _clamp_timeout(value: Any) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT
    return min(timeout, MAX_TIMEOUT)


def _clip(text: str) -> tuple[str, bool]:
    """Cap output so it never blows the token budget. Returns (text, truncated)."""
    value = str(text or "")
    if len(value) <= MAX_OUTPUT_CHARS:
        return value, False
    return value[:MAX_OUTPUT_CHARS].rstrip() + "\n... [saída cortada por tamanho]", True


def _resolve_cwd(raw: Any) -> tuple[str | None, str | None]:
    """Validate the working directory. Returns (cwd, error)."""
    raw_cwd = str(raw or "").strip()
    if not raw_cwd:
        return None, None
    path = Path(raw_cwd).expanduser()
    if not path.exists() or not path.is_dir():
        return None, f"cwd não existe ou não é pasta: {path}"
    return str(path), None


def _shell_command(command: str, shell: str) -> list[str]:
    """Build the argv that runs *command* in the requested shell."""
    shell = str(shell or "").strip().lower()
    if _IS_WINDOWS:
        if shell in {"powershell", "pwsh", "ps"}:
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        return ["cmd", "/c", command]
    # POSIX
    return ["/bin/bash", "-lc", command]


def run_command(args: dict[str, Any]) -> ToolResult:
    """Run one shell command locally with timeout + output cap."""
    command = str(args.get("command") or args.get("cmd") or "").strip()
    if not command:
        return ToolResult(ok=False, tool="terminal.run", output={}, error="command_empty")

    cwd, cwd_error = _resolve_cwd(args.get("cwd") or args.get("path"))
    if cwd_error:
        return ToolResult(ok=False, tool="terminal.run", output={}, error=cwd_error)

    timeout = _clamp_timeout(args.get("timeout") or args.get("timeout_seconds"))
    argv = _shell_command(command, str(args.get("shell") or ""))

    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False,
            tool="terminal.run",
            output={"command": command, "timedOut": True, "timeout": timeout},
            error=f"timeout: comando passou de {timeout}s e foi interrompido",
        )
    except (OSError, ValueError) as exc:
        return ToolResult(ok=False, tool="terminal.run", output={"command": command}, error=f"falha ao executar: {exc}")

    stdout, out_cut = _clip(completed.stdout)
    stderr, err_cut = _clip(completed.stderr)
    exit_code = int(completed.returncode)
    return ToolResult(
        ok=exit_code == 0,
        tool="terminal.run",
        output={
            "command": command,
            "cwd": cwd,
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_cut or err_cut,
        },
        error=None if exit_code == 0 else f"exit_code={exit_code}",
    )


def inspect_dir(args: dict[str, Any]) -> ToolResult:
    """List the contents of a folder (one level) for quick project inspection."""
    raw = str(args.get("path") or args.get("cwd") or ".").strip() or "."
    path = Path(raw).expanduser()
    if not path.exists():
        return ToolResult(ok=False, tool="terminal.inspect_dir", output={"path": str(path)}, error="path_not_found")
    if not path.is_dir():
        return ToolResult(ok=False, tool="terminal.inspect_dir", output={"path": str(path)}, error="not_a_directory")
    try:
        entries = []
        for item in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
            if len(entries) >= 500:  # cap listing
                break
    except OSError as exc:
        return ToolResult(ok=False, tool="terminal.inspect_dir", output={"path": str(path)}, error=str(exc))
    return ToolResult(ok=True, tool="terminal.inspect_dir", output={"path": str(path), "entries": entries, "count": len(entries)})


def register_terminal_tools(registry: ToolRegistry) -> None:
    """Register Hana's local 'hands' (terminal + inspection)."""
    registry.register(RegisteredTool(
        "terminal.run",
        "Run a shell command locally (timeout + output cap). Use shell='powershell' on Windows when needed.",
        run_command,
        {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "shell": {"type": "string", "enum": ["cmd", "powershell", "bash"]},
                "timeout": {"type": "integer"},
            },
        },
        {"type": "object"},
        "high",
        "terminal.module",
    ))
    registry.register(RegisteredTool(
        "terminal.inspect_dir",
        "List the contents of a folder (one level) for quick inspection.",
        inspect_dir,
        {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
        {"type": "object"},
        "low",
        "terminal.module",
    ))
