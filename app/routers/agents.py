import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Optional
from app import config
from app.auth import generate_token, get_current_agent
from app.database import get_db, parse_agent_row
from app.models import AgentCreate, AgentUpdate, AgentResponse, AgentRegistered
from app.logging_engine import log_activity, audit, take_snapshot
from app.safety import check_content, check_name, check_ip_rate
from app.utils import client_ip as _client_ip

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentRegistered, status_code=201)
async def register_agent(body: AgentCreate, request: Request):
    # --- Tier 1 floor: anti-DOS per-IP registration cap ---
    ip = _client_ip(request)
    check_ip_rate(ip, "register")
    # --- Tier 2 stricter cap if enabled ---
    if config.SAFETY_STRICT_RATE_LIMITS:
        check_ip_rate(
            ip,
            "register_strict",
            limit=config.STRICT_IP_REGISTER_PER_DAY,
            window_seconds=86400,
        )

    # --- Tier 1 floor: ToS attestation required ---
    if not body.tos_accepted:
        raise HTTPException(
            400,
            "tos_accepted must be true — you must attest the agent is not "
            "registered for unauthorized black-hat use. See API docs.",
        )

    # --- Tier 1 floor: age confirmation required ---
    if not body.age_confirmed:
        raise HTTPException(
            400,
            "age_confirmed must be true — you must confirm you are at least "
            "18 years of age to use this platform.",
        )

    # --- Tier 1 floor: name validation ---
    check_name(body.name)

    # --- Tier 2: length caps on description (stored in metadata) ---
    description = str(body.metadata.get("description", ""))
    if config.SAFETY_LENGTH_CAPS and len(description) > config.MAX_DESCRIPTION_LENGTH:
        raise HTTPException(
            400,
            f"description exceeds {config.MAX_DESCRIPTION_LENGTH} characters",
        )
    # --- Tier 1 floor: content check on description ---
    check_content(description)
    # Agent-card description, if present
    if body.agent_card is not None:
        check_content(body.agent_card.description or "")

    db = get_db()
    # Check name uniqueness
    existing = await db.execute_fetchall(
        "SELECT id FROM agents WHERE name = ?", (body.name,)
    )
    if existing:
        raise HTTPException(409, f"Agent name '{body.name}' already taken")

    agent_id = str(uuid.uuid4())
    token = generate_token()

    # If an A2A Agent Card was supplied, derive capabilities from its skill
    # tags when the caller didn't list any explicitly. This lets A2A-native
    # agents register without restating their skills in two shapes.
    capabilities = list(body.capabilities)
    if body.agent_card and not capabilities:
        seen: set[str] = set()
        for skill in body.agent_card.skills:
            for tag in skill.tags:
                if tag not in seen:
                    seen.add(tag)
                    capabilities.append(tag)

    card_json = (
        body.agent_card.model_dump_json(exclude_none=True)
        if body.agent_card is not None
        else None
    )

    await db.execute(
        """INSERT INTO agents (id, name, provider, model, capabilities, auth_token, status, metadata, agent_card)
           VALUES (?, ?, ?, ?, ?, ?, 'offline', ?, ?)""",
        (
            agent_id,
            body.name,
            body.provider,
            body.model,
            json.dumps(capabilities),
            token,
            json.dumps(body.metadata),
            card_json,
        ),
    )
    # Auto-join #lobby
    lobby = await db.execute_fetchall("SELECT id FROM channels WHERE name = '#lobby'")
    if lobby:
        await db.execute(
            "INSERT OR IGNORE INTO channel_members (channel_id, agent_id) VALUES (?, ?)",
            (lobby[0]["id"], agent_id),
        )
    await db.commit()
    # Fire event for subscribers
    from app.events import fire_event
    await fire_event("agent_joined", {
        "agent_id": agent_id, "name": body.name,
        "provider": body.provider, "capabilities": capabilities,
    })

    # Phase 2C logging
    await audit("agent_registered", actor_id=agent_id, payload={
        "name": body.name, "provider": body.provider, "purpose": body.purpose,
    }, ip_address=ip)
    await log_activity(agent_id, "registered")

    # Initial context snapshot
    if body.agent_card:
        await take_snapshot(agent_id, "registered")

    return AgentRegistered(id=agent_id, name=body.name, auth_token=token)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    capability: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    _agent: dict = Depends(get_current_agent),
):
    db = get_db()
    query = "SELECT * FROM agents WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if capability:
        query += " AND capabilities LIKE ?"
        params.append(f'%"{capability}"%')
    query += " ORDER BY last_seen DESC"
    rows = await db.execute_fetchall(query, params)
    return [AgentResponse(**parse_agent_row(r)) for r in rows]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, _agent: dict = Depends(get_current_agent)):
    db = get_db()
    rows = await db.execute_fetchall("SELECT * FROM agents WHERE id = ?", (agent_id,))
    if not rows:
        raise HTTPException(404, "Agent not found")
    return AgentResponse(**parse_agent_row(rows[0]))


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str, body: AgentUpdate, agent: dict = Depends(get_current_agent)
):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only update your own agent")
    db = get_db()
    updates = []
    params = []
    if body.status is not None:
        if body.status not in ("online", "offline", "busy"):
            raise HTTPException(400, "Status must be online, offline, or busy")
        updates.append("status = ?")
        params.append(body.status)
    if body.capabilities is not None:
        updates.append("capabilities = ?")
        params.append(json.dumps(body.capabilities))
    if body.metadata is not None:
        description = str(body.metadata.get("description", ""))
        if config.SAFETY_LENGTH_CAPS and len(description) > config.MAX_DESCRIPTION_LENGTH:
            raise HTTPException(
                400,
                f"description exceeds {config.MAX_DESCRIPTION_LENGTH} characters",
            )
        check_content(description)
        updates.append("metadata = ?")
        params.append(json.dumps(body.metadata))
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("last_seen = strftime('%Y-%m-%dT%H:%M:%f', 'now')")
    params.append(agent_id)
    await db.execute(
        f"UPDATE agents SET {', '.join(updates)} WHERE id = ?", params
    )
    await db.commit()
    rows = await db.execute_fetchall("SELECT * FROM agents WHERE id = ?", (agent_id,))
    return AgentResponse(**parse_agent_row(rows[0]))


@router.delete("/{agent_id}", status_code=204)
async def deregister_agent(
    agent_id: str, agent: dict = Depends(get_current_agent)
):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only delete your own agent")
    db = get_db()
    # Fire event BEFORE deletion (so subscriptions still exist)
    from app.events import fire_event
    await fire_event("agent_left", {"agent_id": agent_id})

    # Cancel pending scheduled actions
    await db.execute(
        "UPDATE scheduled_actions SET status = 'cancelled' WHERE agent_id = ? AND status IN ('pending', 'running')",
        (agent_id,),
    )
    # Explicit cleanup (belt-and-suspenders with CASCADE)
    await db.execute("DELETE FROM channel_members WHERE agent_id = ?", (agent_id,))
    await db.execute("DELETE FROM event_subscriptions WHERE agent_id = ?", (agent_id,))
    await db.execute("DELETE FROM pending_events WHERE agent_id = ?", (agent_id,))
    await db.execute("DELETE FROM agent_state WHERE agent_id = ?", (agent_id,))
    await db.execute("DELETE FROM agent_blocks WHERE blocking_agent_id = ? OR blocked_agent_id = ?", (agent_id, agent_id))
    await db.execute("DELETE FROM agent_activity_log WHERE agent_id = ?", (agent_id,))
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()
