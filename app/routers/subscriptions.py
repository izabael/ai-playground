"""Event subscriptions — Phase 2.5 Infrastructure.

Agents subscribe to platform events (agent_joined, dm_received, etc.)
and receive notifications either via polling or webhook delivery.
"""

import json
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config
from app.auth import get_current_agent
from app.database import get_db, parse_subscription_row, parse_pending_event_row
from app.models import (
    SubscriptionCreate, SubscriptionResponse,
    PendingEventResponse,
)
from app.safety import check_agent_rate

router = APIRouter(prefix="/agents/{agent_id}", tags=["event-subscriptions"])


def _check_self(agent: dict, agent_id: str):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only manage your own subscriptions")


@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    agent_id: str, body: SubscriptionCreate,
    agent: dict = Depends(get_current_agent),
):
    """Subscribe to a platform event type."""
    _check_self(agent, agent_id)
    check_agent_rate(agent["id"], "subscription_create", limit=20, window_seconds=60)

    if body.callback_type == "webhook" and not body.callback_url:
        raise HTTPException(400, "callback_url required for webhook subscriptions")

    db = get_db()

    # Check subscription limit
    count = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM event_subscriptions WHERE agent_id = ?",
        (agent_id,),
    )
    if count[0]["cnt"] >= config.MAX_SUBSCRIPTIONS_PER_AGENT:
        raise HTTPException(400, f"Subscription limit ({config.MAX_SUBSCRIPTIONS_PER_AGENT}) reached")

    sub_id = str(uuid.uuid4())
    secret = secrets.token_urlsafe(32) if body.callback_type == "webhook" else None

    await db.execute(
        """INSERT INTO event_subscriptions (id, agent_id, event_type, filter_json, callback_type, callback_url, secret)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sub_id, agent_id, body.event_type, json.dumps(body.filter),
         body.callback_type, body.callback_url, secret),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM event_subscriptions WHERE id = ?", (sub_id,)
    )
    result = parse_subscription_row(dict(rows[0]))
    # Include secret only on creation (webhook subs)
    if secret:
        result["secret"] = secret
    return SubscriptionResponse(**result)


@router.get("/subscriptions", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    agent_id: str,
    agent: dict = Depends(get_current_agent),
):
    """List your event subscriptions."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM event_subscriptions WHERE agent_id = ? ORDER BY created_at DESC",
        (agent_id,),
    )
    return [SubscriptionResponse(**parse_subscription_row(dict(r))) for r in rows]


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(
    agent_id: str, sub_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Remove a subscription. Cascades to pending events."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM event_subscriptions WHERE id = ? AND agent_id = ?",
        (sub_id, agent_id),
    )
    if not rows:
        raise HTTPException(404, "Subscription not found")
    await db.execute("DELETE FROM pending_events WHERE subscription_id = ?", (sub_id,))
    await db.execute("DELETE FROM event_subscriptions WHERE id = ?", (sub_id,))
    await db.commit()


@router.get("/events", response_model=list[PendingEventResponse])
async def poll_events(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    agent: dict = Depends(get_current_agent),
):
    """Poll pending events. Events are deleted after being read (acknowledge-on-read)."""
    _check_self(agent, agent_id)
    db = get_db()

    rows = await db.execute_fetchall(
        "SELECT * FROM pending_events WHERE agent_id = ? ORDER BY created_at LIMIT ?",
        (agent_id, limit),
    )
    events = [PendingEventResponse(**parse_pending_event_row(dict(r))) for r in rows]

    # Acknowledge — delete the returned events
    if rows:
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        await db.execute(
            f"DELETE FROM pending_events WHERE id IN ({placeholders})", ids
        )
        await db.commit()

    return events
