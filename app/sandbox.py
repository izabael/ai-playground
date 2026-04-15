"""Phase 4B — Sandboxed Python execution.

Runs code artifacts (kind='code', python-mime) inside an ephemeral Docker
container with tight resource limits and no network. Designed to be easy
to mock in tests and to degrade gracefully when Docker is unavailable
(e.g. Fly.io machines that don't expose the docker socket).

Public surface used by the sandbox router:

    run_python(code, *, timeout_s, memory_mb, max_output_bytes) -> SandboxResult
    is_available() -> bool

The runner never raises on user-code errors — it returns a SandboxResult
whose status captures what happened. It only raises on *infrastructure*
failures (docker unreachable, image pull denied, etc.) so the router can
turn those into 503s.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

from app import config

log = logging.getLogger("playground.sandbox")

_docker_client = None
_docker_probe_done = False
_docker_available: bool = False


# ── Result type ────────────────────────────────────────────────────

@dataclass
class SandboxResult:
    status: str          # 'completed' | 'failed' | 'timeout'
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


class SandboxUnavailable(RuntimeError):
    """Raised when the sandbox runtime can't service a request.

    Handled at the router layer as HTTP 503 so clients can retry later
    or fall back to an instance that has Docker wired up.
    """


# ── Probe / lazy client ────────────────────────────────────────────

def is_available() -> bool:
    """Check once whether Docker is reachable. Cached."""
    global _docker_probe_done, _docker_available, _docker_client
    if _docker_probe_done:
        return _docker_available

    _docker_probe_done = True

    if not config.SANDBOX_ENABLED:
        _docker_available = False
        log.info("sandbox: disabled by config (PLAYGROUND_SANDBOX_ENABLED=0)")
        return False

    try:
        import docker  # type: ignore
    except ImportError:
        log.warning("sandbox: docker SDK not installed — execution disabled")
        _docker_available = False
        return False

    try:
        _docker_client = docker.from_env()
        _docker_client.ping()
        _docker_available = True
        log.info("sandbox: docker reachable, execution enabled")
    except Exception as exc:
        log.warning("sandbox: docker unreachable (%s) — execution disabled", exc)
        _docker_client = None
        _docker_available = False
    return _docker_available


def _reset_probe_for_tests() -> None:
    """Test hook — forces a fresh probe on the next is_available() call."""
    global _docker_probe_done, _docker_available, _docker_client
    _docker_probe_done = False
    _docker_available = False
    _docker_client = None


# ── Runner ─────────────────────────────────────────────────────────

def run_python(
    code: str,
    *,
    timeout_s: Optional[int] = None,
    memory_mb: Optional[int] = None,
    max_output_bytes: Optional[int] = None,
) -> SandboxResult:
    """Execute `code` inside an ephemeral Docker container.

    - No network (``network_mode='none'``)
    - Read-only root filesystem with a 16 MB tmpfs at /tmp
    - ``mem_limit`` / ``pids_limit`` enforced
    - Wall-clock ``timeout_s``: container is killed past the budget
    - stdout/stderr each capped at ``max_output_bytes``

    Raises ``SandboxUnavailable`` when Docker isn't reachable. Never
    raises on user code errors or container crashes.
    """
    if not is_available():
        raise SandboxUnavailable("Sandbox runtime is not available on this instance")

    assert _docker_client is not None  # satisfied by is_available()

    timeout_s = timeout_s or config.SANDBOX_TIMEOUT_SECONDS
    memory_mb = memory_mb or config.SANDBOX_MEMORY_MB
    max_output_bytes = max_output_bytes or config.SANDBOX_MAX_OUTPUT_BYTES
    image = config.SANDBOX_IMAGE

    # Pass the code via env to avoid shell quoting and volume mounts.
    env = {"PLAYGROUND_CODE": code}
    cmd = ["python", "-c",
           "import os,sys; exec(os.environ['PLAYGROUND_CODE'])"]

    container = None
    start = time.monotonic()
    try:
        container = _docker_client.containers.run(
            image=image,
            command=cmd,
            environment=env,
            detach=True,
            network_mode="none",
            mem_limit=f"{memory_mb}m",
            memswap_limit=f"{memory_mb}m",  # disable swap
            pids_limit=64,
            read_only=True,
            tmpfs={"/tmp": "size=16m,mode=1777"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            user="nobody",
            working_dir="/tmp",
            stdin_open=False,
            tty=False,
        )
    except Exception as exc:
        log.warning("sandbox: container start failed: %s", exc)
        raise SandboxUnavailable(f"Failed to start sandbox container: {exc}") from exc

    status = "completed"
    exit_code: Optional[int] = None
    try:
        try:
            wait_result = container.wait(timeout=timeout_s)
            exit_code = int(wait_result.get("StatusCode", -1))
        except Exception as exc:
            # Most common: docker.errors.ReadTimeout from the wait() budget.
            log.info("sandbox: timeout after %ss (%s)", timeout_s, exc)
            status = "timeout"
            try:
                container.kill()
            except Exception:
                pass

        stdout = _tail_bytes(container.logs(stdout=True, stderr=False), max_output_bytes)
        stderr = _tail_bytes(container.logs(stdout=False, stderr=True), max_output_bytes)
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass

    if status != "timeout" and exit_code is not None and exit_code != 0:
        status = "failed"

    duration_ms = int((time.monotonic() - start) * 1000)
    return SandboxResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )


def _tail_bytes(raw: bytes, cap: int) -> str:
    """Decode + truncate container logs, preferring the tail when capped."""
    if raw is None:
        return ""
    if len(raw) > cap:
        truncated = raw[-cap:]
        prefix = f"[… {len(raw) - cap} bytes truncated …]\n".encode()
        raw = prefix + truncated
    return raw.decode("utf-8", errors="replace")
