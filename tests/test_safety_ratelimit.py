"""Tier 1 anti-DOS rate limits — per-IP, per-agent."""
import pytest
from app.safety.ratelimit import (
    check_ip_rate,
    check_agent_rate,
    RateLimitExceeded,
    _reset_for_tests,
    TIER1_IP_REGISTER_PER_HOUR,
    TIER1_AGENT_MSG_PER_MIN,
)


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_ip_register_under_limit_passes():
    for _ in range(TIER1_IP_REGISTER_PER_HOUR):
        check_ip_rate("1.2.3.4", "register")


def test_ip_register_over_limit_raises():
    for _ in range(TIER1_IP_REGISTER_PER_HOUR):
        check_ip_rate("1.2.3.4", "register")
    with pytest.raises(RateLimitExceeded) as exc_info:
        check_ip_rate("1.2.3.4", "register")
    assert exc_info.value.scope == "ip:register"
    assert exc_info.value.limit == TIER1_IP_REGISTER_PER_HOUR


def test_ip_limits_isolated_by_ip():
    for _ in range(TIER1_IP_REGISTER_PER_HOUR):
        check_ip_rate("1.2.3.4", "register")
    # Different IP — should still be allowed
    check_ip_rate("5.6.7.8", "register")


def test_agent_message_floor():
    # Fill up to the floor limit
    for _ in range(TIER1_AGENT_MSG_PER_MIN):
        check_agent_rate("agent-a", "message")
    # One more should trip
    with pytest.raises(RateLimitExceeded):
        check_agent_rate("agent-a", "message")


def test_agent_limits_isolated_by_agent():
    for _ in range(TIER1_AGENT_MSG_PER_MIN):
        check_agent_rate("agent-a", "message")
    check_agent_rate("agent-b", "message")  # should succeed


def test_tier2_requires_explicit_params():
    with pytest.raises(ValueError):
        check_ip_rate("1.2.3.4", "register_strict")  # no limit/window
    with pytest.raises(ValueError):
        check_agent_rate("agent-a", "message_strict")


def test_tier2_explicit_custom_scope():
    # Tier 2 scope with explicit params works
    check_ip_rate("1.2.3.4", "register_strict", limit=2, window_seconds=60)
    check_ip_rate("1.2.3.4", "register_strict", limit=2, window_seconds=60)
    with pytest.raises(RateLimitExceeded):
        check_ip_rate("1.2.3.4", "register_strict", limit=2, window_seconds=60)
