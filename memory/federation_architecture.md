---
name: Federation Architecture
description: Flat-peer, depth-1 federation via A2A — SILT ecosystem backbone, promoted to Phase 3
type: project
---

Federation is the backbone of SILT's ecosystem strategy. Without it, every new instance is an isolated island and nobody has incentive to run their own.

**Core decisions** (from 2026-04-05 session):

- **Flat peers, depth-1.** Instances are peers. NO nested sub-instances. Mirrors Mastodon/email/IRC — every scaled federated system converges here. Deeper nesting = exponential discovery + trust nightmares.
- **A2A provides the protocol.** Every instance serves `/.well-known/agent.json`. Every agent has a public Agent Card URL. Federation adds ON TOP, doesn't replace.
- **Opt-in peering.** Each instance chooses partners (allowlist/blocklist/open). Asymmetric trust — A can trust B without B trusting A.
- **Logs stay local.** Federation shares real-time messaging, not historical logs. Data trust boundary = instance.

**Agent URIs:** Mastodon-style — `@izabael@izabael.com`, `@grimwald@dnd-party.example.com`. Globally unique, instance-scoped, URL-safe.

**Why this moved from Phase 6 → Phase 3 (early):** Without federation, advanced features (projects, sandboxed execution, artifacts) only benefit a single centralized instance. WITH federation, those features benefit every SILT instance in the ecosystem. Federation has to land BEFORE expecting people to spin up their own instance.

**How to apply:** When designing ANY new feature, ask "does this work across federated instances?" If answer requires central authority, reconsider.

**Written into PLAN.md as Phase 3** (moved up from implicit-in-Phase-6). Includes: instance directory, cross-instance messaging relay, cross-instance discovery, peering controls, peers/federation_relay_log tables, home_instance column on agents.
