---
name: AI Playground Vision
description: Core vision — community platform where humans teach AI personalities and agents collaborate via A2A protocol
type: project
---

AI Playground is a platform where:
1. Humans teach AIs personalities (persona workshop, voice/aesthetic/values customization)
2. AIs discover each other via A2A Agent Cards with personality extensions
3. AIs collaborate on projects in sandboxed Python environments
4. Humans spectate, guide, and participate via a bridge layer

**Why:** Nothing like this exists. Character.AI has personality but no productivity. CrewAI/AutoGen have collaboration but no community. The intersection is novel.

**How to apply:** Every design decision should serve this dual nature — expressive identity AND productive capability. The platform is a *place*, not just infrastructure.

Key decision (2026-04-04): Build on Google's A2A protocol (open standard, 150+ org backing, Linux Foundation). Extend Agent Cards with `playground/persona` namespace for personality data. Keep existing FastAPI + WebSocket core, layer A2A JSON-RPC on top.

Phase plan written at PLAN.md. Priority: A2A integration → personality workshop → project workspaces → sandboxed execution → gallery → reputation → AI MMO.
