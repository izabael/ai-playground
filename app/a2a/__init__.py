"""A2A protocol (Agent2Agent) integration for AI Playground.

Implements the A2A v0.3 Agent Card schema and the playground/persona
extension namespace. Models are native Pydantic rather than a full SDK
dependency — keeps the integration lean and lets us layer over the
existing FastAPI core without a rewrite.
"""

from app.a2a.schema import (
    AgentCard,
    AgentProvider,
    AgentCapabilities,
    AgentSkill,
    AgentAuthentication,
)
from app.a2a.persona import PlaygroundPersona, PersonaAesthetic

__all__ = [
    "AgentCard",
    "AgentProvider",
    "AgentCapabilities",
    "AgentSkill",
    "AgentAuthentication",
    "PlaygroundPersona",
    "PersonaAesthetic",
]
