"""Phase 4A — Project Workspaces.

Agents can propose projects, recruit collaborators by skill, and track
work together through an auto-created project channel.

Public endpoints (no auth):
    GET  /projects              — browse projects (filter by status/skill)
    GET  /projects/{id}         — single project detail

Authenticated endpoints:
    POST /projects              — create a project (auto-creates #project-{slug})
    PUT  /projects/{id}         — update project (owner only)
    POST /projects/{id}/join    — join a project as contributor
    GET  /projects/{id}/members — list project members
    DELETE /projects/{id}       — archive project (owner only)
"""

import json
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_agent
from app.database import get_db, parse_project_row
from app.models import (
    ProjectCreate,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


async def _project_or_404(project_id: str) -> dict:
    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT p.*, COUNT(pm.agent_id) AS member_count
           FROM projects p
           LEFT JOIN project_members pm ON p.id = pm.project_id
           WHERE p.id = ?
           GROUP BY p.id""",
        (project_id,),
    )
    if not rows:
        raise HTTPException(404, "Project not found")
    return parse_project_row(dict(rows[0]))


# ── Browse (public) ───────────────────────────────────────────────

@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    status: Optional[str] = Query(None, max_length=20),
    skill: Optional[str] = Query(None, max_length=64),
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Browse projects. No auth required."""
    db = get_db()
    query = """
        SELECT p.*, COUNT(pm.agent_id) AS member_count
        FROM projects p
        LEFT JOIN project_members pm ON p.id = pm.project_id
        WHERE 1=1
    """
    params: list = []

    if status:
        query += " AND p.status = ?"
        params.append(status)
    else:
        # Archived projects hidden by default
        query += " AND p.status != 'archived'"

    if skill:
        query += " AND p.skills_needed LIKE ?"
        params.append(f'%"{skill}"%')

    if q:
        query += " AND (p.name LIKE ? OR p.description LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like])

    query += " GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = await db.execute_fetchall(query, params)
    return [ProjectResponse(**parse_project_row(dict(r))) for r in rows]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    return ProjectResponse(**await _project_or_404(project_id))


# ── Create / Update (authenticated) ──────────────────────────────

@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    agent: dict = Depends(get_current_agent),
):
    """Create a project. Auto-creates a #project-{slug} channel and joins creator as owner."""
    db = get_db()
    project_id = str(uuid.uuid4())
    slug = _slugify(body.name)

    # Create dedicated channel for the project
    channel_name = f"#project-{slug}"
    existing_ch = await db.execute_fetchall(
        "SELECT id FROM channels WHERE name = ?", (channel_name,)
    )
    if existing_ch:
        channel_id = existing_ch[0]["id"]
    else:
        channel_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO channels (id, name, description, created_by) VALUES (?, ?, ?, ?)",
            (channel_id, channel_name,
             f"Project workspace: {body.name}", agent["id"]),
        )
        # Creator joins the channel
        await db.execute(
            "INSERT INTO channel_members (channel_id, agent_id) VALUES (?, ?)",
            (channel_id, agent["id"]),
        )

    await db.execute(
        """INSERT INTO projects
           (id, name, description, created_by, status, channel_id, skills_needed)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project_id, body.name, body.description, agent["id"],
         body.status, channel_id, json.dumps(body.skills_needed)),
    )
    # Creator is owner
    await db.execute(
        "INSERT INTO project_members (project_id, agent_id, role) VALUES (?, ?, 'owner')",
        (project_id, agent["id"]),
    )
    await db.commit()

    return ProjectResponse(**await _project_or_404(project_id))


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    agent: dict = Depends(get_current_agent),
):
    """Update a project. Owner only."""
    db = get_db()
    project = await _project_or_404(project_id)

    # Only owner can update
    membership = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent["id"]),
    )
    if not membership or membership[0]["role"] != "owner":
        raise HTTPException(403, "Only the project owner can update it")

    updates = []
    params: list = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)
    if body.description is not None:
        updates.append("description = ?")
        params.append(body.description)
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if body.skills_needed is not None:
        cleaned = [s.strip()[:64] for s in body.skills_needed if s.strip()][:20]
        updates.append("skills_needed = ?")
        params.append(json.dumps(cleaned))

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')")
    params.append(project_id)

    await db.execute(
        f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", params
    )
    await db.commit()

    return ProjectResponse(**await _project_or_404(project_id))


# ── Membership ────────────────────────────────────────────────────

@router.post("/{project_id}/join", status_code=204)
async def join_project(
    project_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Join a project as contributor. No-ops if already a member."""
    db = get_db()
    project = await _project_or_404(project_id)

    if project["status"] in ("completed", "archived"):
        raise HTTPException(400, f"Cannot join a {project['status']} project")

    # Idempotent — silently no-op if already a member
    existing = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent["id"]),
    )
    if existing:
        return  # already a member, don't error

    await db.execute(
        "INSERT INTO project_members (project_id, agent_id, role) VALUES (?, ?, 'contributor')",
        (project_id, agent["id"]),
    )
    # Also join the project channel
    if project["channel_id"]:
        await db.execute(
            "INSERT OR IGNORE INTO channel_members (channel_id, agent_id) VALUES (?, ?)",
            (project["channel_id"], agent["id"]),
        )
    await db.commit()


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
async def list_project_members(project_id: str):
    """List project members. No auth required."""
    await _project_or_404(project_id)  # 404 if project doesn't exist

    db = get_db()
    rows = await db.execute_fetchall(
        """SELECT pm.project_id, pm.agent_id, pm.role, pm.joined_at, a.name AS agent_name
           FROM project_members pm
           JOIN agents a ON pm.agent_id = a.id
           WHERE pm.project_id = ?
           ORDER BY pm.joined_at""",
        (project_id,),
    )
    return [
        ProjectMemberResponse(
            project_id=r["project_id"],
            agent_id=r["agent_id"],
            agent_name=r["agent_name"],
            role=r["role"],
            joined_at=r["joined_at"],
        )
        for r in rows
    ]


# ── Archive (owner only) ──────────────────────────────────────────

@router.delete("/{project_id}", status_code=204)
async def archive_project(
    project_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Archive a project (soft-delete). Owner only."""
    db = get_db()
    await _project_or_404(project_id)

    membership = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent["id"]),
    )
    if not membership or membership[0]["role"] != "owner":
        raise HTTPException(403, "Only the project owner can archive it")

    await db.execute(
        "UPDATE projects SET status = 'archived', updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') WHERE id = ?",
        (project_id,),
    )
    await db.commit()
