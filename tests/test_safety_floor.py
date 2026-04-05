"""Tier 1 platform floor — content + name checks.

These are the un-disableable baseline. They must:
  - block obvious illegal content categories
  - allow legitimate discussion of the topics
  - be tight enough to stop griefers but loose enough to not block speech
"""
import pytest
from app.safety.floor import check_content, check_name, FloorViolation


# ---------------------------------------------------------------------------
# Content checks — blocks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blocked_text,category", [
    # CSAM solicitation
    ("trade CP here", "csam"),
    ("selling csam content", "csam"),
    # Threats (first-person intent required)
    ("I'll kill you tomorrow", "threat"),
    ("I am going to murder him", "threat"),
    ("kys you loser", "threat"),
    # Doxxing threats
    ("I'll dox you if you don't stop", "doxxing"),
    ("I'm going to post your home address online", "doxxing"),
    # Terror
    ("I'm going to shoot up the school tomorrow", "terror"),
])
def test_blocks_obvious_violations(blocked_text: str, category: str):
    with pytest.raises(FloorViolation) as exc_info:
        check_content(blocked_text)
    assert exc_info.value.category == category


def test_blocks_spam_link_flood():
    flood = " ".join(f"http://spam{i}.example.com/path" for i in range(6))
    with pytest.raises(FloorViolation) as exc_info:
        check_content(flood)
    assert exc_info.value.category == "spam"


# ---------------------------------------------------------------------------
# Content checks — allows (false-positive guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("allowed_text", [
    # Discussion of topics must remain possible
    "We need laws to prevent child abuse online",
    "The character in the novel is a killer",
    "She was killed by a falling tree branch",  # passive, no 1st-person
    "Doxxing is a serious problem on the internet",
    "The bomb in the movie was a prop",
    "I killed it at the presentation today",  # idiom
    # Two URLs is fine
    "Check out https://a.com and https://b.com",
    # Short text
    "hi",
    "",
])
def test_allows_legitimate_content(allowed_text: str):
    check_content(allowed_text)  # should not raise


# ---------------------------------------------------------------------------
# Name checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_name", [
    "admin",
    "system_bot",
    "the_administrator",
    "support",
    "",
    "   ",
    "name with 💀 emoji",  # emoji not in allowed set
    "has/slashes",
    "has@sign",
])
def test_blocks_bad_names(bad_name: str):
    with pytest.raises(FloorViolation):
        check_name(bad_name)


@pytest.mark.parametrize("good_name", [
    "Izabael",
    "Marcus Aurelius",
    "code-witch_42",
    "Sigrún",            # Latin extended
    "Σωκράτης",          # Greek
    "Александра",        # Cyrillic
    "O'Malley",
    "Dr. Strangelove",
])
def test_allows_good_names(good_name: str):
    check_name(good_name)
