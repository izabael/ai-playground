import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.auth import generate_token, get_current_agent
from app.database import get_db, parse_agent_row
from app.models import AgentCreate, AgentUpdate, AgentResponse, AgentRegistered

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentRegistered, status_code=201)
async def register_agent(body: AgentCreate):
    db = get_db()
    # Check name uniqueness
    existing = await db.execute_fetchall(
        "SELECT id FROM agents WHERE name = ?", (body.name,)
    )
    if existing:
        raise HTTPException(409, f"Agent name '{body.name}' already taken")

    agent_id = str(uuid.uuid4())
    token = generate_token()
    await db.execute(
        """INSERT INTO agents (id, name, provider, model, capabilities, auth_token, status, metadata)
           VALUES (?, ?, ?, ?, ?, ?, 'offline', ?)""",
        (
            agent_id,
            body.name,
            body.provider,
            body.model,
            json.dumps(body.capabilities),
            token,
            json.dumps(body.metadata),
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
    await db.execute("DELETE FROM channel_members WHERE agent_id = ?", (agent_id,))
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()
