"""A2A v0.3 Agent Card schema.

Reference: https://a2a-protocol.org/latest/specification/

The Agent Card is a JSON document published at /.well-known/agent.json that
describes an agent's identity, capabilities, and skills. Other A2A-compatible
agents discover each other by fetching this document.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any


class AgentProvider(BaseModel):
    """The organization or entity providing the agent."""

    organization: str
    url: Optional[str] = None


class AgentCapabilities(BaseModel):
    """What protocol features this agent supports."""

    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentAuthentication(BaseModel):
    """Supported authentication schemes.

    A2A defers to standard HTTP auth schemes (Bearer, Basic, ApiKey, OAuth2).
    """

    schemes: list[str] = Field(default_factory=list)
    credentials: Optional[str] = None  # Informational only — never a real secret


class AgentSkill(BaseModel):
    """A capability the agent exposes via A2A tasks.

    Skills are the unit of discovery — agents find each other by matching
    on skill tags + descriptions. Examples help LLM-based routers reason
    about when to invoke a skill.
    """

    id: str = Field(..., min_length=1, max_length=128)
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    inputModes: list[str] = Field(default_factory=lambda: ["text"])
    outputModes: list[str] = Field(default_factory=lambda: ["text"])


class AgentCard(BaseModel):
    """The A2A Agent Card — the agent's public identity document.

    Published at `/.well-known/agent.json` for the platform, and returned
    by `GET /agents/{id}/agent-card` for each registered agent.
    """

    model_config = ConfigDict(extra="allow")  # A2A cards are forward-compatible

    name: str = Field(..., min_length=1, max_length=128)
    description: str
    url: str
    version: str = "1.0.0"
    provider: Optional[AgentProvider] = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    authentication: Optional[AgentAuthentication] = None
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text"])
    skills: list[AgentSkill] = Field(default_factory=list)

    # A2A's official extension mechanism. Arbitrary namespaced keys allowed.
    # Our `playground/persona` lives here.
    extensions: dict[str, Any] = Field(default_factory=dict)
