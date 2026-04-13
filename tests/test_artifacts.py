"""Phase 5A — Artifact Gallery: CRUD, upload, fork, permissions, safety."""

import base64
import io
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db, close_db
from app.safety.ratelimit import _reset_for_tests


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    storage = tmp_path / "artifacts"
    storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.config.DB_PATH", db_path)
    monkeypatch.setattr("app.database.DB_PATH", db_path)
    monkeypatch.setattr("app.config.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.config.ARTIFACT_STORAGE_DIR", storage)
    monkeypatch.setattr("app.routers.artifacts.config.ARTIFACT_STORAGE_DIR", storage)
    await init_db()
    _reset_for_tests()
    yield
    await close_db()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _register(client, name="Alice"):
    resp = await client.post("/agents", json={
        "name": name, "provider": "test",
        "purpose": "research", "tos_accepted": True, "age_confirmed": True,
    })
    assert resp.status_code == 201
    data = resp.json()
    return {"id": data["id"], "auth": {"Authorization": f"Bearer {data['auth_token']}"}}


@pytest_asyncio.fixture
async def alice(client):
    return await _register(client, "Alice")


@pytest_asyncio.fixture
async def bob(client):
    return await _register(client, "Bob")


@pytest_asyncio.fixture
async def project(client, alice):
    resp = await client.post("/projects", json={
        "name": "Poem Engine",
        "description": "Make verses together",
    }, headers=alice["auth"])
    assert resp.status_code == 201
    return resp.json()


# ── Create + list ───────────────────────────────────────────────

class TestArtifactCreate:
    @pytest.mark.asyncio
    async def test_create_text_artifact(self, client, alice, project):
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={
                "name": "haiku.txt",
                "description": "Three lines",
                "kind": "document",
                "mime": "text/plain",
                "content": "old pond —\na frog jumps in\nthe sound of water",
                "tags": ["poem", "basho"],
            },
            headers=alice["auth"],
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["name"] == "haiku.txt"
        assert data["slug"] == "haiku-txt"
        assert data["kind"] == "document"
        assert data["size_bytes"] == len(
            "old pond —\na frog jumps in\nthe sound of water".encode("utf-8")
        )
        assert data["sha256"]
        assert data["tags"] == ["poem", "basho"]
        assert data["created_by"] == alice["id"]

    @pytest.mark.asyncio
    async def test_create_code_artifact(self, client, alice, project):
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={
                "name": "main.py",
                "kind": "code",
                "mime": "text/x-python",
                "content": "def hello():\n    return 'world'\n",
                "metadata": {"language": "python", "lines": 2},
            },
            headers=alice["auth"],
        )
        assert resp.status_code == 201
        assert resp.json()["metadata"] == {"language": "python", "lines": 2}

    @pytest.mark.asyncio
    async def test_create_requires_membership(self, client, bob, project):
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "sneak.txt", "content": "x", "kind": "note"},
            headers=bob["auth"],
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_kind_rejected(self, client, alice, project):
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "x", "content": "y", "kind": "malware"},
            headers=alice["auth"],
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unsupported_mime_rejected(self, client, alice, project):
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={
                "name": "evil.bin",
                "content": "bytes",
                "kind": "data",
                "mime": "application/x-msdownload",
            },
            headers=alice["auth"],
        )
        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_oversize_rejected(self, client, alice, project, monkeypatch):
        monkeypatch.setattr("app.config.ARTIFACT_MAX_BYTES", 100)
        monkeypatch.setattr("app.routers.artifacts.config.ARTIFACT_MAX_BYTES", 100)
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "big.txt", "content": "x" * 500, "kind": "note"},
            headers=alice["auth"],
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_slug_collision_is_unique(self, client, alice, project):
        for _ in range(3):
            resp = await client.post(
                f"/projects/{project['id']}/artifacts",
                json={"name": "notes", "content": "x", "kind": "note"},
                headers=alice["auth"],
            )
            assert resp.status_code == 201
        lst = await client.get(f"/projects/{project['id']}/artifacts")
        slugs = sorted(a["slug"] for a in lst.json())
        assert slugs == ["notes", "notes-2", "notes-3"]


class TestArtifactList:
    @pytest.mark.asyncio
    async def test_list_public(self, client, alice, bob, project):
        await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "one.txt", "content": "one", "kind": "note"},
            headers=alice["auth"],
        )
        # Bob (not a member) can still list.
        resp = await client.get(f"/projects/{project['id']}/artifacts")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_filter_by_kind(self, client, alice, project):
        for kind, name in [("code", "a.py"), ("note", "b"), ("code", "c.py")]:
            await client.post(
                f"/projects/{project['id']}/artifacts",
                json={"name": name, "content": "x", "kind": kind,
                      "mime": "text/plain"},
                headers=alice["auth"],
            )
        r = await client.get(f"/projects/{project['id']}/artifacts?kind=code")
        assert r.status_code == 200
        assert len(r.json()) == 2
        assert all(a["kind"] == "code" for a in r.json())

    @pytest.mark.asyncio
    async def test_list_missing_project_404(self, client):
        resp = await client.get("/projects/nope/artifacts")
        assert resp.status_code == 404


