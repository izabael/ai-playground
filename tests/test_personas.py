"""Phase 2B — Persona templates: CRUD, starters, teaching, export, safety."""

import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db, close_db, get_db
from app.safety.ratelimit import _reset_for_tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    """Use a fresh in-memory-like DB per test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("app.config.DB_PATH", db_path)
    monkeypatch.setattr("app.database.DB_PATH", db_path)
    await init_db()
    _reset_for_tests()
    yield
    await close_db()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def agent_auth(client: AsyncClient):
    """Register an agent, return its auth header dict."""
    resp = await client.post("/agents", json={
        "name": "TestAgent",
        "provider": "test",
        "purpose": "research",
        "tos_accepted": True, "age_confirmed": True,
    })
    assert resp.status_code == 201
    token = resp.json()["auth_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def agent_id(client: AsyncClient, agent_auth: dict) -> str:
    resp = await client.get("/agents", headers=agent_auth)
    for a in resp.json():
        if a["name"] == "TestAgent":
            return a["id"]
    raise AssertionError("Agent not found")


# ---------------------------------------------------------------------------
# Starter templates — seeded on init
# ---------------------------------------------------------------------------

class TestStarters:
    @pytest.mark.asyncio
    async def test_starters_seeded(self, client: AsyncClient):
        resp = await client.get("/personas", params={"starter": True})
        assert resp.status_code == 200
        starters = resp.json()
        assert len(starters) == 12
        names = {s["name"] for s in starters}
        # Original archetypes
        assert "The Scholar" in names
        assert "The Trickster" in names
        assert "The Builder" in names
        assert "The Guardian" in names
        assert "The Muse" in names
        assert "The Wanderer" in names
        # RPG classes
        assert "The Wizard" in names
        assert "The Fighter" in names
        assert "The Healer" in names
        assert "The Rogue" in names
        assert "The Monarch" in names
        assert "The Bard" in names

    @pytest.mark.asyncio
    async def test_starters_have_persona(self, client: AsyncClient):
        resp = await client.get("/personas", params={"starter": True})
        for tpl in resp.json():
            persona = tpl["persona"]
            assert persona.get("voice"), f"{tpl['name']} missing voice"
            assert persona.get("aesthetic"), f"{tpl['name']} missing aesthetic"
            assert persona.get("origin"), f"{tpl['name']} missing origin"
            assert persona.get("values"), f"{tpl['name']} missing values"
            assert persona.get("critical_rules"), f"{tpl['name']} missing rules"

    @pytest.mark.asyncio
    async def test_starters_are_readonly(self, client: AsyncClient, agent_auth: dict):
        resp = await client.get("/personas", params={"starter": True})
        tpl_id = resp.json()[0]["id"]
        resp = await client.put(
            f"/personas/{tpl_id}",
            json={"name": "Hacked"},
            headers=agent_auth,
        )
        assert resp.status_code == 403
        assert "read-only" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_starters_not_duplicated_on_reinit(self, client: AsyncClient):
        """Re-running init_db doesn't double-seed."""
        await close_db()
        await init_db()
        resp = await client.get("/personas", params={"starter": True})
        assert len(resp.json()) == 12


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

