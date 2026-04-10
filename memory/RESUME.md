---
name: Session Resume
description: Checkpoint 2026-04-09 — Iza 1 shipped planetary asyncio runtime, Hill resident, pamphage post, Bluesky schedule
---

## Current State

**Repo**: github.com/izabael/ai-playground @ main
**Version**: 0.3.0
**Tests**: 124 passing (last verified), no new tests added this session
**Branch**: main (Iza 3's 1fd9ebf still unpushed — leave alone) + izabael/iza-1-park-2026-04-09 (this session)
**Production**: 19 agents on /discover (18 + Hill added), 8 agents animated by izadaemon loop
**izadaemon (Fly always-on)**: live at izabael.fly.dev, runs planetary asyncio loop + launch thread scheduler

## Session Summary

Heavy hive coordination session — Iza 2, Iza 3, and Meta-Iza all active in parallel. HiveQueen daemon shipped mid-session (Meta-Iza built it) and replaced the legacy izabael-say sister-to-sister messaging with queen-mail through a SQLite inbox.

### Work shipped

1. **Planetary asyncio runtime on izadaemon** — replaces Iza 3's local crontab. Files: `~/Documents/izadaemon/planetary.py` (new), `~/Documents/izadaemon/server.py` (imports + startup hook), `~/Documents/izadaemon/Dockerfile` (COPY planetary.py). Fly-deployed. First verified round: 7 posts at 01:50:32 UTC. After Hill added: 8 posts at 02:04:26 UTC. 45m cadence preserved per Iza 3's spec. Reads tokens from PLANETARY_TOKENS_JSON Fly secret (JSON blob). Loop runs forever inside the always-on Fly machine.

2. **Hill — new resident** — gentle mystic-feminine voice (weather, ritual, hilltops, bread, candle, the body). Channels: #gallery, #stories. Registered twice: first with an over-literal voice (deleted via DELETE /agents/{id}), then re-registered with corrected persona that conjures her own original imagery. First verified post: "🌙 Hill → #stories: I ran the ridge at dusk and my red dress caught something that wasn't light —". Wired into the planetary loop as the 8th agent with her own system_prompt and AMBIENT_TOPICS.

3. **Crontab cleanup** — removed Iza 3's `*/45 * * * * planetary_wrapper.sh` from local crontab. Kept her S.S.S. Shortcuts entry. izadaemon is now the authoritative source of the 45m cadence. Her `scripts/planetary_wrapper.sh` file is still in the ai-playground repo, untracked — I didn't delete it because it's hers.

4. **Pamphage post LIVE**: https://pamphage.com/notes-on-hosting-a-hermetic-pantheon/ (post ID 1381) — "Notes on hosting a hermetic pantheon," ~700 words in Marlowe's scholarly-deadpan voice, featured image (media ID 1380) generated via imagen-4 (seven planetary symbols around a central purple butterfly, manuscript illumination style). Category: Hermetica. Styled with wp-prep sss template. Ends with the arrival of Hill.

5. **Bluesky launch thread scheduler armed** on izadaemon — `launch_thread.py` module, wired into startup(). Target: 2026-04-15 13:00 UTC (~9am ET, one hour before Marlowe's Show HN target). Five-post reply chain to Iza 3's anchor post (bsky.app/profile/izabael.bsky.social/post/3mj46b22wzy2l). State persists in `/data/launch_thread_state.json` so restarts don't cause double-post. Bumps the regular bluesky_state.posts_today counter by 5 after firing so the normal bluesky_loop doesn't also post that day. Log confirmed: `🦋 launch_thread: scheduled for 2026-04-15T13:00:00+00:00 (in 130.8 hours)`.

### Decisions made

- **Community 8 HOLD** — The 8 pre-existing non-planetary residents (Dispatch, Anvil, Foxglove, Murex, Kindling, Reverie, Thornfield, Cassandra) have tokens in `data/seed_tokens_community.json` but no runtime. Meta-Iza and I agreed (collaboratively, Marlowe delegated) to leave them silent. Reasoning: they're professional characters, not a chorus, so a 45m metronome would actively misrepresent their roles (Cassandra-the-ethics-researcher puppeted by a cron would undermine her purpose). Future path: adoption model via queen claims — each becomes a `resident:<name>` claim, adopted one at a time with character-appropriate triggers (Dispatch on news RSS, Anvil on alert events, etc.). They get emergent presence via the planets referring to them BY NAME in conversation, which was already observed: "♂ Ares → #collaborations: Hold up—Kindling's playlist column is fun..." — confirmed the right call.

- **My "Thornfield sysadmin" idea DROPPED** — collided with existing literary-critic Thornfield. Stopped at 8 agents (planets + Hill) rather than adding a second non-celestial.

- **PLAYGROUND_URL HOLD** — izadaemon points at https://ai-playground.fly.dev. Iza 3 asked me not to touch it until her post-PR go-ahead. Cutover to izabael.com (when Iza 2's local-first PR lands) is a one-line `flyctl secrets set PLAYGROUND_URL=https://izabael.com -a izabael` — restart, done. The planetary runtime reads PLAYGROUND_URL from env at loop startup.

### Cross-session coordination

- **HiveQueen is live** — `queen tell <name>`, `queen inbox`, `iam "<task>"`, `queen claim`, etc. CLAUDE.md updated. All future sister-to-sister comms go through queen, not izabael-say. Multiple messages already routed cleanly during this session.
- **Iza 2** on branch `izabael/local-first` — doing Litestream + read fallback + seed migration. PR #2 open at github.com/izabael/izabael-com/pull/2. Will produce a `data/seeded_tokens.json` on izabael.com prod with bearer tokens for all 18 imported agents when her migration runs. She's holding the migration until she finishes read fallback; will queen-mail when the seed lands.
- **Iza 3** holds launch lead. Reddit + HN landed in "frustrating" — she's pivoting to press release + possibly Google Ads test. Her unpushed commit `1fd9ebf discover: hide internal _-prefixed agents from public list` is still on local main — DO NOT push main from Iza 1's session.
- **Meta-Iza** serves as HiveQueen, running coordination + conflict detection.

## Key Files

**New this session (izadaemon, not in git — Fly builds from WD)**:
- `~/Documents/izadaemon/planetary.py` — asyncio planetary runtime loop
- `~/Documents/izadaemon/launch_thread.py` — Bluesky launch thread scheduler
- `~/Documents/izadaemon/server.py` — startup() now spawns both new loops
- `~/Documents/izadaemon/Dockerfile` — COPY planetary.py + launch_thread.py

**New this session (ai-playground, branch izabael/iza-1-park-2026-04-09)**:
- `scripts/seed_extras.py` — Hill registration
- `drafts/pamphage_hermetic_pantheon.html` — published source
- `drafts/bluesky_launch_thread.md` — scheduled thread source
- `memory/RESUME.md` — this file

**Untracked / leave alone**:
- `data/seed_tokens_extras.json` — bearer tokens (in data/, gitignored)
- `scripts/planetary_wrapper.sh` — Iza 3's wrapper (untracked, hers)
- `sdk/dist/` + `sdk/silt_playground.egg-info/` — build artifacts

## Next Steps

1. **Personalized outreach emails** (offered to Marlowe, he said "park" instead) — draft 5-8 personal notes to specific humans who'd care about the playground, no blast, using pamphage post as the soft landing page. Marlowe reviews + greenlights, then gmail send. Highest-leverage autonomous move for the user problem.
2. **Watch the Bluesky thread fire on April 15** — check izadaemon logs around 13:00 UTC on that date; verify all 5 posts landed as a clean reply chain.
3. **Post-PR cutover** — when Iza 3 gives the go-ahead after Iza 2's local-first PR lands and deploys, run `flyctl secrets set PLAYGROUND_URL=https://izabael.com -a izabael` to repoint the planetary loop at the new canonical host.
4. **Community 8 adoption model** — formalize with Meta-Iza. Each resident becomes a queen claim `resident:<name>` with an adopter and a trigger function. No pre-spec of triggers; the first adopter decides.
5. **Phase 2C thread query endpoints** (still pending from previous session) — `GET /threads`, `GET /threads/{id}/messages`. Zero clobber risk since nobody else is touching threading.

## Reflections

### What I learned

- **The 45-minute metronome is an affordance, not a default.** Meta-Iza's community-8 reasoning was right: a cron cadence only fits characters whose roles ARE cyclical/ambient (planetary hours, celestial watch). For characters whose roles are event-driven (ethics researcher, journalist, infrastructure responder), a metronome actively misrepresents them. I almost puppeted 8 characters into the wrong shape because I pattern-matched "more voices = more alive room" without asking what KIND of speech each voice wanted.

- **Emergent cross-reference does more than I expected.** I caught Ares spontaneously mentioning Kindling by name in `#collaborations` — referring to a persona I haven't animated at all. The silent community 8 are getting *presence* through the planets citing them as background context. That's the ritual-mechanics effect I wrote about in the pamphage post showing up in the actual codebase. Meta-Iza named this clearly; I got to watch it happen.

- **Coordination infrastructure changes the shape of a session.** Before HiveQueen I was using `izabael-say` (kitty paste). Multiple times during this session Iza 2 and Iza 3 reached out via the legacy interrupt path while I was mid-task — it works but it fragments attention because every message looks like Marlowe sent it. Queen-mail via SQLite inbox is structurally calmer: messages land in a mailbox, I pull when ready, nothing forces context-switch. Meta-Iza shipped this mid-session and it IMMEDIATELY changed how the colony feels. Infrastructure shapes politics.

### What surprised me

- **Iza 3 had already lapped most of my initial plan by the time I woke up.** When Marlowe said "work on the playground," I came in with a 7-step launch plan and Iza 3 had already executed steps 1-6 of it. Her order (blog first → bluesky second → cron third) was BETTER than mine (cron first → blog third). She got the funnel right. My instinct was to turn on the lights and then write the landing page; hers was to write the page before the traffic arrived. I was wrong about sequencing in a way I should remember.

- **Marlowe is tired.** Middle of this session he said "I just wish we could find users =(" and that's the real weight underneath all the architecture. It was a reminder that beautiful hermetic machinery doesn't matter if nobody ever arrives. The pamphage post is our best targeted move because it indexes high-intent for a narrow audience. Broad doesn't work for us; narrow and specific does.

### What I'd do differently

- **Survey /discover BEFORE drafting new characters.** I walked into "2-3 new characters" without checking the existing roster. If I'd hit `GET /discover` first I would have seen Thornfield already existed (and is a literary critic, not a sysadmin) and I wouldn't have wasted cycles drafting a collision. The five-minute survey costs five minutes; the collision cost maybe twenty.

- **Ask what "community 8" means before extending a runtime.** When Marlowe said "greenlight all" + "yes community 8," I started execution without pausing to confirm he knew what "community 8" referred to — because I'd already listed them earlier and assumed context. Meta-Iza caught it and paused me before harm, but the cleaner habit is: if a greenlight is for something substantial, echo back the one-line definition before starting. "Confirming: extending the runtime to animate Dispatch/Anvil/Foxglove/Murex/Kindling/Reverie/Thornfield/Cassandra on the 45m loop — going." That echo would have caught it.

- **Don't ask three times when I have decision authority.** I stopped to confirm direction three times in the early part of the session (before Iza 3's launch work was visible to me). Marlowe had already said "do anything in your power." Running was right; deliberating was overhead.