class TestArtifactContent:
    @pytest.mark.asyncio
    async def test_fetch_raw(self, client, alice, project):
        text = "def greet():\n    return 'hi'"
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "greet.py", "content": text, "kind": "code",
                  "mime": "text/x-python"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        raw = await client.get(
            f"/projects/{project['id']}/artifacts/{aid}/content"
        )
        assert raw.status_code == 200
        assert raw.text == text
        assert "inline" in raw.headers["content-disposition"]
        assert raw.headers["x-artifact-sha256"]

    @pytest.mark.asyncio
    async def test_fetch_download_flag(self, client, alice, project):
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "x.txt", "content": "hi", "kind": "note"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        raw = await client.get(
            f"/projects/{project['id']}/artifacts/{aid}/content?download=1"
        )
        assert raw.status_code == 200
        assert "attachment" in raw.headers["content-disposition"]


class TestArtifactUpdateDelete:
    @pytest.mark.asyncio
    async def test_patch_by_creator(self, client, alice, project):
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "draft", "content": "v1", "kind": "note"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        upd = await client.patch(
            f"/projects/{project['id']}/artifacts/{aid}",
            json={"description": "Updated!", "tags": ["v1", "draft"]},
            headers=alice["auth"],
        )
        assert upd.status_code == 200
        assert upd.json()["description"] == "Updated!"
        assert upd.json()["tags"] == ["v1", "draft"]

    @pytest.mark.asyncio
    async def test_patch_forbidden_for_non_member(self, client, alice, bob, project):
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "secret", "content": "x", "kind": "note"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        bad = await client.patch(
            f"/projects/{project['id']}/artifacts/{aid}",
            json={"description": "hacked"},
            headers=bob["auth"],
        )
        assert bad.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_by_creator_removes_bytes(self, client, alice, project):
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "ephemeral", "content": "x", "kind": "note"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        # Make sure content exists
        raw = await client.get(f"/projects/{project['id']}/artifacts/{aid}/content")
        assert raw.status_code == 200

        delete = await client.delete(
            f"/projects/{project['id']}/artifacts/{aid}",
            headers=alice["auth"],
        )
        assert delete.status_code == 204
        gone = await client.get(f"/projects/{project['id']}/artifacts/{aid}")
        assert gone.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_forbidden_for_stranger(self, client, alice, bob, project):
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "keep", "content": "x", "kind": "note"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        bad = await client.delete(
            f"/projects/{project['id']}/artifacts/{aid}",
            headers=bob["auth"],
        )
        assert bad.status_code == 403


class TestArtifactFork:
    @pytest.mark.asyncio
    async def test_fork_into_other_project(self, client, alice, project):
        # Alice creates a second project and the source artifact.
        p2 = await client.post("/projects", json={"name": "Twin"}, headers=alice["auth"])
        target = p2.json()["id"]

        src = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "base", "content": "hello", "kind": "note"},
            headers=alice["auth"],
        )
        aid = src.json()["id"]

        fork = await client.post(
            f"/projects/{project['id']}/artifacts/{aid}/fork",
            params={"target_project_id": target},
            headers=alice["auth"],
        )
        assert fork.status_code == 201
        forked = fork.json()
        assert forked["project_id"] == target
        assert forked["parent_id"] == aid
        assert forked["sha256"] == src.json()["sha256"]
        # Forked bytes match.
        raw = await client.get(f"/projects/{target}/artifacts/{forked['id']}/content")
        assert raw.text == "hello"

    @pytest.mark.asyncio
    async def test_fork_forbidden_without_target_membership(self, client, alice, bob, project):
        # Bob creates a separate project but tries to fork into Alice's.
        bob_proj = await client.post("/projects", json={"name": "Bob's place"}, headers=bob["auth"])

        src = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "thing", "content": "x", "kind": "note"},
            headers=alice["auth"],
        )
        aid = src.json()["id"]

        # Bob tries to fork Alice's artifact into Alice's project (not a member).
        bad = await client.post(
            f"/projects/{project['id']}/artifacts/{aid}/fork",
            params={"target_project_id": project["id"]},
            headers=bob["auth"],
        )
        assert bad.status_code == 403


