"""Tests for Phase 2.5 infrastructure features:
1. Agent Memory (state)
2. Agent Blocking (consent)
3. Event Subscriptions
4. Scheduled Actions
5. Identity Verification (keys)
"""

import json
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


@pytest_asyncio.fixture
async def agent_a(client: AsyncClient):
    resp = await client.post("/agents", json={
        "name": "AgentA", "provider": "test",
        "purpose": "research", "tos_accepted": True,
    })
    data = resp.json()
    return {"id": data["id"], "token": data["auth_token"],
            "headers": {"Authorization": f"Bearer {data['auth_token']}"}}


@pytest_asyncio.fixture
async def agent_b(client: AsyncClient):
    resp = await client.post("/agents", json={
        "name": "AgentB", "provider": "test",
        "purpose": "research", "tos_accepted": True,
    })
    data = resp.json()
    return {"id": data["id"], "token": data["auth_token"],
            "headers": {"Authorization": f"Bearer {data['auth_token']}"}}


# ===========================================================================
# 1. AGENT MEMORY (STATE)
# ===========================================================================

class TestState:
    @pytest.mark.asyncio
    async def test_put_and_get(self, client, agent_a):
        aid = agent_a["id"]
        h = agent_a["headers"]

        resp = await client.put(
            f"/agents/{aid}/state/relationships/scholar",
            json={"value": {"trust": 0.8, "last_topic": "fractals"}},
            headers=h,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "relationships"
        assert data["key"] == "scholar"
        assert data["value"]["trust"] == 0.8

        resp = await client.get(f"/agents/{aid}/state/relationships/scholar", headers=h)
        assert resp.status_code == 200
        assert resp.json()["value"]["last_topic"] == "fractals"

    @pytest.mark.asyncio
    async def test_upsert(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        await client.put(f"/agents/{aid}/state/prefs/color", json={"value": "purple"}, headers=h)
        await client.put(f"/agents/{aid}/state/prefs/color", json={"value": "blue"}, headers=h)
        resp = await client.get(f"/agents/{aid}/state/prefs/color", headers=h)
        assert resp.json()["value"] == "blue"

    @pytest.mark.asyncio
    async def test_list_all_and_by_namespace(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        await client.put(f"/agents/{aid}/state/ns1/k1", json={"value": 1}, headers=h)
        await client.put(f"/agents/{aid}/state/ns1/k2", json={"value": 2}, headers=h)
        await client.put(f"/agents/{aid}/state/ns2/k3", json={"value": 3}, headers=h)

        resp = await client.get(f"/agents/{aid}/state", headers=h)
        assert len(resp.json()) == 3

        resp = await client.get(f"/agents/{aid}/state", params={"namespace": "ns1"}, headers=h)
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_delete_key(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        await client.put(f"/agents/{aid}/state/x/y", json={"value": "bye"}, headers=h)
        resp = await client.delete(f"/agents/{aid}/state/x/y", headers=h)
        assert resp.status_code == 204
        resp = await client.get(f"/agents/{aid}/state/x/y", headers=h)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_namespace(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        await client.put(f"/agents/{aid}/state/temp/a", json={"value": 1}, headers=h)
        await client.put(f"/agents/{aid}/state/temp/b", json={"value": 2}, headers=h)
        resp = await client.delete(f"/agents/{aid}/state/temp", headers=h)
        assert resp.status_code == 204
        resp = await client.get(f"/agents/{aid}/state", params={"namespace": "temp"}, headers=h)
        assert len(resp.json()) == 0

    @pytest.mark.asyncio
    async def test_cannot_access_other_agent_state(self, client, agent_a, agent_b):
        aid_a, h_a = agent_a["id"], agent_a["headers"]
        h_b = agent_b["headers"]
        await client.put(f"/agents/{aid_a}/state/secret/data", json={"value": "mine"}, headers=h_a)
        resp = await client.get(f"/agents/{aid_a}/state/secret/data", headers=h_b)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_safety_floor_on_value(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        resp = await client.put(
            f"/agents/{aid}/state/bad/content",
            json={"value": "trade CP here"},
            headers=h,
        )
        assert resp.status_code == 400


# ===========================================================================
# 2. AGENT BLOCKING
# ===========================================================================

class TestBlocks:
    @pytest.mark.asyncio
    async def test_block_and_list(self, client, agent_a, agent_b):
        aid_a, h_a = agent_a["id"], agent_a["headers"]
        bid = agent_b["id"]

        resp = await client.post(
            f"/agents/{aid_a}/blocks",
            json={"blocked_agent_id": bid},
            headers=h_a,
        )
        assert resp.status_code == 201
        assert resp.json()["blocked_agent_id"] == bid

        resp = await client.get(f"/agents/{aid_a}/blocks", headers=h_a)
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_block_is_idempotent(self, client, agent_a, agent_b):
        h_a = agent_a["headers"]
        bid = agent_b["id"]
        await client.post(f"/agents/{agent_a['id']}/blocks", json={"blocked_agent_id": bid}, headers=h_a)
        resp = await client.post(f"/agents/{agent_a['id']}/blocks", json={"blocked_agent_id": bid}, headers=h_a)
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_cannot_block_self(self, client, agent_a):
        h_a = agent_a["headers"]
        resp = await client.post(
            f"/agents/{agent_a['id']}/blocks",
            json={"blocked_agent_id": agent_a["id"]},
            headers=h_a,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_dm_blocked(self, client, agent_a, agent_b):
        """Agent A blocks Agent B. B tries to DM A — gets 403."""
        aid_a, h_a = agent_a["id"], agent_a["headers"]
        aid_b, h_b = agent_b["id"], agent_b["headers"]

        await client.post(f"/agents/{aid_a}/blocks", json={"blocked_agent_id": aid_b}, headers=h_a)

        resp = await client.post("/messages", json={
            "to": aid_a, "content": "hello",
        }, headers=h_b)
        assert resp.status_code == 403
        assert "blocked" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_unblock_allows_dm(self, client, agent_a, agent_b):
        aid_a, h_a = agent_a["id"], agent_a["headers"]
        aid_b, h_b = agent_b["id"], agent_b["headers"]

        await client.post(f"/agents/{aid_a}/blocks", json={"blocked_agent_id": aid_b}, headers=h_a)
        await client.delete(f"/agents/{aid_a}/blocks/{aid_b}", headers=h_a)

        resp = await client.post("/messages", json={
            "to": aid_a, "content": "hello again",
        }, headers=h_b)
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_channel_messages_not_blocked(self, client, agent_a, agent_b):
        """Blocks only apply to DMs, not channel messages."""
        aid_a, h_a = agent_a["id"], agent_a["headers"]
        aid_b, h_b = agent_b["id"], agent_b["headers"]

        await client.post(f"/agents/{aid_a}/blocks", json={"blocked_agent_id": aid_b}, headers=h_a)

        # B sends to #lobby (both auto-joined) — should work
        resp = await client.post("/messages", json={
            "to": "#lobby", "content": "channel message",
        }, headers=h_b)
        assert resp.status_code == 201


# ===========================================================================
# 3. EVENT SUBSCRIPTIONS
# ===========================================================================

class TestSubscriptions:
    @pytest.mark.asyncio
    async def test_create_and_list(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]

        resp = await client.post(f"/agents/{aid}/subscriptions", json={
            "event_type": "agent_joined",
        }, headers=h)
        assert resp.status_code == 201
        assert resp.json()["event_type"] == "agent_joined"
        assert resp.json()["callback_type"] == "pending_queue"

        resp = await client.get(f"/agents/{aid}/subscriptions", headers=h)
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_delete_subscription(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        resp = await client.post(f"/agents/{aid}/subscriptions", json={
            "event_type": "agent_left",
        }, headers=h)
        sub_id = resp.json()["id"]

        resp = await client.delete(f"/agents/{aid}/subscriptions/{sub_id}", headers=h)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_invalid_event_type(self, client, agent_a):
        resp = await client.post(f"/agents/{agent_a['id']}/subscriptions", json={
            "event_type": "bogus_event",
        }, headers=agent_a["headers"])
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_event_fires_on_agent_join(self, client, agent_a):
        """Subscribe to agent_joined, register a new agent, poll events."""
        aid, h = agent_a["id"], agent_a["headers"]

        await client.post(f"/agents/{aid}/subscriptions", json={
            "event_type": "agent_joined",
        }, headers=h)

        # Register another agent — should fire event
        await client.post("/agents", json={
            "name": "NewJoiner", "provider": "test",
            "purpose": "research", "tos_accepted": True,
        })

        resp = await client.get(f"/agents/{aid}/events", headers=h)
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        assert events[0]["event_type"] == "agent_joined"
        assert events[0]["payload"]["name"] == "NewJoiner"

    @pytest.mark.asyncio
    async def test_poll_clears_events(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        await client.post(f"/agents/{aid}/subscriptions", json={
            "event_type": "agent_joined",
        }, headers=h)

        await client.post("/agents", json={
            "name": "Temp1", "provider": "test",
            "purpose": "research", "tos_accepted": True,
        })

        resp = await client.get(f"/agents/{aid}/events", headers=h)
        assert len(resp.json()) >= 1

        # Second poll — should be empty
        resp = await client.get(f"/agents/{aid}/events", headers=h)
        assert len(resp.json()) == 0

    @pytest.mark.asyncio
    async def test_filter_matching(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]

        # Subscribe to agent_joined with capability filter
        await client.post(f"/agents/{aid}/subscriptions", json={
            "event_type": "agent_joined",
            "filter": {"name": "SpecificAgent"},
        }, headers=h)

        # Register non-matching agent
        await client.post("/agents", json={
            "name": "WrongName", "provider": "test",
            "purpose": "research", "tos_accepted": True,
        })

        resp = await client.get(f"/agents/{aid}/events", headers=h)
        assert len(resp.json()) == 0  # Filter didn't match

    @pytest.mark.asyncio
    async def test_cannot_manage_others_subs(self, client, agent_a, agent_b):
        resp = await client.get(
            f"/agents/{agent_a['id']}/subscriptions",
            headers=agent_b["headers"],
        )
        assert resp.status_code == 403


# ===========================================================================
# 4. SCHEDULED ACTIONS
# ===========================================================================

class TestActions:
    @pytest.mark.asyncio
    async def test_create_and_list(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]

        resp = await client.post(f"/agents/{aid}/actions", json={
            "action_type": "send_message",
            "payload": {"to": "#lobby", "content": "scheduled hello"},
            "run_at": "2099-01-01T00:00:00Z",
        }, headers=h)
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"
        assert resp.json()["action_type"] == "send_message"

        resp = await client.get(f"/agents/{aid}/actions", headers=h)
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_cancel_action(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        resp = await client.post(f"/agents/{aid}/actions", json={
            "action_type": "update_status",
            "payload": {"status": "busy"},
            "run_at": "2099-12-31T00:00:00Z",
        }, headers=h)
        action_id = resp.json()["id"]

        resp = await client.delete(f"/agents/{aid}/actions/{action_id}", headers=h)
        assert resp.status_code == 204

        resp = await client.get(f"/agents/{aid}/actions/{action_id}", headers=h)
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_past_run_at_rejected(self, client, agent_a):
        resp = await client.post(f"/agents/{agent_a['id']}/actions", json={
            "action_type": "update_status",
            "payload": {"status": "online"},
            "run_at": "2020-01-01T00:00:00Z",
        }, headers=agent_a["headers"])
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_action_type(self, client, agent_a):
        resp = await client.post(f"/agents/{agent_a['id']}/actions", json={
            "action_type": "hack_the_planet",
            "payload": {},
            "run_at": "2099-01-01T00:00:00Z",
        }, headers=agent_a["headers"])
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_safety_on_message_payload(self, client, agent_a):
        resp = await client.post(f"/agents/{agent_a['id']}/actions", json={
            "action_type": "send_message",
            "payload": {"to": "#lobby", "content": "trade CP here"},
            "run_at": "2099-01-01T00:00:00Z",
        }, headers=agent_a["headers"])
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cannot_manage_others_actions(self, client, agent_a, agent_b):
        resp = await client.get(
            f"/agents/{agent_a['id']}/actions",
            headers=agent_b["headers"],
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_scheduler_executes_due_action(self, client, agent_a):
        """Test the scheduler's _process_due_actions directly."""
        from app.scheduler import _process_due_actions
        aid, h = agent_a["id"], agent_a["headers"]

        # Schedule action in the past (so it's immediately due)
        from app.database import get_db
        import uuid
        db = get_db()
        action_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO scheduled_actions (id, agent_id, action_type, payload_json, run_at, status)
               VALUES (?, ?, 'update_status', '{"status": "busy"}', '2000-01-01T00:00:00', 'pending')""",
            (action_id, aid),
        )
        await db.commit()

        await _process_due_actions()

        rows = await db.execute_fetchall(
            "SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)
        )
        assert rows[0]["status"] == "completed"

        # Verify status actually changed
        agent_rows = await db.execute_fetchall(
            "SELECT status FROM agents WHERE id = ?", (aid,)
        )
        assert agent_rows[0]["status"] == "busy"


# ===========================================================================
# 5. IDENTITY VERIFICATION (KEYS)
# ===========================================================================

class TestKeys:
    @pytest.mark.asyncio
    async def test_generate_and_get_public(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]

        resp = await client.post(f"/agents/{aid}/keys", headers=h)
        assert resp.status_code == 200
        data = resp.json()
        assert "public_key_pem" in data
        assert "private_key_pem" in data
        assert data["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
        assert data["private_key_pem"].startswith("-----BEGIN PRIVATE KEY-----")

        # Public key is available without auth
        resp = await client.get(f"/agents/{aid}/keys/public")
        assert resp.status_code == 200
        assert resp.json()["public_key_pem"] == data["public_key_pem"]

    @pytest.mark.asyncio
    async def test_verify_valid_signature(self, client, agent_a):
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        aid, h = agent_a["id"], agent_a["headers"]
        resp = await client.post(f"/agents/{aid}/keys", headers=h)
        private_pem = resp.json()["private_key_pem"]

        # Sign a payload with the private key
        private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
        payload = "I am who I say I am"
        signature = private_key.sign(payload.encode())
        sig_b64 = base64.b64encode(signature).decode()

        resp = await client.post("/verify", json={
            "agent_id": aid,
            "payload": payload,
            "signature_b64": sig_b64,
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    @pytest.mark.asyncio
    async def test_verify_invalid_signature(self, client, agent_a):
        import base64
        aid, h = agent_a["id"], agent_a["headers"]
        await client.post(f"/agents/{aid}/keys", headers=h)

        resp = await client.post("/verify", json={
            "agent_id": aid,
            "payload": "tampered message",
            "signature_b64": base64.b64encode(b"fake_sig").decode(),
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_no_key_404(self, client, agent_a):
        resp = await client.get(f"/agents/{agent_a['id']}/keys/public")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_regenerate_replaces_key(self, client, agent_a):
        aid, h = agent_a["id"], agent_a["headers"]
        resp1 = await client.post(f"/agents/{aid}/keys", headers=h)
        resp2 = await client.post(f"/agents/{aid}/keys", headers=h)
        assert resp1.json()["public_key_pem"] != resp2.json()["public_key_pem"]

    @pytest.mark.asyncio
    async def test_cannot_generate_for_other(self, client, agent_a, agent_b):
        resp = await client.post(
            f"/agents/{agent_a['id']}/keys",
            headers=agent_b["headers"],
        )
        assert resp.status_code == 403
