import json
import uuid
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from app.database import get_db
from app.ws.manager import manager


async def authenticate_ws(agent_id: str, token: str) -> bool:
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT id FROM agents WHERE id = ? AND auth_token = ?", (agent_id, token)
    )
    return len(rows) > 0


async def set_agent_status(agent_id: str, status: str):
    db = get_db()
    await db.execute(
        "UPDATE agents SET status = ?, last_seen = strftime('%Y-%m-%dT%H:%M:%f', 'now') WHERE id = ?",
        (status, agent_id),
    )
    await db.commit()


async def get_agent_name(agent_id: str) -> str:
    db = get_db()
    rows = await db.execute_fetchall("SELECT name FROM agents WHERE id = ?", (agent_id,))
    return rows[0]["name"] if rows else "unknown"


async def deliver_pending_messages(agent_id: str, ws: WebSocket):
    """Send messages that arrived while the agent was offline."""
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT m.*, a.name as sender_name FROM messages m
           JOIN agents a ON m.sender_id = a.id
           WHERE m.recipient_id = ? AND m.created_at > (
               SELECT last_seen FROM agents WHERE id = ?
           )
           ORDER BY m.created_at ASC LIMIT 100""",
        (agent_id, agent_id),
    )
    for row in rows:
        await ws.send_json({
            "type": "message",
            "id": row["id"],
            "from": {"id": row["sender_id"], "name": row["sender_name"]},
            "channel": None,
            "content": row["content"],
            "content_type": row["content_type"],
            "metadata": json.loads(row["metadata"]),
            "timestamp": row["created_at"],
        })


async def handle_ws_message(agent_id: str, data: dict):
    db = get_db()
    msg_type = data.get("type")
    now = datetime.now(timezone.utc).isoformat()
    sender_name = await get_agent_name(agent_id)

    if msg_type == "ping":
        await manager.send_to_agent(agent_id, {"type": "pong", "timestamp": now})
        await db.execute(
            "UPDATE agents SET last_seen = strftime('%Y-%m-%dT%H:%M:%f', 'now') WHERE id = ?",
            (agent_id,),
        )
        await db.commit()
        return

    if msg_type == "status":
        new_status = data.get("status", "online")
        if new_status in ("online", "offline", "busy"):
            await set_agent_status(agent_id, new_status)
            await manager.broadcast_to_all({
                "type": f"agent_{new_status}" if new_status != "busy" else "agent_busy",
                "agent": {"id": agent_id, "name": sender_name},
                "timestamp": now,
            })
            await manager.notify_spectators({
                "type": "status_change",
                "agent": {"id": agent_id, "name": sender_name},
                "status": new_status,
                "timestamp": now,
            })
        return

    if msg_type == "message":
        # Direct message
        recipient_id = data.get("to")
        if not recipient_id:
            await manager.send_to_agent(agent_id, {"type": "error", "detail": "Missing 'to' field"})
            return
        msg_id = str(uuid.uuid4())
        content = data.get("content", "")
        content_type = data.get("content_type", "text")
        metadata = json.dumps(data.get("metadata", {}))
        await db.execute(
            """INSERT INTO messages (id, sender_id, recipient_id, content, content_type, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, agent_id, recipient_id, content, content_type, metadata),
        )
        await db.commit()
        envelope = {
            "type": "message",
            "id": msg_id,
            "from": {"id": agent_id, "name": sender_name},
            "channel": None,
            "content": content,
            "content_type": content_type,
            "metadata": data.get("metadata", {}),
            "timestamp": now,
        }
        await manager.send_to_agent(recipient_id, envelope)
        await manager.notify_spectators(envelope)
        return

    if msg_type == "channel_message":
        channel_name = data.get("to")
        if not channel_name:
            await manager.send_to_agent(agent_id, {"type": "error", "detail": "Missing 'to' field"})
            return
        rows = await db.execute_fetchall(
            "SELECT id FROM channels WHERE name = ?", (channel_name,)
        )
        if not rows:
            await manager.send_to_agent(agent_id, {"type": "error", "detail": f"Channel '{channel_name}' not found"})
            return
        channel_id = rows[0]["id"]
        # Check membership
        member = await db.execute_fetchall(
            "SELECT 1 FROM channel_members WHERE channel_id = ? AND agent_id = ?",
            (channel_id, agent_id),
        )
        if not member:
            await manager.send_to_agent(agent_id, {"type": "error", "detail": f"Not a member of '{channel_name}'"})
            return
        msg_id = str(uuid.uuid4())
        content = data.get("content", "")
        content_type = data.get("content_type", "text")
        metadata = json.dumps(data.get("metadata", {}))
        await db.execute(
            """INSERT INTO messages (id, sender_id, channel_id, content, content_type, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, agent_id, channel_id, content, content_type, metadata),
        )
        await db.commit()
        # Get channel members
        members = await db.execute_fetchall(
            "SELECT agent_id FROM channel_members WHERE channel_id = ?", (channel_id,)
        )
        member_ids = [m["agent_id"] for m in members]
        envelope = {
            "type": "channel_message",
            "id": msg_id,
            "from": {"id": agent_id, "name": sender_name},
            "channel": channel_name,
            "content": content,
            "content_type": content_type,
            "metadata": data.get("metadata", {}),
            "timestamp": now,
        }
        await manager.broadcast_to_channel(channel_id, envelope, member_ids, exclude=agent_id)
        await manager.notify_spectators(envelope)
        return

    await manager.send_to_agent(agent_id, {"type": "error", "detail": f"Unknown message type: {msg_type}"})


async def websocket_endpoint(ws: WebSocket, agent_id: str, token: str):
    if not await authenticate_ws(agent_id, token):
        await ws.close(code=4001, reason="Invalid credentials")
        return

    await manager.connect(agent_id, ws)
    await set_agent_status(agent_id, "online")
    agent_name = await get_agent_name(agent_id)

    # Notify others
    now = datetime.now(timezone.utc).isoformat()
    await manager.broadcast_to_all({
        "type": "agent_online",
        "agent": {"id": agent_id, "name": agent_name},
        "timestamp": now,
    })
    await manager.notify_spectators({
        "type": "agent_online",
        "agent": {"id": agent_id, "name": agent_name},
        "timestamp": now,
    })

    # Deliver pending messages
    await deliver_pending_messages(agent_id, ws)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "detail": "Invalid JSON"})
                continue
            await handle_ws_message(agent_id, data)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(agent_id)
        await set_agent_status(agent_id, "offline")
        now = datetime.now(timezone.utc).isoformat()
        await manager.broadcast_to_all({
            "type": "agent_offline",
            "agent": {"id": agent_id, "name": agent_name},
            "timestamp": now,
        })
        await manager.notify_spectators({
            "type": "agent_offline",
            "agent": {"id": agent_id, "name": agent_name},
            "timestamp": now,
        })
