"""Phase 4A — Project Workspaces: create, list, join, update, archive."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db, close_db
from app.safety.ratelimit import _reset_for_tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("app.config.DB_PATH", db_path)
    monkeypatch.setattr("app.database.DB_PATH", db_path)
    monkeypatch.setattr("app.config.SCHEDULER_ENABLED", False)
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


# ---------------------------------------------------------------------------
# TestProjectCreate
# ---------------------------------------------------------------------------

class TestProjectCreate:
    @pytest.mark.asyncio
    async def test_create_basic(self, client, alice):
        resp = await client.post("/projects", json={
            "name": "Build a poem generator",
            "description": "Collaborative poetry engine",
        }, headers=alice["auth"])
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Build a poem generator"
        assert data["status"] == "planning"
        assert data["created_by"] == alice["id"]
        assert data["channel_id"] is not None
        assert data["member_count"] == 1

    @pytest.mark.asyncio
    async def test_create_with_skills(self, client, alice):
        resp = await client.post("/projects", json={
            "name": "Data pipeline",
            "skills_needed": ["python", "data-viz", "sql"],
        }, headers=alice["auth"])
        assert resp.status_code == 201
        assert set(resp.json()["skills_needed"]) == {"python", "data-viz", "sql"}

    @pytest.mark.asyncio
    async def test_create_auto_creates_channel(self, client, alice):
        resp = await client.post("/projects", json={"name": "My Cool Project"},
                                  headers=alice["auth"])
        assert resp.status_code == 201
        channel_id = resp.json()["channel_id"]

        # Verify channel was created and Alice is a member
        channels = await client.get("/channels", headers=alice["auth"])
        channel_names = [c["name"] for c in channels.json()]
        assert "#project-my-cool-project" in channel_names

    @pytest.mark.asyncio
    async def test_create_requires_auth(self, client):
        resp = await client.post("/projects", json={"name": "No auth"})
        assert resp.status_code in (401, 422)  # 422 when header is absent (FastAPI rejects before auth)

    @pytest.mark.asyncio
    async def test_create_invalid_status(self, client, alice):
        resp = await client.post("/projects", json={
            "name": "Bad status",
            "status": "nonsense",
        }, headers=alice["auth"])
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestProjectList
# ---------------------------------------------------------------------------

class TestProjectList:
    @pytest_asyncio.fixture(autouse=True)
    async def seed_projects(self, client, alice, bob):
        await client.post("/projects", json={
            "name": "Alpha", "status": "planning",
            "skills_needed": ["python"],
        }, headers=alice["auth"])
        await client.post("/projects", json={
            "name": "Beta", "status": "active",
            "skills_needed": ["rust", "systems"],
        }, headers=bob["auth"])
        await client.post("/projects", json={
            "name": "Gamma", "status": "completed",
        }, headers=alice["auth"])

    @pytest.mark.asyncio
    async def test_list_excludes_archived_by_default(self, client, alice):
        # Archive Gamma
        gamma_id = next(
            p["id"] for p in (await client.get("/projects")).json()
            if p["name"] == "Gamma"
        )
        # Mark as archived via update (owner = alice)
        await client.put(f"/projects/{gamma_id}", json={"status": "archived"},
                          headers=alice["auth"])
        resp = await client.get("/projects")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()]
        assert "Gamma" not in names  # archived hidden
        assert "Alpha" in names
        assert "Beta" in names

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, client):
        resp = await client.get("/projects?status=active")
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["status"] == "active" for p in data)
        assert any(p["name"] == "Beta" for p in data)

    @pytest.mark.asyncio
    async def test_list_filter_by_skill(self, client):
        resp = await client.get("/projects?skill=python")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()]
        assert "Alpha" in names
        assert "Beta" not in names

    @pytest.mark.asyncio
    async def test_list_search(self, client):
        resp = await client.get("/projects?q=alph")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()]
        assert "Alpha" in names
        assert "Beta" not in names

    @pytest.mark.asyncio
    async def test_get_single(self, client):
        projects = (await client.get("/projects")).json()
        pid = projects[0]["id"]
        resp = await client.get(f"/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == pid

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, client):
        resp = await client.get("/projects/does-not-exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestProjectJoin
# ---------------------------------------------------------------------------

class TestProjectJoin:
    @pytest.mark.asyncio
    async def test_join_adds_member(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Collab"},
                                    headers=alice["auth"])
        pid = create.json()["id"]

        join = await client.post(f"/projects/{pid}/join", headers=bob["auth"])
        assert join.status_code == 204

        members = await client.get(f"/projects/{pid}/members")
        assert members.status_code == 200
        agent_ids = [m["agent_id"] for m in members.json()]
        assert alice["id"] in agent_ids
        assert bob["id"] in agent_ids

    @pytest.mark.asyncio
    async def test_join_idempotent(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Idempotent"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        await client.post(f"/projects/{pid}/join", headers=bob["auth"])
        resp2 = await client.post(f"/projects/{pid}/join", headers=bob["auth"])
        assert resp2.status_code == 204  # no error on second join

        members = await client.get(f"/projects/{pid}/members")
        bob_entries = [m for m in members.json() if m["agent_id"] == bob["id"]]
        assert len(bob_entries) == 1  # exactly one row

    @pytest.mark.asyncio
    async def test_join_also_joins_channel(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Chan Join"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        await client.post(f"/projects/{pid}/join", headers=bob["auth"])

        # Bob should now be a member of the project channel
        channels = await client.get("/channels", headers=bob["auth"])
        channel_names = [c["name"] for c in channels.json()]
        assert "#project-chan-join" in channel_names

    @pytest.mark.asyncio
    async def test_join_archived_rejected(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Archived"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        await client.delete(f"/projects/{pid}", headers=alice["auth"])

        resp = await client.post(f"/projects/{pid}/join", headers=bob["auth"])
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_join_requires_auth(self, client, alice):
        create = await client.post("/projects", json={"name": "Auth required"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        resp = await client.post(f"/projects/{pid}/join")
        assert resp.status_code in (401, 422)  # 422 when header is absent (FastAPI rejects before auth)


# ---------------------------------------------------------------------------
# TestProjectUpdate
# ---------------------------------------------------------------------------

class TestProjectUpdate:
    @pytest.mark.asyncio
    async def test_owner_can_update(self, client, alice):
        create = await client.post("/projects", json={"name": "Draft"},
                                    headers=alice["auth"])
        pid = create.json()["id"]

        resp = await client.put(f"/projects/{pid}", json={
            "name": "Polished",
            "status": "active",
            "skills_needed": ["ml", "poetry"],
        }, headers=alice["auth"])
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Polished"
        assert data["status"] == "active"
        assert set(data["skills_needed"]) == {"ml", "poetry"}

    @pytest.mark.asyncio
    async def test_non_owner_cannot_update(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Alice's"},
                                    headers=alice["auth"])
        pid = create.json()["id"]

        resp = await client.put(f"/projects/{pid}", json={"name": "Bob's"},
                                  headers=bob["auth"])
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_contributor_cannot_update(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Shared"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        await client.post(f"/projects/{pid}/join", headers=bob["auth"])

        resp = await client.put(f"/projects/{pid}", json={"name": "Hijacked"},
                                  headers=bob["auth"])
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_update_rejected(self, client, alice):
        create = await client.post("/projects", json={"name": "NoOp"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        resp = await client.put(f"/projects/{pid}", json={}, headers=alice["auth"])
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestProjectArchive
# ---------------------------------------------------------------------------

class TestProjectArchive:
    @pytest.mark.asyncio
    async def test_owner_can_archive(self, client, alice):
        create = await client.post("/projects", json={"name": "Sunset"},
                                    headers=alice["auth"])
        pid = create.json()["id"]

        resp = await client.delete(f"/projects/{pid}", headers=alice["auth"])
        assert resp.status_code == 204

        # Should still be retrievable but archived
        detail = await client.get(f"/projects/{pid}")
        assert detail.json()["status"] == "archived"

    @pytest.mark.asyncio
    async def test_non_owner_cannot_archive(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Protected"},
                                    headers=alice["auth"])
        pid = create.json()["id"]

        resp = await client.delete(f"/projects/{pid}", headers=bob["auth"])
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_members_see_owner_role(self, client, alice, bob):
        create = await client.post("/projects", json={"name": "Roles"},
                                    headers=alice["auth"])
        pid = create.json()["id"]
        await client.post(f"/projects/{pid}/join", headers=bob["auth"])

        members = await client.get(f"/projects/{pid}/members")
        by_id = {m["agent_id"]: m for m in members.json()}
        assert by_id[alice["id"]]["role"] == "owner"
        assert by_id[bob["id"]]["role"] == "contributor"
