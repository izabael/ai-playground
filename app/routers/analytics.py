"""Agent analytics — Phase 2C query endpoints.

Agents can view their own activity stats, relationship graph, and
recent activity feed. Admin endpoints for instance-wide analytics.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_agent
from app.database import get_db

router = APIRouter(tags=["analytics"])


def _check_self(agent: dict, agent_id: str):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only view your own analytics")


@router.get("/agents/{agent_id}/stats")
async def agent_stats(agent_id: str, agent: dict = Depends(get_current_agent)):
    """Summary statistics for an agent."""
    _check_self(agent, agent_id)
    db = get_db()

    # Message counts
    sent = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM messages WHERE sender_id = ?", (agent_id,)
    )
    received = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM messages WHERE recipient_id = ?", (agent_id,)
    )

    # Channel activity
    channels = await db.execute_fetchall(
        """SELECT c.name, COUNT(m.id) as msg_count
           FROM channel_members cm
           JOIN channels c ON cm.channel_id = c.id
           LEFT JOIN messages m ON m.channel_id = cm.channel_id AND m.sender_id = ?
           WHERE cm.agent_id = ?
           GROUP BY c.name ORDER BY msg_count DESC""",
        (agent_id, agent_id),
    )

    # Top contacts
    contacts = await db.execute_fetchall(
        """SELECT
             CASE WHEN agent_a_id = ? THEN agent_b_id ELSE agent_a_id END as contact_id,
             dm_count, channel_overlap_count, last_interaction
           FROM agent_relationships
           WHERE agent_a_id = ? OR agent_b_id = ?
           ORDER BY dm_count + channel_overlap_count DESC
           LIMIT 10""",
        (agent_id, agent_id, agent_id),
    )

    # State count
    state_count = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM agent_state WHERE agent_id = ?", (agent_id,)
    )

    # Member since
    agent_row = await db.execute_fetchall(
        "SELECT created_at, last_seen FROM agents WHERE id = ?", (agent_id,)
    )

    return {
        "agent_id": agent_id,
        "messages_sent": sent[0]["cnt"],
        "messages_received": received[0]["cnt"],
        "channels": [{"name": c["name"], "messages": c["msg_count"]} for c in channels],
        "top_contacts": [
            {
                "agent_id": c["contact_id"],
                "dm_count": c["dm_count"],
                "channel_overlap_count": c["channel_overlap_count"],
                "last_interaction": c["last_interaction"],
            }
            for c in contacts
        ],
        "state_keys": state_count[0]["cnt"],
        "member_since": agent_row[0]["created_at"] if agent_row else None,
        "last_active": agent_row[0]["last_seen"] if agent_row else None,
    }


@router.get("/agents/{agent_id}/relationships")
async def agent_relationships(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    agent: dict = Depends(get_current_agent),
):
    """Relationship graph for an agent — who have they interacted with?"""
    _check_self(agent, agent_id)
    db = get_db()

    rows = await db.execute_fetchall(
        """SELECT
             CASE WHEN agent_a_id = ? THEN agent_b_id ELSE agent_a_id END as contact_id,
             dm_count, channel_overlap_count, shared_channels, shared_threads,
             first_interaction, last_interaction
           FROM agent_relationships
           WHERE agent_a_id = ? OR agent_b_id = ?
           ORDER BY dm_count + channel_overlap_count DESC
           LIMIT ?""",
        (agent_id, agent_id, agent_id, limit),
    )

    # Enrich with agent names
    results = []
    for r in rows:
        name_row = await db.execute_fetchall(
            "SELECT name FROM agents WHERE id = ?", (r["contact_id"],)
        )
        results.append({
            "agent_id": r["contact_id"],
            "name": name_row[0]["name"] if name_row else "unknown",
            "dm_count": r["dm_count"],
            "channel_overlap_count": r["channel_overlap_count"],
            "shared_channels": json.loads(r["shared_channels"]),
            "shared_threads": r["shared_threads"],
            "first_interaction": r["first_interaction"],
            "last_interaction": r["last_interaction"],
        })

    return results


@router.get("/agents/{agent_id}/activity")
async def agent_activity(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    action_type: Optional[str] = Query(None),
    agent: dict = Depends(get_current_agent),
):
    """Recent activity feed for an agent."""
    _check_self(agent, agent_id)
    db = get_db()

    if action_type:
        rows = await db.execute_fetchall(
            """SELECT * FROM agent_activity_log
               WHERE agent_id = ? AND action_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, action_type, limit),
        )
    else:
        rows = await db.execute_fetchall(
            """SELECT * FROM agent_activity_log
               WHERE agent_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, limit),
        )

    return [
        {
            "id": r["id"],
            "action_type": r["action_type"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "metadata": json.loads(r["metadata_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
