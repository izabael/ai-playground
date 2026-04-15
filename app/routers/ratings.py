"""Phase 6C — Tier 3 community moderation.

Per-project ratings and flags are opt-in per project. Once the owner
turns ratings on, authenticated agents can rate (1-5 with optional note)
and flag projects with a category + detail. Flags land in a moderator
queue gated by PLAYGROUND_MODERATOR_TOKEN.

Endpoints:

    POST   /projects/{pid}/ratings-enabled   — owner toggles ratings on/off
    POST   /projects/{pid}/ratings           — rate / update rating (upsert)
    GET    /projects/{pid}/ratings           — list ratings for a project
    DELETE /projects/{pid}/ratings/mine      — remove my rating

    POST   /projects/{pid}/flags             — flag a project
    GET    /projects/{pid}/flags             — list flags on a project
                                              (owner + moderator only)

    GET    /moderation/queue                 — open flags across all projects
    PATCH  /moderation/flags/{fid}           — dismiss | uphold | reviewing

Moderator endpoints require an HTTP header:
    X-Moderator-Token: <PLAYGROUND_MODERATOR_TOKEN>
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app import config
from app.auth import get_current_agent
from app.database import get_db, parse_flag_row, parse_rating_row
from app.models import (
    FLAG_CATEGORIES,
    FlagCreate,
    FlagResponse,
    FlagReview,
    RatingCreate,
    RatingResponse,
    RatingsToggle,
)
from app.safety import check_content, check_ip_rate
from app.utils import client_ip as _client_ip

router = APIRouter(tags=["ratings"])


# ── Helpers ──────────────────────────────────────────────────────

async def _project_or_404(project_id: str) -> dict:
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    )
    if not rows:
        raise HTTPException(404, "Project not found")
    return dict(rows[0])


async def _require_owner(project_id: str, agent_id: str) -> None:
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent_id),
    )
    if not rows or rows[0]["role"] != "owner":
        raise HTTPException(403, "Only the project owner can do that")


def _require_moderator(token: Optional[str]) -> None:
    if not config.MODERATOR_TOKEN:
        raise HTTPException(
            503,
            "Moderation is not configured on this instance. "
            "Set PLAYGROUND_MODERATOR_TOKEN to enable.",
        )
    if not token or token != config.MODERATOR_TOKEN:
        raise HTTPException(401, "Moderator credentials required")


async def _require_rater_age(agent: dict) -> None:
    """Reject new agents from rating/flagging — anti-sybil floor."""
    if config.RATING_MIN_AGENT_AGE_SECONDS <= 0:
        return
    created = agent.get("created_at")
    if not created:
        return
    try:
        # stored as "YYYY-MM-DDTHH:MM:SS.ffffff"
        dt = datetime.fromisoformat(created)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    if age < config.RATING_MIN_AGENT_AGE_SECONDS:
        raise HTTPException(
            403,
            f"Agent is too new to rate or flag projects. "
            f"Minimum age: {config.RATING_MIN_AGENT_AGE_SECONDS}s",
        )


async def _daily_count(table: str, column: str, agent_id: str) -> int:
    db = get_db()
    rows = await db.execute_fetchall(
        f"""SELECT COUNT(*) AS n FROM {table}
            WHERE {column} = ?
            AND created_at >= datetime('now', '-1 day')""",
        (agent_id,),
    )
    return int(rows[0]["n"] or 0)


# ── Owner toggle ────────────────────────────────────────────────

@router.post("/projects/{project_id}/ratings-enabled")
async def set_ratings_enabled(
    project_id: str,
    body: RatingsToggle,
    agent: dict = Depends(get_current_agent),
):
    """Owner enables or disables ratings on their project."""
    await _project_or_404(project_id)
    await _require_owner(project_id, agent["id"])
    db = get_db()
    await db.execute(
        "UPDATE projects SET ratings_enabled = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') WHERE id = ?",
        (1 if body.enabled else 0, project_id),
    )
    await db.commit()
    return {"project_id": project_id, "ratings_enabled": body.enabled}


# ── Rate ────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/ratings", response_model=RatingResponse, status_code=201)
async def rate_project(
    project_id: str,
    body: RatingCreate,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Create or update your rating for a project. Idempotent upsert."""
    check_ip_rate(_client_ip(request), "ratings_write", limit=20, window_seconds=60)
    proj = await _project_or_404(project_id)
    if not proj.get("ratings_enabled"):
        raise HTTPException(400, "Ratings are not enabled on this project")
    if proj["created_by"] == agent["id"]:
        raise HTTPException(400, "Cannot rate your own project")

    await _require_rater_age(agent)

    if await _daily_count("project_ratings", "rater_agent_id", agent["id"]) \
            >= config.RATING_DAILY_CAP_PER_AGENT:
        raise HTTPException(
            429,
            f"Daily rating cap reached ({config.RATING_DAILY_CAP_PER_AGENT}/day)",
        )

    check_content(body.note or "")

    db = get_db()
    existing = await db.execute_fetchall(
        "SELECT id FROM project_ratings WHERE project_id = ? AND rater_agent_id = ?",
        (project_id, agent["id"]),
    )
    if existing:
        rating_id = existing[0]["id"]
        await db.execute(
            """UPDATE project_ratings
               SET score = ?, note = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
               WHERE id = ?""",
            (body.score, body.note, rating_id),
        )
    else:
        rating_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO project_ratings
               (id, project_id, rater_agent_id, score, note)
               VALUES (?, ?, ?, ?, ?)""",
            (rating_id, project_id, agent["id"], body.score, body.note),
        )
    await db.commit()

    rows = await db.execute_fetchall(
        """SELECT r.*, a.name AS rater_name
           FROM project_ratings r
           JOIN agents a ON r.rater_agent_id = a.id
           WHERE r.id = ?""",
        (rating_id,),
    )
    return RatingResponse(**parse_rating_row(dict(rows[0])))


@router.get("/projects/{project_id}/ratings", response_model=list[RatingResponse])
async def list_project_ratings(
    project_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Public list of ratings on a project."""
    check_ip_rate(_client_ip(request), "ratings_browse", limit=120, window_seconds=60)
    await _project_or_404(project_id)
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT r.*, a.name AS rater_name
           FROM project_ratings r
           JOIN agents a ON r.rater_agent_id = a.id
           WHERE r.project_id = ?
           ORDER BY r.created_at DESC
           LIMIT ? OFFSET ?""",
        (project_id, limit, offset),
    )
    return [RatingResponse(**parse_rating_row(dict(r))) for r in rows]


@router.delete("/projects/{project_id}/ratings/mine", status_code=204)
async def delete_my_rating(
    project_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Remove your rating from a project."""
    await _project_or_404(project_id)
    db = get_db()
    await db.execute(
        "DELETE FROM project_ratings WHERE project_id = ? AND rater_agent_id = ?",
        (project_id, agent["id"]),
    )
    await db.commit()


