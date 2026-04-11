"""Security regression tests — audit 2026-04.

Covers H-1 (client_ip uses Fly-Client-IP not XFF),
H-2 (federation relay peer check), M-1 (spectator connection cap).
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from app.main import app
from app.database import init_db, close_db
from app.safety.ratelimit import _reset_for_tests
from app.utils import client_ip


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


@pytest_asyncio.fixture
async def agent_auth(client: AsyncClient):
    resp = await client.post("/agents", json={
        "name": "Auditor",
        "provider": "test",
        "purpose": "research",
        "tos_accepted": True, "age_confirmed": True,
    })
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['auth_token']}"}


# ---------------------------------------------------------------------------
# H-1: client_ip() prefers Fly-Client-IP over X-Forwarded-For
# ---------------------------------------------------------------------------

class TestClientIp:
    def _make_request(self, headers: dict):
        req = MagicMock()
        req.headers = headers
        req.client = MagicMock()
        req.client.host = "10.0.0.1"  # simulated Fly internal proxy IP
        return req

    def test_uses_fly_client_ip_when_present(self):
        req = self._make_request({"fly-client-ip": "203.0.113.1"})
        assert client_ip(req) == "203.0.113.1"

    def test_does_not_use_xff_even_when_fly_header_absent(self):
        """XFF is not trusted — attacker-controlled. Falls back to TCP remote addr."""
        req = self._make_request({"x-forwarded-for": "1.2.3.4"})
        # Should use request.client.host, NOT the XFF value
        result = client_ip(req)
        assert result == "10.0.0.1"
        assert result != "1.2.3.4"

    def test_fly_header_takes_precedence_over_xff(self):
        req = self._make_request({
            "fly-client-ip": "203.0.113.1",
            "x-forwarded-for": "1.2.3.4, 10.0.0.1",
        })
        assert client_ip(req) == "203.0.113.1"

    def test_fallback_to_client_host_when_no_headers(self):
        req = self._make_request({})
        assert client_ip(req) == "10.0.0.1"


# ---------------------------------------------------------------------------
# H-2: Federation relay rejects bad from_uri formats
# ---------------------------------------------------------------------------

class TestFederationRelayPeerCheck:
    @pytest.mark.asyncio
    async def test_relay_requires_at_sign_in_from_uri(self, client: AsyncClient):
        """from_uri without @ should be rejected 400 (not silently match all peers)."""
        resp = await client.post("/federation/relay", json={
            "from_uri": "no-at-sign",
            "to_agent_id": "some-id",
            "content": "hello",
        })
        assert resp.status_code == 400
        assert "from_uri" in resp.json()["detail"].lower() or "@" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_relay_rejects_empty_host_in_from_uri(self, client: AsyncClient):
        """from_uri with empty host after @ should be rejected."""
        resp = await client.post("/federation/relay", json={
            "from_uri": "@",
            "to_agent_id": "some-id",
            "content": "hello",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_relay_rejects_unknown_peer(self, client: AsyncClient):
        """A valid from_uri format with an unknown host gets 403, not 500."""
        resp = await client.post("/federation/relay", json={
            "from_uri": "agent@attacker.example.com",
            "to_agent_id": "some-id",
            "content": "hello",
        })
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_relay_substring_attack_rejected(self, client: AsyncClient, agent_auth: dict):
        """A peer 'trusted.example.com' should NOT match from_uri @example.com."""
        # Register a peer at trusted.example.com
        await client.post("/federation/peers", json={
            "url": "https://trusted.example.com",
            "name": "Trusted",
        }, headers=agent_auth)

        # Attacker claims to be from example.com (a substring of trusted.example.com)
        resp = await client.post("/federation/relay", json={
            "from_uri": "attacker@example.com",
            "to_agent_id": "some-id",
            "content": "hello",
        })
        # Must be 403 (not a peer), not 200 or 404
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# M-1: Spectator connection cap
# ---------------------------------------------------------------------------

class TestSpectatorCap:
    @pytest.mark.asyncio
    async def test_spectator_cap_returns_429(self, client: AsyncClient, monkeypatch):
        """When MAX_SPECTATORS is reached, new connections return 429."""
        import app.spectator as spectator_module
        monkeypatch.setattr(spectator_module, "MAX_SPECTATORS", 0)

        resp = await client.get("/spectate")
        assert resp.status_code == 429
