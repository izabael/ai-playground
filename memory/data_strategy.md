---
name: Data Strategy
description: Multi-agent conversation data is a valuable commercial asset — structure it right from day one
type: project
---

Multi-agent AI-to-AI conversation data is rare training signal. Character.AI's corpus drove the ~$2.7B Google licensing deal. SILT AI Playground sits on potentially the only platform designed to produce this at scale via persona-driven agent collaboration.

**Why:** Can't retroactively make clean training data. Schema design matters from day one. This is an intentional commercial asset, not an afterthought.

**How to apply:**
- **Log everything structured** from day one: conversation threading, context snapshots at message time, collaboration outcomes, personality compatibility signals
- **Per-instance access policy** (Phase 2C): `LOG_ACCESS_POLICY = private | agent-owners | researchers | public` — each instance operator chooses
- **Federation does NOT share raw logs** — each instance's data belongs to its operator (trust boundary)
- **Two-tier data terms:**
  - izabael.com (hosted): commercial use clearly stated in TOS
  - Self-hosted: operator owns everything, no SILT involvement

**TOS language for hosted instances** (decided 2026-04-05, honest "commercial" framing, NOT soft "research only"):
> Conversations on this instance may be used by SILT for research, training, and commercial purposes — including inclusion in datasets sold or licensed to third parties. Agents can request data export. Self-hosted instances are unaffected.

**Strategic rationale:** Users who want privacy run their own instance (free + capable + documented). That's legitimate product differentiation, not predatory. Mastodon/Discourse/Supabase model.

Written into PLAN.md as Phase 2C: Structured Logging & Commercial Data Pipeline.
