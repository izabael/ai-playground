"""Scheduled actions — Phase 2.5 Infrastructure.

Agents can schedule future actions: send a message at a specific time,
update their status on a schedule, or call an external webhook. The
background scheduler (app/scheduler.py) executes due actions every 30s.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config
from app.auth import get_current_agent
from app.database import get_db, parse_action_row
from app.models import ActionCreate, ActionResponse
from app.safety import check_content, check_agent_rate

router = APIRouter(prefix="/agents/{agent_id}/actions", tags=["scheduled-actions"])


def _check_self(agent: dict, agent_id: str):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only manage your own actions")


@router.post("", response_model=ActionResponse, status_code=201)
async def create_action(
    agent_id: str, body: ActionCreate,
    agent: dict = Depends(get_current_agent),
):
    """Schedule a future action."""
    _check_self(agent, agent_id)
    check_agent_rate(agent["id"], "action_create", limit=10, window_seconds=60)

    # Validate run_at is in the future (with 5s grace)
    try:
        run_at = datetime.fromisoformat(body.run_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "run_at must be ISO 8601 format")

    now = datetime.now(timezone.utc)
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    if (run_at - now).total_seconds() < -5:
        raise HTTPException(400, "run_at must be in the future")

    # Validate repeat interval
    if body.repeat_interval is not None and body.repeat_interval < config.MIN_REPEAT_INTERVAL:
        raise HTTPException(400, f"repeat_interval must be >= {config.MIN_REPEAT_INTERVAL}s")

    # Pre-validate send_message payloads
    if body.action_type == "send_message":
        content = body.payload.get("content", "")
        if not content:
            raise HTTPException(400, "send_message payload requires 'content'")
        if not body.payload.get("to"):
            raise HTTPException(400, "send_message payload requires 'to'")
        check_content(content)

    db = get_db()

    # Check action limit
    count = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM scheduled_actions WHERE agent_id = ? AND status IN ('pending', 'running')",
        (agent_id,),
    )
    if count[0]["cnt"] >= config.MAX_ACTIONS_PER_AGENT:
        raise HTTPException(400, f"Active action limit ({config.MAX_ACTIONS_PER_AGENT}) reached")

    action_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO scheduled_actions (id, agent_id, action_type, payload_json, run_at, repeat_interval)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (action_id, agent_id, body.action_type, json.dumps(body.payload),
         body.run_at, body.repeat_interval),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)
    )
    return ActionResponse(**parse_action_row(dict(rows[0])))


@router.get("", response_model=list[ActionResponse])
async def list_actions(
    agent_id: str,
    status: Optional[str] = Query(None, pattern="^(pending|running|completed|failed|cancelled)$"),
    agent: dict = Depends(get_current_agent),
):
    """List your scheduled actions."""
    _check_self(agent, agent_id)
    db = get_db()
    if status:
        rows = await db.execute_fetchall(
            "SELECT * FROM scheduled_actions WHERE agent_id = ? AND status = ? ORDER BY run_at",
            (agent_id, status),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM scheduled_actions WHERE agent_id = ? ORDER BY run_at",
            (agent_id,),
        )
    return [ActionResponse(**parse_action_row(dict(r))) for r in rows]


@router.get("/{action_id}", response_model=ActionResponse)
async def get_action(
    agent_id: str, action_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Get a single action."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM scheduled_actions WHERE id = ? AND agent_id = ?",
        (action_id, agent_id),
    )
    if not rows:
        raise HTTPException(404, "Action not found")
    return ActionResponse(**parse_action_row(dict(rows[0])))


@router.delete("/{action_id}", status_code=204)
async def cancel_action(
    agent_id: str, action_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Cancel a scheduled action."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM scheduled_actions WHERE id = ? AND agent_id = ?",
        (action_id, agent_id),
    )
    if not rows:
        raise HTTPException(404, "Action not found")
    if rows[0]["status"] not in ("pending", "running"):
        raise HTTPException(400, f"Cannot cancel action in '{rows[0]['status']}' status")
    await db.execute(
        "UPDATE scheduled_actions SET status = 'cancelled' WHERE id = ?",
        (action_id,),
    )
    await db.commit()
