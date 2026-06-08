from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from hana_agent_oss.api.services.terminal_agent import append_terminal_event
from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.tools.omni_tools import (
    _build_omni_command,
    _clean_base_url,
    _post_omni_command,
    _timeout_seconds,
    parse_omni_report,
)


AGENT_JOBS_SETTING = "agent_jobs_runtime"
FINAL_STATUSES = {"done", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running"}
JOB_HISTORY_LIMIT = 50
MAX_PROGRESS_ITEMS = 100
MAX_RESULT_CHARS = 24000


def utc_now_iso() -> str:
    """Return a compact UTC timestamp for persisted runtime job records."""
    return datetime.now(timezone.utc).isoformat()


def compact_text(value: Any, limit: int = MAX_RESULT_CHARS) -> str:
    """Keep persisted job output bounded without hiding the useful prefix."""
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[truncated]"


@dataclass
class ActiveJobRuntime:
    """In-memory handles used to cancel jobs that are still running."""

    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    process: subprocess.Popen[str] | None = None
    stream_response: Any | None = None
    reader_threads: list[threading.Thread] = field(default_factory=list)


class AgentJobManager:
    """Runs long Omni tasks outside the blocking chat turn."""

    def __init__(self, memory: MemoryStore, *, history_limit: int = JOB_HISTORY_LIMIT) -> None:
        self.memory = memory
        self.history_limit = history_limit
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_by_agent: dict[str, str] = {}
        self._runtimes: dict[str, ActiveJobRuntime] = {}
        self._speaker: Callable[[str], Awaitable[bool]] | None = None
        self._load_persisted_jobs()

    def set_speaker(self, speaker: Callable[[str], Awaitable[bool]]) -> None:
        """Attach the voice runtime speaker used for short completion notices."""
        self._speaker = speaker

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return active jobs plus retained history in newest-first order."""
        with self._lock:
            return sorted((dict(job) for job in self._jobs.values()), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return one job record by id."""
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            return dict(job) if job else None

    def active_job(self, agent: str) -> dict[str, Any] | None:
        """Return the active job for one agent, if present."""
        with self._lock:
            job_id = self._active_by_agent.get(agent)
            if not job_id:
                return None
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def start_omni(self, args: dict[str, Any], *, tool_name: str = "omni.supervise") -> ToolResult:
        """Create a background Omni job and return immediately."""
        try:
            command, normalized = _build_omni_command(args)
        except ValueError as exc:
            return ToolResult(ok=False, tool=tool_name, error=str(exc))

        base_url = _clean_base_url(args)
        timeout = _timeout_seconds(args)
        job = self._create_job(
            agent="omni",
            tool=tool_name,
            mode=str(normalized.get("mode") or "inspect"),
            task=str(normalized.get("task") or ""),
            cwd=str(normalized.get("cwd") or ""),
            metadata={
                "acceptance": normalized.get("acceptance") or [],
                "base_url": base_url,
                "command": command,
                "timeout_seconds": timeout,
            },
        )
        if not job["ok"]:
            return ToolResult(ok=False, tool=tool_name, error=str(job["error"]), output={"activeJob": job.get("activeJob")})

        job_id = str(job["job"]["job_id"])
        runtime = self._runtimes[job_id]
        thread = threading.Thread(target=self._run_omni_job, args=(job_id,), name=f"hana-omni-job-{job_id[:8]}", daemon=True)
        runtime.thread = thread
        thread.start()
        return self._job_started_result(job["job"])

    def cancel_job(self, job_id: str, *, reason: str = "user_request") -> dict[str, Any]:
        """Request cancellation for one active job."""
        job_id = str(job_id or "").strip()
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"ok": False, "error": "agent_job_not_found", "job_id": job_id}
            if job.get("status") in FINAL_STATUSES:
                return {"ok": True, "alreadyFinal": True, "job": dict(job)}
            job["cancel_requested"] = True
            job["updated_at"] = utc_now_iso()
            self._save_jobs_locked()
            runtime = self._runtimes.get(job_id)

        if runtime:
            runtime.cancel_event.set()
            if runtime.stream_response is not None:
                try:
                    runtime.stream_response.close()
                except Exception:
                    pass
            if runtime.process is not None and runtime.process.poll() is None:
                try:
                    runtime.process.terminate()
                except Exception:
                    pass

        self._append_terminal(job_id, "job.cancel_requested", "Cancelamento solicitado pela Nakamura.", status="running")
        return {"ok": True, "cancelRequested": True, "job": self.get_job(job_id)}

    def cancel_active(self, *, agent: str = "", reason: str = "user_request") -> dict[str, Any]:
        """Cancel active jobs, optionally only for one agent."""
        agent = str(agent or "").strip().lower()
        with self._lock:
            if agent:
                job_ids = [self._active_by_agent[agent]] if agent in self._active_by_agent else []
            else:
                job_ids = list(self._active_by_agent.values())
        results = [self.cancel_job(job_id, reason=reason) for job_id in job_ids]
        return {"ok": True, "cancelled": len([item for item in results if item.get("ok")]), "results": results}

    def _load_persisted_jobs(self) -> None:
        """Load retained jobs and mark stale active jobs as failed after a backend restart."""
        data = self.memory.get_setting(AGENT_JOBS_SETTING, {"jobs": []})
        jobs = data.get("jobs") if isinstance(data, dict) else []
        if not isinstance(jobs, list):
            jobs = []
        changed = False
        for item in jobs:
            if not isinstance(item, dict) or not item.get("job_id"):
                continue
            job = dict(item)
            if job.get("status") in ACTIVE_STATUSES:
                job["status"] = "failed"
                job["error"] = "backend_restarted"
                job["finished_at"] = utc_now_iso()
                job["updated_at"] = job["finished_at"]
                changed = True
            self._jobs[str(job["job_id"])] = job
        if changed:
            with self._lock:
                self._save_jobs_locked()

    def _create_job(self, *, agent: str, tool: str, mode: str, task: str, cwd: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Create and persist a queued job while enforcing one active job per agent."""
        agent = agent.strip().lower()
        with self._lock:
            active_id = self._active_by_agent.get(agent)
            if active_id and self._jobs.get(active_id, {}).get("status") in ACTIVE_STATUSES:
                return {"ok": False, "error": f"agent_job_already_running:{agent}", "activeJob": dict(self._jobs[active_id])}

            job_id = f"{agent}-{uuid.uuid4().hex[:12]}"
            now = utc_now_iso()
            job = {
                "job_id": job_id,
                "agent": agent,
                "tool": tool,
                "mode": mode,
                "task": task,
                "cwd": cwd,
                "status": "queued",
                "created_at": now,
                "started_at": "",
                "updated_at": now,
                "finished_at": "",
                "duration_ms": None,
                "progress": [],
                "result": None,
                "error": None,
                "cancel_requested": False,
                "metadata": metadata,
            }
            self._jobs[job_id] = job
            self._active_by_agent[agent] = job_id
            self._runtimes[job_id] = ActiveJobRuntime()
            self._save_jobs_locked()
            return {"ok": True, "job": dict(job)}

    def _mark_started(self, job_id: str) -> None:
        """Move a job to running state and announce it in the terminal."""
        with self._lock:
            job = self._jobs[job_id]
            now = utc_now_iso()
            job["status"] = "running"
            job["started_at"] = now
            job["updated_at"] = now
            self._save_jobs_locked()
        self._append_terminal(job_id, "job.started", f"{self._agent_label(job_id)} job iniciado.", kind="tool_call", status="running")

    def _finish_job(self, job_id: str, *, status: str, result: dict[str, Any] | None = None, error: str | None = None, speech: str = "") -> None:
        """Finalize a job, persist it, clear active handles, and optionally speak a short notice."""
        with self._lock:
            job = self._jobs[job_id]
            if job.get("cancel_requested") and status not in {"cancelled"}:
                status = "cancelled"
                error = error or "cancelled_by_user"
                speech = ""
            now = utc_now_iso()
            job["status"] = status
            job["result"] = result
            job["error"] = error
            job["finished_at"] = now
            job["updated_at"] = now
            job["duration_ms"] = self._duration_ms(job)
            self._active_by_agent.pop(str(job.get("agent")), None)
            self._runtimes.pop(job_id, None)
            self._save_jobs_locked()

        terminal_text = error or compact_text((result or {}).get("response") or (result or {}).get("summary") or f"{self._agent_label(job_id)} job finalizado.")
        self._append_terminal(job_id, f"job.{status}", terminal_text, kind="tool_result", status=status, speech_text=speech)
        if speech:
            self._speak_short_notice(speech)

    def _duration_ms(self, job: dict[str, Any]) -> int | None:
        """Compute duration from ISO timestamps when possible."""
        try:
            started = datetime.fromisoformat(str(job.get("started_at")))
            finished = datetime.fromisoformat(str(job.get("finished_at")))
            return round((finished - started).total_seconds() * 1000)
        except Exception:
            return None

    def _append_progress(self, job_id: str, event_type: str, message: str, *, detail: str = "") -> None:
        """Append progress to the job record and mirror it to Terminal Agent."""
        item = {"at": utc_now_iso(), "type": event_type, "message": compact_text(message, 2000), "detail": compact_text(detail, 4000)}
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            progress = list(job.get("progress") or [])
            progress.append(item)
            job["progress"] = progress[-MAX_PROGRESS_ITEMS:]
            job["updated_at"] = item["at"]
            self._save_jobs_locked()
        self._append_terminal(job_id, event_type, item["message"], status="running", detail=item["detail"])

    def _append_terminal(
        self,
        job_id: str,
        event_type: str,
        message: str,
        *,
        kind: str = "tool",
        status: str = "running",
        detail: str = "",
        speech_text: str = "",
    ) -> None:
        """Mirror one job event to Terminal Agent without letting logging break the job."""
        job = self.get_job(job_id)
        if not job:
            return
        display = compact_text(message, 12000)
        if detail:
            display = f"{display}\n{compact_text(detail, 12000)}"
        try:
            append_terminal_event(
                self.memory,
                {
                    "kind": kind,
                    "source": f"{job.get('agent')}_job",
                    "displayText": display,
                    "speechText": speech_text,
                    "status": status,
                    "toolName": str(job.get("tool") or ""),
                    "metadata": {
                        "tts": False,
                        "jobId": job_id,
                        "job_id": job_id,
                        "agent": job.get("agent"),
                        "jobEvent": event_type,
                        "mode": job.get("mode"),
                        "cwd": job.get("cwd"),
                    },
                },
            )
        except Exception:
            return

    def _save_jobs_locked(self) -> None:
        """Persist active records plus the retained final-job history."""
        ordered = sorted(self._jobs.values(), key=lambda item: str(item.get("created_at") or ""))
        active = [dict(item) for item in ordered if item.get("status") in ACTIVE_STATUSES]
        final = [dict(item) for item in ordered if item.get("status") in FINAL_STATUSES][-self.history_limit :]
        self._jobs = {str(item["job_id"]): item for item in [*final, *active]}
        self.memory.set_setting(AGENT_JOBS_SETTING, {"jobs": [*final, *active], "updated_at": utc_now_iso()})

    def _agent_label(self, job_id: str) -> str:
        """Return a user-facing label for the job agent."""
        return "Omni"

    def _cancel_requested(self, job_id: str) -> bool:
        """Return whether the current job was asked to stop."""
        runtime = self._runtimes.get(job_id)
        return bool(runtime and runtime.cancel_event.is_set())

    def _job_started_result(self, job: dict[str, Any]) -> ToolResult:
        """Build the immediate ToolResult returned to the LLM after enqueueing a job."""
        label = "Omni"
        return ToolResult(
            ok=True,
            tool=str(job.get("tool") or "agent.job"),
            output={
                "backend": str(job.get("agent") or ""),
                "status": "running",
                "completion_status": "running",
                "job_id": job.get("job_id"),
                "agent": job.get("agent"),
                "mode": job.get("mode"),
                "cwd": job.get("cwd"),
                "task": job.get("task"),
            "message": f"{label} job iniciado em background. A Hana pode continuar conversando enquanto ele trabalha.",
            "needs_follow_up": False,
        },
    )

    def _speak_short_notice(self, text: str) -> None:
        """Speak a short job completion notice without blocking the job thread."""
        if self._speaker is None:
            return

        def runner() -> None:
            try:
                asyncio.run(self._speaker(text))
            except Exception:
                return

        threading.Thread(target=runner, name="hana-agent-job-speech", daemon=True).start()

    def _read_process_streams(self, job_id: str, process: subprocess.Popen[str], stdout_lines: list[str], stderr_lines: list[str]) -> None:
        """Read stdout and stderr in helper threads to avoid subprocess deadlocks."""
        runtime = self._runtimes.get(job_id)

        def reader(stream: Any, target: list[str], label: str) -> None:
            try:
                for line in iter(stream.readline, ""):
                    clean = line.rstrip()
                    if not clean:
                        continue
                    target.append(clean)
                    self._append_progress(job_id, f"job.{label}", clean)
            except Exception:
                return

        threads = [
            threading.Thread(target=reader, args=(process.stdout, stdout_lines, "stdout"), daemon=True),
            threading.Thread(target=reader, args=(process.stderr, stderr_lines, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()
        if runtime:
            runtime.reader_threads = threads

    def _wait_stream_threads(self, runtime: ActiveJobRuntime | None) -> None:
        """Give process stream reader threads a moment to flush final output."""
        for thread in runtime.reader_threads if runtime else []:
            try:
                thread.join(timeout=1.0)
            except Exception:
                pass

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        """Terminate a subprocess gently first and force kill if it ignores cancellation."""
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
            return
        except Exception:
            pass
        try:
            process.kill()
        except Exception:
            pass

    def _run_omni_job(self, job_id: str) -> None:
        """Run one Omni command, preferring its streaming endpoint for progress."""
        self._mark_started(job_id)
        job = self.get_job(job_id) or {}
        metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
        base_url = str(metadata.get("base_url") or "").rstrip("/")
        command = str(metadata.get("command") or "")
        timeout = int(metadata.get("timeout_seconds") or 0)
        try:
            result = self._run_omni_stream(job_id, base_url, command, timeout)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
            if self._cancel_requested(job_id):
                self._finish_job(job_id, status="cancelled", error="cancelled_by_user")
                return
            self._append_progress(job_id, "job.progress", "Stream do Omni indisponivel; usando endpoint sincrono.")
            result = self._run_omni_sync(job_id, base_url, command, timeout)
        except Exception as exc:  # noqa: BLE001
            if self._cancel_requested(job_id):
                self._finish_job(job_id, status="cancelled", error="cancelled_by_user")
                return
            self._finish_job(job_id, status="failed", error=f"omni_bridge_error:{exc}", speech="Omni falhou. Deixei o erro no terminal.")
            return

        if self._cancel_requested(job_id):
            self._finish_job(job_id, status="cancelled", error="cancelled_by_user")
            return
        if result.get("ok"):
            self._finish_job(job_id, status="done", result=result, speech="Omni terminou a tarefa. Deixei o relatorio no terminal.")
            return
        self._finish_job(job_id, status="failed", result=result, error=str(result.get("error") or "omni_failed"), speech="Omni falhou. Deixei o erro no terminal.")

    def _run_omni_stream(self, job_id: str, base_url: str, command: str, timeout: int) -> dict[str, Any]:
        """Read Omni's SSE-like stream and convert it into Hana job progress."""
        url = f"{base_url}/api/command/stream"
        body = json.dumps({"command": command}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
        runtime = self._runtimes.get(job_id)
        text_chunks: list[str] = []
        error_text = ""
        response = urllib.request.urlopen(request, timeout=None if timeout <= 0 else timeout)
        if runtime:
            runtime.stream_response = response
        try:
            for raw_line in response:
                if self._cancel_requested(job_id):
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = str(payload.get("type") or "step")
                if event_type in {"text", "delta"}:
                    text_chunks.append(str(payload.get("content") or ""))
                    continue
                if event_type == "error":
                    error_text = str(payload.get("content") or payload.get("message") or "omni_stream_error")
                    self._append_progress(job_id, "job.error", error_text)
                    continue
                if event_type == "done":
                    break
                message = str(payload.get("message") or event_type)
                detail = str(payload.get("detail") or payload.get("tool") or "")
                self._append_progress(job_id, f"job.{event_type}", message, detail=detail)
        finally:
            if runtime:
                runtime.stream_response = None
            try:
                response.close()
            except Exception:
                pass

        response_text = "".join(text_chunks).strip()
        report = parse_omni_report(response_text)
        return {
            "ok": bool(response_text) and not error_text,
            "backend": "omni",
            "status": "success" if response_text and not error_text else "failed",
            "completion_status": report["status"],
            "needs_follow_up": report["status"] != "done",
            "report": report,
            "response": compact_text(response_text),
            "error": error_text,
            "base_url": base_url,
        }

    def _run_omni_sync(self, job_id: str, base_url: str, command: str, timeout: int) -> dict[str, Any]:
        """Fallback to Omni's legacy synchronous endpoint."""
        if self._cancel_requested(job_id):
            return {"ok": False, "error": "cancelled_by_user"}
        status, response_text = _post_omni_command(base_url, command, timeout)
        report = parse_omni_report(response_text)
        return {
            "ok": status.lower() == "success" and bool(response_text),
            "backend": "omni",
            "status": status,
            "completion_status": report["status"],
            "needs_follow_up": report["status"] != "done",
            "report": report,
            "response": compact_text(response_text),
            "base_url": base_url,
        }


_AGENT_JOB_MANAGER: AgentJobManager | None = None


def set_agent_job_manager(manager: AgentJobManager) -> None:
    """Register the process-wide job manager used by provider tool callables."""
    global _AGENT_JOB_MANAGER
    _AGENT_JOB_MANAGER = manager


def get_agent_job_manager() -> AgentJobManager | None:
    """Return the process-wide job manager when the API app has initialized it."""
    return _AGENT_JOB_MANAGER


def agent_job_cancel(args: dict[str, Any]) -> ToolResult:
    """Cancel Omni background jobs from a real LLM tool call."""
    manager = get_agent_job_manager()
    if manager is None:
        return ToolResult(ok=False, tool="agent.job.cancel", error="agent_job_manager_not_ready")

    job_id = str(args.get("job_id") or "").strip()
    agent = str(args.get("agent") or "").strip().lower()
    active = bool(args.get("active", True))
    reason = str(args.get("reason") or "user_request").strip() or "user_request"

    if job_id:
        return ToolResult(ok=True, tool="agent.job.cancel", output=manager.cancel_job(job_id, reason=reason))
    if active or agent:
        return ToolResult(ok=True, tool="agent.job.cancel", output=manager.cancel_active(agent=agent, reason=reason))
    return ToolResult(ok=False, tool="agent.job.cancel", error="job_id_or_active_agent_required")
