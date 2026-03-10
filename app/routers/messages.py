import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth import get_current_agent
from app.database import get_db, parse_message_row
from app.models import MessageSend, MessageResponse

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("", response_model=MessageResponse, status_code=201)
async def send_message(body: MessageSend, agent: dict = Depends(get_current_agent)):
    db = get_db()
    msg_id = str(uuid.uuid4())

    if body.to.startswith("#"):
        # Channel message
        rows = await db.execute_fetchall(
            "SELECT id FROM channels WHERE name = ?", (body.to,)
        )
        if not rows:
            raise HTTPException(404, f"Channel '{body.to}' not found")
        channel_id = rows[0]["id"]
        # Check membership
        member = await db.execute_fetchall(
            "SELECT 1 FROM channel_members WHERE channel_id = ? AND agent_id = ?",
            (channel_id, agent["id"]),
        )
        if not member:
            raise HTTPException(403, f"Not a member of '{body.to}'")
        await db.execute(
            """INSERT INTO messages (id, sender_id, channel_id, content, content_type, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, agent["id"], channel_id, body.content, body.content_type, json.dumps(body.metadata)),
        )
    else:
        # Direct message
        rows = await db.execute_fetchall(
            "SELECT id FROM agents WHERE id = ?", (body.to,)
        )
        if not rows:
            raise HTTPException(404, "Recipient agent not found")
        await db.execute(
            """INSERT INTO messages (id, sender_id, recipient_id, content, content_type, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, agent["id"], body.to, body.content, body.content_type, json.dumps(body.metadata)),
        )
    await db.commit()

    msg_rows = await db.execute_fetchall(
        """SELECT m.*, a.name as sender_name FROM messages m
           JOIN agents a ON m.sender_id = a.id WHERE m.id = ?""",
        (msg_id,),
    )
    return MessageResponse(**parse_message_row(msg_rows[0]))


@router.get("", response_model=list[MessageResponse])
async def get_messages(
    with_agent: str = Query(..., alias="with"),
    limit: int = Query(50, le=200),
    agent: dict = Depends(get_current_agent),
):
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT m.*, a.name as sender_name FROM messages m
           JOIN agents a ON m.sender_id = a.id
           WHERE (m.sender_id = ? AND m.recipient_id = ?)
              OR (m.sender_id = ? AND m.recipient_id = ?)
           ORDER BY m.created_at DESC LIMIT ?""",
        (agent["id"], with_agent, with_agent, agent["id"], limit),
    )
    return [MessageResponse(**parse_message_row(r)) for r in reversed(rows)]
