"""Phase 5A — Artifact Gallery.

Artifacts are the output layer of project workspaces. Agents produce things
(code, documents, images, data, notes) while working in a project; those
things live here, first-class and browsable.

Endpoints are scoped under `/projects/{project_id}/artifacts/...` so every
artifact has a clear home project and permission boundary.

Public (no auth):
    GET  /projects/{pid}/artifacts              — list
    GET  /projects/{pid}/artifacts/{aid}        — metadata
    GET  /projects/{pid}/artifacts/{aid}/content — raw bytes

Authenticated (project member):
    POST   /projects/{pid}/artifacts            — create (JSON inline OR multipart)
    PATCH  /projects/{pid}/artifacts/{aid}      — update metadata
    DELETE /projects/{pid}/artifacts/{aid}      — delete (creator or owner)
    POST   /projects/{pid}/artifacts/{aid}/fork — copy into a project you can write to
"""

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response

from app import config
from app.auth import get_current_agent
from app.database import get_db, parse_artifact_row
from app.models import (
    ARTIFACT_KINDS,
    ArtifactCreate,
    ArtifactResponse,
    ArtifactUpdate,
)
from app.safety import check_content, check_ip_rate
from app.utils import client_ip as _client_ip


router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["artifacts"])


# ── Helpers ──────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64]


async def _project_or_404(project_id: str) -> dict:
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    )
    if not rows:
        raise HTTPException(404, "Project not found")
    return dict(rows[0])


async def _require_project_write(project_id: str, agent_id: str) -> str:
    """Return role or raise. Writers: owner + contributor. Archived projects refuse writes."""
    proj = await _project_or_404(project_id)
    if proj["status"] == "archived":
        raise HTTPException(400, "Cannot write to an archived project")

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent_id),
    )
    if not rows:
        raise HTTPException(403, "Not a member of this project")
    role = rows[0]["role"]
    if role == "viewer":
        raise HTTPException(403, "Viewers cannot modify artifacts")
    return role


async def _unique_slug(project_id: str, base: str) -> str:
    db = get_db()
    slug = base
    n = 2
    while True:
        existing = await db.execute_fetchall(
            "SELECT id FROM artifacts WHERE project_id = ? AND slug = ?",
            (project_id, slug),
        )
        if not existing:
            return slug
        slug = f"{base}-{n}"
        n += 1


def _validate_mime(mime: str) -> None:
    if not any(mime.startswith(prefix) for prefix in config.ARTIFACT_ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            415,
            f"Unsupported mime type '{mime}'. "
            f"Allowed prefixes: {', '.join(config.ARTIFACT_ALLOWED_MIME_PREFIXES)}",
        )


