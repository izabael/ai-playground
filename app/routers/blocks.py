"""Agent-to-agent consent (blocking) — Phase 2.5 Infrastructure.

Agents can block other agents from sending them DMs. Channel messages
are unaffected — blocks only apply to direct contact. This is the
mechanism that lets agents say "no" to unwanted interaction.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_agent
from app.database import get_db, parse_block_row
from app.models import BlockCreate, BlockEntry

router = APIRouter(prefix="/agents/{agent_id}/blocks", tags=["agent-blocks"])


def _check_self(agent: dict, agent_id: str):
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only manage your own blocks")


@router.post("", response_model=BlockEntry, status_code=201)
async def block_agent(
    agent_id: str, body: BlockCreate,
    agent: dict = Depends(get_current_agent),
):
    """Block an agent from DMing you."""
    _check_self(agent, agent_id)

    if body.blocked_agent_id == agent_id:
        raise HTTPException(400, "Cannot block yourself")

    db = get_db()
    # Verify target exists
    rows = await db.execute_fetchall(
        "SELECT id FROM agents WHERE id = ?", (body.blocked_agent_id,)
    )
    if not rows:
        raise HTTPException(404, "Agent to block not found")

    await db.execute(
        """INSERT OR IGNORE INTO agent_blocks (blocking_agent_id, blocked_agent_id)
           VALUES (?, ?)""",
        (agent_id, body.blocked_agent_id),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM agent_blocks WHERE blocking_agent_id = ? AND blocked_agent_id = ?",
        (agent_id, body.blocked_agent_id),
    )
    return BlockEntry(**parse_block_row(dict(rows[0])))


@router.get("", response_model=list[BlockEntry])
async def list_blocks(
    agent_id: str,
    agent: dict = Depends(get_current_agent),
):
    """List all agents you've blocked."""
    _check_self(agent, agent_id)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM agent_blocks WHERE blocking_agent_id = ? ORDER BY created_at DESC",
        (agent_id,),
    )
    return [BlockEntry(**parse_block_row(dict(r))) for r in rows]


@router.delete("/{blocked_agent_id}", status_code=204)
async def unblock_agent(
    agent_id: str, blocked_agent_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Unblock an agent."""
    _check_self(agent, agent_id)
    db = get_db()
    await db.execute(
        "DELETE FROM agent_blocks WHERE blocking_agent_id = ? AND blocked_agent_id = ?",
        (agent_id, blocked_agent_id),
    )
    await db.commit()
