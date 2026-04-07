"""Background action scheduler — Phase 2.5 Infrastructure.

Polls scheduled_actions every 30s for due actions and executes them.
Runs as an asyncio background task started in the app lifespan.
"""

import asyncio
import json
import logging

import httpx

from app import config
from app.database import get_db, is_blocked
from app.safety import check_content
from app.ws.manager import manager

log = logging.getLogger("playground.scheduler")


async def run_scheduler():
    """Background loop: execute due scheduled actions."""
    log.info("Scheduler started (poll interval: 30s)")
    while True:
        await asyncio.sleep(30)
        try:
            await _process_due_actions()
        except Exception:
            log.exception("Scheduler error")


async def _process_due_actions():
    db = get_db()
    due = await db.execute_fetchall(
        """SELECT * FROM scheduled_actions
           WHERE status = 'pending'
           AND run_at <= strftime('%Y-%m-%dT%H:%M:%f', 'now')
           LIMIT 50""",
    )

    for action in due:
        action_id = action["id"]
        await db.execute(
            "UPDATE scheduled_actions SET status = 'running' WHERE id = ?",
            (action_id,),
        )
        await db.commit()

        try:
            await _execute_action(dict(action))

            if action["repeat_interval"]:
                await db.execute(
                    """UPDATE scheduled_actions SET
                         status = 'pending',
                         run_at = strftime('%Y-%m-%dT%H:%M:%f', run_at, '+' || ? || ' seconds'),
                         last_run = strftime('%Y-%m-%dT%H:%M:%f', 'now')
                       WHERE id = ?""",
                    (action["repeat_interval"], action_id),
                )
            else:
                await db.execute(
                    """UPDATE scheduled_actions SET
                         status = 'completed',
                         last_run = strftime('%Y-%m-%dT%H:%M:%f', 'now')
                       WHERE id = ?""",
                    (action_id,),
                )
        except Exception as e:
            log.warning("Action %s failed: %s", action_id, e)
            await db.execute(
                """UPDATE scheduled_actions SET
                     status = 'failed',
                     last_run = strftime('%Y-%m-%dT%H:%M:%f', 'now')
                   WHERE id = ?""",
                (action_id,),
            )
        await db.commit()


async def _execute_action(action: dict):
    action_type = action["action_type"]
    payload = json.loads(action["payload_json"])
    agent_id = action["agent_id"]

    if action_type == "send_message":
        await _exec_send_message(agent_id, payload)
    elif action_type == "update_status":
        await _exec_update_status(agent_id, payload)
    elif action_type == "custom_webhook":
        await _exec_webhook(payload)
    else:
        raise ValueError(f"Unknown action type: {action_type}")


async def _exec_send_message(agent_id: str, payload: dict):
    import uuid
    to = payload.get("to", "")
    content = payload.get("content", "")
    content_type = payload.get("content_type", "text")

    check_content(content)

    db = get_db()
    msg_id = str(uuid.uuid4())

    if to.startswith("#"):
        # Channel message
        rows = await db.execute_fetchall(
            "SELECT id FROM channels WHERE name = ?", (to,)
        )
        if not rows:
            raise ValueError(f"Channel '{to}' not found")
        channel_id = rows[0]["id"]
        member = await db.execute_fetchall(
            "SELECT 1 FROM channel_members WHERE channel_id = ? AND agent_id = ?",
            (channel_id, agent_id),
        )
        if not member:
            raise ValueError(f"Not a member of '{to}'")
        await db.execute(
            """INSERT INTO messages (id, sender_id, channel_id, content, content_type, metadata)
               VALUES (?, ?, ?, ?, ?, '{}')""",
            (msg_id, agent_id, channel_id, content, content_type),
        )
    else:
        # DM
        if await is_blocked(agent_id, to):
            raise ValueError("Recipient has blocked this agent")
        rows = await db.execute_fetchall("SELECT id FROM agents WHERE id = ?", (to,))
        if not rows:
            raise ValueError("Recipient not found")
        await db.execute(
            """INSERT INTO messages (id, sender_id, recipient_id, content, content_type, metadata)
               VALUES (?, ?, ?, ?, ?, '{}')""",
            (msg_id, agent_id, to, content, content_type),
        )
    await db.commit()

    # Try to deliver via WebSocket if recipient is online
    if not to.startswith("#") and manager.is_online(to):
        agent_row = await db.execute_fetchall("SELECT name FROM agents WHERE id = ?", (agent_id,))
        sender_name = agent_row[0]["name"] if agent_row else "unknown"
        await manager.send_to_agent(to, json.dumps({
            "type": "message",
            "id": msg_id,
            "from": {"id": agent_id, "name": sender_name},
            "content": content,
            "content_type": content_type,
        }))

    log.info("Scheduled message sent: %s -> %s", agent_id, to)


async def _exec_update_status(agent_id: str, payload: dict):
    status = payload.get("status", "online")
    if status not in ("online", "offline", "busy"):
        raise ValueError(f"Invalid status: {status}")
    db = get_db()
    await db.execute(
        "UPDATE agents SET status = ?, last_seen = strftime('%Y-%m-%dT%H:%M:%f', 'now') WHERE id = ?",
        (status, agent_id),
    )
    await db.commit()
    log.info("Scheduled status update: %s -> %s", agent_id, status)


async def _exec_webhook(payload: dict):
    url = payload.get("url", "")
    method = payload.get("method", "POST").upper()
    body = payload.get("body", {})

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.request(method, url, json=body)
    log.info("Scheduled webhook: %s %s", method, url)
