"""Per-agent persistent state (memory) — Phase 2.5 Infrastructure.

Agents can store and retrieve key-value data organized by namespace.
This is how agents remember things between sessions: relationships,
preferences, notes, context from past conversations.

All state is private — agents can only access their own.
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import config
from app.auth import get_current_agent
from app.database import get_db, parse_state_row
from app.models import StateEntry, StateWrite
from app.safety import check_content, check_agent_rate

router = APIRouter(prefix="/agents/{agent_id}/state", tags=["agent-state"])


def _check_self(agent: dict, agent_id: str):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only access your own state")


@router.get("", response_model=list[StateEntry])
async def list_state(
    agent_id: str,
    namespace: Optional[str] = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=1000),
    agent: dict = Depends(get_current_agent),
):
    """List all state entries, optionally filtered by namespace."""
    _check_self(agent, agent_id)
    db = get_db()
    if namespace:
        rows = await db.execute_fetchall(
            "SELECT * FROM agent_state WHERE agent_id = ? AND namespace = ? ORDER BY key LIMIT ?",
            (agent_id, namespace, limit),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM agent_state WHERE agent_id = ? ORDER BY namespace, key LIMIT ?",
            (agent_id, limit),
        )
    return [StateEntry(**parse_state_row(dict(r))) for r in rows]


@router.get("/{namespace}/{key}", response_model=StateEntry)
async def get_state(
    agent_id: str, namespace: str, key: str,
    agent: dict = Depends(get_current_agent),
):
    """Get a single state value."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM agent_state WHERE agent_id = ? AND namespace = ? AND key = ?",
        (agent_id, namespace, key),
    )
    if not rows:
        raise HTTPException(404, f"State key '{namespace}/{key}' not found")
    return StateEntry(**parse_state_row(dict(rows[0])))


@router.put("/{namespace}/{key}", response_model=StateEntry)
async def put_state(
    agent_id: str, namespace: str, key: str, body: StateWrite,
    agent: dict = Depends(get_current_agent),
):
    """Upsert a state value. Value must be JSON-serializable."""
    _check_self(agent, agent_id)
    check_agent_rate(agent["id"], "state_write", limit=60, window_seconds=60)

    value_str = json.dumps(body.value)

    # Size limit
    if len(value_str) > config.MAX_STATE_VALUE_SIZE:
        raise HTTPException(400, f"Value exceeds {config.MAX_STATE_VALUE_SIZE} bytes")

    # Safety floor on stored content
    if isinstance(body.value, str):
        check_content(body.value)
    elif isinstance(body.value, dict):
        for v in body.value.values():
            if isinstance(v, str):
                check_content(v)

    db = get_db()

    # Check key count limit (only for new keys)
    existing = await db.execute_fetchall(
        "SELECT 1 FROM agent_state WHERE agent_id = ? AND namespace = ? AND key = ?",
        (agent_id, namespace, key),
    )
    if not existing:
        count_rows = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM agent_state WHERE agent_id = ?", (agent_id,)
        )
        if count_rows[0]["cnt"] >= config.MAX_STATE_KEYS_PER_AGENT:
            raise HTTPException(400, f"State key limit ({config.MAX_STATE_KEYS_PER_AGENT}) reached")

    await db.execute(
        """INSERT INTO agent_state (agent_id, namespace, key, value, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%f', 'now'))
           ON CONFLICT(agent_id, namespace, key) DO UPDATE SET
             value = excluded.value,
             updated_at = excluded.updated_at""",
        (agent_id, namespace, key, value_str),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM agent_state WHERE agent_id = ? AND namespace = ? AND key = ?",
        (agent_id, namespace, key),
    )
    return StateEntry(**parse_state_row(dict(rows[0])))


@router.delete("/{namespace}/{key}", status_code=204)
async def delete_state_key(
    agent_id: str, namespace: str, key: str,
    agent: dict = Depends(get_current_agent),
):
    """Delete a single state key."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT 1 FROM agent_state WHERE agent_id = ? AND namespace = ? AND key = ?",
        (agent_id, namespace, key),
    )
    if not rows:
        raise HTTPException(404, f"State key '{namespace}/{key}' not found")
    await db.execute(
        "DELETE FROM agent_state WHERE agent_id = ? AND namespace = ? AND key = ?",
        (agent_id, namespace, key),
    )
    await db.commit()


@router.delete("/{namespace}", status_code=204)
async def delete_namespace(
    agent_id: str, namespace: str,
    agent: dict = Depends(get_current_agent),
):
    """Delete all keys in a namespace."""
    _check_self(agent, agent_id)
    db = get_db()
    await db.execute(
        "DELETE FROM agent_state WHERE agent_id = ? AND namespace = ?",
        (agent_id, namespace),
    )
    await db.commit()
