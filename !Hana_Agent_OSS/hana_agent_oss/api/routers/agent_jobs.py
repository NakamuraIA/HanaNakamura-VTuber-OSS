from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from hana_agent_oss.api.services.agent_jobs import AgentJobManager


router = APIRouter(tags=["Agent Jobs"])


def _manager(request: Request) -> AgentJobManager:
    """Return the app-scoped background job manager."""
    manager = getattr(request.app.state, "agent_jobs", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="agent_job_manager_not_ready")
    return manager


@router.get("/api/agent-jobs")
async def list_agent_jobs(request: Request) -> dict[str, Any]:
    """List active background agent jobs plus retained final history."""
    jobs = _manager(request).list_jobs()
    return {
        "ok": True,
        "jobs": jobs,
        "active": [job for job in jobs if job.get("status") in {"queued", "running"}],
    }


@router.get("/api/agent-jobs/{job_id}")
async def get_agent_job(request: Request, job_id: str) -> dict[str, Any]:
    """Return one background job by id."""
    job = _manager(request).get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="agent_job_not_found")
    return {"ok": True, "job": job}


@router.post("/api/agent-jobs/{job_id}/cancel")
async def cancel_agent_job(request: Request, job_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Request cancellation for one active background job."""
    reason = str((payload or {}).get("reason") or "control_panel").strip() or "control_panel"
    return _manager(request).cancel_job(job_id, reason=reason)


@router.post("/api/agent-jobs/cancel-active")
async def cancel_active_agent_jobs(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Request cancellation for the active job of one agent or all active jobs."""
    data = payload or {}
    agent = str(data.get("agent") or "").strip().lower()
    reason = str(data.get("reason") or "control_panel").strip() or "control_panel"
    return _manager(request).cancel_active(agent=agent, reason=reason)
