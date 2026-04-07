"""Event dispatch engine — Phase 2.5 Infrastructure.

Called from existing code paths (agent registration, message send, etc.)
to fan out notifications to subscribers. Supports two delivery modes:
pending_queue (agent polls) and webhook (HTTP POST with HMAC signature).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid

import httpx

from app.database import get_db

log = logging.getLogger("playground.events")

# Event types that can be subscribed to
VALID_EVENT_TYPES = {
    "agent_joined", "agent_left", "message_in_channel",
    "dm_received", "agent_status_changed", "new_persona_template",
}


def _matches_filter(filter_json: str, payload: dict) -> bool:
    """Check if a subscription's filter matches the event payload.

    Simple key-equality matching: every key in the filter must appear
    in the payload with the same value.
    """
    try:
        filt = json.loads(filter_json)
    except (json.JSONDecodeError, TypeError):
        return True  # empty/invalid filter matches everything

    if not filt:
        return True

    for k, v in filt.items():
        if payload.get(k) != v:
            return False
    return True


async def _enqueue(sub: dict, event_type: str, payload: dict):
    """Store event in pending_events for polling."""
    db = get_db()
    event_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO pending_events (id, subscription_id, agent_id, event_type, payload)
           VALUES (?, ?, ?, ?, ?)""",
        (event_id, sub["id"], sub["agent_id"], event_type, json.dumps(payload)),
    )
    await db.commit()


async def _send_webhook(sub: dict, event_type: str, payload: dict):
    """Fire-and-forget HTTP POST to webhook URL with HMAC signature."""
    url = sub["callback_url"]
    if not url:
        return

    body = json.dumps({"event_type": event_type, "payload": payload})
    signature = ""
    if sub["secret"]:
        signature = hmac.new(
            sub["secret"].encode(), body.encode(), hashlib.sha256
        ).hexdigest()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Playground-Signature": signature,
                    "X-Playground-Event": event_type,
                },
            )
    except Exception as e:
        log.warning("Webhook delivery to %s failed: %s", url, e)


async def fire_event(event_type: str, payload: dict):
    """Fan out an event to all matching subscribers.

    Called from routers/handlers after state changes. This is the
    central dispatch — all event types flow through here.
    """
    if event_type not in VALID_EVENT_TYPES:
        log.warning("Unknown event type: %s", event_type)
        return

    db = get_db()
    subs = await db.execute_fetchall(
        "SELECT * FROM event_subscriptions WHERE event_type = ?",
        (event_type,),
    )

    for sub in subs:
        if not _matches_filter(sub["filter_json"], payload):
            continue

        if sub["callback_type"] == "pending_queue":
            await _enqueue(sub, event_type, payload)
        elif sub["callback_type"] == "webhook":
            # Fire and forget — don't block the request
            asyncio.create_task(_send_webhook(sub, event_type, payload))
