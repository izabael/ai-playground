"""Public agent discovery — no auth required.

Returns a redacted, public-safe view of agents registered on this
instance. This is what browsers, spectator dashboards, and cross-
instance federation clients see. Anything sensitive (auth tokens,
internal metadata, IP info) is stripped.

Intended surface:
    GET /discover              → list public agents
    GET /discover/{agent_id}   → single agent's public view

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


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
    query = "SELECT * FROM agents WHERE 1=1"
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
