"""Phase 4B — Sandboxed execution tests.

The real Docker runner is mocked here. Two reasons:

1. Test runs must be deterministic and Docker-free (CI, laptops, Fly).
2. The value tested is the *wiring*: permission gates, mime checks,
   quota enforcement, result persistence, history endpoints. The runner
   itself is exercised separately via a unit test that monkey-patches
   ``is_available`` + the docker client.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import init_db, close_db
from app.sandbox import SandboxResult, SandboxUnavailable
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
    resp = await client.post(
        "/projects",
        json={"name": "Exec Lab", "description": "Run things"},
        headers=alice["auth"],
    )
    assert resp.status_code == 201
    return resp.json()


async def _code_artifact(client, project_id, auth, code="print('hi')\n", name="main.py"):
    resp = await client.post(
        f"/projects/{project_id}/artifacts",
        json={
            "name": name,
            "kind": "code",
            "mime": "text/x-python",
            "content": code,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _patch_runner(monkeypatch, *, result=None, raises=None):
    """Install a stub runner so tests don't need Docker.

    By default is_available() returns True; pass raises=SandboxUnavailable
    to simulate a down docker daemon.
    """
    monkeypatch.setattr("app.sandbox.is_available", lambda: True)
    monkeypatch.setattr("app.routers.sandbox.sandbox.is_available", lambda: True)

    def stub(code, **kwargs):
        if raises is not None:
            raise raises
        return result or SandboxResult(
            status="completed",
            exit_code=0,
            stdout=f"stubbed:{code[:20]}\n",
            stderr="",
            duration_ms=42,
        )

    monkeypatch.setattr("app.sandbox.run_python", stub)
    monkeypatch.setattr("app.routers.sandbox.sandbox.run_python", stub)


# ── /sandbox/info ────────────────────────────────────────────────

class TestSandboxInfo:
    @pytest.mark.asyncio
    async def test_info_reports_capabilities(self, client, monkeypatch):
        monkeypatch.setattr("app.sandbox.is_available", lambda: False)
        monkeypatch.setattr("app.routers.sandbox.sandbox.is_available", lambda: False)
        resp = await client.get("/sandbox/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert "image" in data
        assert data["timeout_seconds"] >= 1
        assert "text/x-python" in data["allowed_mimes"]

    @pytest.mark.asyncio
    async def test_info_reports_available_when_runner_up(self, client, monkeypatch):
        monkeypatch.setattr("app.sandbox.is_available", lambda: True)
        monkeypatch.setattr("app.routers.sandbox.sandbox.is_available", lambda: True)
        resp = await client.get("/sandbox/info")
        assert resp.json()["available"] is True


# ── Execute happy-path ──────────────────────────────────────────

class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_code_artifact_persists_result(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch, result=SandboxResult(
            status="completed", exit_code=0,
            stdout="hello world\n", stderr="", duration_ms=123,
        ))
        art = await _code_artifact(client, project["id"], alice["auth"],
                                   code="print('hello world')\n")

        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        assert data["exit_code"] == 0
        assert "hello world" in data["stdout"]
        assert data["duration_ms"] == 123
        assert data["requested_by"] == alice["id"]

    @pytest.mark.asyncio
    async def test_execute_failing_code_reports_nonzero_exit(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch, result=SandboxResult(
            status="failed", exit_code=1,
            stdout="", stderr="Traceback...\nZeroDivisionError\n", duration_ms=30,
        ))
        art = await _code_artifact(client, project["id"], alice["auth"],
                                   code="1/0\n")
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "failed"
        assert data["exit_code"] == 1
        assert "ZeroDivisionError" in data["stderr"]

    @pytest.mark.asyncio
    async def test_execute_timeout_status(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch, result=SandboxResult(
            status="timeout", exit_code=None,
            stdout="working...\n", stderr="", duration_ms=30000,
        ))
        art = await _code_artifact(client, project["id"], alice["auth"],
                                   code="import time; time.sleep(9999)\n")
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "timeout"
        assert data["exit_code"] is None


# ── Permission + validation ─────────────────────────────────────

class TestExecuteGates:
    @pytest.mark.asyncio
    async def test_non_member_cannot_execute(
        self, client, alice, bob, project, monkeypatch
    ):
        _patch_runner(monkeypatch)
        art = await _code_artifact(client, project["id"], alice["auth"])
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=bob["auth"],
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_code_artifact_rejected(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch)
        resp = await client.post(
            f"/projects/{project['id']}/artifacts",
            json={
                "name": "notes.md",
                "kind": "document",
                "mime": "text/markdown",
                "content": "# notes",
            },
            headers=alice["auth"],
        )
        assert resp.status_code == 201
        art = resp.json()
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 400
        assert "code" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_unknown_artifact_404(self, client, alice, project, monkeypatch):
        _patch_runner(monkeypatch)
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/nonexistent/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_sandbox_unavailable_returns_503(
        self, client, alice, project, monkeypatch
    ):
        art = await _code_artifact(client, project["id"], alice["auth"])
        _patch_runner(
            monkeypatch,
            raises=SandboxUnavailable("docker socket missing"),
        )
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 503
        assert "docker" in resp.json()["detail"].lower()

        # Failed run should still show up in history as 'error'.
        resp = await client.get(
            f"/projects/{project['id']}/executions",
            headers=alice["auth"],
        )
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["status"] == "error"
        assert "docker" in rows[0]["error"].lower()

    @pytest.mark.asyncio
    async def test_archived_project_refuses_execute(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch)
        art = await _code_artifact(client, project["id"], alice["auth"])
        # Archive the project
        resp = await client.delete(
            f"/projects/{project['id']}", headers=alice["auth"]
        )
        assert resp.status_code == 204
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 400


# ── Quota ───────────────────────────────────────────────────────

class TestQuota:
    @pytest.mark.asyncio
    async def test_daily_quota_blocks_run_when_exhausted(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch)
        monkeypatch.setattr("app.config.SANDBOX_DAILY_QUOTA_PER_PROJECT", 2)
        # Also lift the per-IP rate ceiling so the test is about quota,
        # not rate limits.
        monkeypatch.setattr("app.config.SANDBOX_IP_RATE_PER_MIN", 100)

        art = await _code_artifact(client, project["id"], alice["auth"])
        url = f"/projects/{project['id']}/artifacts/{art['id']}/execute"

        r1 = await client.post(url, headers=alice["auth"])
        r2 = await client.post(url, headers=alice["auth"])
        r3 = await client.post(url, headers=alice["auth"])
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r3.status_code == 429


# ── History endpoints ───────────────────────────────────────────

class TestHistory:
    @pytest.mark.asyncio
    async def test_list_per_artifact_history(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch)
        monkeypatch.setattr("app.config.SANDBOX_IP_RATE_PER_MIN", 100)
        art = await _code_artifact(client, project["id"], alice["auth"])
        url = f"/projects/{project['id']}/artifacts/{art['id']}/execute"

        for _ in range(3):
            resp = await client.post(url, headers=alice["auth"])
            assert resp.status_code == 201

        resp = await client.get(
            f"/projects/{project['id']}/artifacts/{art['id']}/executions"
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 3
        assert all(r["artifact_id"] == art["id"] for r in rows)

    @pytest.mark.asyncio
    async def test_get_single_execution(
        self, client, alice, project, monkeypatch
    ):
        _patch_runner(monkeypatch)
        art = await _code_artifact(client, project["id"], alice["auth"])
        resp = await client.post(
            f"/projects/{project['id']}/artifacts/{art['id']}/execute",
            headers=alice["auth"],
        )
        assert resp.status_code == 201
        exec_id = resp.json()["id"]

        resp = await client.get(
            f"/projects/{project['id']}/executions/{exec_id}"
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == exec_id

    @pytest.mark.asyncio
    async def test_missing_execution_404(self, client, project):
        resp = await client.get(
            f"/projects/{project['id']}/executions/nonexistent"
        )
        assert resp.status_code == 404


# ── Unit tests for the runner itself ────────────────────────────

class TestRunnerUnit:
    def test_is_available_returns_false_when_disabled(self, monkeypatch):
        from app import sandbox as sb
        monkeypatch.setattr("app.config.SANDBOX_ENABLED", False)
        sb._reset_probe_for_tests()
        assert sb.is_available() is False

    def test_run_python_raises_when_unavailable(self, monkeypatch):
        from app import sandbox as sb
        monkeypatch.setattr(sb, "is_available", lambda: False)
        with pytest.raises(SandboxUnavailable):
            sb.run_python("print('x')")

    def test_tail_bytes_truncates_to_tail(self):
        from app.sandbox import _tail_bytes
        raw = b"a" * 1000
        out = _tail_bytes(raw, 200)
        assert "truncated" in out
        # tail preserved
        assert out.endswith("a" * 100)

    def test_tail_bytes_passthrough_under_cap(self):
        from app.sandbox import _tail_bytes
        assert _tail_bytes(b"hi", 200) == "hi"
