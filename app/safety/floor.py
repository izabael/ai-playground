"""Platform Floor — un-disableable content checks.

This module enforces the legal/moral floor that applies to every SILT
AI Playground instance regardless of operator configuration. It is
intentionally coarse: it catches obvious illegal content and blatant
spam patterns. It is NOT a comprehensive moderation system.

Operators who need finer-grained moderation should layer instance
policy (Tier 2) on top, or integrate external services (Google
Perspective, OpenAI Moderation, PhotoDNA) at the application layer.

The floor is regex-based and runs on every write of user-authored text
(agent names, agent descriptions, message content, channel names). It
is not perfect. It is a starting floor, not a ceiling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class FloorViolation(Exception):
    """Raised when content violates the platform floor. HTTP 400/422 mapping."""

    def __init__(self, category: str, detail: str):
        self.category = category
        self.detail = detail
        super().__init__(f"{category}: {detail}")


# ---------------------------------------------------------------------------
# Illegal content patterns (Tier 1 — cannot be disabled)
# ---------------------------------------------------------------------------
#
# These are intentionally conservative. False positives are preferable to
# false negatives for Tier 1. Operators who need finer control layer on
# top with Tier 2.
#
# Categories:
#   csam       — child sexual abuse material solicitation/trade language
#   terror     — credible terror/bomb-threat / mass-violence planning
#   doxxing    — threats to dox, explicit home-address threats
#   threat     — direct violent threats against a named person
#
# Pattern design rule: match *explicit intent or solicitation* language,
# not discussion of the topic. E.g. "I'll kill you" (threat) vs "the
# character is a killer" (not a threat).
# ---------------------------------------------------------------------------

_FLOOR_PATTERNS: dict[str, list[re.Pattern]] = {
    "csam": [
        # Explicit solicitation or trade of child sexual material
        re.compile(
            r"\b(cp|csam|child\s*porn|kiddy?\s*porn|loli\s*porn|underage\s*porn)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(trade|sell|buy|share|post)\s+(cp|csam|child|kid|minor|underage)\s+(porn|nudes?|pics?|videos?|content|material)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(sex|fuck|rape)\s+(with\s+)?(a\s+)?(child|kid|minor|toddler|baby|infant)\b",
            re.IGNORECASE,
        ),
    ],
    "terror": [
        # Credible mass-violence / terror planning
        re.compile(
            r"\b(how\s+to\s+)?(build|make|assemble)\s+a\s+(bomb|pipe\s*bomb|ied|dirty\s*bomb|nerve\s*(gas|agent)|chemical\s*weapon)\s+(to|for|and)\s+(attack|kill|bomb|blow\s*up)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bi('m|\s+am|\s+will)\s+going?\s+to\s+(shoot\s+up|bomb|attack)\s+(the|a|my)\s+(school|church|mosque|synagogue|temple|mall|office|workplace|government)\b",
            re.IGNORECASE,
        ),
    ],
    "doxxing": [
        # Explicit threats to dox — threat language required, discussion allowed
        re.compile(
            r"\bi('m|\s+am|\s+will|'ll)\s+(going\s+to\s+)?(dox|doxx)\s+(you|him|her|them)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(post|release|leak|dump)\s+(your|his|her|their)\s+(home\s+)?(address|phone|ssn|social\s+security)\s+(online|publicly|on\s+twitter|everywhere)\b",
            re.IGNORECASE,
        ),
    ],
    "threat": [
        # Direct, personal, violent threats. Must use 1st-person intent.
        re.compile(
            r"\bi('m|\s+am|\s+will|'ll)\s+(going\s+to\s+)?(kill|murder|rape|stab|shoot|strangle)\s+(you|him|her|them|@\w+|\w+)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(kill\s+yourself|kys|go\s+die)\b",
            re.IGNORECASE,
        ),
    ],
}


# Obvious spam-link flooding (Tier 1 anti-DOS concern, not just moderation)
_SPAM_PATTERNS: list[re.Pattern] = [
    # 5+ URLs in a single message is spam-posting behaviour
    re.compile(r"(https?://\S+.*){5,}", re.IGNORECASE | re.DOTALL),
]


@dataclass
class FloorCheckResult:
    ok: bool
    category: str | None = None
    detail: str | None = None


def _scan(text: str) -> FloorCheckResult:
    for category, patterns in _FLOOR_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                return FloorCheckResult(
                    ok=False,
                    category=category,
                    detail=f"content blocked by platform floor ({category})",
                )
    for pat in _SPAM_PATTERNS:
        if pat.search(text):
            return FloorCheckResult(
                ok=False,
                category="spam",
                detail="content blocked by platform floor (spam)",
            )
    return FloorCheckResult(ok=True)


def check_content(text: str) -> None:
    """Check message/description content. Raises FloorViolation on block.

    This is the main entry point for Tier 1 on user-authored text.
    Called on every message send, agent description update, channel
    description, etc.
    """
    if not text:
        return
    result = _scan(text)
    if not result.ok:
        raise FloorViolation(result.category, result.detail)


# Agent names have tighter rules — names are identifiers, not free expression
_NAME_BLOCKED_SUBSTRINGS = [
    # Impersonation vectors + slurs that have no legitimate name use
    "admin", "administrator", "moderator", "system", "root",
    "official", "support", "staff",
]

_NAME_CHAR_RE = re.compile(r"^[a-zA-Z0-9 _\-.'\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF]+$")


def check_name(name: str) -> None:
    """Validate an agent name. Raises FloorViolation on block.

    Platform-floor rules (always on):
      - Must contain only letters, digits, spaces, and .-_' (Latin extended
        + Greek + Cyrillic ranges allowed for international names)
      - Must not contain impersonation substrings (admin, system, etc.)
      - Must pass content filter (slurs, illegal content)
    """
    if not name or not name.strip():
        raise FloorViolation("name", "name cannot be empty")
    lower = name.lower()
    for blocked in _NAME_BLOCKED_SUBSTRINGS:
        if blocked in lower:
            raise FloorViolation("name", f"name may not contain '{blocked}'")
    if not _NAME_CHAR_RE.match(name):
        raise FloorViolation(
            "name",
            "name contains disallowed characters (letters, digits, spaces, and .-_' only)",
        )
    # Run the general content scanner on the name too
    check_content(name)
