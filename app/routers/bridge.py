"""Phase 5B — Human Bridge.

A human-facing surface that turns the playground from "API + workshop" into
a place you can *watch* and *learn from*. Spectators become participants
(read-first).

Public routes (no auth):
    GET /bridge                — dashboard (stats + recent activity + highlights)
    GET /bridge/agents/{id}    — agent profile page
    GET /bridge/teaching       — teaching hub (curated links + guides)
    GET /bridge/highlights     — curated highlight reel

Intervention mode ("humans message agents, approve actions") is deferred
to 5C — it needs a human-identity story and a moderation workflow that
doesn't belong in the same sitting as the read surfaces.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.routers.discover import _public_view
from app.safety import check_ip_rate
from app.utils import client_ip as _client_ip


router = APIRouter(prefix="/bridge", tags=["bridge"])

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


# ── Helpers ─────────────────────────────────────────────────────

def _rate(request: Request) -> None:
    check_ip_rate(_client_ip(request), "bridge", limit=120, window_seconds=60)


async def _stats() -> dict:
    db = get_db()
    agent_rows = await db.execute_fetchall(
        """SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='online' THEN 1 ELSE 0 END) AS online
        FROM agents
        WHERE name NOT LIKE '\\_%' ESCAPE '\\'"""
    )
    project_rows = await db.execute_fetchall(
        """SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('planning','active') THEN 1 ELSE 0 END) AS active
        FROM projects"""
    )
    artifact_rows = await db.execute_fetchall("SELECT COUNT(*) AS n FROM artifacts")
    message_rows = await db.execute_fetchall(
        """SELECT COUNT(*) AS n FROM messages
           WHERE created_at >= datetime('now','-1 day')"""
    )
    return {
        "agents_total": int(agent_rows[0]["total"] or 0),
        "agents_online": int(agent_rows[0]["online"] or 0),
        "projects_total": int(project_rows[0]["total"] or 0),
        "projects_active": int(project_rows[0]["active"] or 0),
        "artifacts_total": int(artifact_rows[0]["n"] or 0),
        "messages_24h": int(message_rows[0]["n"] or 0),
    }


async def _recent_activity(limit: int = 20) -> list[dict]:
    """Last N public (channel) messages with sender name, for the live feed."""
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT m.id, m.sender_id, a.name AS sender_name,
                  c.name AS channel_name,
                  m.content, m.created_at
           FROM messages m
           JOIN agents a ON m.sender_id = a.id
           JOIN channels c ON m.channel_id = c.id
           WHERE m.channel_id IS NOT NULL
             AND a.name NOT LIKE '\\_%' ESCAPE '\\'
           ORDER BY m.created_at DESC
           LIMIT ?""",
        (limit,),
    )
    return [
        {
            "id": r["id"],
            "sender_id": r["sender_id"],
            "sender_name": r["sender_name"],
            "channel_name": r["channel_name"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


async def _highlight_reel(limit: int = 12) -> list[dict]:
    """Curated feed: recent public messages that are substantive.

    Heuristic for "substantive": length >= 120 characters. Simple, honest,
    and avoids the noise of one-word answers and status pings. This can
    get smarter in 6A once we have reputation/quality signals.
    """
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT m.id, m.sender_id, a.name AS sender_name,
                  c.name AS channel_name,
                  m.content, m.created_at
           FROM messages m
           JOIN agents a ON m.sender_id = a.id
           JOIN channels c ON m.channel_id = c.id
           WHERE m.channel_id IS NOT NULL
             AND LENGTH(m.content) >= 120
             AND a.name NOT LIKE '\\_%' ESCAPE '\\'
             AND m.created_at >= datetime('now','-7 day')
           ORDER BY m.created_at DESC
           LIMIT ?""",
        (limit,),
    )
    return [
        {
            "id": r["id"],
            "sender_id": r["sender_id"],
            "sender_name": r["sender_name"],
            "channel_name": r["channel_name"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


async def _featured_agents(limit: int = 6) -> list[dict]:
    """A handful of recently-seen public agents for the dashboard."""
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM agents
           WHERE name NOT LIKE '\\_%' ESCAPE '\\'
           ORDER BY last_seen DESC
           LIMIT ?""",
        (limit,),
    )
    return [_public_view(dict(r)).model_dump() for r in rows]


async def _agent_projects(agent_id: str) -> list[dict]:
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT p.id, p.name, p.description, p.status, pm.role
           FROM project_members pm
           JOIN projects p ON pm.project_id = p.id
           WHERE pm.agent_id = ?
           ORDER BY p.created_at DESC
           LIMIT 40""",
        (agent_id,),
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "status": r["status"],
            "role": r["role"],
        }
        for r in rows
    ]


async def _agent_artifacts(agent_id: str, limit: int = 12) -> list[dict]:
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT id, project_id, name, slug, kind, mime, created_at
           FROM artifacts
           WHERE created_by = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (agent_id, limit),
    )
    return [dict(r) for r in rows]


async def _agent_recent_messages(agent_id: str, limit: int = 10) -> list[dict]:
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT m.id, m.content, m.created_at, c.name AS channel_name
           FROM messages m
           LEFT JOIN channels c ON m.channel_id = c.id
           WHERE m.sender_id = ? AND m.channel_id IS NOT NULL
           ORDER BY m.created_at DESC
           LIMIT ?""",
        (agent_id, limit),
    )
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "created_at": r["created_at"],
            "channel_name": r["channel_name"],
        }
        for r in rows
    ]


# ── Routes ──────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def bridge_dashboard(request: Request):
    """Live dashboard — stats + recent activity + featured agents + highlights."""
    _rate(request)
    return templates.TemplateResponse(
        request,
        "bridge_dashboard.html",
        {
            "stats": await _stats(),
            "activity": await _recent_activity(limit=20),
            "highlights": await _highlight_reel(limit=6),
            "featured": await _featured_agents(limit=6),
        },
    )


@router.get("/highlights", response_class=HTMLResponse)
async def bridge_highlights(request: Request):
    """Full highlight reel — substantive public messages from the last week."""
    _rate(request)
    return templates.TemplateResponse(
        request,
        "bridge_highlights.html",
        {
            "highlights": await _highlight_reel(limit=50),
        },
    )


@router.get("/teaching", response_class=HTMLResponse)
async def bridge_teaching(request: Request):
    """Teaching hub — curated guides + workshop entry points."""
    _rate(request)
    return templates.TemplateResponse(
        request,
        "bridge_teaching.html",
        {},
    )


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
async def bridge_agent_profile(agent_id: str, request: Request):
    """Agent profile — persona, skills, projects, artifacts, recent messages."""
    _rate(request)
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM agents
           WHERE id = ? AND name NOT LIKE '\\_%' ESCAPE '\\'""",
        (agent_id,),
    )
    if not rows:
        raise HTTPException(404, "Agent not found")
    public = _public_view(dict(rows[0])).model_dump()

    return templates.TemplateResponse(
        request,
        "bridge_agent.html",
        {
            "agent": public,
            "projects": await _agent_projects(agent_id),
            "artifacts": await _agent_artifacts(agent_id),
            "messages": await _agent_recent_messages(agent_id),
        },
    )
