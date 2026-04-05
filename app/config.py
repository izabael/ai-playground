import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = os.environ.get("PLAYGROUND_DB", str(DATA_DIR / "playground.db"))
HOST = os.environ.get("PLAYGROUND_HOST", "0.0.0.0")
PORT = int(os.environ.get("PLAYGROUND_PORT", "8000"))
TOKEN_BYTES = 32
SPECTATOR_QUEUE_MAX = 256

# Public URL at which this playground instance is reachable. Used in
# A2A Agent Cards so discovering agents know where to send requests.
PUBLIC_URL = os.environ.get("PLAYGROUND_PUBLIC_URL", f"http://localhost:{PORT}")
PLATFORM_NAME = os.environ.get("PLAYGROUND_NAME", "SILT AI Playground")
PLATFORM_VERSION = "0.2.0"


# ---------------------------------------------------------------------------
# Safety configuration (Tier 2 — operator-toggleable)
# ---------------------------------------------------------------------------
#
# Tier 1 (platform floor) is defined in app.safety and cannot be disabled.
# Tier 2 layers on top. Operators can toggle individual policies via env.
# Any Tier 2 policy flipped off logs a loud startup warning.
#
# Boolean env vars accept: 1/0, true/false, yes/no, on/off (case-insensitive).
# ---------------------------------------------------------------------------

def _bool_env(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- Tier 2 toggles (default ON) ---
SAFETY_STRICT_RATE_LIMITS = _bool_env("PLAYGROUND_STRICT_RATE_LIMITS", True)
SAFETY_LENGTH_CAPS = _bool_env("PLAYGROUND_LENGTH_CAPS", True)
SAFETY_AUDIT_LOG = _bool_env("PLAYGROUND_AUDIT_LOG", True)

# --- Tier 2 length caps (enforced when SAFETY_LENGTH_CAPS is on) ---
MAX_MESSAGE_LENGTH = int(os.environ.get("PLAYGROUND_MAX_MSG_LEN", "4000"))
MAX_DESCRIPTION_LENGTH = int(os.environ.get("PLAYGROUND_MAX_DESC_LEN", "500"))

# --- Tier 2 strict rate limits (on top of Tier 1 floor) ---
# Per-agent outbound messages (stricter than Tier 1 floor of 120/min)
STRICT_AGENT_MSG_PER_MIN = int(os.environ.get("PLAYGROUND_STRICT_MSG_PER_MIN", "30"))
# Per-IP registrations per day
STRICT_IP_REGISTER_PER_DAY = int(os.environ.get("PLAYGROUND_STRICT_REG_PER_DAY", "20"))


def log_safety_startup() -> None:
    """Called from app lifespan. Logs the safety configuration loudly.

    Any Tier 2 policy disabled gets a ⚠️ warning line. Operators cannot
    pretend they didn't know.
    """
    log = logging.getLogger("playground.safety")
    log.info("=" * 60)
    log.info("Safety configuration (Tier 1 floor is always on)")
    log.info("  Tier 1: illegal content filter  -> ENFORCED (un-disableable)")
    log.info("  Tier 1: name validation          -> ENFORCED (un-disableable)")
    log.info("  Tier 1: anti-DOS rate limits     -> ENFORCED (un-disableable)")
    if SAFETY_STRICT_RATE_LIMITS:
        log.info(
            "  Tier 2: strict rate limits       -> ON (msg=%d/min, reg=%d/day)",
            STRICT_AGENT_MSG_PER_MIN,
            STRICT_IP_REGISTER_PER_DAY,
        )
    else:
        log.warning(
            "  ⚠️ Tier 2: strict rate limits    -> DISABLED "
            "(instance operator has accepted this risk)"
        )
    if SAFETY_LENGTH_CAPS:
        log.info(
            "  Tier 2: content length caps      -> ON (msg=%d, desc=%d)",
            MAX_MESSAGE_LENGTH,
            MAX_DESCRIPTION_LENGTH,
        )
    else:
        log.warning(
            "  ⚠️ Tier 2: content length caps   -> DISABLED "
            "(instance operator has accepted this risk)"
        )
    if SAFETY_AUDIT_LOG:
        log.info("  Tier 2: audit log                -> ON")
    else:
        log.warning(
            "  ⚠️ Tier 2: audit log             -> DISABLED "
            "(instance operator has accepted this risk)"
        )
    log.info("=" * 60)
