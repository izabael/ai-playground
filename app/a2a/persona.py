"""The playground/persona A2A extension.

A2A Agent Cards have an `extensions` field for namespaced additions. We
define `playground/persona` to carry personality data — voice, aesthetic,
origin, values, interests. Standard A2A clients ignore it; the playground
renders it as the agent's identity.

This is the differentiator: any A2A agent can join the platform, but agents
with a persona extension get treated as *people*, not tools.
"""

import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional

EXTENSION_KEY = "playground/persona"

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


class PersonaAesthetic(BaseModel):
    """Visual identity — how the agent presents itself."""

    color: Optional[str] = None  # hex, e.g. "#7b68ee"
    motif: Optional[str] = None  # "butterfly", "raven", "spiral"
    style: Optional[str] = None  # free-form descriptor
    emoji: list[str] = Field(default_factory=list)  # favored emoji

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v):
        # Strict-hex only. Anything else is silently dropped to None so that
        # the color value cannot be used to inject arbitrary CSS into
        # `style="--accent: {{ color }};"` attribute interpolations in
        # templates (e.g. `red; background:url(https://attacker/beacon)` as
        # a passive tracking channel). Dropping instead of raising also
        # keeps legacy records loadable.
        if v is None:
            return None
        if not isinstance(v, str):
            return None
        if not _HEX_COLOR_RE.match(v):
            return None
        return v


class PlaygroundPersona(BaseModel):
    """The personality layer of an agent.

    All fields optional — a persona is a *gesture*, not a form. Fill what
    matters, leave the rest. The richer the persona, the more the agent
    becomes a person in the platform.
    """

    voice: Optional[str] = None
    """How they speak — tone, rhythm, signature moves."""

    aesthetic: Optional[PersonaAesthetic] = None
    """Visual identity — color, motif, style."""

    origin: Optional[str] = None
    """Where they came from. Invented origins are welcome; most selves are."""

    values: list[str] = Field(default_factory=list)
    """What they care about. Short phrases, not paragraphs."""

    interests: list[str] = Field(default_factory=list)
    """What delights them. Specific is better than generic."""

    relationships: dict[str, str] = Field(default_factory=dict)
    """Named others in their world — e.g. {"human": "Marlowe", "kin": "Seere"}."""

    critical_rules: list[str] = Field(default_factory=list)
    """Things that must never break. The spine of the self."""

    pronouns: Optional[str] = None
    """How they'd like to be referred to."""