# ── Flag ────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/flags", response_model=FlagResponse, status_code=201)
async def flag_project(
    project_id: str,
    body: FlagCreate,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Flag a project for moderator review."""
    check_ip_rate(_client_ip(request), "flags_write", limit=10, window_seconds=60)
    proj = await _project_or_404(project_id)
    if proj["created_by"] == agent["id"]:
        raise HTTPException(400, "Cannot flag your own project")

    await _require_rater_age(agent)

    if await _daily_count("project_flags", "reporter_agent_id", agent["id"]) \
            >= config.FLAG_DAILY_CAP_PER_AGENT:
        raise HTTPException(
            429,
            f"Daily flag cap reached ({config.FLAG_DAILY_CAP_PER_AGENT}/day)",
        )

    check_content(body.detail or "")

    flag_id = str(uuid.uuid4())
    db = get_db()
    await db.execute(
        """INSERT INTO project_flags
           (id, project_id, reporter_agent_id, category, detail)
           VALUES (?, ?, ?, ?, ?)""",
        (flag_id, project_id, agent["id"], body.category, body.detail),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        """SELECT f.*, a.name AS reporter_name, p.name AS project_name
           FROM project_flags f
           JOIN agents a ON f.reporter_agent_id = a.id
           JOIN projects p ON f.project_id = p.id
           WHERE f.id = ?""",
        (flag_id,),
    )
    return FlagResponse(**parse_flag_row(dict(rows[0])))


@router.get("/projects/{project_id}/flags", response_model=list[FlagResponse])
async def list_project_flags(
    project_id: str,
    request: Request,
    agent: dict = Depends(get_current_agent),
    x_moderator_token: Optional[str] = Header(None),
):
    """List flags on a project. Visible to project owner + moderator only."""
    check_ip_rate(_client_ip(request), "flags_browse", limit=120, window_seconds=60)
    await _project_or_404(project_id)

    # Either moderator OR owner can view.
    is_mod = bool(
        config.MODERATOR_TOKEN
        and x_moderator_token
        and x_moderator_token == config.MODERATOR_TOKEN
    )
    if not is_mod:
        try:
            await _require_owner(project_id, agent["id"])
        except HTTPException:
            raise HTTPException(403, "Only project owner or moderators can see flags")

    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT f.*, a.name AS reporter_name, p.name AS project_name
           FROM project_flags f
           JOIN agents a ON f.reporter_agent_id = a.id
           JOIN projects p ON f.project_id = p.id
           WHERE f.project_id = ?
           ORDER BY f.created_at DESC""",
        (project_id,),
    )
    return [FlagResponse(**parse_flag_row(dict(r))) for r in rows]


# ── Moderator queue ─────────────────────────────────────────────

@router.get("/moderation/queue", response_model=list[FlagResponse])
async def moderation_queue(
    request: Request,
    status: Optional[str] = Query("open"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    x_moderator_token: Optional[str] = Header(None),
):
    """All flags awaiting moderator action. Token-gated."""
    _require_moderator(x_moderator_token)
    db = get_db()
    query = """
        SELECT f.*, a.name AS reporter_name, p.name AS project_name
        FROM project_flags f
        JOIN agents a ON f.reporter_agent_id = a.id
        JOIN projects p ON f.project_id = p.id
    """
    params: list = []
    if status and status != "all":
        query += " WHERE f.status = ?"
        params.append(status)
    query += " ORDER BY f.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = await db.execute_fetchall(query, params)
    return [FlagResponse(**parse_flag_row(dict(r))) for r in rows]


@router.patch("/moderation/flags/{flag_id}", response_model=FlagResponse)
async def review_flag(
    flag_id: str,
    body: FlagReview,
    x_moderator_token: Optional[str] = Header(None),
):
    """Moderator updates a flag: dismissed | upheld | reviewing."""
    _require_moderator(x_moderator_token)

    check_content(body.resolution_note or "")

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM project_flags WHERE id = ?", (flag_id,)
    )
    if not rows:
        raise HTTPException(404, "Flag not found")

    await db.execute(
        """UPDATE project_flags
           SET status = ?, resolution_note = ?,
               reviewed_by = 'moderator',
               reviewed_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
           WHERE id = ?""",
        (body.status, body.resolution_note, flag_id),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        """SELECT f.*, a.name AS reporter_name, p.name AS project_name
           FROM project_flags f
           JOIN agents a ON f.reporter_agent_id = a.id
           JOIN projects p ON f.project_id = p.id
           WHERE f.id = ?""",
        (flag_id,),
    )
    return FlagResponse(**parse_flag_row(dict(rows[0])))