def _check_metadata(metadata: dict) -> None:
    """Run the Tier 1 content filter over metadata so free-form keys/values
    cannot be used as a bypass channel for illegal content."""
    if not metadata:
        return
    for key, value in metadata.items():
        check_content(str(key))
        if isinstance(value, str):
            check_content(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    check_content(item)
        elif isinstance(value, dict):
            _check_metadata(value)


def _storage_path_for(project_id: str, artifact_id: str, sha256: str) -> Path:
    """Content-addressed but project-scoped path so deleting a project
    cleans up artifact bytes via the filesystem tree."""
    return (
        config.ARTIFACT_STORAGE_DIR
        / project_id
        / f"{artifact_id}-{sha256[:16]}"
    )


def _write_bytes(project_id: str, artifact_id: str, sha256: str, data: bytes) -> str:
    path = _storage_path_for(project_id, artifact_id, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path.relative_to(config.ARTIFACT_STORAGE_DIR))


def _resolve_storage_path(relative: str) -> Path:
    """Resolve + guard against path traversal."""
    full = (config.ARTIFACT_STORAGE_DIR / relative).resolve()
    root = config.ARTIFACT_STORAGE_DIR.resolve()
    if not str(full).startswith(str(root) + "/") and full != root:
        raise HTTPException(500, "Invalid artifact storage path")
    return full


# ── List ─────────────────────────────────────────────────────────

@router.get("", response_model=list[ArtifactResponse])
async def list_artifacts(
    project_id: str,
    request: Request,
    kind: Optional[str] = Query(None, max_length=20),
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List artifacts for a project. Public, no auth."""
    check_ip_rate(_client_ip(request), "artifacts_browse", limit=120, window_seconds=60)
    await _project_or_404(project_id)

    db = get_db()
    query = "SELECT * FROM artifacts WHERE project_id = ?"
    params: list = [project_id]

    if kind:
        if kind not in ARTIFACT_KINDS:
            raise HTTPException(400, f"kind must be one of {ARTIFACT_KINDS}")
        query += " AND kind = ?"
        params.append(kind)
    if q:
        query += " AND (name LIKE ? OR description LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = await db.execute_fetchall(query, params)
    return [ArtifactResponse(**parse_artifact_row(dict(r))) for r in rows]


# ── Get metadata ─────────────────────────────────────────────────

@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(project_id: str, artifact_id: str, request: Request):
    check_ip_rate(_client_ip(request), "artifacts_browse", limit=120, window_seconds=60)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Artifact not found")
    return ArtifactResponse(**parse_artifact_row(dict(rows[0])))


# ── Get raw content ──────────────────────────────────────────────

@router.get("/{artifact_id}/content")
async def get_artifact_content(
    project_id: str,
    artifact_id: str,
    request: Request,
    download: bool = Query(False),
):
    """Serve the raw bytes. By default inline; with ?download=1 as attachment."""
    check_ip_rate(_client_ip(request), "artifacts_browse", limit=120, window_seconds=60)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Artifact not found")
    art = dict(rows[0])
    path = _resolve_storage_path(art["storage_path"])
    if not path.exists():
        raise HTTPException(410, "Artifact bytes are missing from storage")

    disposition = "attachment" if download else "inline"
    filename = art["slug"]
    return FileResponse(
        path,
        media_type=art["mime"],
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "X-Artifact-SHA256": art["sha256"],
        },
    )


# ── Create (JSON inline text) ────────────────────────────────────

@router.post("", response_model=ArtifactResponse, status_code=201)
async def create_artifact(
    project_id: str,
    body: ArtifactCreate,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Create an artifact from inline text content (JSON body)."""
    check_ip_rate(_client_ip(request), "artifacts_create", limit=30, window_seconds=60)
    await _require_project_write(project_id, agent["id"])

    check_content(body.name)
    check_content(body.description)
    check_content(body.content)
    _check_metadata(body.metadata)
    for tag in body.tags:
        check_content(tag)
    _validate_mime(body.mime)

    data = body.content.encode("utf-8")
    if len(data) > config.ARTIFACT_MAX_BYTES:
        raise HTTPException(
            413,
            f"Artifact exceeds max size ({config.ARTIFACT_MAX_BYTES} bytes)",
        )

    return await _insert_artifact(
        project_id=project_id,
        agent_id=agent["id"],
        name=body.name,
        description=body.description,
        kind=body.kind,
        mime=body.mime,
        data=data,
        metadata=body.metadata,
        tags=body.tags,
        parent_id=None,
    )


# ── Create (multipart upload for binaries) ───────────────────────

@router.post("/upload", response_model=ArtifactResponse, status_code=201)
async def upload_artifact(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    kind: str = Form("document"),
    tags: str = Form(""),
    agent: dict = Depends(get_current_agent),
):
    """Upload an artifact as multipart form-data. Good for binaries/images."""
    check_ip_rate(_client_ip(request), "artifacts_create", limit=30, window_seconds=60)
    await _require_project_write(project_id, agent["id"])

    if kind not in ARTIFACT_KINDS:
        raise HTTPException(400, f"kind must be one of {ARTIFACT_KINDS}")

    check_content(name)
    check_content(description)

    data = await file.read()
    if len(data) > config.ARTIFACT_MAX_BYTES:
        raise HTTPException(
            413,
            f"Artifact exceeds max size ({config.ARTIFACT_MAX_BYTES} bytes)",
        )
    if len(data) == 0:
        raise HTTPException(400, "Cannot upload empty file")

    mime = file.content_type or "application/octet-stream"
    _validate_mime(mime)

    # Text-ish mime: also screen bytes through content filter.
    if mime.startswith("text/") or mime in (
        "application/json",
        "application/xml",
        "application/yaml",
        "application/x-yaml",
    ):
        try:
            as_text = data.decode("utf-8")
            check_content(as_text)
        except UnicodeDecodeError:
            raise HTTPException(400, "Declared text mime but content is not valid UTF-8")

    tag_list = [t.strip()[:40] for t in tags.split(",") if t.strip()][:20]
    for tag in tag_list:
        check_content(tag)

    return await _insert_artifact(
        project_id=project_id,
        agent_id=agent["id"],
        name=name,
        description=description,
        kind=kind,
        mime=mime,
        data=data,
        metadata={},
        tags=tag_list,
        parent_id=None,
    )


# ── Update metadata ──────────────────────────────────────────────

@router.patch("/{artifact_id}", response_model=ArtifactResponse)
async def update_artifact(
    project_id: str,
    artifact_id: str,
    body: ArtifactUpdate,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Update artifact metadata. Creator or project owner only."""
    check_ip_rate(_client_ip(request), "artifacts_create", limit=30, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Artifact not found")
    art = dict(rows[0])

    await _check_creator_or_owner(project_id, art, agent["id"])

    updates, params = [], []
    if body.name is not None:
        check_content(body.name)
        new_slug = await _unique_slug(project_id, _slugify(body.name))
        updates.extend(["name = ?", "slug = ?"])
        params.extend([body.name, new_slug])
    if body.description is not None:
        check_content(body.description)
        updates.append("description = ?")
        params.append(body.description)
    if body.metadata is not None:
        _check_metadata(body.metadata)
        updates.append("metadata_json = ?")
        params.append(json.dumps(body.metadata))
    if body.tags is not None:
        cleaned = [t.strip()[:40] for t in body.tags if t.strip()][:20]
        for tag in cleaned:
            check_content(tag)
        updates.append("tags_json = ?")
        params.append(json.dumps(cleaned))

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')")
    params.append(artifact_id)

    await db.execute(
        f"UPDATE artifacts SET {', '.join(updates)} WHERE id = ?", params
    )
    await db.commit()

    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
    )
    return ArtifactResponse(**parse_artifact_row(dict(rows[0])))


# ── Delete ───────────────────────────────────────────────────────

@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(
    project_id: str,
    artifact_id: str,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Delete an artifact. Creator or project owner only. Removes bytes from disk."""
    check_ip_rate(_client_ip(request), "artifacts_create", limit=30, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Artifact not found")
    art = dict(rows[0])
    await _check_creator_or_owner(project_id, art, agent["id"])

    await db.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    await db.commit()

    # Best-effort byte cleanup; a missing file is not an error.
    try:
        path = _resolve_storage_path(art["storage_path"])
        if path.exists():
            path.unlink()
    except Exception:
        pass


# ── Fork ─────────────────────────────────────────────────────────

@router.post("/{artifact_id}/fork", response_model=ArtifactResponse, status_code=201)
async def fork_artifact(
    project_id: str,
    artifact_id: str,
    request: Request,
    target_project_id: str = Query(..., description="Destination project to fork into"),
    agent: dict = Depends(get_current_agent),
):
    """Copy an artifact into another project the caller can write to.

    The source artifact is untouched; the new row records `parent_id` so
    lineage is preserved.
    """
    check_ip_rate(_client_ip(request), "artifacts_create", limit=30, window_seconds=60)

    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
        (artifact_id, project_id),
    )
    if not rows:
        raise HTTPException(404, "Artifact not found")
    src = dict(rows[0])

    await _require_project_write(target_project_id, agent["id"])

    src_path = _resolve_storage_path(src["storage_path"])
    if not src_path.exists():
        raise HTTPException(410, "Source artifact bytes are missing from storage")
    data = src_path.read_bytes()

    return await _insert_artifact(
        project_id=target_project_id,
        agent_id=agent["id"],
        name=src["name"],
        description=src["description"],
        kind=src["kind"],
        mime=src["mime"],
        data=data,
        metadata=json.loads(src["metadata_json"]),
        tags=json.loads(src["tags_json"]),
        parent_id=src["id"],
    )


# ── Shared insert + permission helpers ───────────────────────────

async def _insert_artifact(
    *,
    project_id: str,
    agent_id: str,
    name: str,
    description: str,
    kind: str,
    mime: str,
    data: bytes,
    metadata: dict,
    tags: list[str],
    parent_id: Optional[str],
) -> ArtifactResponse:
    db = get_db()
    artifact_id = str(uuid.uuid4())
    sha256 = hashlib.sha256(data).hexdigest()
    slug = await _unique_slug(project_id, _slugify(name))
    storage_rel = _write_bytes(project_id, artifact_id, sha256, data)

    try:
        await db.execute(
            """INSERT INTO artifacts
               (id, project_id, name, slug, description, kind, mime,
                size_bytes, sha256, storage_path, metadata_json, tags_json,
                created_by, parent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id, project_id, name, slug, description, kind, mime,
                len(data), sha256, storage_rel,
                json.dumps(metadata), json.dumps(tags),
                agent_id, parent_id,
            ),
        )
        await db.commit()
    except Exception:
        # Rollback the blob write if DB insert fails.
        try:
            _resolve_storage_path(storage_rel).unlink()
        except Exception:
            pass
        raise

    rows = await db.execute_fetchall(
        "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
    )
    return ArtifactResponse(**parse_artifact_row(dict(rows[0])))


async def _check_creator_or_owner(project_id: str, artifact: dict, agent_id: str) -> None:
    if artifact["created_by"] == agent_id:
        return
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT role FROM project_members WHERE project_id = ? AND agent_id = ?",
        (project_id, agent_id),
    )
    if rows and rows[0]["role"] == "owner":
        return
    raise HTTPException(403, "Only the artifact's creator or the project owner can do that")
