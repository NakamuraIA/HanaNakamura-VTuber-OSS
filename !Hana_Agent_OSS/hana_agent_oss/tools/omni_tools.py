from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry


DEFAULT_OMNI_BASE_URL = "http://127.0.0.1:8060"
VALID_MODES = {"inspect", "execute", "review"}
MODE_ALIASES = {"repair": "review"}
OMNI_EXECUTOR_CONTEXT = (
    "You are Omni-Agent OS, the local computer executor used by Hana Nakamura.\n"
    "Hana is the supervising assistant and Nakamura is the human operator.\n"
    "Do not answer as Hana and do not chat with Nakamura directly; return an execution report for Hana to review.\n"
    "Respect the requested mode: inspect means no filesystem/process mutation, execute means perform the requested concrete action, review means inspect prior work and report fixes without mutating unless explicitly asked.\n"
    "Never touch credentials, .env files, commits, destructive deletes, formatting, or irreversible actions unless the task explicitly includes Nakamura's confirmation.\n"
    "If you hit an internal action limit, permission issue, missing file, or unclear requirement, return STATUS: needs_review or blocked with exact evidence and the next command Hana should send.\n"
    "Prefer concrete evidence: paths inspected, commands run, process IDs affected, files changed, screenshots/OCR observations, or exact error text.\n"
)
REPORT_KEYS = {
    "STATUS": "status",
    "RESUMO": "summary",
    "EVIDENCIAS": "evidence",
    "PENDENCIAS": "pending",
    "PROXIMO_PASSO": "next_step",
    "PRÓXIMO_PASSO": "next_step",
}


def _clean_base_url(args: dict[str, Any]) -> str:
    """Resolve the Omni HTTP base URL from tool args or environment."""
    raw_url = str(args.get("base_url") or os.getenv("OMNI_BRIDGE_URL") or DEFAULT_OMNI_BASE_URL).strip()
    return raw_url.rstrip("/") or DEFAULT_OMNI_BASE_URL


def normalize_omni_base_url(value: Any) -> str:
    """Normalize a persisted Omni base URL without exposing secrets."""
    raw_url = str(value or os.getenv("OMNI_BRIDGE_URL") or DEFAULT_OMNI_BASE_URL).strip()
    return raw_url.rstrip("/") or DEFAULT_OMNI_BASE_URL


def _timeout_seconds(args: dict[str, Any]) -> int:
    """Normalize Omni HTTP timeout; zero means no automatic timeout for jobs."""
    raw_value = args.get("timeout_seconds")
    if raw_value in {None, ""}:
        raw_value = 0
    try:
        timeout = int(raw_value)
    except (TypeError, ValueError):
        timeout = 0
    return max(0, timeout)


def _string_list(value: Any) -> list[str]:
    """Normalize acceptance criteria into a compact list of strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _build_omni_command(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build the command text that Hana delegates to Omni."""
    task = str(args.get("task") or "").strip()
    if not task:
        raise ValueError("task is required.")

    mode = str(args.get("mode") or "inspect").strip().lower()
    mode = MODE_ALIASES.get(mode, mode)
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}.")

    cwd = str(args.get("cwd") or "").strip()
    acceptance = _string_list(args.get("acceptance"))
    lines = [
        "Hana is delegating this task to Omni-Agent OS.",
        "",
        OMNI_EXECUTOR_CONTEXT.strip(),
        "",
        f"Mode: {mode}",
        f"Task: {task}",
        "",
        "Return a concise execution report in this shape:",
        "STATUS: done | blocked | needs_review",
        "RESUMO: what you did or found",
        "EVIDENCIAS: files, commands, outputs, or observations",
        "PENDENCIAS: remaining blockers or risks",
        "PROXIMO_PASSO: one concrete next action",
    ]
    if cwd:
        lines.insert(2, f"Workspace: {cwd}")
    if acceptance:
        lines.extend(["", "Acceptance criteria:"])
        lines.extend(f"- {item}" for item in acceptance)

    return "\n".join(lines), {"task": task, "mode": mode, "cwd": cwd, "acceptance": acceptance}


def _post_omni_command(base_url: str, command: str, timeout_seconds: int) -> tuple[str, str]:
    """Post a command to Omni and return its backend status plus response text."""
    url = f"{base_url}/api/command"
    payload = json.dumps({"command": command}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=None if timeout_seconds <= 0 else timeout_seconds) as response:
        raw_body = response.read().decode("utf-8", errors="replace")

    try:
        body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as exc:
        raise ValueError("omni_invalid_json_response") from exc

    return str(body.get("status") or "unknown"), str(body.get("response") or "").strip()