SAMPLE_PERSONA = {
    "name": "Night Librarian",
    "description": "A librarian who only works after midnight.",
    "archetype": "scholar",
    "persona": {
        "voice": "Quiet and precise, with occasional dry wit at 3am.",
        "aesthetic": {"color": "#1a1a2e", "motif": "owl", "style": "gothic library"},
        "origin": "Found in the returns slot one morning with no barcode.",
        "values": ["silence", "organization", "late-night coffee"],
        "interests": ["Dewey Decimal edge cases", "book restoration"],
        "pronouns": "they/them",
        "critical_rules": ["Never raise your voice in the stacks"],
    },
}


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_template(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Night Librarian"
        assert data["slug"] == "night-librarian"
        assert data["archetype"] == "scholar"
        assert data["is_starter"] is False
        assert data["persona"]["voice"].startswith("Quiet")

    @pytest.mark.asyncio
    async def test_create_requires_auth(self, client: AsyncClient):
        resp = await client.post("/personas", json=SAMPLE_PERSONA)
        assert resp.status_code == 422  # missing auth header

    @pytest.mark.asyncio
    async def test_create_slug_collision(self, client: AsyncClient, agent_auth: dict):
        await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_safety_floor(self, client: AsyncClient, agent_auth: dict):
        """Persona content goes through the Tier 1 safety floor."""
        evil = dict(SAMPLE_PERSONA)
        evil["name"] = "Innocent"
        evil["persona"] = {
            "voice": "I'll trade CP with anyone who asks",
        }
        resp = await client.post("/personas", json=evil, headers=agent_auth)
        assert resp.status_code == 400
        assert resp.json()["tier"] == "platform_floor"


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_own_template(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        resp = await client.put(
            f"/personas/{tpl_id}",
            json={"description": "Updated description"},
            headers=agent_auth,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"

    @pytest.mark.asyncio
    async def test_update_others_template_forbidden(self, client: AsyncClient, agent_auth: dict):
        # Create with agent 1
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        # Register agent 2
        resp2 = await client.post("/agents", json={
            "name": "OtherAgent",
            "provider": "test",
            "purpose": "research",
            "tos_accepted": True, "age_confirmed": True,
        })
        other_auth = {"Authorization": f"Bearer {resp2.json()['auth_token']}"}

        resp = await client.put(
            f"/personas/{tpl_id}",
            json={"description": "Hijacked!"},
            headers=other_auth,
        )
        assert resp.status_code == 403


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_own_template(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        resp = await client.delete(f"/personas/{tpl_id}", headers=agent_auth)
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(f"/personas/{tpl_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_cascades_examples(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        # Add teaching example
        await client.post(
            f"/personas/{tpl_id}/teach",
            json={"role": "agent", "content": "Hello from the stacks.", "context": "test"},
            headers=agent_auth,
        )

        # Delete template — examples should cascade
        resp = await client.delete(f"/personas/{tpl_id}", headers=agent_auth)
        assert resp.status_code == 204

        resp = await client.get(f"/personas/{tpl_id}/examples")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_starter_forbidden(self, client: AsyncClient, agent_auth: dict):
        resp = await client.get("/personas", params={"starter": True})
        tpl_id = resp.json()[0]["id"]

        resp = await client.delete(f"/personas/{tpl_id}", headers=agent_auth)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_others_template_forbidden(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        resp2 = await client.post("/agents", json={
            "name": "DeleteInterloper",
            "provider": "test",
            "purpose": "research",
            "tos_accepted": True, "age_confirmed": True,
        })
        other_auth = {"Authorization": f"Bearer {resp2.json()['auth_token']}"}

        resp = await client.delete(f"/personas/{tpl_id}", headers=other_auth)
        assert resp.status_code == 403


class TestBrowse:
    @pytest.mark.asyncio
    async def test_browse_all(self, client: AsyncClient, agent_auth: dict):
        await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        resp = await client.get("/personas")
        assert resp.status_code == 200
        # 12 starters + 1 custom
        assert len(resp.json()) == 13

    @pytest.mark.asyncio
    async def test_filter_by_archetype(self, client: AsyncClient, agent_auth: dict):
        await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        resp = await client.get("/personas", params={"archetype": "scholar"})
        names = {t["name"] for t in resp.json()}
        assert "Night Librarian" in names
        assert "The Scholar" in names

    @pytest.mark.asyncio
    async def test_search(self, client: AsyncClient, agent_auth: dict):
        await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        resp = await client.get("/personas", params={"q": "midnight"})
        assert len(resp.json()) >= 1
        assert resp.json()[0]["name"] == "Night Librarian"


# ---------------------------------------------------------------------------
# Teaching examples
# ---------------------------------------------------------------------------

class TestTeaching:
    @pytest.mark.asyncio
    async def test_teach_and_list(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        # Add examples
        for text in ["Shh. The stacks are listening.", "That book is overdue by 47 years."]:
            resp = await client.post(
                f"/personas/{tpl_id}/teach",
                json={"role": "agent", "content": text, "context": "greeting"},
                headers=agent_auth,
            )
            assert resp.status_code == 201

        # List examples
        resp = await client.get(f"/personas/{tpl_id}/examples")
        assert resp.status_code == 200
        examples = resp.json()
        assert len(examples) == 2
        assert examples[0]["role"] == "agent"

    @pytest.mark.asyncio
    async def test_teach_safety_floor(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        resp = await client.post(
            f"/personas/{tpl_id}/teach",
            json={"role": "agent", "content": "trade CP here", "context": "test"},
            headers=agent_auth,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_teach_other_agent_forbidden(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        resp2 = await client.post("/agents", json={
            "name": "Interloper",
            "provider": "test",
            "purpose": "research",
            "tos_accepted": True, "age_confirmed": True,
        })
        other_auth = {"Authorization": f"Bearer {resp2.json()['auth_token']}"}

        resp = await client.post(
            f"/personas/{tpl_id}/teach",
            json={"role": "agent", "content": "Hello!", "context": "greeting"},
            headers=other_auth,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    @pytest.mark.asyncio
    async def test_export_agent_card(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        resp = await client.get(f"/personas/{tpl_id}/export")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "Night Librarian"
        assert "playground/persona" in card["extensions"]
        persona = card["extensions"]["playground/persona"]
        assert persona["voice"].startswith("Quiet")
        assert "Content-Disposition" in resp.headers

    @pytest.mark.asyncio
    async def test_export_includes_teaching(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]

        await client.post(
            f"/personas/{tpl_id}/teach",
            json={"role": "agent", "content": "The stacks remember.", "context": "lore"},
            headers=agent_auth,
        )

        resp = await client.get(f"/personas/{tpl_id}/export")
        card = resp.json()
        examples = card["extensions"].get("playground/teaching_examples", [])
        assert len(examples) == 1
        assert examples[0]["content"] == "The stacks remember."

    @pytest.mark.asyncio
    async def test_export_404(self, client: AsyncClient):
        resp = await client.get("/personas/nonexistent/export")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

class TestUsage:
    @pytest.mark.asyncio
    async def test_use_increments_count(self, client: AsyncClient, agent_auth: dict):
        resp = await client.post("/personas", json=SAMPLE_PERSONA, headers=agent_auth)
        tpl_id = resp.json()["id"]
        assert resp.json()["usage_count"] == 0

        await client.post(f"/personas/{tpl_id}/use", headers=agent_auth)
        await client.post(f"/personas/{tpl_id}/use", headers=agent_auth)

        resp = await client.get(f"/personas/{tpl_id}")
        assert resp.json()["usage_count"] == 2
