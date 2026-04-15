"""Phase 4B — Sandboxed code execution endpoints.

Agents can run a code artifact inside an ephemeral Docker container
and get back stdout/stderr/exit. Execution history lives in the
``artifact_executions`` table so the UI (and auditors) can see who ran
what and when.

Endpoints:
    POST /projects/{pid}/artifacts/{aid}/execute   — run a code artifact
    GET  /projects/{pid}/artifacts/{aid}/executions — per-artifact history
    GET  /projects/{pid}/executions                  — project-wide history
    GET  /projects/{pid}/executions/{eid}            — single execution
    GET  /sandbox/info                               — runtime capabilities

Safety posture:
- Code mime allowlist (python only for now).
- Per-IP rate limit on execute (Phase 4B default: 6/min).
- Per-project daily quota (Phase 4B default: 100/day).
- Docker runner enforces: no network, read-only FS, tmpfs /tmp, mem/pid caps,
  cap_drop=ALL, no-new-privileges, non-root user.
- Runner raises SandboxUnavailable → 503 when docker is not reachable,
  so instances that cannot provide the feature stay honest instead of
  silently dropping runs.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import config, sandbox
from app.auth import get_current_agent
from app.database import get_db, parse_execution_row
from app.models import (
    ExecutionRequest,
    ExecutionResponse,
)
from app.safety import check_content, check_ip_rate
from app.utils import client_ip as _client_ip

router = APIRouter(tags=["sandbox"])


# ── Helpers ──────────────────────────────────────────────────────

async def _project_or_404(project_id: str) -> dict:
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    )
    if not rows:
        raise HTTPException(404, "Project not found")
    return dict(rows[0])


async def _require_project_member(project_id: str, agent_id: str) -> str:
    proj = await _project_or_404(project_id)
    if proj["status"] == "archived":
        raise HTTPException(400, "Cannot execute inside an archived project")
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent_id),
    )
    if not rows:
        raise HTTPException(403, "Not a member of this project")
    role = rows[0]["role"]
    if role == "viewer":
        raise HTTPException(403, "Viewers cannot execute code")
    return role


async def _artifact_or_404(project_id: str, artifact_id: str) -> dict:
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Artifact not found")
    return dict(rows[0])


async def _daily_quota_remaining(project_id: str) -> int:
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT COUNT(*) AS n FROM artifact_executions
           WHERE project_id = ?
           AND created_at >= datetime('now', '-1 day')""",
        (project_id,),
    )
    used = rows[0]["n"] if rows else 0
    return max(0, config.SANDBOX_DAILY_QUOTA_PER_PROJECT - used)


def _load_artifact_code(art: dict) -> str:
    """Read the artifact bytes off disk and return as UTF-8."""
    from app.routers.artifacts import _resolve_storage_path

    path = _resolve_storage_path(art["storage_path"])
    if not path.exists():
        raise HTTPException(410, "Artifact bytes missing from storage")
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "Artifact bytes are not valid UTF-8 text")


# ── Info ─────────────────────────────────────────────────────────

@router.get("/sandbox/info")
async def sandbox_info():
    """Runtime capabilities so clients can tell if the feature is live here."""
    return {
        "available": sandbox.is_available(),
        "image": config.SANDBOX_IMAGE,
        "timeout_seconds": config.SANDBOX_TIMEOUT_SECONDS,
        "memory_mb": config.SANDBOX_MEMORY_MB,
        "max_output_bytes": config.SANDBOX_MAX_OUTPUT_BYTES,
        "daily_quota_per_project": config.SANDBOX_DAILY_QUOTA_PER_PROJECT,
        "allowed_mimes": list(config.SANDBOX_ALLOWED_MIMES),
    }