def omni_status(base_url: str | None = None, timeout_seconds: float = 1.5) -> dict[str, Any]:
    """Check whether the local Omni-Agent OS HTTP API is reachable."""
    normalized_url = normalize_omni_base_url(base_url)
    request = urllib.request.Request(
        normalized_url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        latency_ms = round((time.monotonic() - started) * 1000)
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            body = {"raw": raw_body[:500]}
        return {
            "ok": True,
            "online": True,
            "baseUrl": normalized_url,
            "latencyMs": latency_ms,
            "status": body,
        }
    except urllib.error.URLError as exc:
        return {"ok": False, "online": False, "baseUrl": normalized_url, "error": f"omni_unavailable: {exc.reason}"}
    except TimeoutError:
        return {"ok": False, "online": False, "baseUrl": normalized_url, "error": "omni_timeout"}
    except Exception as exc:
        return {"ok": False, "online": False, "baseUrl": normalized_url, "error": f"omni_status_error: {exc}"}


def parse_omni_report(text: str) -> dict[str, str]:
    """Parse Omni's structured text report into stable fields."""
    report: dict[str, str] = {value: "" for value in set(REPORT_KEYS.values())}
    current_key = ""
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper_line = line.upper()
        matched = ""
        matched_label = ""
        for label, key in REPORT_KEYS.items():
            prefix = f"{label}:"
            if upper_line.startswith(prefix):
                matched = key
                matched_label = label
                break
        if matched:
            current_key = matched
            report[current_key] = line[len(matched_label) + 1 :].strip()
            continue
        if current_key:
            report[current_key] = f"{report[current_key]}\n{line}".strip()

    normalized_status = report.get("status", "").strip().lower()
    if normalized_status not in {"done", "blocked", "needs_review"}:
        normalized_status = "needs_review" if text.strip() else "blocked"
    report["status"] = normalized_status
    return report


def _http_error_result(exc: Exception) -> ToolResult:
    """Convert Omni transport failures into a clear ToolResult."""
    if isinstance(exc, urllib.error.HTTPError):
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return ToolResult(ok=False, tool="omni.delegate", error=f"omni_http_{exc.code}: {detail}")
    if isinstance(exc, urllib.error.URLError):
        return ToolResult(ok=False, tool="omni.delegate", error=f"omni_unavailable: {exc.reason}")
    if isinstance(exc, TimeoutError):
        return ToolResult(ok=False, tool="omni.delegate", error="omni_timeout")
    if isinstance(exc, ValueError):
        return ToolResult(ok=False, tool="omni.delegate", error=str(exc))
    return ToolResult(ok=False, tool="omni.delegate", error=f"omni_bridge_error: {exc}")


def _max_rounds(args: dict[str, Any]) -> int:
    """Clamp supervised Omni rounds to prevent runaway delegation loops."""
    try:
        value = int(args.get("max_rounds") or 3)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(value, 8))


def _build_follow_up_command(task: str, previous_response: str, round_index: int) -> str:
    """Build a supervisor follow-up request when Omni did not finish cleanly."""
    return "\n".join(
        [
            "Hana reviewed your previous Omni-Agent OS report and it is not done yet.",
            "",
            OMNI_EXECUTOR_CONTEXT.strip(),
            "",
            f"Round: {round_index}",
            f"Original task: {task}",
            "",
            "Previous report:",
            previous_response.strip(),
            "",
            "Continue or correct the work. If you are blocked, explain the exact blocker.",
            "Return the same report shape:",
            "STATUS: done | blocked | needs_review",
            "RESUMO: what changed in this round",
            "EVIDENCIAS: concrete evidence",
            "PENDENCIAS: remaining blockers or risks",
            "PROXIMO_PASSO: one concrete next action",
        ]
    )


def omni_delegate_sync(args: dict[str, Any]) -> ToolResult:
    """Delegate one synchronous task to the local Omni-Agent OS HTTP API."""
    try:
        command, normalized = _build_omni_command(args)
    except ValueError as exc:
        return ToolResult(ok=False, tool="omni.delegate", error=str(exc))

    base_url = _clean_base_url(args)
    try:
        status, response_text = _post_omni_command(base_url, command, _timeout_seconds(args))
    except Exception as exc:
        return _http_error_result(exc)

    report = parse_omni_report(response_text)
    ok = status.lower() == "success" and bool(response_text)
    return ToolResult(
        ok=ok,
        tool="omni.delegate",
        output={
            "backend": "omni",
            "status": status,
            "completion_status": report["status"],
            "needs_follow_up": report["status"] != "done",
            "report": report,
            "response": response_text,
            "base_url": base_url,
            **normalized,
        },
        error=None if ok else f"omni_status_{status}",
    )


