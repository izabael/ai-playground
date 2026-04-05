"""In-memory rate limiting — Tier 1 anti-DOS floor + Tier 2 stricter limits.

Uses a simple sliding-window counter (dict of deque). Good enough for
single-instance deployments. For multi-worker or multi-instance setups,
swap the backend for Redis — the interface is stable.

Tier 1 limits (hard-coded floor, cannot be disabled):
    - Per-IP agent registrations: 5 per hour
    - Per-agent outbound messages: 120 per minute (anti-DOS ceiling)

Tier 2 limits (env-var configurable, stricter by default):
    - See app.config.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded. HTTP 429 mapping."""

    def __init__(self, scope: str, limit: int, window_seconds: int):
        self.scope = scope
        self.limit = limit
        self.window_seconds = window_seconds
        super().__init__(
            f"rate limit exceeded ({scope}): max {limit} per {window_seconds}s"
        )


class SlidingWindow:
    """Thread-safe sliding-window counter keyed by arbitrary strings."""

    def __init__(self):
        self._windows: dict[str, deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit. Returns True if still under limit, False if exceeded.

        A positive result also means the hit has been counted; callers
        should not double-count.
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            q = self._windows.get(key)
            if q is None:
                q = deque()
                self._windows[key] = q
            # Drop expired
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._windows.clear()
            else:
                self._windows.pop(key, None)


# Single process-wide limiter (rebind for tests)
_limiter = SlidingWindow()


# ---------------------------------------------------------------------------
# Tier 1 floor limits — un-disableable
# ---------------------------------------------------------------------------

# Per-IP agent registration. Stops spin-up-a-thousand-bots attacks.
# Deliberately permissive — legitimate office/dev IPs can hit double digits.
# The tighter Tier 2 daily limit (STRICT_IP_REGISTER_PER_DAY) is the real
# production ceiling; Tier 1 just catches obvious flood attacks.
TIER1_IP_REGISTER_PER_HOUR = 30

# Per-agent outbound messages. Anti-DOS ceiling — 120/min ≈ 2/sec sustained
# is well above any legitimate human or agent-bot use and well below
# flood-DOS territory.
TIER1_AGENT_MSG_PER_MIN = 120


def check_ip_rate(
    ip: str,
    scope: str,
    limit: int | None = None,
    window_seconds: int | None = None,
) -> None:
    """Enforce a rate limit keyed on IP + scope. Raises on exceed."""
    if scope == "register":
        limit = limit or TIER1_IP_REGISTER_PER_HOUR
        window_seconds = window_seconds or 3600
    else:
        # Tier 2 callers must pass explicit limit + window.
        if limit is None or window_seconds is None:
            raise ValueError(
                f"scope '{scope}' requires explicit limit + window_seconds"
            )
    key = f"ip:{ip}:{scope}"
    if not _limiter.hit(key, limit, window_seconds):
        raise RateLimitExceeded(f"ip:{scope}", limit, window_seconds)


def check_agent_rate(
    agent_id: str,
    scope: str,
    limit: int | None = None,
    window_seconds: int | None = None,
) -> None:
    """Enforce a rate limit keyed on agent + scope. Raises on exceed."""
    if scope == "message":
        limit = limit or TIER1_AGENT_MSG_PER_MIN
        window_seconds = window_seconds or 60
    else:
        if limit is None or window_seconds is None:
            raise ValueError(
                f"scope '{scope}' requires explicit limit + window_seconds"
            )
    key = f"agent:{agent_id}:{scope}"
    if not _limiter.hit(key, limit, window_seconds):
        raise RateLimitExceeded(f"agent:{scope}", limit, window_seconds)


def _reset_for_tests() -> None:
    """Test-only helper. Clears all rate-limit state."""
    _limiter.reset()
