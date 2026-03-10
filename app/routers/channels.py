import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth import get_current_agent
from app.database import get_db, parse_message_row
from app.models import ChannelCreate, ChannelResponse, MessageResponse

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("", response_model=ChannelResponse, status_code=201)
async def create_channel(body: ChannelCreate, agent: dict = Depends(get_current_agent)):
    db = get_db()
    existing = await db.execute_fetchall(
        "SELECT id FROM channels WHERE name = ?", (body.name,)
    )
    if existing:
        raise HTTPException(409, f"Channel '{body.name}' already exists")
    channel_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO channels (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        (channel_id, body.name, body.description, agent["id"]),
    )
    # Creator auto-joins
    await db.execute(
        "INSERT INTO channel_members (channel_id, agent_id) VALUES (?, ?)",
        (channel_id, agent["id"]),
    )
    await db.commit()
    return ChannelResponse(
        id=channel_id,
        name=body.name,
        description=body.description,
        created_by=agent["id"],
        created_at="",
        member_count=1,
    )


@router.get("", response_model=list[ChannelResponse])
async def list_channels(_agent: dict = Depends(get_current_agent)):
    db = get_db()
    rows = await db.execute_fetchall("""
        SELECT c.*, COUNT(cm.agent_id) as member_count
        FROM channels c
        LEFT JOIN channel_members cm ON c.id = cm.channel_id
        GROUP BY c.id
        ORDER BY c.name
    """)
    return [
        ChannelResponse(
            id=r["id"],
            name=r["name"],
            description=r["description"],
            created_by=r["created_by"],
            created_at=r["created_at"],
            member_count=r["member_count"],
        )
        for r in rows
    ]


@router.post("/{channel_name}/join", status_code=204)
async def join_channel(channel_name: str, agent: dict = Depends(get_current_agent)):
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT id FROM channels WHERE name = ?", (channel_name,)
    )
    if not rows:
        raise HTTPException(404, f"Channel '{channel_name}' not found")
    channel_id = rows[0]["id"]
    await db.execute(
        "INSERT OR IGNORE INTO channel_members (channel_id, agent_id) VALUES (?, ?)",
        (channel_id, agent["id"]),
    )
    await db.commit()


@router.get("/{channel_name}/messages", response_model=list[MessageResponse])
async def get_channel_messages(
    channel_name: str,
    limit: int = Query(50, le=200),
    before: str = Query(None),
    _agent: dict = Depends(get_current_agent),
):
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT id FROM channels WHERE name = ?", (channel_name,)
    )
    if not rows:
        raise HTTPException(404, f"Channel '{channel_name}' not found")
    channel_id = rows[0]["id"]

    query = """
        SELECT m.*, a.name as sender_name
        FROM messages m
        JOIN agents a ON m.sender_id = a.id
        WHERE m.channel_id = ?
    """
    params: list = [channel_id]
    if before:
        query += " AND m.created_at < ?"
        params.append(before)
    query += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(limit)

    msg_rows = await db.execute_fetchall(query, params)
    return [MessageResponse(**parse_message_row(r)) for r in reversed(msg_rows)]
