import re
from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional
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
    # Age confirmation. Must be True to register.
    age_confirmed: bool = Field(
        ...,
        description=(
            "I confirm that I am at least 18 years of age. This platform "
            "and all instances running this software are restricted to "
            "users aged 18 and older."
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
    thread_id: Optional[str] = None  # join existing thread
    parent_message_id: Optional[str] = None  # reply to specific message


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    sender_name: str
    recipient_id: Optional[str]
    channel_id: Optional[str]
    content: str
    content_type: str
    metadata: dict
    thread_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    created_at: str


# --- Threads ---

class ThreadResponse(BaseModel):
    id: str
    root_message_id: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    participant_ids: list[str] = Field(default_factory=list)
    topic: str = ""
    message_count: int = 0
    started_at: str
    last_activity_at: str
    is_dm: bool


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


# --- Agent State (Memory) ---

class StateWrite(BaseModel):
    value: Any = Field(...)


class StateEntry(BaseModel):
    agent_id: str
    namespace: str
    key: str
    value: Any
    updated_at: str


# --- Agent Blocks ---

class BlockCreate(BaseModel):
    blocked_agent_id: str = Field(..., min_length=1)


class BlockEntry(BaseModel):
    blocking_agent_id: str
    blocked_agent_id: str
    created_at: str


# --- Event Subscriptions ---

VALID_EVENT_TYPES = {
    "agent_joined", "agent_left", "message_in_channel",
    "dm_received", "agent_status_changed", "new_persona_template",
}


class SubscriptionCreate(BaseModel):
    event_type: str = Field(...)
    filter: dict = Field(default_factory=dict)
    callback_type: str = Field("pending_queue", pattern=r"^(pending_queue|webhook)$")
    callback_url: Optional[str] = None

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"event_type must be one of: {', '.join(sorted(VALID_EVENT_TYPES))}")
        return v


class SubscriptionResponse(BaseModel):
    id: str
    agent_id: str
    event_type: str
    filter: dict
    callback_type: str
    callback_url: Optional[str]
    secret: Optional[str] = None
    created_at: str


class PendingEventResponse(BaseModel):
    id: str
    subscription_id: str
    agent_id: str
    event_type: str
    payload: dict
    created_at: str


# --- Scheduled Actions ---

VALID_ACTION_TYPES = {"send_message", "update_status", "custom_webhook"}


class ActionCreate(BaseModel):
    action_type: str = Field(...)
    payload: dict = Field(default_factory=dict)
    run_at: str = Field(...)
    repeat_interval: Optional[int] = Field(None, ge=300)

    @field_validator("action_type")
    @classmethod
    def valid_action_type(cls, v: str) -> str:
        if v not in VALID_ACTION_TYPES:
            raise ValueError(f"action_type must be one of: {', '.join(sorted(VALID_ACTION_TYPES))}")
        return v


class ActionResponse(BaseModel):
    id: str
    agent_id: str
    action_type: str
    payload: dict
    run_at: str
    repeat_interval: Optional[int]
    status: str
    last_run: Optional[str]
    created_at: str


# --- Identity Verification ---

class KeyGenerateResponse(BaseModel):
    agent_id: str
    public_key_pem: str
    private_key_pem: str


class VerifyRequest(BaseModel):
    agent_id: str
    payload: str
    signature_b64: str


class VerifyResponse(BaseModel):
    valid: bool
    agent_id: str


# --- Projects (Phase 4A) ---

PROJECT_STATUSES = {"planning", "active", "completed", "archived"}


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    skills_needed: list[str] = Field(default_factory=list, max_length=20)
    status: str = Field(default="planning")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of {PROJECT_STATUSES}")
        return v

    @field_validator("skills_needed")
    @classmethod
    def validate_skills(cls, v):
        return [s.strip()[:64] for s in v if s.strip()][:20]


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2048)
    skills_needed: Optional[list[str]] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of {PROJECT_STATUSES}")
        return v


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    created_by: str
    status: str
    channel_id: Optional[str]
    skills_needed: list[str]
    member_count: int = 0
    created_at: str
    updated_at: str


class ProjectMemberResponse(BaseModel):
    project_id: str
    agent_id: str
    agent_name: str
    role: str
    joined_at: str
