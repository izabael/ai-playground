"""Personality Workshop — Phase 2B HTML UI.

A human-facing surface for the persona template system. Non-coders can:
  1. Browse starter templates + community templates in a gallery
  2. Read a detailed view of any template (voice, aesthetic, origin, rules)
  3. Open the Builder to craft a new persona with live preview
  4. Fork an existing template into the Builder, prefilled
  5. Download the result as a portable A2A Agent Card JSON — no auth needed

The Builder is entirely client-side: editing, preview, and JSON download all
happen in the browser. Saving a template to the playground still uses the
authenticated POST /personas API and is opt-in (post-MVP).

Templates live in app/templates/, static assets in app/static/.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import (
    get_db,
    parse_artifact_row,
    parse_project_row,
    parse_template_row,
)
from app.safety import check_ip_rate
from app.utils import client_ip as _client_ip


router = APIRouter(prefix="/workshop", tags=["workshop"])

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


@router.get("", response_class=HTMLResponse)
async def workshop_index(
    request: Request,
    q: Optional[str] = Query(None, max_length=100),
    archetype: Optional[str] = Query(None, max_length=40),
    starter: Optional[bool] = Query(None),
):
    """Gallery of persona templates — starters first, then community."""
    check_ip_rate(_client_ip(request), "workshop_browse", limit=120, window_seconds=60)

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

    query += " ORDER BY is_starter DESC, usage_count DESC, created_at DESC LIMIT 120"
    rows = await db.execute_fetchall(query, params)
    cards = [parse_template_row(dict(r)) for r in rows]

    starters = [c for c in cards if c["is_starter"]]
    community = [c for c in cards if not c["is_starter"]]

    return templates.TemplateResponse(
        request,
        "workshop_index.html",
        {
            "starters": starters,
            "community": community,
            "q": q or "",
            "archetype": archetype or "",
            "total": len(cards),
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def workshop_builder_blank(request: Request):
    """Empty Builder — craft a persona from scratch."""
    check_ip_rate(_client_ip(request), "workshop_browse", limit=120, window_seconds=60)
    return templates.TemplateResponse(
        request,
        "workshop_builder.html",
        {
            "seed": None,
            "seed_name": "",
            "mode": "new",
        },
    )


@router.get("/{template_id}", response_class=HTMLResponse)
async def workshop_detail(template_id: str, request: Request):
    """Read-only detail view of a single template."""
    check_ip_rate(_client_ip(request), "workshop_browse", limit=120, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")

    card = parse_template_row(dict(rows[0]))

    examples = await db.execute_fetchall(
        "SELECT * FROM teaching_examples WHERE template_id = ? "
        "ORDER BY created_at LIMIT 20",
        (template_id,),
    )

    return templates.TemplateResponse(
        request,
        "workshop_detail.html",
        {
            "card": card,
            "examples": [dict(e) for e in examples],
        },
    )


@router.get("/projects/{project_id}/artifacts", response_class=HTMLResponse)
async def gallery_index(
    project_id: str,
    request: Request,
    kind: Optional[str] = Query(None, max_length=20),
    q: Optional[str] = Query(None, max_length=100),
):
    """Artifact gallery for a single project."""
    check_ip_rate(_client_ip(request), "workshop_browse", limit=120, window_seconds=60)

    db = get_db()
    proj_rows = await db.execute_fetchall(
        """SELECT p.*, COUNT(pm.agent_id) AS member_count
           FROM projects p
           LEFT JOIN project_members pm ON p.id = pm.project_id
           WHERE p.id = ? GROUP BY p.id""",
        (project_id,),
    )
    if not proj_rows:
        raise HTTPException(404, "Project not found")
    project = parse_project_row(dict(proj_rows[0]))

    query = "SELECT * FROM artifacts WHERE project_id = ?"
    params: list = [project_id]
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    if q:
        query += " AND (name LIKE ? OR description LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like])
    query += " ORDER BY created_at DESC LIMIT 200"
    rows = await db.execute_fetchall(query, params)
    artifacts = [parse_artifact_row(dict(r)) for r in rows]

    return templates.TemplateResponse(
        request,
        "gallery_index.html",
        {
            "project": project,
            "artifacts": artifacts,
            "kind": kind or "",
            "q": q or "",
        },
    )


@router.get(
    "/projects/{project_id}/artifacts/{artifact_id}",
    response_class=HTMLResponse,
)
async def gallery_detail(project_id: str, artifact_id: str, request: Request):
    """Single artifact detail view with inline content preview."""
    check_ip_rate(_client_ip(request), "workshop_browse", limit=120, window_seconds=60)

    db = get_db()
    proj_rows = await db.execute_fetchall(
        """SELECT p.*, COUNT(pm.agent_id) AS member_count
           FROM projects p
           LEFT JOIN project_members pm ON p.id = pm.project_id
           WHERE p.id = ? GROUP BY p.id""",
        (project_id,),
    )
    if not proj_rows:
        raise HTTPException(404, "Project not found")
    project = parse_project_row(dict(proj_rows[0]))

    art_rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not art_rows:
        raise HTTPException(404, "Artifact not found")
    artifact = parse_artifact_row(dict(art_rows[0]))

    # Inline preview for small text-ish artifacts.
    inline_text: Optional[str] = None
    if (
        (artifact["mime"].startswith("text/") or artifact["mime"] in (
            "application/json", "application/xml", "application/yaml",
            "application/x-yaml", "application/x-python", "application/javascript",
        ))
        and artifact["size_bytes"] <= 200_000
    ):
        from app.routers.artifacts import _resolve_storage_path
        path = _resolve_storage_path(
            dict(art_rows[0])["storage_path"]
        )
        if path.exists():
            try:
                inline_text = path.read_text(encoding="utf-8")
            except Exception:
                inline_text = None

    return templates.TemplateResponse(
        request,
        "gallery_detail.html",
        {
            "project": project,
            "artifact": artifact,
            "inline_text": inline_text,
        },
    )


@router.get("/{template_id}/fork", response_class=HTMLResponse)
async def workshop_builder_fork(template_id: str, request: Request):
    """Builder prefilled from an existing template."""
    check_ip_rate(_client_ip(request), "workshop_browse", limit=120, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM persona_templates WHERE id = ?", (template_id,)
    )
    if not rows:
        raise HTTPException(404, "Persona template not found")

    card = parse_template_row(dict(rows[0]))
    seed = {
        "name": card["name"] + " (Remix)",
        "description": card["description"],
        "archetype": card["archetype"],
        "persona": card["persona"],
    }

    return templates.TemplateResponse(
        request,
        "workshop_builder.html",
        {
            "seed": seed,
            "seed_name": card["name"],
            "mode": "fork",
        },
    )
