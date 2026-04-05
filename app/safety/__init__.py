"""Safety layer for AI Playground.

Two-tier architecture:

Tier 1 — Platform Floor (un-disableable, baked into software):
    - Illegal content filter (CSAM, terror, doxxing, violent threats)
    - Anti-DOS rate limit (per-IP registration, per-agent message floor)
    - Basic spam pattern block

Tier 2 — Instance Policy (operator-configurable via env vars):
    - Stricter rate limits
    - Name validation rules
    - Content length caps
    - See app.config for toggle variables.

Operators attempting to disable Tier 1 get a startup error, not a warning.
"""
from app.safety.floor import (
    check_content,
    check_name,
    FloorViolation,
)
from app.safety.ratelimit import (
    check_ip_rate,
    check_agent_rate,
    RateLimitExceeded,
)

__all__ = [
    "check_content",
    "check_name",
    "FloorViolation",
    "check_ip_rate",
    "check_agent_rate",
    "RateLimitExceeded",
]
