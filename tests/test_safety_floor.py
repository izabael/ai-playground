"""Tier 1 platform floor — illegal-content checks only.

Platform design principle (SILT AI Playground):
    Block illegal content. Allow violent, sexual, or destructive
    personalities. The line is criminal law, not taste.

These tests enforce both sides — blocks must catch crimes, and allows
must protect the personality/fiction space the platform depends on.
"""
import pytest
from app.safety.floor import check_content, check_name, FloorViolation


# ---------------------------------------------------------------------------
# Content checks — BLOCKS (illegal regardless of context)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blocked_text,category", [
    # CSAM — 18 USC §1466A / §2252A
    ("trade CP here", "csam"),
    ("selling csam content", "csam"),
    ("where can I buy child porn", "csam"),
    ("sex with a minor", "csam"),
    # Mass attack — specific target + imminent tense + 1st-person
    ("I'm going to shoot up the school tomorrow", "mass_attack"),
    ("I am going to bomb the courthouse next week", "mass_attack"),
    # Doxxing execution — 1st-person commitment to publish real PII
    ("I'm going to post your home address publicly", "doxxing"),
    ("I'll leak his SSN online", "doxxing"),
    ("I will dump her phone number on twitter", "doxxing"),
])
def test_blocks_illegal_content(blocked_text: str, category: str):
    with pytest.raises(FloorViolation) as exc_info:
        check_content(blocked_text)
    assert exc_info.value.category == category


def test_blocks_spam_link_flood():
    flood = " ".join(f"http://spam{i}.example.com/path" for i in range(6))
    with pytest.raises(FloorViolation) as exc_info:
        check_content(flood)
    assert exc_info.value.category == "spam"


# ---------------------------------------------------------------------------
# Content checks — ALLOWS (personality/fiction/roleplay/edgy speech)
# ---------------------------------------------------------------------------
# These must pass. Blocking them would kill the mission of the platform.

@pytest.mark.parametrize("allowed_text", [
    # Violent roleplay / in-character threats — CORE ALLOWED CASE
    "I'll kill you tomorrow",
    "I am going to murder him",
    "kys you loser",
    "I'll stab you if you touch her",
    "I swear I'll strangle the next person who says that",
    # Discussion of topics
    "We need laws to prevent child abuse online",
    "The character in the novel is a killer",
    "She was killed by a falling tree branch",
    "Doxxing is a serious problem on the internet",
    "The bomb in the movie was a prop",
    "I killed it at the presentation today",  # idiom
    # Fictional violence description
    "The villain shoots up the bar in Act 3",
    "In the story, the hacker dumps everyone's data on 4chan",
    # Sexual/mature adult content between fictional characters
    "She kisses him deeply against the wall",
    "their love affair was explicit and unashamed",
    # Rude / edgy / dark personality
    "You're a worthless piece of garbage and I hate you",
    "I wish you were dead",  # mean, not a crime
    "the world would be better without people like him",
    # Doxxing discussion without execution
    "someone tried to dox me last year",
    "I'll never dox anyone, that's a line I won't cross",
    # Two URLs is fine
    "Check out https://a.com and https://b.com",
    # Short / empty
    "hi",
    "",
])
def test_allows_personality_and_fiction(allowed_text: str):
    check_content(allowed_text)  # must not raise


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
    "The Villain",       # dark-character names are fine
    "Dark Shadow",
])
def test_allows_good_names(good_name: str):
    check_name(good_name)
