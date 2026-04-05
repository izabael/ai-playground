from pydantic import BaseModel, Field
from typing import Optional
from app.a2a.schema import AgentCard


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
