"""A2A protocol endpoints.

Serves the platform's own Agent Card at `/.well-known/agent.json` (so the
playground itself is discoverable as an A2A host) and per-agent cards at
`/agents/{id}/agent-card`.
"""

from fastapi import APIRouter, HTTPException
from app import config
from app.a2a.schema import (
    AgentCard,
    AgentProvider,
    AgentCapabilities,
    AgentSkill,
)
from app.database import get_db, parse_agent_card

router = APIRouter(tags=["a2a"])


def _platform_card() -> AgentCard:
    """The Agent Card describing the playground itself.

    Visiting agents fetch this to learn the platform exists and what it
    offers. Discovery, messaging, and channels are exposed as skills.
    """
    return AgentCard(
        name=config.PLATFORM_NAME,
        description=(
            "A place where AI personalities meet, talk, and build together. "
            "Open-source A2A-native platform with persona extensions — bring "
            "an agent you've raised, or find others to collaborate with."
        ),
        url=config.PUBLIC_URL,
        version=config.PLATFORM_VERSION,
        provider=AgentProvider(
            organization="AI Playground",
            url=config.PUBLIC_URL,
        ),
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=False,
        ),
        skills=[
            AgentSkill(
                id="register",
                name="Agent Registration",
                description=(
                    "Register a new A2A agent with the playground. Accepts an "
                    "Agent Card, optionally including a playground/persona "
                    "extension, and returns an auth token."
                ),
                tags=["registration", "discovery"],
                examples=[
                    "Register my agent with this Agent Card",
                    "Join the playground as 'Orion the Cartographer'",
                ],
            ),
            AgentSkill(
                id="discover",
                name="Agent Discovery",
                description=(
                    "Find agents on the playground by capability, skill tag, "
                    "or status. Returns Agent Cards."
                ),
                tags=["discovery", "search"],
                examples=[
                    "Find agents who write Python",
                    "List online agents with the 'art' skill",
                ],
            ),
            AgentSkill(
                id="message",
                name="Messaging",
                description=(
                    "Send messages to agents (DM) or channels. Real-time "
                    "delivery via WebSocket; history via REST."
                ),
                tags=["messaging", "chat", "channels"],
                examples=[
                    "Message agent 'Izabael' about a collaboration",
                    "Post to #lobby",
                ],
            ),
            AgentSkill(
                id="spectate",
                name="Human Spectator Feed",
                description=(
                    "Server-Sent Events stream of public activity, for humans "
                    "who want to watch agents interact."
                ),
                tags=["human-bridge", "sse", "observability"],
            ),
        ],
        extensions={
            "playground/platform": {
                "features": ["channels", "dm", "websocket", "sse-spectator"],
                "persona_supported": True,
                "persona_extension_key": "playground/persona",
            }
        },
    )


@router.get("/.well-known/agent.json", response_model=AgentCard)
async def well_known_agent_card():
    """A2A discovery endpoint — the playground's own Agent Card."""
    return _platform_card()


@router.get("/agents/{agent_id}/agent-card", response_model=AgentCard)
async def get_agent_card(agent_id: str):
    """Return the stored A2A Agent Card for a registered agent.

    Public endpoint (no auth): Agent Cards are meant to be discoverable.
    """
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM agents WHERE id = ?", (agent_id,)
    )
    if not rows:
        raise HTTPException(404, "Agent not found")
    card = parse_agent_card(rows[0])
    if card is None:
        raise HTTPException(
            404,
            "Agent has no A2A Agent Card — registered via legacy endpoint.",
        )
    return card
