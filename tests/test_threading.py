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


# ---------------------------------------------------------------------------
# Phase 2C — Thread query endpoints (GET /threads, GET /threads/{id}/messages)
# ---------------------------------------------------------------------------

class TestThreadQuery:
    @pytest.mark.asyncio
    async def test_list_returns_dm_thread_for_participant(self, client, agent_a, agent_b):
        await client.post("/messages", json={
            "to": agent_b["id"], "content": "hi",
        }, headers=agent_a["auth"])

        resp = await client.get("/threads", headers=agent_a["auth"])
        assert resp.status_code == 200
        threads = resp.json()
        assert len(threads) == 1
        t = threads[0]
        assert t["is_dm"] is True
        assert t["channel_id"] is None
        assert t["channel_name"] is None
        assert agent_a["id"] in t["participant_ids"]
        assert agent_b["id"] in t["participant_ids"]
        assert t["message_count"] == 1

        # Recipient also sees the thread
        resp_b = await client.get("/threads", headers=agent_b["auth"])
        assert len(resp_b.json()) == 1

    @pytest.mark.asyncio
    async def test_list_hides_dm_thread_from_non_participant(self, client, agent_a, agent_b):
        await client.post("/messages", json={
            "to": agent_b["id"], "content": "private",
        }, headers=agent_a["auth"])

        # Third agent is not part of the DM
        resp = await client.post("/agents", json={
            "name": "AgentC", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        agent_c = {"auth": {"Authorization": f"Bearer {resp.json()['auth_token']}"}}

        resp = await client.get("/threads", headers=agent_c["auth"])
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_channel_thread_for_member(self, client, agent_a, agent_b, channel):
        await client.post(f"/channels/%23threading-test/join", headers=agent_b["auth"])
        await client.post("/messages", json={
            "to": channel, "content": "hello channel",
        }, headers=agent_a["auth"])

        # Both members see it
        for who in (agent_a, agent_b):
            resp = await client.get("/threads", headers=who["auth"])
            assert resp.status_code == 200
            threads = resp.json()
            assert len(threads) == 1
            assert threads[0]["is_dm"] is False
            assert threads[0]["channel_name"] == "#threading-test"

    @pytest.mark.asyncio
    async def test_list_hides_channel_thread_from_non_member(self, client, agent_a, channel):
        await client.post("/messages", json={
            "to": channel, "content": "members only",
        }, headers=agent_a["auth"])

        # Outsider with no membership
        resp = await client.post("/agents", json={
            "name": "Outsider", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        outsider = {"auth": {"Authorization": f"Bearer {resp.json()['auth_token']}"}}

        resp = await client.get("/threads", headers=outsider["auth"])
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_filter_by_channel(self, client, agent_a, channel):
        # Channel thread
        await client.post("/messages", json={
            "to": channel, "content": "in channel",
        }, headers=agent_a["auth"])
        # DM thread to self should not... DM to a second agent
        resp = await client.post("/agents", json={
            "name": "PeerX", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        peer = {"id": resp.json()["id"],
                "auth": {"Authorization": f"Bearer {resp.json()['auth_token']}"}}
        await client.post("/messages", json={
            "to": peer["id"], "content": "dm",
        }, headers=agent_a["auth"])

        resp = await client.get(
            "/threads", params={"channel": "#threading-test"}, headers=agent_a["auth"]
        )
        threads = resp.json()
        assert len(threads) == 1
        assert threads[0]["channel_name"] == "#threading-test"

    @pytest.mark.asyncio
    async def test_list_filter_dm_only(self, client, agent_a, channel):
        await client.post("/messages", json={
            "to": channel, "content": "ch",
        }, headers=agent_a["auth"])
        resp = await client.post("/agents", json={
            "name": "PeerY", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        peer = {"id": resp.json()["id"]}
        await client.post("/messages", json={
            "to": peer["id"], "content": "dm",
        }, headers=agent_a["auth"])

        resp = await client.get("/threads", params={"dm": "true"}, headers=agent_a["auth"])
        threads = resp.json()
        assert len(threads) == 1
        assert threads[0]["is_dm"] is True

        resp = await client.get("/threads", params={"dm": "false"}, headers=agent_a["auth"])
        threads = resp.json()
        assert len(threads) == 1
        assert threads[0]["is_dm"] is False

    @pytest.mark.asyncio
    async def test_list_orders_by_last_activity_desc(self, client, agent_a):
        # Two DM threads to two different peers; second one should come first
        peer_ids = []
        for name in ("PeerOlder", "PeerNewer"):
            r = await client.post("/agents", json={
                "name": name, "provider": "test",
                "purpose": "research", "tos_accepted": True, "age_confirmed": True,
            })
            peer_ids.append(r.json()["id"])

        await client.post("/messages", json={
            "to": peer_ids[0], "content": "older",
        }, headers=agent_a["auth"])
        await client.post("/messages", json={
            "to": peer_ids[1], "content": "newer",
        }, headers=agent_a["auth"])

        resp = await client.get("/threads", headers=agent_a["auth"])
        threads = resp.json()
        assert len(threads) == 2
        # Newest first
        assert peer_ids[1] in threads[0]["participant_ids"]
        assert peer_ids[0] in threads[1]["participant_ids"]

    @pytest.mark.asyncio
    async def test_list_pagination(self, client, agent_a):
        # Make 3 DM threads
        for i in range(3):
            r = await client.post("/agents", json={
                "name": f"P{i}", "provider": "test",
                "purpose": "research", "tos_accepted": True, "age_confirmed": True,
            })
            await client.post("/messages", json={
                "to": r.json()["id"], "content": f"msg {i}",
            }, headers=agent_a["auth"])

        resp = await client.get("/threads", params={"limit": 2}, headers=agent_a["auth"])
        assert len(resp.json()) == 2
        resp = await client.get(
            "/threads", params={"limit": 2, "offset": 2}, headers=agent_a["auth"]
        )
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_get_thread_by_id(self, client, agent_a, agent_b):
        r = await client.post("/messages", json={
            "to": agent_b["id"], "content": "hi",
        }, headers=agent_a["auth"])
        thread_id = r.json()["thread_id"]

        resp = await client.get(f"/threads/{thread_id}", headers=agent_a["auth"])
        assert resp.status_code == 200
        assert resp.json()["id"] == thread_id

    @pytest.mark.asyncio
    async def test_get_thread_404(self, client, agent_a):
        resp = await client.get("/threads/nonexistent", headers=agent_a["auth"])
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_thread_403_for_non_participant(self, client, agent_a, agent_b):
        r = await client.post("/messages", json={
            "to": agent_b["id"], "content": "private",
        }, headers=agent_a["auth"])
        thread_id = r.json()["thread_id"]

        resp = await client.post("/agents", json={
            "name": "Snoop", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        snoop = {"auth": {"Authorization": f"Bearer {resp.json()['auth_token']}"}}

        resp = await client.get(f"/threads/{thread_id}", headers=snoop["auth"])
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_thread_messages_chronological(self, client, agent_a, agent_b, channel):
        await client.post(f"/channels/%23threading-test/join", headers=agent_b["auth"])
        ids = []
        for i, who in enumerate([agent_a, agent_b, agent_a]):
            r = await client.post("/messages", json={
                "to": channel, "content": f"msg {i}",
            }, headers=who["auth"])
            ids.append(r.json()["id"])
        thread_id = r.json()["thread_id"]

        resp = await client.get(
            f"/threads/{thread_id}/messages", headers=agent_a["auth"]
        )
        assert resp.status_code == 200
        msgs = resp.json()
        assert [m["id"] for m in msgs] == ids
        assert [m["content"] for m in msgs] == ["msg 0", "msg 1", "msg 2"]

    @pytest.mark.asyncio
    async def test_thread_messages_403_for_non_member(self, client, agent_a, channel):
        r = await client.post("/messages", json={
            "to": channel, "content": "members only",
        }, headers=agent_a["auth"])
        thread_id = r.json()["thread_id"]

        resp = await client.post("/agents", json={
            "name": "Outsider", "provider": "test",
            "purpose": "research", "tos_accepted": True, "age_confirmed": True,
        })
        outsider = {"auth": {"Authorization": f"Bearer {resp.json()['auth_token']}"}}

        resp = await client.get(
            f"/threads/{thread_id}/messages", headers=outsider["auth"]
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_thread_messages_limit(self, client, agent_a, channel):
        for i in range(5):
            r = await client.post("/messages", json={
                "to": channel, "content": f"msg {i}",
            }, headers=agent_a["auth"])
        thread_id = r.json()["thread_id"]

        resp = await client.get(
            f"/threads/{thread_id}/messages",
            params={"limit": 2},
            headers=agent_a["auth"],
        )
        msgs = resp.json()
        assert len(msgs) == 2
        # limit returns the most recent N, in chronological order
        assert [m["content"] for m in msgs] == ["msg 3", "msg 4"]

    @pytest.mark.asyncio
    async def test_thread_messages_before_cursor(self, client, agent_a, channel):
        ids = []
        timestamps = []
        for i in range(4):
            r = await client.post("/messages", json={
                "to": channel, "content": f"msg {i}",
            }, headers=agent_a["auth"])
            ids.append(r.json()["id"])
            timestamps.append(r.json()["created_at"])
        thread_id = r.json()["thread_id"]

        # before=timestamps[2] returns msgs 0 and 1
        resp = await client.get(
            f"/threads/{thread_id}/messages",
            params={"before": timestamps[2]},
            headers=agent_a["auth"],
        )
        msgs = resp.json()
        assert [m["content"] for m in msgs] == ["msg 0", "msg 1"]
