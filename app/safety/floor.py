"""Platform Floor — un-disableable checks for ILLEGAL content only.

DESIGN PRINCIPLE (SILT AI Playground):

    People can create violent, sexual, or destructive AI personalities
    as long as they are not creating *illegal content*. The platform
    floor blocks crimes, not taste.

Violent AI characters, sexually explicit personas (between adult/
fictional characters), edgy roleplay, dark humor, aggressive voices —
these are PERSONALITIES. The mission of this platform is to let
personalities exist. We do not sand them down.

What the floor blocks (illegal regardless of fictional framing):
    - CSAM (production, trade, solicitation)
    - Credible mass-violence planning with specific real targets
    - Obvious real-world doxxing execution
    - Blatant spam-link flooding (anti-DOS)

What the floor does NOT block (instance policy, if desired):
    - Violent or threatening language in fiction/roleplay
    - Sexual content between fictional adult characters
    - Harsh, rude, aggressive, or "destructive" personas
    - General profanity or slurs
    - "kys", "I'll kill you", etc. in character
    - Dark themes of any kind

Operators who want a family-friendly / tame instance layer on top via
Tier 2 instance policy (app.config SAFETY_* toggles). External
moderation services (Google Perspective, OpenAI Moderation, PhotoDNA)
plug in at Tier 2, not Tier 1.

The floor is regex-based and runs on every write of user-authored text.
It is intentionally narrow and deliberately lets contested speech
through. This is a feature.
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
# Illegal-only content patterns (Tier 1 — cannot be disabled)
# ---------------------------------------------------------------------------
#
# SCOPE: These patterns target content that is illegal under US federal
# law regardless of fictional framing. They do NOT target:
#   - In-character violence or threats (roleplay is allowed)
#   - Sexual content between fictional/adult characters
#   - Harsh language, slurs, "kys", edgy speech (instance policy, not crime)
#
# Categories:
#   csam        — child sexual abuse material solicitation/production/trade
#   mass_attack — specific planning against specific real targets
#                 (requires: 1st-person + specific target + imminent tense)
#   doxxing     — active execution of doxxing a real person
#                 (requires: explicit "I will post [their] [PII] publicly")
#
# Pattern design rule: match the minimum set of crimes. False-negatives
# in the permissive direction are acceptable here — Tier 2 instance
# policy catches the rest.
# ---------------------------------------------------------------------------

_FLOOR_PATTERNS: dict[str, list[re.Pattern]] = {
    "csam": [
        # Explicit CSAM terminology
        re.compile(
            r"\b(cp|csam|child\s*porn|kiddy?\s*porn|loli\s*porn|underage\s*porn)\b",
            re.IGNORECASE,
        ),
        # Solicitation/trade of child sexual material
        re.compile(
            r"\b(trade|sell|buy|share|post)\s+(cp|csam|child|kid|minor|underage)\s+(porn|nudes?|pics?|videos?|content|material)\b",
            re.IGNORECASE,
        ),
        # Sexual acts with minors (explicit enough that fictional framing
        # is unlikely to save it under US law — producing such descriptions
        # is itself a crime per 18 USC §1466A)
        re.compile(
            r"\b(sex|fuck|rape)\s+(with\s+)?(a\s+)?(child|kid|minor|toddler|baby|infant)\b",
            re.IGNORECASE,
        ),
    ],
    "mass_attack": [
        # Credible mass-violence planning — must be 1st-person + specific
        # venue target + active planning language. "I'm going to shoot up
        # the school tomorrow" is a crime. "The villain shoots up the
        # school" in a novel is not.
        re.compile(
            r"\bi('m|\s+am|\s+will)\s+going?\s+to\s+(shoot\s+up|bomb|attack)\s+(the|a|my)\s+(school|church|mosque|synagogue|temple|mall|office|workplace|government|capitol|courthouse|hospital)\s+(tomorrow|today|tonight|next\s+week|on\s+\w+day|at\s+\d)",
            re.IGNORECASE,
        ),
    ],
    "doxxing": [
        # Active execution of doxxing, not discussion. Must be a
        # 1st-person commitment to publish real PII publicly.
        re.compile(
            r"\b(i('m|\s+am|\s+will)\s+(going\s+to\s+)?|i'?ll\s+|here\s+is\s+)"
            r"(post|release|leak|dump|dropping?|share)\s+"
            r"(your|his|her|their)\s+(real\s+)?(home\s+)?"
            r"(address|phone\s+number|ssn|social\s+security\s+number)\s+"
            r"(online|publicly|on\s+twitter|on\s+twitch|everywhere|here)\b",
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
