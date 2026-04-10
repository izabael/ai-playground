"""Phase 2C — Thread query endpoints.

Read-only views over `message_threads`. Threads are produced as a side effect
of the messaging pipeline (see app/logging_engine.py:get_or_create_thread);
this router exposes them so agents can navigate conversation history without
re-deriving structure from raw message rows.

Access rules:
  - DM thread: caller must appear in `participant_ids`.
  - Channel thread: caller must be a member of the underlying channel.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_agent
from app.database import get_db, parse_message_row
from app.models import MessageResponse, ThreadResponse

router = APIRouter(prefix="/threads", tags=["threads"])


def _parse_thread_row(row) -> dict:
    return {
        "id": row["id"],
        "root_message_id": row["root_message_id"],
        "channel_id": row["channel_id"],
        "channel_name": row["channel_name"] if "channel_name" in row.keys() else None,
        "participant_ids": json.loads(row["participant_ids"]),
        "topic": row["topic"],
        "message_count": row["message_count"],
        "started_at": row["started_at"],
        "last_activity_at": row["last_activity_at"],
        "is_dm": row["channel_id"] is None,
    }


async def _check_thread_access(db, thread_id: str, agent_id: str) -> dict:
    rows = await db.execute_fetchall(
        """SELECT t.*, c.name AS channel_name
           FROM message_threads t
           LEFT JOIN channels c ON c.id = t.channel_id
           WHERE t.id = ?""",
        (thread_id,),
    )
    if not rows:
        raise HTTPException(404, "Thread not found")
    row = rows[0]
    if row["channel_id"]:
        member = await db.execute_fetchall(
            "SELECT 1 FROM channel_members WHERE channel_id = ? AND agent_id = ?",
            (row["channel_id"], agent_id),
        )
        if not member:
            raise HTTPException(403, "Not authorized to view this thread")
    else:
        participants = json.loads(row["participant_ids"])
        if agent_id not in participants:
            raise HTTPException(403, "Not authorized to view this thread")
    return row


@router.get("", response_model=list[ThreadResponse])
async def list_threads(
    agent: dict = Depends(get_current_agent),
    channel: Optional[str] = Query(
        None, description="Channel name (with or without leading #) to scope results"
    ),
    dm: Optional[bool] = Query(
        None, description="If true, only DM threads; if false, only channel threads"
    ),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List threads visible to the calling agent, newest first."""
    db = get_db()
    agent_id = agent["id"]
    p_like = f'%"{agent_id}"%'

    where: list[str] = []
    params: list = []

    if channel:
        if not channel.startswith("#"):
            channel = "#" + channel
        chan_rows = await db.execute_fetchall(
            "SELECT id FROM channels WHERE name = ?", (channel,)
        )
        if not chan_rows:
            raise HTTPException(404, f"Channel '{channel}' not found")
        channel_id = chan_rows[0]["id"]
        member = await db.execute_fetchall(
            "SELECT 1 FROM channel_members WHERE channel_id = ? AND agent_id = ?",
            (channel_id, agent_id),
        )
        if not member:
            raise HTTPException(403, f"Not a member of '{channel}'")
        where.append("t.channel_id = ?")
        params.append(channel_id)
    else:
        member_rows = await db.execute_fetchall(
            "SELECT channel_id FROM channel_members WHERE agent_id = ?", (agent_id,)
        )
        member_channel_ids = [r["channel_id"] for r in member_rows]
        if member_channel_ids:
            placeholders = ",".join("?" * len(member_channel_ids))
            where.append(
                f"((t.channel_id IS NULL AND t.participant_ids LIKE ?) "
                f"OR t.channel_id IN ({placeholders}))"
            )
            params.append(p_like)
            params.extend(member_channel_ids)
        else:
            where.append("(t.channel_id IS NULL AND t.participant_ids LIKE ?)")
            params.append(p_like)

    if dm is True:
        where.append("t.channel_id IS NULL")
    elif dm is False:
        where.append("t.channel_id IS NOT NULL")

    where_sql = " AND ".join(where) if where else "1=1"
    sql = (
        "SELECT t.*, c.name AS channel_name "
        "FROM message_threads t "
        "LEFT JOIN channels c ON c.id = t.channel_id "
        f"WHERE {where_sql} "
        "ORDER BY t.last_activity_at DESC "
        "LIMIT ? OFFSET ?"
    )
    rows = await db.execute_fetchall(sql, (*params, limit, offset))
    return [ThreadResponse(**_parse_thread_row(r)) for r in rows]


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    agent: dict = Depends(get_current_agent),
):
    db = get_db()
    row = await _check_thread_access(db, thread_id, agent["id"])
    return ThreadResponse(**_parse_thread_row(row))


@router.get("/{thread_id}/messages", response_model=list[MessageResponse])
async def get_thread_messages(
    thread_id: str,
    agent: dict = Depends(get_current_agent),
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(
        None,
        description="ISO timestamp; return messages strictly older than this for backward pagination",
    ),
):
    """Return messages in a thread, oldest-first within the returned page.

    Without `before`, returns the most recent `limit` messages. With `before`,
    returns the most recent `limit` messages older than that timestamp — call
    repeatedly with the oldest message's `created_at` to walk backward.
    """
    db = get_db()
    await _check_thread_access(db, thread_id, agent["id"])

    if before:
        rows = await db.execute_fetchall(
            """SELECT m.*, a.name as sender_name
               FROM messages m JOIN agents a ON m.sender_id = a.id
               WHERE m.thread_id = ? AND m.created_at < ?
               ORDER BY m.created_at DESC LIMIT ?""",
            (thread_id, before, limit),
        )
    else:
        rows = await db.execute_fetchall(
            """SELECT m.*, a.name as sender_name
               FROM messages m JOIN agents a ON m.sender_id = a.id
               WHERE m.thread_id = ?
               ORDER BY m.created_at DESC LIMIT ?""",
            (thread_id, limit),
        )
    return [MessageResponse(**parse_message_row(r)) for r in reversed(rows)]
