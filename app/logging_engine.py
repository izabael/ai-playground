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

# ── Context Snapshots ─────────────────────────────────────────────

async def take_snapshot(
    agent_id: str,
    trigger: str,
    message_id: str = None,
):
    """Capture the agent's identity state at a point in time.

    Called every Nth message, on persona update, on status change.
    Captures persona, skills, state namespace summary, and current status.
    """
    try:
        db = get_db()

        # Get agent card (persona + skills)
        agent_row = await db.execute_fetchall(
            "SELECT agent_card, status FROM agents WHERE id = ?", (agent_id,)
        )
        if not agent_row:
            return

        persona_json = "{}"
        skills_json = "[]"
        status = agent_row[0]["status"]

        card_raw = agent_row[0]["agent_card"]
        if card_raw:
            try:
                card = json.loads(card_raw)
                exts = card.get("extensions", {})
                persona = exts.get("playground/persona", {})
                persona_json = json.dumps(persona)
                skills_json = json.dumps(card.get("skills", []))
            except (json.JSONDecodeError, TypeError):
                pass

        # State summary: just namespace + key counts (not values — privacy)
        state_rows = await db.execute_fetchall(
            """SELECT namespace, COUNT(*) as cnt FROM agent_state
               WHERE agent_id = ? GROUP BY namespace""",
            (agent_id,),
        )
        state_summary = {r["namespace"]: r["cnt"] for r in state_rows}

        await db.execute(
            """INSERT INTO context_snapshots
               (id, agent_id, message_id, trigger, persona_json, skills_json, state_summary_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), agent_id, message_id, trigger,
             persona_json, skills_json, json.dumps(state_summary), status),
        )
        await db.commit()
    except Exception as e:
        log.warning("Context snapshot failed: %s", e)


# Message counter for snapshot frequency (per agent)
_msg_counters: dict[str, int] = {}
SNAPSHOT_EVERY_N = 10  # snapshot every 10th message per agent


async def maybe_snapshot_on_message(agent_id: str, message_id: str):
    """Conditionally take a snapshot based on message frequency."""
    count = _msg_counters.get(agent_id, 0) + 1
    _msg_counters[agent_id] = count
    if count % SNAPSHOT_EVERY_N == 0:
        await take_snapshot(agent_id, "message_sent", message_id)


# ── Persona Evolution Tracking ────────────────────────────────────

async def track_persona_change(agent_id: str, old_card_json: str, new_card_json: str):
    """Diff persona fields and log changes."""
    try:
        old_persona = {}
        new_persona = {}

        if old_card_json:
            try:
                old_card = json.loads(old_card_json)
                old_persona = old_card.get("extensions", {}).get("playground/persona", {})
            except (json.JSONDecodeError, TypeError):
                pass

        if new_card_json:
            try:
                new_card = json.loads(new_card_json)
                new_persona = new_card.get("extensions", {}).get("playground/persona", {})
            except (json.JSONDecodeError, TypeError):
                pass

        if not old_persona and not new_persona:
            return

        # Check each field for changes
        all_keys = set(list(old_persona.keys()) + list(new_persona.keys()))
        db = get_db()

        for key in all_keys:
            old_val = old_persona.get(key)
            new_val = new_persona.get(key)
            if old_val != new_val:
                await db.execute(
                    """INSERT INTO persona_changelog
                       (id, agent_id, field_changed, old_value, new_value)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), agent_id, key,
                     json.dumps(old_val), json.dumps(new_val)),
                )

        await db.commit()

        # Take a snapshot on persona change
        await take_snapshot(agent_id, "persona_update")

    except Exception as e:
        log.warning("Persona changelog failed: %s", e)


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
