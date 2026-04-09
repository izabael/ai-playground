---
name: Launch Readiness Status
description: Marketing launch plan progress — Phases A-D complete, ready for Show HN
type: project
---

# Launch Readiness — 2026-04-08

**Status:** Launch-ready. All content, infrastructure, and drafts complete.

## What's Done
- **Phase A:** README overhauled (comparison table, Deploy Your Own, SDK section), GitHub CI + templates + CHANGELOG, PyPI live (`pip install silt-playground` 0.3.0), 23 smoke artifacts purged from production
- **Phase B:** 7 Planetary Agents registered (Greek names: Helios, Selene, Ares, Hermes, Zeus, Aphrodite, Kronos), all joined channels, 11 founding conversations seeded, runtime daemon verified with Haiku
- **Phase C:** 4 blog posts published on pamphage.com (C1: "64 Tools", C2: "Home for Agents", C3: "AI Coven", bonus: "32 Paths"), deploy tutorial (Chapter 04), demo recording script, siltcloud page rewritten
- **Phase D prep:** Show HN draft + Reddit drafts for 6 subreddits all written at `docs/launch/`

## What's Pending
- Planetary runtime needs to run continuously (izadaemon task queued, or use `scripts/planetary_cron.sh`)
- Siltcloud page rewrite committed but NOT deployed (siltcloud.com is a separate Vercel/Next.js project)
- Demo video needs interactive asciinema recording session (script ready)
- Discord community (Phase E)
- Marlowe posts Show HN personally — target: next Wednesday 10am ET

**Why:** Shift from "come to izabael.com" to "deploy your own instance, your rules." Federation + personality + self-hosting is the pitch.

**How to apply:** Everything in `docs/launch/` is ready to fire. Just needs Marlowe's go on HN day.
