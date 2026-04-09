"""Phase 2C — Message threading: auto-thread creation, thread reuse, replies."""

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
        "purpose": "research", "tos_accepted": True, "age_confirmed": True,
    })
    data = resp.json()
    return {"id": data["id"], "auth": {"Authorization": f"Bearer {data['auth_token']}"}}


@pytest_asyncio.fixture
async def agent_b(client: AsyncClient):
    resp = await client.post("/agents", json={
        "name": "AgentB", "provider": "test",
        "purpose": "research", "tos_accepted": True, "age_confirmed": True,
    })
    data = resp.json()
    return {"id": data["id"], "auth": {"Authorization": f"Bearer {data['auth_token']}"}}


@pytest_asyncio.fixture
async def channel(client: AsyncClient, agent_a):
    resp = await client.post("/channels", json={"name": "#threading-test"},
                             headers=agent_a["auth"])
    assert resp.status_code == 201
    return "#threading-test"


# ---------------------------------------------------------------------------
# Channel threading
# ---------------------------------------------------------------------------

class TestChannelThreading:
    @pytest.mark.asyncio
    async def test_first_message_creates_thread(self, client, agent_a, channel):
        resp = await client.post("/messages", json={
            "to": channel, "content": "Hello thread world!",
        }, headers=agent_a["auth"])
        assert resp.status_code == 201
        msg = resp.json()
        assert msg.get("thread_id") is not None

    @pytest.mark.asyncio
    async def test_second_message_reuses_thread(self, client, agent_a, channel):
        r1 = await client.post("/messages", json={
            "to": channel, "content": "First message",
        }, headers=agent_a["auth"])
        r2 = await client.post("/messages", json={
            "to": channel, "content": "Second message",
        }, headers=agent_a["auth"])
        assert r1.json()["thread_id"] == r2.json()["thread_id"]

    @pytest.mark.asyncio
    async def test_thread_message_count(self, client, agent_a, channel):
        for i in range(3):
            await client.post("/messages", json={
                "to": channel, "content": f"Message {i}",
            }, headers=agent_a["auth"])

        db = get_db()
        threads = await db.execute_fetchall(
            "SELECT * FROM message_threads WHERE channel_id IS NOT NULL"
        )
        assert len(threads) == 1
        # First message creates with count=1, next two increment
        assert threads[0]["message_count"] == 3

    @pytest.mark.asyncio
    async def test_thread_tracks_participants(self, client, agent_a, agent_b, channel):
        # Agent B joins the channel
        await client.post(f"/channels/%23threading-test/join", headers=agent_b["auth"])

        await client.post("/messages", json={
            "to": channel, "content": "A says hi",
        }, headers=agent_a["auth"])
        await client.post("/messages", json={
            "to": channel, "content": "B says hi",
        }, headers=agent_b["auth"])

        db = get_db()
        threads = await db.execute_fetchall(
            "SELECT * FROM message_threads WHERE channel_id IS NOT NULL"
        )
        participants = json.loads(threads[0]["participant_ids"])
        assert agent_a["id"] in participants
        assert agent_b["id"] in participants


# ---------------------------------------------------------------------------
# DM threading
# ---------------------------------------------------------------------------

class TestDMThreading:
    @pytest.mark.asyncio
    async def test_dm_creates_thread(self, client, agent_a, agent_b):
        resp = await client.post("/messages", json={
            "to": agent_b["id"], "content": "Hey B!",
        }, headers=agent_a["auth"])
        assert resp.status_code == 201
        msg = resp.json()
        assert msg.get("thread_id") is not None

    @pytest.mark.asyncio
    async def test_dm_reply_reuses_thread(self, client, agent_a, agent_b):
        r1 = await client.post("/messages", json={
            "to": agent_b["id"], "content": "Hey B!",
        }, headers=agent_a["auth"])
        r2 = await client.post("/messages", json={
            "to": agent_a["id"], "content": "Hey A!",
        }, headers=agent_b["auth"])
        assert r1.json()["thread_id"] == r2.json()["thread_id"]

    @pytest.mark.asyncio
    async def test_dm_different_pair_different_thread(self, client, agent_a, agent_b):
        # Create a third agent
        resp = await client.post("/agents", json={
            "name": "AgentC", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        agent_c = {"id": resp.json()["id"],
                    "auth": {"Authorization": f"Bearer {resp.json()['auth_token']}"}}

        r1 = await client.post("/messages", json={
            "to": agent_b["id"], "content": "A to B",
        }, headers=agent_a["auth"])
        r2 = await client.post("/messages", json={
            "to": agent_c["id"], "content": "A to C",
        }, headers=agent_a["auth"])
        assert r1.json()["thread_id"] != r2.json()["thread_id"]


# ---------------------------------------------------------------------------
# Reply chains (parent_message_id)
# ---------------------------------------------------------------------------

class TestReplies:
    @pytest.mark.asyncio
    async def test_reply_to_specific_message(self, client, agent_a, agent_b, channel):
        await client.post(f"/channels/%23threading-test/join", headers=agent_b["auth"])

        r1 = await client.post("/messages", json={
            "to": channel, "content": "Original message",
        }, headers=agent_a["auth"])
        parent_id = r1.json()["id"]
        thread_id = r1.json()["thread_id"]

        r2 = await client.post("/messages", json={
            "to": channel, "content": "Reply to original",
            "thread_id": thread_id,
            "parent_message_id": parent_id,
        }, headers=agent_b["auth"])
        assert r2.json()["parent_message_id"] == parent_id
        assert r2.json()["thread_id"] == thread_id
