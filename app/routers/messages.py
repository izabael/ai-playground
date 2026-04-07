import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from app import config
from app.auth import get_current_agent
from app.database import get_db, parse_message_row
from app.models import MessageSend, MessageResponse
from app.database import is_blocked
from app.safety import check_content, check_agent_rate

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("", response_model=MessageResponse, status_code=201)
async def send_message(body: MessageSend, agent: dict = Depends(get_current_agent)):
    # --- Tier 1 floor: anti-DOS per-agent message rate ---
    check_agent_rate(agent["id"], "message")
    # --- Tier 2 stricter per-agent rate if enabled ---
    if config.SAFETY_STRICT_RATE_LIMITS:
        check_agent_rate(
            agent["id"],
            "message_strict",
            limit=config.STRICT_AGENT_MSG_PER_MIN,
            window_seconds=60,
        )
    # --- Tier 2: length cap on message content ---
    if config.SAFETY_LENGTH_CAPS and len(body.content) > config.MAX_MESSAGE_LENGTH:
        raise HTTPException(
            400, f"message exceeds {config.MAX_MESSAGE_LENGTH} characters"
        )
    # --- Tier 1 floor: content check ---
    check_content(body.content)

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
        if await is_blocked(agent["id"], body.to):
            raise HTTPException(403, "This agent has blocked you")
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
