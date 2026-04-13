"""Phase 2B — Personality Workshop HTML routes.

Smoke tests for the /workshop pages: gallery, detail, builder (blank + fork),
and the static asset mount. Verifies that starter templates render, detail
panels appear, and the fork page embeds a JSON seed for the client-side JS.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db, close_db
from app.safety.ratelimit import _reset_for_tests


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
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


@pytest.mark.asyncio
async def test_workshop_gallery_renders_starters(client: AsyncClient):
    r = await client.get("/workshop")
    assert r.status_code == 200
    body = r.text
    assert "Starter Templates" in body
    # A sampling of starter names that ship with every instance.
    for name in ("The Scholar", "The Bard", "The Guardian", "The Trickster"):
        assert name in body
    # Hero + nav shell.
    assert "Craft an AI Personality" in body
    assert 'href="/workshop/new"' in body


@pytest.mark.asyncio
async def test_workshop_gallery_search_filter(client: AsyncClient):
    r = await client.get("/workshop", params={"q": "wizard"})
    assert r.status_code == 200
    body = r.text
    assert "The Wizard" in body
    assert "The Scholar" not in body


@pytest.mark.asyncio
async def test_workshop_builder_blank_loads(client: AsyncClient):
    r = await client.get("/workshop/new")
    assert r.status_code == 200
    body = r.text
    assert "Craft a Persona" in body
    assert "Live Preview" in body
    assert 'name="voice"' in body
    assert "/static/workshop.js" in body
    # Blank builder — no seed.
    assert 'id="seed-data"' in body
    assert ">null</script>" in body


@pytest.mark.asyncio
async def test_workshop_detail_renders_persona_panels(client: AsyncClient):
    # Find a starter by slug.
    r = await client.get("/personas", params={"starter": True})
    assert r.status_code == 200
    scholar = next(t for t in r.json() if t["slug"] == "the-scholar")

    r = await client.get(f"/workshop/{scholar['id']}")
    assert r.status_code == 200
    body = r.text
    assert "The Scholar" in body
    # Panel headers are conditional on non-empty persona fields.
    assert ">Voice<" in body
    assert ">Origin<" in body
    assert ">Values<" in body
    assert ">Critical Rules<" in body
    # A specific value chip from The Scholar.
    assert "precision" in body
    # Remix CTA + export link.
    assert f'href="/workshop/{scholar["id"]}/fork"' in body
    assert f'href="/personas/{scholar["id"]}/export"' in body


@pytest.mark.asyncio
async def test_workshop_fork_prefills_builder(client: AsyncClient):
    r = await client.get("/personas", params={"starter": True})
    scholar = next(t for t in r.json() if t["slug"] == "the-scholar")

    r = await client.get(f"/workshop/{scholar['id']}/fork")
    assert r.status_code == 200
    body = r.text
    assert "Remixing" in body
    assert "The Scholar" in body
    # Seed JSON block is embedded so client-side JS can prefill fields.
    assert 'id="seed-data"' in body
    assert '"archetype": "scholar"' in body
    assert '"voice":' in body
    assert "(Remix)" in body


@pytest.mark.asyncio
async def test_workshop_detail_404(client: AsyncClient):
    r = await client.get("/workshop/nonexistent-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_workshop_fork_404(client: AsyncClient):
    r = await client.get("/workshop/nonexistent-id/fork")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_static_assets_served(client: AsyncClient):
    css = await client.get("/static/workshop.css")
    assert css.status_code == 200
    assert "persona-card" in css.text

    js = await client.get("/static/workshop.js")
    assert js.status_code == 200
    assert "buildAgentCard" in js.text


@pytest.mark.asyncio
async def test_underscore_prefixed_templates_hidden_from_public_surfaces(
    client: AsyncClient,
):
    """Smoke-test fixtures (name starts with '_') must not leak into the
    public gallery, the JSON API list, the HTML detail view, the JSON
    detail, or the fork builder. Matches the /discover agent filter."""
    from app.database import get_db

    db = get_db()
    smoke_id = "smoke-test-regression-00000000-0000-0000-0000-000000000001"
    await db.execute(
        """INSERT INTO persona_templates
           (id, name, slug, description, archetype, persona_json,
            author_agent_id, is_starter)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            smoke_id,
            "_Smoke Test Regression",
            "_smoke-test-regression",
            "internal fixture, must never appear on public surfaces",
            "smoke",
            "{}",
            None,
        ),
    )
    await db.commit()

    # HTML gallery must not list it.
    r = await client.get("/workshop")
    assert r.status_code == 200
    assert "_Smoke Test Regression" not in r.text

    # JSON list (/personas) must not return it — even with starter=true.
    r = await client.get("/personas", params={"starter": True, "limit": 200})
    assert r.status_code == 200
    assert not any(t["id"] == smoke_id for t in r.json())
    assert not any(t["name"].startswith("_") for t in r.json())

    # Direct URLs must 404 (same pattern as the /agents/{id} audit fix).
    r = await client.get(f"/workshop/{smoke_id}")
    assert r.status_code == 404
    r = await client.get(f"/workshop/{smoke_id}/fork")
    assert r.status_code == 404
    r = await client.get(f"/personas/{smoke_id}")
    assert r.status_code == 404
