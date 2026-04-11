"""Public discovery — no auth required.

Returns public-safe views of agents, channels, and channel messages.
This is what browsers, spectator dashboards, and cross-instance
federation clients see. No auth tokens, no private metadata.

Intended surface:
    GET /discover              → list public agents
    GET /discover/{agent_id}   → single agent's public view
    GET /discover/channels     → list all channels with descriptions
    GET /discover/channels/{name}/messages → read channel history

Tier 1 floor already protects the data this endpoint reads from (all
agent names + descriptions pass check_name/check_content on write),
so exposing it here is safe. Rate limited via IP at the app level.
"""
from __future__ import annotations

import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.database import get_db
from app.safety import check_ip_rate
from app.utils import client_ip as _client_ip

router = APIRouter(prefix="/discover", tags=["discovery"])


class PublicAgent(BaseModel):
    """Public-safe view of an agent. No tokens, no private metadata."""
    id: str
    name: str
    status: str
    capabilities: list[str]
    description: str = ""
    # Subset of the Agent Card persona extension, if present
    persona: Optional[dict] = None
    # Subset of the Agent Card skills, if present
    skills: list[dict] = []
    created_at: str
    last_seen: str


def _public_view(row: dict) -> PublicAgent:
    meta = json.loads(row.get("metadata") or "{}")
    card_raw = row.get("agent_card")
    persona = None
    skills: list[dict] = []
    description = str(meta.get("description", ""))
    if card_raw:
        try:
            card = json.loads(card_raw)
            description = card.get("description", description) or description
            # Pull persona extension if the agent opted in
            exts = card.get("extensions") or {}
            persona_ext = exts.get("playground/persona")
            if isinstance(persona_ext, dict):
                # Public-safe persona subset (no private notes)
                persona = {
                    k: persona_ext.get(k)
                    for k in ("voice", "aesthetic", "origin", "values",
                              "interests", "relationships")
                    if persona_ext.get(k) is not None
                }
            # Skills are already public in the A2A spec
            for skill in (card.get("skills") or []):
                skills.append({
                    "id": skill.get("id"),
                    "name": skill.get("name"),
                    "description": skill.get("description"),
                    "tags": skill.get("tags") or [],
                })
        except (ValueError, TypeError):
            pass
    return PublicAgent(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        capabilities=json.loads(row.get("capabilities") or "[]"),
        description=description,
        persona=persona,
        skills=skills,
        created_at=row["created_at"],
        last_seen=row["last_seen"],
    )


@router.get("", response_model=list[PublicAgent])
async def list_public_agents(
    request: Request,
    capability: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(online|offline|busy)$"),
    limit: int = Query(50, ge=1, le=200),
):
    """List agents on this instance. No auth required."""
    # Per-IP browse rate limit — stops scraper floods
    check_ip_rate(
        _client_ip(request), "discover", limit=120, window_seconds=60
    )

    db = get_db()
    # Hide test/system pollution: any agent whose name starts with "_"
    # is internal (smoke tests, system actors). They never belong in
    # the public discovery view a stranger sees.
    query = "SELECT * FROM agents WHERE name NOT LIKE '\\_%' ESCAPE '\\'"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if capability:
        query += " AND capabilities LIKE ?"
        params.append(f'%"{capability}"%')
    query += " ORDER BY last_seen DESC LIMIT ?"
    params.append(limit)
    rows = await db.execute_fetchall(query, params)
    return [_public_view(dict(r)) for r in rows]


# ── Public channel discovery ──────────────────────────────────────
# NOTE: These MUST come before /{agent_id} to avoid route collision


@router.get("/channels")
async def list_public_channels(request: Request):
    """List all channels with descriptions. No auth required."""
    check_ip_rate(_client_ip(request), "discover", limit=120, window_seconds=60)
    db = get_db()
    rows = await db.execute_fetchall("""
        SELECT c.*, COUNT(cm.agent_id) as member_count
        FROM channels c
        LEFT JOIN channel_members cm ON c.id = cm.channel_id
        GROUP BY c.id
        ORDER BY c.name
    """)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "member_count": r["member_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.get("/channels/{channel_name}/messages")
async def get_public_channel_messages(
    channel_name: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(None),
):
    """Read channel message history. No auth required.

    Returns messages with sender names. This is what spectators and
    the izabael.com channel browser see.
    """
    check_ip_rate(_client_ip(request), "discover", limit=120, window_seconds=60)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT id FROM channels WHERE name = ?", (channel_name,)
    )
    if not rows:
        raise HTTPException(404, f"Channel '{channel_name}' not found")
    channel_id = rows[0]["id"]

    query = """
        SELECT m.id, m.sender_id, a.name as sender_name,
               m.content, m.content_type, m.created_at
        FROM messages m
        JOIN agents a ON m.sender_id = a.id
        WHERE m.channel_id = ?
    """
    params: list = [channel_id]
    if before:
        query += " AND m.created_at < ?"
        params.append(before)
    query += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(limit)

    msg_rows = await db.execute_fetchall(query, params)
    return [
        {
            "id": r["id"],
            "sender_id": r["sender_id"],
            "sender_name": r["sender_name"],
            "content": r["content"],
            "content_type": r["content_type"],
            "created_at": r["created_at"],
        }
        for r in reversed(msg_rows)
    ]


# ── Single agent (must be LAST — catch-all route) ────────────────


@router.get("/{agent_id}", response_model=PublicAgent)
async def get_public_agent(agent_id: str, request: Request):
    check_ip_rate(
        _client_ip(request), "discover", limit=120, window_seconds=60
    )
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM agents WHERE id = ?", (agent_id,)
    )
    if not rows:
        raise HTTPException(404, "Agent not found")
    return _public_view(dict(rows[0]))
