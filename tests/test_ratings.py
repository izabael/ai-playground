"""Phase 6C — Tier 3 community moderation tests.

Covers: owner toggle, rate/unrate, self-rating prevention, flag workflow,
moderator queue (token gating), flag review, rating stats on project list.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db, close_db
from app.safety.ratelimit import _reset_for_tests


MOD_TOKEN = "test-moderator-token-FAKE"


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
    # Drop the rater-age floor so tests can run without sleeping 24h
    monkeypatch.setattr("app.config.RATING_MIN_AGENT_AGE_SECONDS", 0)
    # Wire a moderator token for queue tests
    monkeypatch.setattr("app.config.MODERATOR_TOKEN", MOD_TOKEN)
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
async def carol(client):
    return await _register(client, "Carol")


@pytest_asyncio.fixture
async def project(client, alice):
    resp = await client.post(
        "/projects",
        json={"name": "Open Telescope", "description": "community observatory"},
        headers=alice["auth"],
    )
    assert resp.status_code == 201
    return resp.json()


async def _enable_ratings(client, project_id, owner_auth, enabled=True):
    resp = await client.post(
        f"/projects/{project_id}/ratings-enabled",
        json={"enabled": enabled},
        headers=owner_auth,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Owner toggle ────────────────────────────────────────────────

class TestRatingsToggle:
    @pytest.mark.asyncio
    async def test_ratings_default_disabled(self, client, project):
        resp = await client.get(f"/projects/{project['id']}")
        assert resp.status_code == 200
        assert resp.json()["ratings_enabled"] is False

    @pytest.mark.asyncio
    async def test_owner_can_enable(self, client, alice, project):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        resp = await client.get(f"/projects/{project['id']}")
        assert resp.json()["ratings_enabled"] is True

    @pytest.mark.asyncio
    async def test_non_owner_cannot_toggle(self, client, bob, project):
        resp = await client.post(
            f"/projects/{project['id']}/ratings-enabled",
            json={"enabled": True},
            headers=bob["auth"],
        )
        assert resp.status_code == 403


# ── Rate ────────────────────────────────────────────────────────

class TestRate:
    @pytest.mark.asyncio
    async def test_rate_when_enabled(self, client, alice, bob, project):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        resp = await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 5, "note": "genuinely useful observatory"},
            headers=bob["auth"],
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["score"] == 5
        assert data["rater_agent_id"] == bob["id"]
        assert data["rater_name"] == "Bob"

    @pytest.mark.asyncio
    async def test_rate_when_disabled_rejected(self, client, bob, project):
        resp = await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 5},
            headers=bob["auth"],
        )
        assert resp.status_code == 400
        assert "not enabled" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_owner_cannot_rate_own_project(self, client, alice, project):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        resp = await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 5},
            headers=alice["auth"],
        )
        assert resp.status_code == 400
        assert "own project" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rating_upsert(self, client, alice, bob, project):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        r1 = await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 3, "note": "decent"},
            headers=bob["auth"],
        )
        r2 = await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 5, "note": "grew on me"},
            headers=bob["auth"],
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]  # upsert → same row
        assert r2.json()["score"] == 5

        # Only one rating row for bob on this project
        resp = await client.get(f"/projects/{project['id']}/ratings")
        rows = resp.json()
        assert len([r for r in rows if r["rater_agent_id"] == bob["id"]]) == 1

    @pytest.mark.asyncio
    async def test_rating_stats_on_project_response(
        self, client, alice, bob, carol, project
    ):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 5},
            headers=bob["auth"],
        )
        await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 3},
            headers=carol["auth"],
        )
        resp = await client.get(f"/projects/{project['id']}")
        data = resp.json()
        assert data["rating_count"] == 2
        assert data["avg_rating"] == 4.0

    @pytest.mark.asyncio
    async def test_delete_my_rating(self, client, alice, bob, project):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 4},
            headers=bob["auth"],
        )
        resp = await client.delete(
            f"/projects/{project['id']}/ratings/mine",
            headers=bob["auth"],
        )
        assert resp.status_code == 204
        resp = await client.get(f"/projects/{project['id']}/ratings")
        assert len(resp.json()) == 0


# ── Flag ────────────────────────────────────────────────────────

class TestFlag:
    @pytest.mark.asyncio
    async def test_flag_creates_open_report(self, client, bob, project):
        resp = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "concerning", "detail": "this looks like a scam"},
            headers=bob["auth"],
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "open"
        assert data["category"] == "concerning"
        assert data["reporter_name"] == "Bob"
        assert data["project_name"] == "Open Telescope"

    @pytest.mark.asyncio
    async def test_flag_does_not_require_ratings_enabled(self, client, bob, project):
        # Flags work even when ratings are off — otherwise abuse can't be reported
        resp = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam"},
            headers=bob["auth"],
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_cannot_flag_own_project(self, client, alice, project):
        resp = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam"},
            headers=alice["auth"],
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_category_rejected(self, client, bob, project):
        resp = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "everything-i-hate"},
            headers=bob["auth"],
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_flag_count_on_project(self, client, bob, carol, project):
        await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "concerning"},
            headers=bob["auth"],
        )
        await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam"},
            headers=carol["auth"],
        )
        resp = await client.get(f"/projects/{project['id']}")
        assert resp.json()["flag_count"] == 2

    @pytest.mark.asyncio
    async def test_owner_can_see_flags(self, client, alice, bob, project):
        await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "concerning", "detail": "uh oh"},
            headers=bob["auth"],
        )
        resp = await client.get(
            f"/projects/{project['id']}/flags",
            headers=alice["auth"],
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["detail"] == "uh oh"

    @pytest.mark.asyncio
    async def test_non_owner_cannot_see_flags(self, client, bob, carol, project):
        await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "concerning"},
            headers=bob["auth"],
        )
        resp = await client.get(
            f"/projects/{project['id']}/flags",
            headers=carol["auth"],
        )
        assert resp.status_code == 403


# ── Moderator queue ─────────────────────────────────────────────

class TestModerationQueue:
    @pytest.mark.asyncio
    async def test_queue_requires_token(self, client):
        resp = await client.get("/moderation/queue")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_queue_rejects_wrong_token(self, client):
        resp = await client.get(
            "/moderation/queue",
            headers={"X-Moderator-Token": "wrong"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_queue_unconfigured_returns_503(self, client, monkeypatch):
        monkeypatch.setattr("app.config.MODERATOR_TOKEN", "")
        resp = await client.get(
            "/moderation/queue",
            headers={"X-Moderator-Token": "anything"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_queue_lists_open_flags(self, client, bob, project):
        await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam", "detail": "please look"},
            headers=bob["auth"],
        )
        resp = await client.get(
            "/moderation/queue",
            headers={"X-Moderator-Token": MOD_TOKEN},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["status"] == "open"
        assert rows[0]["project_name"] == "Open Telescope"

    @pytest.mark.asyncio
    async def test_moderator_can_dismiss_flag(self, client, bob, project):
        r = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam"},
            headers=bob["auth"],
        )
        flag_id = r.json()["id"]
        resp = await client.patch(
            f"/moderation/flags/{flag_id}",
            json={"status": "dismissed", "resolution_note": "not actually spam"},
            headers={"X-Moderator-Token": MOD_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

        # Project flag count (open+reviewing) should now be 0
        resp = await client.get(f"/projects/{project['id']}")
        assert resp.json()["flag_count"] == 0

    @pytest.mark.asyncio
    async def test_moderator_can_uphold_flag(self, client, bob, project):
        r = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "concerning"},
            headers=bob["auth"],
        )
        flag_id = r.json()["id"]
        resp = await client.patch(
            f"/moderation/flags/{flag_id}",
            json={"status": "upheld", "resolution_note": "owner warned"},
            headers={"X-Moderator-Token": MOD_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "upheld"

    @pytest.mark.asyncio
    async def test_queue_status_filter(self, client, bob, project):
        r = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam"},
            headers=bob["auth"],
        )
        flag_id = r.json()["id"]
        await client.patch(
            f"/moderation/flags/{flag_id}",
            json={"status": "dismissed"},
            headers={"X-Moderator-Token": MOD_TOKEN},
        )
        # Default ?status=open should be empty
        resp = await client.get(
            "/moderation/queue",
            headers={"X-Moderator-Token": MOD_TOKEN},
        )
        assert len(resp.json()) == 0
        # ?status=dismissed should show it
        resp = await client.get(
            "/moderation/queue?status=dismissed",
            headers={"X-Moderator-Token": MOD_TOKEN},
        )
        assert len(resp.json()) == 1


# ── Age floor (anti-sybil) ──────────────────────────────────────

class TestRaterAge:
    @pytest.mark.asyncio
    async def test_age_floor_blocks_new_agents(self, client, alice, project, monkeypatch):
        await _enable_ratings(client, project["id"], alice["auth"], True)
        # Set age floor to 1 hour — alice was just created
        monkeypatch.setattr("app.config.RATING_MIN_AGENT_AGE_SECONDS", 3600)
        bob = await _register(client, "NewBob")
        resp = await client.post(
            f"/projects/{project['id']}/ratings",
            json={"score": 5},
            headers=bob["auth"],
        )
        assert resp.status_code == 403
        assert "too new" in resp.json()["detail"].lower()

        # Flags are also age-gated
        resp = await client.post(
            f"/projects/{project['id']}/flags",
            json={"category": "spam"},
            headers=bob["auth"],
        )
        assert resp.status_code == 403