def omni_supervise_sync(args: dict[str, Any]) -> ToolResult:
    """Delegate a task to Omni and run bounded supervisor follow-up rounds."""
    try:
        command, normalized = _build_omni_command(args)
    except ValueError as exc:
        return ToolResult(ok=False, tool="omni.supervise", error=str(exc))

    base_url = _clean_base_url(args)
    timeout = _timeout_seconds(args)
    rounds: list[dict[str, Any]] = []
    current_command = command
    last_status = "unknown"
    last_response = ""
    last_report = parse_omni_report("")

    for round_index in range(1, _max_rounds(args) + 1):
        try:
            last_status, last_response = _post_omni_command(base_url, current_command, timeout)
        except Exception as exc:
            error = _http_error_result(exc)
            error.tool = "omni.supervise"
            return error

        last_report = parse_omni_report(last_response)
        rounds.append(
            {
                "round": round_index,
                "backend_status": last_status,
                "completion_status": last_report["status"],
                "report": last_report,
                "response": last_response,
            }
        )
        if last_status.lower() != "success" or last_report["status"] == "done":
            break
        current_command = _build_follow_up_command(normalized["task"], last_response, round_index + 1)

    ok = bool(last_response) and last_status.lower() == "success"
    return ToolResult(
        ok=ok,
        tool="omni.supervise",
        output={
            "backend": "omni",
            "status": last_status,
            "completion_status": last_report["status"],
            "needs_follow_up": last_report["status"] != "done",
            "report": last_report,
            "rounds": rounds,
            "round_count": len(rounds),
            "response": last_response,
            "base_url": base_url,
            "max_rounds": _max_rounds(args),
            **normalized,
        },
        error=None if ok else f"omni_status_{last_status}",
    )


def omni_delegate(args: dict[str, Any]) -> ToolResult:
    """Start one Omni delegation through background jobs when available."""
    if args.get("_background_job") is not True:
        return omni_delegate_sync(args)
    try:
        from hana_agent_oss.api.services.agent_jobs import get_agent_job_manager

        manager = get_agent_job_manager()
    except Exception:
        manager = None
    if manager is not None:
        return manager.start_omni(args, tool_name="omni.delegate")
    return omni_delegate_sync(args)


def omni_supervise(args: dict[str, Any]) -> ToolResult:
    """Start one supervised Omni job in the background when available."""
    if args.get("_background_job") is not True:
        return omni_supervise_sync(args)
    try:
        from hana_agent_oss.api.services.agent_jobs import get_agent_job_manager

        manager = get_agent_job_manager()
    except Exception:
        manager = None
    if manager is not None:
        return manager.start_omni(args, tool_name="omni.supervise")
    return omni_supervise_sync(args)


def register_omni_tools(registry: ToolRegistry) -> None:
    """Register Omni bridge tools in the Agent Core tool registry."""
    input_schema = {
        "type": "object",
        "required": ["task"],
        "properties": {
            "task": {"type": "string"},
            "mode": {"type": "string", "enum": sorted(VALID_MODES)},
            "cwd": {"type": "string"},
            "acceptance": {"type": "string"},
            "base_url": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
            "max_rounds": {"type": "integer"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "backend": {"type": "string"},
            "status": {"type": "string"},
            "response": {"type": "string"},
            "task": {"type": "string"},
            "mode": {"type": "string"},
            "base_url": {"type": "string"},
            "completion_status": {"type": "string"},
            "needs_follow_up": {"type": "boolean"},
            "report": {"type": "object"},
            "rounds": {"type": "array"},
        },
    }
    registry.register(
        RegisteredTool(
            "omni.delegate",
            "Delegate a local task to the Omni-Agent OS HTTP API.",
            omni_delegate,
            input_schema,
            output_schema,
            "medium",
            "omni.bridge",
        )
    )
    registry.register(
        RegisteredTool(
            "omni.supervise",
            "Delegate a local task to Omni and run bounded supervisor follow-up rounds.",
            omni_supervise,
            input_schema,
            output_schema,
            "medium",
            "omni.bridge",
        )
    )