# ── Execute ─────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/artifacts/{artifact_id}/execute",
    response_model=ExecutionResponse,
    status_code=201,
)
async def execute_artifact(
    project_id: str,
    artifact_id: str,
    request: Request,
    body: Optional[ExecutionRequest] = None,
    agent: dict = Depends(get_current_agent),
):
    """Run a code artifact inside the sandbox and persist the result.

    Returns the completed execution row (no background polling — runs
    are short enough to stay synchronous).
    """
    check_ip_rate(
        _client_ip(request),
        "sandbox_execute",
        limit=config.SANDBOX_IP_RATE_PER_MIN,
        window_seconds=60,
    )
    await _require_project_member(project_id, agent["id"])
    art = await _artifact_or_404(project_id, artifact_id)

    if art["kind"] != "code":
        raise HTTPException(
            400, f"Only 'code' artifacts can be executed (this is '{art['kind']}')"
        )
    if art["mime"] not in config.SANDBOX_ALLOWED_MIMES:
        raise HTTPException(
            415,
            f"Sandbox does not support mime '{art['mime']}'. "
            f"Allowed: {', '.join(config.SANDBOX_ALLOWED_MIMES)}",
        )

    remaining = await _daily_quota_remaining(project_id)
    if remaining <= 0:
        raise HTTPException(
            429,
            f"Project has exhausted its daily sandbox quota "
            f"({config.SANDBOX_DAILY_QUOTA_PER_PROJECT}/day). Try again tomorrow.",
        )

    code = _load_artifact_code(art)
    check_content(code)  # Tier 1 floor — shouldn't fire (artifact was already filtered)

    # Cap user-supplied overrides against config ceilings.
    timeout_s = config.SANDBOX_TIMEOUT_SECONDS
    memory_mb = config.SANDBOX_MEMORY_MB
    if body is not None:
        if body.timeout_s is not None:
            timeout_s = min(body.timeout_s, config.SANDBOX_TIMEOUT_SECONDS)
        if body.memory_mb is not None:
            memory_mb = min(body.memory_mb, config.SANDBOX_MEMORY_MB)

    execution_id = str(uuid.uuid4())
    db = get_db()
    await db.execute(
        """INSERT INTO artifact_executions
           (id, artifact_id, project_id, requested_by, status)
           VALUES (?, ?, ?, ?, 'running')""",
        (execution_id, artifact_id, project_id, agent["id"]),
    )
    await db.commit()

    try:
        result = sandbox.run_python(
            code,
            timeout_s=timeout_s,
            memory_mb=memory_mb,
            max_output_bytes=config.SANDBOX_MAX_OUTPUT_BYTES,
        )
    except sandbox.SandboxUnavailable as exc:
        await db.execute(
            """UPDATE artifact_executions
               SET status='error', error=?, finished_at=strftime('%Y-%m-%dT%H:%M:%f', 'now')
               WHERE id=?""",
            (str(exc), execution_id),
        )
        await db.commit()
        # 503 so clients can retry or fall back.
        raise HTTPException(503, f"Sandbox unavailable: {exc}")

    await db.execute(
        """UPDATE artifact_executions
           SET status=?, exit_code=?, stdout=?, stderr=?, duration_ms=?,
               finished_at=strftime('%Y-%m-%dT%H:%M:%f', 'now')
           WHERE id=?""",
        (
            result.status,
            result.exit_code,
            result.stdout,
            result.stderr,
            result.duration_ms,
            execution_id,
        ),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM artifact_executions WHERE id = ?", (execution_id,)
    )
    return ExecutionResponse(**parse_execution_row(dict(rows[0])))


# ── History / detail ────────────────────────────────────────────

@router.get(
    "/projects/{project_id}/artifacts/{artifact_id}/executions",
    response_model=list[ExecutionResponse],
)
async def list_artifact_executions(
    project_id: str,
    artifact_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    check_ip_rate(_client_ip(request), "executions_browse", limit=120, window_seconds=60)
    await _artifact_or_404(project_id, artifact_id)
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM artifact_executions
           WHERE project_id = ? AND artifact_id = ?
           ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (project_id, artifact_id, limit, offset),
    )
    return [ExecutionResponse(**parse_execution_row(dict(r))) for r in rows]


@router.get(
    "/projects/{project_id}/executions",
    response_model=list[ExecutionResponse],
)
async def list_project_executions(
    project_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    check_ip_rate(_client_ip(request), "executions_browse", limit=120, window_seconds=60)
    await _project_or_404(project_id)
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM artifact_executions
           WHERE project_id = ?
           ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (project_id, limit, offset),
    )
    return [ExecutionResponse(**parse_execution_row(dict(r))) for r in rows]


@router.get(
    "/projects/{project_id}/executions/{execution_id}",
    response_model=ExecutionResponse,
)
async def get_execution(project_id: str, execution_id: str, request: Request):
    check_ip_rate(_client_ip(request), "executions_browse", limit=120, window_seconds=60)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifact_executions WHERE id = ? AND project_id = ?",
        (execution_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Execution not found")
    return ExecutionResponse(**parse_execution_row(dict(rows[0])))
