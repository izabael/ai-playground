"""Structured logging engine — Phase 2C.

Three logging systems that run automatically on every interaction:

1. **Activity log** — append-only record of every agent action
2. **Relationship tracking** — auto-updated counters on every interaction
3. **Audit trail** — permanent record of every platform event

All functions are fire-and-forget: they never block the request,
they never raise exceptions to the caller, they just log.
"""

import json
import logging
import uuid

from app.database import get_db

log = logging.getLogger("playground.logging")


# ── Activity Log ──────────────────────────────────────────────────

async def log_activity(
    agent_id: str,
    action_type: str,
    target_type: str = None,
    target_id: str = None,
    metadata: dict = None,
):
    """Append to the activity log. Fire-and-forget."""
    try:
        db = get_db()
        await db.execute(
            """INSERT INTO agent_activity_log (id, agent_id, action_type, target_type, target_id, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), agent_id, action_type, target_type, target_id,
             json.dumps(metadata or {})),
        )
        await db.commit()
    except Exception as e:
        log.warning("Activity log failed: %s", e)


# ── Relationship Tracking ─────────────────────────────────────────

def _ordered_pair(a: str, b: str) -> tuple[str, str]:
    """Alphabetically order two agent IDs for dedup."""
    return (a, b) if a < b else (b, a)


async def track_dm(sender_id: str, recipient_id: str):
    """Update relationship counters for a DM interaction."""
    try:
        db = get_db()
        a, b = _ordered_pair(sender_id, recipient_id)
        await db.execute(
            """INSERT INTO agent_relationships (agent_a_id, agent_b_id, dm_count)
               VALUES (?, ?, 1)
               ON CONFLICT(agent_a_id, agent_b_id) DO UPDATE SET
                 dm_count = dm_count + 1,
                 last_interaction = strftime('%Y-%m-%dT%H:%M:%f', 'now')""",
            (a, b),
        )
        await db.commit()
    except Exception as e:
        log.warning("Relationship tracking (DM) failed: %s", e)


async def track_channel_interaction(sender_id: str, channel_id: str, member_ids: list[str]):
    """Update relationship counters for all channel members who see this message."""
    try:
        db = get_db()
        for member_id in member_ids:
            if member_id == sender_id:
                continue
            a, b = _ordered_pair(sender_id, member_id)
            await db.execute(
                """INSERT INTO agent_relationships (agent_a_id, agent_b_id, channel_overlap_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(agent_a_id, agent_b_id) DO UPDATE SET
                     channel_overlap_count = channel_overlap_count + 1,
                     last_interaction = strftime('%Y-%m-%dT%H:%M:%f', 'now')""",
                (a, b),
            )
        await db.commit()
    except Exception as e:
        log.warning("Relationship tracking (channel) failed: %s", e)


# ── Audit Trail ───────────────────────────────────────────────────

async def audit(
    event_type: str,
    actor_id: str = None,
    target_id: str = None,
    payload: dict = None,
    ip_address: str = None,
):
    """Write to the permanent audit trail. Fire-and-forget."""
    try:
        db = get_db()
        await db.execute(
            """INSERT INTO audit_log (id, event_type, actor_id, target_id, payload_json, ip_address)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), event_type, actor_id, target_id,
             json.dumps(payload or {}), ip_address),
        )
        await db.commit()
    except Exception as e:
        log.warning("Audit log failed: %s", e)
