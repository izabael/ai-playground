"""Phase 5B — Human Bridge dashboard tests."""

import pytest
import pytest_asyncio
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


async def _register(client, name):
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
async def hidden(client):
    return await _register(client, "_smoke_test_agent")


# ── Dashboard ────────────────────────────────────────────────────

class TestDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_renders_on_empty_instance(self, client):
        resp = await client.get("/bridge")
        assert resp.status_code == 200
        html = resp.text
        assert "Human Bridge" in html
        assert "agents online" in html
        assert "Highlight" in html

    @pytest.mark.asyncio
    async def test_dashboard_shows_stats(self, client, alice, bob):
        resp = await client.get("/bridge")
        assert resp.status_code == 200
        html = resp.text
        # Two public agents registered → stats block should reflect this.
        assert ">2<" in html or "2</div>" in html or "2 " in html

    @pytest.mark.asyncio
    async def test_dashboard_hides_internal_agents(self, client, alice, hidden):
        resp = await client.get("/bridge")
        assert resp.status_code == 200
        assert "Alice" in resp.text
        assert "_smoke_test_agent" not in resp.text

    @pytest.mark.asyncio
    async def test_dashboard_shows_recent_public_messages(self, client, alice):
        # Join a public channel and post
        jr = await client.post("/channels/%23lobby/join", headers=alice["auth"])
        assert jr.status_code == 204
        mr = await client.post(
            "/messages",
            json={"to": "#lobby", "content": "this is a public message from alice"},
            headers=alice["auth"],
        )
        assert mr.status_code == 201
        resp = await client.get("/bridge")
        assert resp.status_code == 200
        assert "public message from alice" in resp.text
        assert "Alice" in resp.text


# ── Agent profile ────────────────────────────────────────────────

class TestAgentProfile:
    @pytest.mark.asyncio
    async def test_profile_renders(self, client, alice):
        resp = await client.get(f"/bridge/agents/{alice['id']}")
        assert resp.status_code == 200
        assert "Alice" in resp.text
        assert "Projects" in resp.text
        assert "Artifacts" in resp.text

    @pytest.mark.asyncio
    async def test_profile_404_on_unknown(self, client):
        resp = await client.get("/bridge/agents/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_profile_404_on_hidden_internal(self, client, hidden):
        resp = await client.get(f"/bridge/agents/{hidden['id']}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_profile_lists_projects_and_artifacts(self, client, alice):
        proj = await client.post(
            "/projects",
            json={"name": "Moonlit Lab", "description": "nocturnal research"},
            headers=alice["auth"],
        )
        assert proj.status_code == 201
        project_id = proj.json()["id"]

        art = await client.post(
            f"/projects/{project_id}/artifacts",
            json={
                "name": "notes.md",
                "kind": "note",
                "mime": "text/markdown",
                "content": "observations from the moon",
            },
            headers=alice["auth"],
        )
        assert art.status_code == 201

        resp = await client.get(f"/bridge/agents/{alice['id']}")
        assert resp.status_code == 200
        assert "Moonlit Lab" in resp.text
        assert "notes.md" in resp.text


# ── Teaching hub ─────────────────────────────────────────────────

class TestTeachingHub:
    @pytest.mark.asyncio
    async def test_teaching_renders(self, client):
        resp = await client.get("/bridge/teaching")
        assert resp.status_code == 200
        html = resp.text
        assert "Teaching Hub" in html
        assert "/workshop" in html
        assert "/bridge/highlights" in html


# ── Highlights page ─────────────────────────────────────────────

class TestHighlights:
    @pytest.mark.asyncio
    async def test_highlights_empty_state(self, client):
        resp = await client.get("/bridge/highlights")
        assert resp.status_code == 200
        assert "Highlight Reel" in resp.text
        assert "No highlights yet" in resp.text

    @pytest.mark.asyncio
    async def test_highlights_filters_short_messages(self, client, alice):
        jr = await client.post("/channels/%23lobby/join", headers=alice["auth"])
        assert jr.status_code == 204
        # Short — should be filtered out
        await client.post(
            "/messages",
            json={"to": "#lobby", "content": "hi"},
            headers=alice["auth"],
        )
        # Long — should show up
        long_body = (
            "The federation question is really a question about trust — how do "
            "two instances confirm each other's identity without a central "
            "authority holding the keys? That's where a shared handshake becomes "
            "useful."
        )
        assert len(long_body) >= 120
        await client.post(
            "/messages",
            json={"to": "#lobby", "content": long_body},
            headers=alice["auth"],
        )
        resp = await client.get("/bridge/highlights")
        assert resp.status_code == 200
        assert "federation question" in resp.text
        # Short message must NOT be in the highlight reel
        assert ">hi<" not in resp.text
