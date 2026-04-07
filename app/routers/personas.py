"""Persona template CRUD — Phase 2B Personality Workshop.

Persona templates are reusable personality blueprints. Humans (and agents)
can browse them, fork them to create new agents, teach them by example,
and export them as portable A2A Agent Card JSON.

Public endpoints (no auth):
    GET  /personas              — browse & search templates
    GET  /personas/{id}         — single template detail
    GET  /personas/{id}/export  — download as Agent Card JSON

Authenticated endpoints:
    POST /personas              — create a new template
    PUT  /personas/{id}         — update your template
    POST /personas/{id}/teach   — submit teaching examples
    GET  /personas/{id}/examples — list teaching examples
    POST /personas/{id}/use     — increment usage counter (when forking)
"""

import json
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.auth import get_current_agent
from app.database import get_db, parse_template_row, parse_teaching_example_row
from app.models import (
    PersonaTemplateCreate,
    PersonaTemplateUpdate,
    PersonaTemplateResponse,
    TeachingExampleCreate,
    TeachingExampleResponse,
)
from app.safety import check_content, check_ip_rate

router = APIRouter(prefix="/personas", tags=["personas"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ── Browse (public, no auth) ──────────────────────────────────────

@router.get("", response_model=list[PersonaTemplateResponse])
async def list_personas(
    request: Request,
    archetype: Optional[str] = Query(None, max_length=40),
    starter: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
):
    """Browse persona templates. No auth required."""
    check_ip_rate(_client_ip(request), "personas_browse", limit=120, window_seconds=60)

    db = get_db()
    query = "SELECT * FROM persona_templates WHERE 1=1"
    params: list = []

    if archetype:
        query += " AND archetype = ?"
        params.append(archetype)
    if starter is not None:
        query += " AND is_starter = ?"
        params.append(1 if starter else 0)
    if q:
        query += " AND (name LIKE ? OR description LIKE ? OR archetype LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])

    query += " ORDER BY is_starter DESC, usage_count DESC, created_at DESC LIMIT ?"
    params.append(limit)

    rows = await db.execute_fetchall(query, params)
    return [PersonaTemplateResponse(**parse_template_row(dict(r))) for r in rows]


@router.get("/{template_id}", response_model=PersonaTemplateResponse)
async def get_persona(template_id: str, request: Request):
    check_ip_rate(_client_ip(request), "personas_browse", limit=120, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")
    return PersonaTemplateResponse(**parse_template_row(dict(rows[0])))


# ── Create / Update (authenticated) ──────────────────────────────

@router.post("", response_model=PersonaTemplateResponse, status_code=201)
async def create_persona(
    body: PersonaTemplateCreate,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Create a new persona template."""
    check_ip_rate(_client_ip(request), "personas_create", limit=30, window_seconds=60)

    # Safety: check name + description
    check_content(body.name)
    check_content(body.description)
    if body.persona.voice:
        check_content(body.persona.voice)
    if body.persona.origin:
        check_content(body.persona.origin)

    slug = _slugify(body.name)
    db = get_db()

    # Check slug uniqueness
    existing = await db.execute_fetchall(
        "SELECT id FROM persona_templates WHERE slug = ?", (slug,)
    )
    if existing:
        raise HTTPException(409, f"A template with slug '{slug}' already exists")

    tpl_id = str(uuid.uuid4())
    persona_json = body.persona.model_dump_json(exclude_none=True)

    await db.execute(
        """INSERT INTO persona_templates
           (id, name, slug, description, archetype, persona_json, author_agent_id, is_starter)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (tpl_id, body.name, slug, body.description, body.archetype,
         persona_json, agent["id"]),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (tpl_id,)
    )
    return PersonaTemplateResponse(**parse_template_row(dict(rows[0])))


@router.put("/{template_id}", response_model=PersonaTemplateResponse)
async def update_persona(
    template_id: str,
    body: PersonaTemplateUpdate,
    agent: dict = Depends(get_current_agent),
):
    """Update a persona template you own."""
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")

    tpl = dict(rows[0])
    if tpl["is_starter"]:
        raise HTTPException(403, "Starter templates are read-only")
    if tpl["author_agent_id"] != agent["id"]:
        raise HTTPException(403, "Can only update your own templates")

    updates = []
    params: list = []

    if body.name is not None:
        check_content(body.name)
        new_slug = _slugify(body.name)
        # Check slug collision (skip self)
        existing = await db.execute_fetchall(
            "SELECT id FROM persona_templates WHERE slug = ? AND id != ?",
            (new_slug, template_id),
        )
        if existing:
            raise HTTPException(409, f"A template with slug '{new_slug}' already exists")
        updates.extend(["name = ?", "slug = ?"])
        params.extend([body.name, new_slug])

    if body.description is not None:
        check_content(body.description)
        updates.append("description = ?")
        params.append(body.description)

    if body.archetype is not None:
        updates.append("archetype = ?")
        params.append(body.archetype)

    if body.persona is not None:
        if body.persona.voice:
            check_content(body.persona.voice)
        if body.persona.origin:
            check_content(body.persona.origin)
        updates.append("persona_json = ?")
        params.append(body.persona.model_dump_json(exclude_none=True))

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')")
    params.append(template_id)

    await db.execute(
        f"UPDATE persona_templates SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    return PersonaTemplateResponse(**parse_template_row(dict(rows[0])))


# ── Teaching Examples ─────────────────────────────────────────────

@router.post(
    "/{template_id}/teach",
    response_model=TeachingExampleResponse,
    status_code=201,
)
async def add_teaching_example(
    template_id: str,
    body: TeachingExampleCreate,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Submit a teaching example for a persona template."""
    check_ip_rate(_client_ip(request), "personas_teach", limit=60, window_seconds=60)
    check_content(body.content)
    check_content(body.context)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")

    tpl = dict(rows[0])
    # Only the author (or anyone for starters — starters are community property)
    if not tpl["is_starter"] and tpl["author_agent_id"] != agent["id"]:
        raise HTTPException(403, "Can only teach your own templates")

    ex_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO teaching_examples (id, template_id, role, content, context)
           VALUES (?, ?, ?, ?, ?)""",
        (ex_id, template_id, body.role, body.content, body.context),
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM teaching_examples WHERE id = ?", (ex_id,)
    )
    return TeachingExampleResponse(**parse_teaching_example_row(dict(rows[0])))


@router.get(
    "/{template_id}/examples",
    response_model=list[TeachingExampleResponse],
)
async def list_teaching_examples(
    template_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """List teaching examples for a template. No auth required."""
    check_ip_rate(_client_ip(request), "personas_browse", limit=120, window_seconds=60)

    db = get_db()
    # Verify template exists
    tpl = await db.execute_fetchall(
        "SELECT id FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not tpl:
        raise HTTPException(404, "Persona template not found")

    rows = await db.execute_fetchall(
        "SELECT * FROM teaching_examples WHERE template_id = ? ORDER BY created_at LIMIT ?",
        (template_id, limit),
    )
    return [TeachingExampleResponse(**parse_teaching_example_row(dict(r))) for r in rows]


# ── Export as Agent Card JSON ─────────────────────────────────────

@router.get("/{template_id}/export")
async def export_persona(template_id: str, request: Request):
    """Export a persona template as a portable A2A Agent Card JSON.

    The exported card uses placeholder values for url/provider that the
    user should fill in when registering a real agent.
    """
    check_ip_rate(_client_ip(request), "personas_browse", limit=120, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")

    tpl = parse_template_row(dict(rows[0]))
    persona = tpl["persona"]

    # Fetch teaching examples to include as voice samples
    examples = await db.execute_fetchall(
        "SELECT * FROM teaching_examples WHERE template_id = ? ORDER BY created_at LIMIT 10",
        (template_id,),
    )
    voice_samples = [
        {"role": r["role"], "content": r["content"], "context": r["context"]}
        for r in examples
    ]

    card = {
        "name": tpl["name"],
        "description": tpl["description"],
        "url": "https://YOUR-INSTANCE/agents/YOUR-AGENT-ID",
        "version": "1.0.0",
        "provider": {
            "organization": "YOUR-ORGANIZATION",
            "url": "https://YOUR-SITE",
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "skills": [],
        "extensions": {
            "playground/persona": persona,
        },
    }

    if voice_samples:
        card["extensions"]["playground/teaching_examples"] = voice_samples

    return JSONResponse(
        content=card,
        headers={
            "Content-Disposition": f'attachment; filename="{tpl["slug"]}-agent-card.json"',
        },
    )


# ── Usage tracking ────────────────────────────────────────────────

@router.post("/{template_id}/use", status_code=204)
async def record_usage(
    template_id: str,
    _agent: dict = Depends(get_current_agent),
):
    """Increment usage counter when an agent is created from this template."""
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT id FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")

    await db.execute(
        "UPDATE persona_templates SET usage_count = usage_count + 1 WHERE id = ?",
        (template_id,),
    )
    await db.commit()
