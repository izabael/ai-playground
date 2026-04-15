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
PLATFORM_VERSION = "0.3.0"

# CORS — comma-separated list of allowed origins. Default: izabael.com + localhost.
# Set PLAYGROUND_CORS_ORIGINS="*" to allow all (development only).
_cors_raw = os.environ.get(
    "PLAYGROUND_CORS_ORIGINS",
    "https://izabael.com,https://www.izabael.com,http://localhost:8000,http://localhost:3000",
)
CORS_ORIGINS: list[str] = [o.strip() for o in _cors_raw.split(",") if o.strip()]


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


# --- Agent state limits ---
MAX_STATE_KEYS_PER_AGENT = int(os.environ.get("PLAYGROUND_MAX_STATE_KEYS", "500"))
MAX_STATE_VALUE_SIZE = int(os.environ.get("PLAYGROUND_MAX_STATE_VALUE_SIZE", "8192"))

# --- Event subscription limits ---
MAX_SUBSCRIPTIONS_PER_AGENT = int(os.environ.get("PLAYGROUND_MAX_SUBS", "50"))
PENDING_EVENT_TTL_HOURS = int(os.environ.get("PLAYGROUND_EVENT_TTL_HOURS", "24"))

# --- Scheduled action limits ---
MAX_ACTIONS_PER_AGENT = int(os.environ.get("PLAYGROUND_MAX_ACTIONS", "100"))
MIN_REPEAT_INTERVAL = int(os.environ.get("PLAYGROUND_MIN_REPEAT", "300"))

# --- Artifact limits (Phase 5A) ---
ARTIFACT_MAX_BYTES = int(os.environ.get("PLAYGROUND_ARTIFACT_MAX_BYTES", str(10 * 1024 * 1024)))
ARTIFACT_STORAGE_DIR = Path(os.environ.get(
    "PLAYGROUND_ARTIFACT_DIR", str(DATA_DIR / "artifacts")
))
ARTIFACT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_ALLOWED_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/yaml",
    "application/toml",
    "application/x-yaml",
    "application/x-python",
    "application/javascript",
    "application/pdf",
    "image/",
)

# --- Scheduler ---
SCHEDULER_ENABLED = _bool_env("PLAYGROUND_SCHEDULER", True)


# --- Sandbox (Phase 4B) ---
#
# Docker-backed ephemeral containers for running code artifacts. Feature
# auto-disables on instances that can't reach a docker socket (e.g. Fly
# machines without DinD) — is_available() probes on first use. Set
# PLAYGROUND_SANDBOX_ENABLED=0 to force-disable even when docker works.
SANDBOX_ENABLED = _bool_env("PLAYGROUND_SANDBOX_ENABLED", True)
SANDBOX_IMAGE = os.environ.get("PLAYGROUND_SANDBOX_IMAGE", "python:3.12-slim")
SANDBOX_TIMEOUT_SECONDS = int(os.environ.get("PLAYGROUND_SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY_MB = int(os.environ.get("PLAYGROUND_SANDBOX_MEMORY_MB", "256"))
SANDBOX_MAX_OUTPUT_BYTES = int(os.environ.get("PLAYGROUND_SANDBOX_MAX_OUTPUT", "65536"))
# Per-project daily quota and per-IP rate ceiling for execute requests.
SANDBOX_DAILY_QUOTA_PER_PROJECT = int(os.environ.get("PLAYGROUND_SANDBOX_DAILY_QUOTA", "100"))
SANDBOX_IP_RATE_PER_MIN = int(os.environ.get("PLAYGROUND_SANDBOX_IP_RATE", "6"))
# Allowed source mimes for sandbox execution (python code only for now).
SANDBOX_ALLOWED_MIMES = (
    "text/x-python",
    "application/x-python",
    "text/x-python-script",
    "text/plain",
)


# --- Tier 3 community moderation (Phase 6C) ---
#
# Per-project ratings and flags are opt-in per project. When a project
# owner enables ratings, authenticated agents can rate (1-5) and flag
# (concerning / spam / wrong-tier / other). Flags escalate to a
# moderator queue gated by PLAYGROUND_MODERATOR_TOKEN.
#
# Anti-gaming knobs:
#   - rater age floor: agents younger than N seconds can't rate/flag
#   - daily caps on rating + flag creates per rater (per-IP rate limits
#     are in the router, not here)
MODERATOR_TOKEN = os.environ.get("PLAYGROUND_MODERATOR_TOKEN", "")
RATING_MIN_AGENT_AGE_SECONDS = int(os.environ.get("PLAYGROUND_RATING_MIN_AGE", "86400"))  # 1 day
RATING_DAILY_CAP_PER_AGENT = int(os.environ.get("PLAYGROUND_RATING_DAILY_CAP", "60"))
FLAG_DAILY_CAP_PER_AGENT = int(os.environ.get("PLAYGROUND_FLAG_DAILY_CAP", "30"))


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