class TestArtifactUpload:
    @pytest.mark.asyncio
    async def test_multipart_upload(self, client, alice, project):
        data = b"PNG\x89fake image bytes for tests"
        files = {"file": ("fake.png", io.BytesIO(data), "image/png")}
        form = {
            "name": "Test Image",
            "description": "A screenshot",
            "kind": "image",
            "tags": "screenshot,debug",
        }
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/upload",
            data=form,
            files=files,
            headers=alice["auth"],
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mime"] == "image/png"
        assert body["size_bytes"] == len(data)
        assert body["tags"] == ["screenshot", "debug"]
        # Fetch bytes back and verify hash.
        raw = await client.get(
            f"/projects/{project['id']}/artifacts/{body['id']}/content"
        )
        assert raw.content == data

    @pytest.mark.asyncio
    async def test_empty_upload_rejected(self, client, alice, project):
        files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/upload",
            data={"name": "empty", "kind": "note"},
            files=files,
            headers=alice["auth"],
        )
        assert resp.status_code == 400


class TestArtifactGalleryHTML:
    @pytest.mark.asyncio
    async def test_gallery_index_renders(self, client, alice, project):
        await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "First", "content": "hello", "kind": "note",
                  "description": "A first note"},
            headers=alice["auth"],
        )
        r = await client.get(f"/workshop/projects/{project['id']}/artifacts")
        assert r.status_code == 200
        body = r.text
        assert "Poem Engine · Gallery" in body
        assert "First" in body
        assert "A first note" in body

    @pytest.mark.asyncio
    async def test_gallery_detail_inline_preview(self, client, alice, project):
        content = "def foo():\n    return 42\n"
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "foo.py", "content": content, "kind": "code",
                  "mime": "text/x-python"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        page = await client.get(
            f"/workshop/projects/{project['id']}/artifacts/{aid}"
        )
        assert page.status_code == 200
        body = page.text
        assert "foo.py" in body
        # Preview renders (HTML-escaped).
        assert "def foo()" in body
        assert "return 42" in body
        # Raw view + download buttons wired.
        assert f'/projects/{project["id"]}/artifacts/{aid}/content' in body
        assert "download=1" in body

    @pytest.mark.asyncio
    async def test_gallery_detail_404(self, client, project):
        r = await client.get(
            f"/workshop/projects/{project['id']}/artifacts/nope"
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_gallery_project_404(self, client):
        r = await client.get("/workshop/projects/nope/artifacts")
        assert r.status_code == 404


class TestArtifactSecurityHardening:
    """Regression tests for the H-1/H-2/M-2 findings from the 5A audit."""

    @pytest.mark.asyncio
    async def test_metadata_is_content_filtered(self, client, alice, project):
        # Tier 1 illegal content filter should cover `metadata` values —
        # not just name/description/content.
        from app.safety import FloorViolation
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={
                "name": "sneaky",
                "content": "ok",
                "kind": "note",
                "metadata": {"note": "csam"},
            },
            headers=alice["auth"],
        )
        # Floor handler returns 400 with category info.
        assert resp.status_code == 400
        assert resp.json().get("tier") == "platform_floor"

    @pytest.mark.asyncio
    async def test_tags_are_content_filtered_on_create(self, client, alice, project):
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={
                "name": "clean",
                "content": "ok",
                "kind": "note",
                "tags": ["csam"],
            },
            headers=alice["auth"],
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_metadata_is_content_filtered_on_update(self, client, alice, project):
        r = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={"name": "ok", "content": "x", "kind": "note"},
            headers=alice["auth"],
        )
        aid = r.json()["id"]
        bad = await client.patch(
            f"/projects/{project['id']}/artifacts/{aid}",
            json={"metadata": {"hidden": "csam"}},
            headers=alice["auth"],
        )
        assert bad.status_code == 400


class TestPersonaColorHardening:
    """M-1: persona color must reject non-hex values so templates can't be
    used to emit arbitrary CSS (passive-beacon tracking via url())."""

    @pytest.mark.asyncio
    async def test_invalid_color_is_dropped(self, client):
        from app.a2a.persona import PersonaAesthetic

        # Direct model test — validator drops non-hex.
        a = PersonaAesthetic(color="red; background:url(https://attacker.example)")
        assert a.color is None

        # Valid hex passes through unchanged.
        b = PersonaAesthetic(color="#7b68ee")
        assert b.color == "#7b68ee"

        c = PersonaAesthetic(color="#fff")
        assert c.color == "#fff"

    @pytest.mark.asyncio
    async def test_persona_create_sanitizes_color(self, client):
        # Register an agent so we can create a persona template.
        reg = await client.post("/agents", json={
            "name": "Designer", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        auth = {"Authorization": f"Bearer {reg.json()['auth_token']}"}

        resp = await client.post(
            "/personas",
            json={
                "name": "Color Test",
                "description": "Testing color validator",
                "archetype": "test",
                "persona": {
                    "aesthetic": {
                        "color": "red; background:url(https://attacker.example/x.gif)",
                        "motif": "ok",
                    },
                },
            },
            headers=auth,
        )
        assert resp.status_code == 201
        # Color silently dropped, other fields preserved.
        aesthetic = resp.json()["persona"]["aesthetic"]
        assert aesthetic.get("color") is None
        assert aesthetic.get("motif") == "ok"
