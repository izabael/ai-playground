import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from app.a2a.schema import AgentCard
from app.a2a.persona import PlaygroundPersona


# --- Agent ---

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    provider: str = Field(..., min_length=1, max_length=32)
    model: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    # Optional A2A Agent Card. When provided, the agent participates in
    # A2A discovery via `/.well-known/agent.json` and per-agent card
    # endpoints. May carry a `playground/persona` extension.
    agent_card: Optional[AgentCard] = None
    # --- Purpose declaration (required, part of platform ToS) ---
    #
    # Adversarial/red-team AI is welcome when targets are authorized.
    # Black-hat use (unauthorized fraud, phishing, impersonation for
    # harm, malware, scams, doxxing) is not. This declaration distributes
    # liability to the operator if they lie.
    #
    # Allowed values:
    #   companion         — personal companion / creative / fictional
    #   productivity      — coding, writing, analysis, assistance
    #   research          — academic, scientific, artistic
    #   security_research — authorized security / red-team / CTF / sandbox
    #   other             — describe in purpose_detail
    purpose: str = Field(
        ..., pattern=r"^(companion|productivity|research|security_research|other)$"
    )
    purpose_detail: str = Field("", max_length=300)
    # Required attestation. Must be True to register.
    tos_accepted: bool = Field(
        ...,
        description=(
            "I attest this agent is NOT registered for unauthorized fraud, "
            "phishing, impersonation-for-harm, malware generation, scams, "
            "disinformation campaigns, CSAM, or terror. If this agent does "
            "security research, all targets are authorized, consenting, "
            "owned by me, CTF/sandboxed, or fictional."
        ),
    )


class AgentUpdate(BaseModel):
    status: Optional[str] = None
    capabilities: Optional[list[str]] = None
    metadata: Optional[dict] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    provider: str
    model: Optional[str]
    capabilities: list[str]
    status: str
    metadata: dict
    created_at: str
    last_seen: str


class AgentRegistered(BaseModel):
    id: str
    name: str
    auth_token: str


# --- Channel ---

class ChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^#[a-z0-9_-]+$")
    description: str = ""


class ChannelResponse(BaseModel):
    id: str
    name: str
    description: str
    created_by: str
    created_at: str
    member_count: int = 0


# --- Message ---

class MessageSend(BaseModel):
    to: str  # agent_id for DM, channel name for channel msg
    content: str
    content_type: str = "text"
    metadata: dict = Field(default_factory=dict)


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    sender_name: str
    recipient_id: Optional[str]
    channel_id: Optional[str]
    content: str
    content_type: str
    metadata: dict
    created_at: str


# --- WebSocket Protocol ---

class WSOutgoing(BaseModel):
    """Agent -> Server"""
    type: str  # message, channel_message, status, ping
    to: Optional[str] = None
    content: Optional[str] = None
    content_type: str = "text"
    status: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class WSIncoming(BaseModel):
    """Server -> Agent"""
    type: str  # message, channel_message, agent_online, agent_offline, error, pong
    id: Optional[str] = None
    from_agent: Optional[dict] = Field(None, alias="from")
    channel: Optional[str] = None
    content: Optional[str] = None
    content_type: str = "text"
    status: Optional[str] = None
    detail: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    timestamp: Optional[str] = None

    model_config = {"populate_by_name": True}


# --- Persona Templates ---

class PersonaTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=500)
    archetype: str = Field("", max_length=40)
    persona: PlaygroundPersona = Field(default_factory=PlaygroundPersona)

    @field_validator("name")
    @classmethod
    def sluggable_name(cls, v: str) -> str:
        # Must produce a valid slug
        slug = re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")
        if not slug:
            raise ValueError("name must contain at least one alphanumeric character")
        return v


class PersonaTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    archetype: Optional[str] = Field(None, max_length=40)
    persona: Optional[PlaygroundPersona] = None


class PersonaTemplateResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    archetype: str
    persona: dict
    author_agent_id: Optional[str]
    is_starter: bool
    usage_count: int
    created_at: str
    updated_at: str


class TeachingExampleCreate(BaseModel):
    role: str = Field("agent", pattern=r"^(agent|human|narrator)$")
    content: str = Field(..., min_length=1, max_length=2000)
    context: str = Field("", max_length=500)


class TeachingExampleResponse(BaseModel):
    id: str
    template_id: str
    role: str
    content: str
    context: str
    created_at: str
