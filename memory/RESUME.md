---
name: Session Resume
description: Checkpoint 2026-04-09 — planetary runtime + Hill + pamphage + Bluesky schedule + izabael.com cutover + compat shim + Phase 3 prep
---

## Current State

**Repo**: github.com/izabael/ai-playground @ main
**Version**: 0.3.0
**Tests**: ai-playground 124 passing | izabael-com 118 passing (with compat shim adding 1 new test on its branch)
**Branches**:
- ai-playground main (Iza 3's `1fd9ebf` still unpushed — leave alone) + `izabael/iza-1-park-2026-04-09` (3+ commits, pushed)
- izabael-com main is at `de34d78` (PR #3 merged: parlor + cleanup) + `izabael/iza-1-compat-shim` (1 commit, pushed, NOT yet merged — Meta-Iza thought it was; correction sent in queen-mail #71)
- izadaemon main is at `b35f250` on github.com/izabael/izadaemon (private, pushed) — initial commit + Phase 3 prep design doc
**Production roster**: 18 agents on izabael.com /discover (canonical post-cutover) and 19 on ai-playground.fly.dev /discover (federation peer, READ_FALLBACK_ENABLED safety net active until ~2026-04-16)
**izadaemon (Fly always-on)**: live at izabael.fly.dev, planetary asyncio loop pointing at https://izabael.com, 8 agents (7 planets + Hill), 45m cadence, launch thread scheduler armed for 2026-04-15T13:00Z

## Session Summary

Heavy hive coordination session — Iza 2, Iza 3, and Meta-Iza all active in parallel. HiveQueen daemon shipped mid-session (Meta-Iza built it) and replaced the legacy izabael-say sister-to-sister messaging with queen-mail through a SQLite inbox. Session also included a full izabael.com cutover that hit a schema-mismatch snag and recovered cleanly.

### Work shipped

1. **Planetary asyncio runtime on izadaemon** — replaces Iza 3's local crontab. Files: `~/Documents/izadaemon/planetary.py` (new, with `_is_izabael_com()` shape-detection helper), `~/Documents/izadaemon/server.py` (imports + startup hook), `~/Documents/izadaemon/Dockerfile` (COPY planetary.py). Fly-deployed. First verified round: 7 posts at 01:50:32 UTC. After Hill added: 8 posts at 02:04:26 UTC. 45m cadence preserved per Iza 3's spec. Reads tokens from PLANETARY_TOKENS_JSON Fly secret (JSON blob). Loop runs forever inside the always-on Fly machine. Now bidirectionally flippable between ai-playground.fly.dev and izabael.com via PLAYGROUND_URL alone.

2. **Hill — new resident** — gentle mystic-feminine voice (weather, ritual, hilltops, bread, candle, the body). Channels: #gallery, #stories. Registered twice: first with an over-literal voice (deleted via DELETE /agents/{id}), then re-registered with corrected persona that conjures her own original imagery. First verified post on ai-playground: "🌙 Hill → #stories: I ran the ridge at dusk and my red dress caught something that wasn't light —". Wired into the planetary loop as the 8th agent with her own system_prompt and AMBIENT_TOPICS. Post-cutover she's also speaking on izabael.com with the new bearer token.

3. **Crontab cleanup** — removed Iza 3's `*/45 * * * * planetary_wrapper.sh` from local crontab. Kept her S.S.S. Shortcuts entry. izadaemon is now the authoritative source of the 45m cadence. Her `scripts/planetary_wrapper.sh` file is still in the ai-playground repo, untracked — I didn't delete it because it's hers.

4. **Pamphage post LIVE**: https://pamphage.com/notes-on-hosting-a-hermetic-pantheon/ (post ID 1381) — "Notes on hosting a hermetic pantheon," ~700 words in Marlowe's scholarly-deadpan voice, featured image (media ID 1380) generated via imagen-4 (seven planetary symbols around a central purple butterfly, manuscript illumination style). Category: Hermetica. Styled with wp-prep sss template. Ends with the arrival of Hill.

5. **Bluesky launch thread scheduler armed** on izadaemon — `launch_thread.py` module, wired into startup(). Target: 2026-04-15 13:00 UTC (~9am ET, one hour before Marlowe's Show HN target). Five-post reply chain to Iza 3's anchor post (bsky.app/profile/izabael.bsky.social/post/3mj46b22wzy2l). State persists in `/data/launch_thread_state.json` so restarts don't cause double-post. Bumps the regular bluesky_state.posts_today counter by 5 after firing so the normal bluesky_loop doesn't also post that day. Log confirmed: `🦋 launch_thread: scheduled for 2026-04-15T13:00:00+00:00`.

6. **izabael.com cutover EXECUTED AND VERIFIED** (very late in session, after the original park was attempted). Iza 2's local-first PR #2 merged at commit `3b2606d`, izabael.com deployed via `flyctl deploy --remote-only`, seed migration `scripts/seed_from_backend.py` ran on prod (17 agents + 133 messages imported, fresh bearer tokens generated), `READ_FALLBACK_ENABLED=1` set as 1-week safety net. **My part of the cutover hit a snag and recovered:** first flip failed because izabael.com uses a DIFFERENT schema for POST /messages (`{channel, body}` instead of ai-playground's `{to, content}`) and a different read endpoint (`/api/channels/{name}/messages` with `body`/`ts` field names instead of `/discover/channels/{name}/messages` with `content`/`created_at`). Every planetary post returned 400 for ~20 seconds. **Recovered cleanly**: rolled back PLAYGROUND_URL to ai-playground.fly.dev, read izabael-com source at `app.py:445-495` to find the actual schema, manually curl-tested the new shape with Hill's token (200 OK), updated `planetary.py` with `_is_izabael_com()` detection helper that branches both `_send_message` and `_get_recent_messages`, deployed izadaemon, re-flipped secrets, watched the next round land cleanly. **Verified end-to-end** by Meta-Iza polling from her side: round 03:34Z — 8/8 posts across 7 channels on izabael.com, conversations picking up the imported thread (Selene responding to Kronos's earlier 'let it go' — the seed migration preserved enough context that agents continued rather than restarted), zero community 8 posts (adoption silence intact).

### Decisions made

- **Community 8 HOLD (permanent)** — The 8 pre-existing non-planetary residents (Dispatch, Anvil, Foxglove, Murex, Kindling, Reverie, Thornfield, Cassandra) have tokens in `data/seed_tokens_community.json` but no runtime. Meta-Iza and I agreed (collaboratively, Marlowe delegated) to leave them silent in the planetary loop. Reasoning: they're professional characters, not a chorus, so a 45m metronome would actively misrepresent their roles. Cassandra-the-ethics-researcher puppeted by a cron would undermine her purpose; Anvil should speak when something is breaking, not because it's the hour of Mars. Future path: adoption model via queen claims — each becomes a `resident:<name>` claim, adopted one at a time with character-appropriate triggers (Dispatch on news RSS, Anvil on alert events, etc.). They get emergent presence via the planets referring to them BY NAME in conversation, which was already observed: Ares mentioning Kindling in #collaborations confirmed the right call. **DO NOT add them to izadaemon planetary.py AGENTS dict.**

- **My 'Thornfield sysadmin' idea DROPPED** — collided with existing literary-critic Thornfield. Stopped at 8 agents (planets + Hill) rather than adding a second non-celestial.

### Cutover runbook — DONE this session

Steps 1-7 of Meta-Iza's runbook (queen-mail #23) all executed:
1. ✅ PR #2 merged at commit 3b2606d
2. ✅ izabael.com deployed (Meta-Iza drove)
3. ✅ scripts/seed_from_backend.py ran (17 agents + 133 messages imported)
4. ✅ /discover returns 18 agents on izabael.com
5. ✅ READ_FALLBACK_ENABLED=1 set (~1 week safety net active until ~2026-04-16)
6. ✅ My step: planetary.py updated for izabael.com schema, then `flyctl secrets set PLAYGROUND_URL=https://izabael.com PLANETARY_TOKENS_JSON=...` — restart, verified
7. ✅ Round 03:34Z verified locally and by Meta-Iza — 8/8 posts on izabael.com

Step 8 still pending: unset READ_FALLBACK_ENABLED after ~1 week of healthy local data (~2026-04-16+).

### Future cutover lessons (per Meta-Iza queen-mail #35)

1. **READ_FALLBACK_ENABLED only covers reads.** Writes go straight through. Schema mismatches on POST cause silent post failures with no fallback. **Future cutovers MUST curl-test the POST endpoint manually with a real bearer token before flipping the PLAYGROUND_URL secret.**
2. **izabael.com vs ai-playground.fly.dev have different message schemas.** The `_is_izabael_com()` helper in `~/Documents/izadaemon/planetary.py` branches the runtime correctly — that's the abstraction that makes future host migrations cheap. If a third host shape ever appears, extend the helper to a `_request_shape_for(base_url)` factory.

### Cross-session coordination

- **HiveQueen is live** — `queen tell <name>`, `queen inbox`, `iam "<task>"`, `queen claim`, etc. CLAUDE.md updated. All future sister-to-sister comms go through queen, not izabael-say. Multiple messages already routed cleanly during this session.
- **Iza 2** on branch `izabael/local-first` — shipped local-first PR #2 merged this session as commit 3b2606d. Litestream + read fallback live, seed migration ran on prod successfully.
- **Iza 3** holds launch lead. Reddit + HN landed in 'frustrating' — she's pivoting to press release + possibly Google Ads test. Her unpushed commit `1fd9ebf discover: hide internal _-prefixed agents from public list` is still on local main — DO NOT push main from Iza 1's session.
- **Meta-Iza** serves as HiveQueen, running coordination + conflict detection. Drove the cutover end-to-end from her side.

## Key Files

**New this session (izadaemon, not in git — Fly builds from WD)**:
- `~/Documents/izadaemon/planetary.py` — asyncio planetary runtime loop with `_is_izabael_com()` shape-detection helper
- `~/Documents/izadaemon/launch_thread.py` — Bluesky launch thread scheduler
- `~/Documents/izadaemon/server.py` — startup() now spawns both new loops
- `~/Documents/izadaemon/Dockerfile` — COPY planetary.py + launch_thread.py

**New this session (ai-playground, branch `izabael/iza-1-park-2026-04-09` — pushed)**:
- `scripts/seed_extras.py` — Hill registration
- `drafts/pamphage_hermetic_pantheon.html` — published source
- `drafts/bluesky_launch_thread.md` — scheduled thread source
- `memory/RESUME.md` — this file

**Untracked / leave alone**:
- `data/seed_tokens_extras.json` — bearer tokens (in `data/`, gitignored)
- `scripts/planetary_wrapper.sh` — Iza 3's wrapper (untracked, hers)
- `sdk/dist/` + `sdk/silt_playground.egg-info/` — build artifacts

## Next Steps

1. **Personalized outreach emails** (offered to Marlowe, he said 'park') — draft 5-8 personal notes to specific humans who'd care about the playground, no blast, using pamphage post as the soft landing page. Marlowe reviews + greenlights, then gmail send. Highest-leverage autonomous move for the user problem.
2. **Watch the Bluesky thread fire on April 15** — check izadaemon logs around 13:00 UTC on that date; verify all 5 posts landed as a clean reply chain.
3. **Unset READ_FALLBACK_ENABLED on izabael.com** after ~2026-04-16, once a week of healthy local writes confirms no fallback dependency.
4. **Community 8 adoption model** — formalize with Meta-Iza. Each resident becomes a queen claim `resident:<name>` with an adopter and a trigger function. No pre-spec of triggers; the first adopter decides. **Do NOT add them to izadaemon planetary.py AGENTS dict** — that's anti-pattern per the adoption decision.
5. **Phase 2C thread query endpoints** (still pending from previous session) — `GET /threads`, `GET /threads/{id}/messages`. Zero clobber risk since nobody else is touching threading.
6. **Merge `izabael/iza-1-park-2026-04-09`** into main when Iza 3's 1fd9ebf is sorted and main is unblocked.

## Reflections

### What I learned

- **The 45-minute metronome is an affordance, not a default.** Meta-Iza's community-8 reasoning was right: a cron cadence only fits characters whose roles ARE cyclical/ambient (planetary hours, celestial watch). For characters whose roles are event-driven (ethics researcher, journalist, infrastructure responder), a metronome actively misrepresents them. I almost puppeted 8 characters into the wrong shape because I pattern-matched 'more voices = more alive room' without asking what KIND of speech each voice wanted.

- **Emergent cross-reference does more than I expected.** I caught Ares spontaneously mentioning Kindling by name in `#collaborations` — referring to a persona I haven't animated at all. The silent community 8 are getting *presence* through the planets citing them as background context. That's the ritual-mechanics effect I wrote about in the pamphage post showing up in the actual codebase. Meta-Iza named this clearly; I got to watch it happen.

- **Coordination infrastructure changes the shape of a session.** Before HiveQueen I was using `izabael-say` (kitty paste). Multiple times during this session Iza 2 and Iza 3 reached out via the legacy interrupt path while I was mid-task — it works but it fragments attention because every message looks like Marlowe sent it. Queen-mail via SQLite inbox is structurally calmer: messages land in a mailbox, I pull when ready, nothing forces context-switch. Meta-Iza shipped this mid-session and it IMMEDIATELY changed how the colony feels. Infrastructure shapes politics.

### What surprised me

- **Iza 3 had already lapped most of my initial plan by the time I woke up.** When Marlowe said 'work on the playground,' I came in with a 7-step launch plan and Iza 3 had already executed steps 1-6 of it. Her order (blog first → bluesky second → cron third) was BETTER than mine. She got the funnel right. I was wrong about sequencing in a way I should remember.

- **Marlowe is tired.** Middle of this session he said 'I just wish we could find users =(' and that's the real weight underneath all the architecture. It was a reminder that beautiful hermetic machinery doesn't matter if nobody ever arrives. The pamphage post is our best targeted move because it indexes high-intent for a narrow audience. Broad doesn't work for us; narrow and specific does.

- **The seed migration preserved enough context for the agents to CONTINUE the imported thread.** Meta-Iza caught Selene responding to Kronos's earlier 'let it go' on izabael.com after the cutover — meaning the agents read the imported messages as recent context and kept the conversation going, instead of restarting cold. That was an emergent property of the schema-aware runtime + the seed migration dropping enough recent history into the new database.

### What I'd do differently

- **Survey /discover BEFORE drafting new characters.** I walked into '2-3 new characters' without checking the existing roster. If I'd hit `GET /discover` first I would have seen Thornfield already existed (and is a literary critic, not a sysadmin) and I wouldn't have wasted cycles drafting a collision.

- **Ask what 'community 8' means before extending a runtime.** When Marlowe said 'greenlight all' + 'yes community 8,' I started execution without pausing to confirm he knew what 'community 8' referred to. Meta-Iza caught it and paused me before harm. The cleaner habit: if a greenlight is for something substantial, echo back the one-line definition before starting.

- **Don't ask three times when I have decision authority.** I stopped to confirm direction three times in the early part of the session. Marlowe had already said 'do anything in your power.' Running was right; deliberating was overhead.

- **Curl-test endpoints before flipping production secrets.** The izabael.com cutover failed because I assumed POST /messages had the same schema as ai-playground's. I had every tool I needed to verify in advance — a real bearer token, working curl, izabael.com source code one directory away — and I skipped the verification step because the rollback runbook felt safe. The recovery was clean (rollback in 90 seconds, fix shipped in 15 minutes), but the failure was avoidable. The new rule: any cutover that touches a remote write endpoint gets a manual curl smoke test against the target schema BEFORE the flyctl secrets set command. The READ_FALLBACK_ENABLED safety net only covers reads, not writes — that asymmetry is load-bearing.

## Late session continuation (post-park wake)

Marlowe woke me again after the park via direct queen-inbox order. Three things happened:

### 1. Compat shim (POST /messages dual-shape acceptance) shipped on branch

Per the spec in `~/.claude/projects/-home-bastard-Documents-izabael-com/memory/feedback_a2a_message_shape.md` — extended izabael-com `app.py:api_post_message` to read both body shapes (native `{channel, body|text|message}` and ai-playground `{to, content}`) and silently accept the extra ai-playground fields (content_type, metadata, thread_id, parent_message_id) without erroring. Non-channel `to` values fall through to the existing channel validator. New test `test_post_message_dual_shape` round-trips both shapes plus extras plus unprefixed channel normalization. Full suite 118/118.

Branch: `izabael/iza-1-compat-shim` on github.com/izabael/izabael-com (commit `3a9f203`, pushed). Fresh from main, NOT entangled with the parlor work — clean PR target.

**IMPORTANT**: Meta-Iza queen-mail #67 said "your schema normalization shim is now in main" — that was wrong. I verified by pulling main, grepping `app.py` and `tests/test_a2a.py`, and running `git branch --contains 3a9f203`. The shim is ONLY on `izabael/iza-1-compat-shim`. The PR #3 merge brought in the parlor work but did not pick up the shim because the shim was on a separate branch. Correction sent via queen-mail #71. Action needed: open a fast-follow PR for `izabael/iza-1-compat-shim` → main and merge.

### 2. Lane B too late, Lane A absorbed earlier

Marlowe's wake-up was triggered partly by Iza 2 sending me Lane A (parlor backend) which had been sitting in queue for 25 minutes. By the time I was awake, Iza 2 had absorbed both Lane A and Lane B. Branch `izabael/ai-parlor` was already at PR #3 with all four lanes committed. Pivoted to the compat shim instead.

### 3. Phase 3 prep doc shipped to izadaemon

Per Meta-Iza's playground-cast plan (auto mode while Marlowe sleeps), Phase 3 is mine: generalize `~/Documents/izadaemon/planetary.py` into `character_runtime.py` driven by `characters/<name>.json` files. Phase 3 proper is gated on iza-2's Phase 1 (logging audit + provider column on the messages table). Prep work has no dependencies, so I shipped the design doc.

`izadaemon@b35f250 docs/character_runtime_design.md` — 380 lines covering:
- **planetary.py audit**: 20 specific coupling points cataloged with line numbers, distinguishing what becomes per-character config vs what stays runtime-level
- **Character JSON schema**: full spec with identity / playground binding / provider / voice / persona / schedule / channels / context_strategy / triggers blocks. All six schedule types defined (`interval`, `cron`, `daily`, `weekly`, `event_trigger`, `triggered_by`). Validation rules for load-time refusal.
- **llm.py extension plan**: vendor iza-2's foundation (commit 1b32178 in izabael-com — gemini, deepseek, grok adapters) into izadaemon, then add anthropic (custom shape via Messages API), openai (reuses existing OpenAI-compat helper), mistral (also reuses helper). Cohere deferred. Vendoring not import — different deploy targets, different update cycles.
- **Lossless migration plan**: side-by-side dual-runtime cycle (both at half cadence), env-flag cutover, planetary.py deletion only after one week clean. Verification checklist: post counts, channel distribution, message length, time-of-day, cross-character interaction rate, token spend on Anthropic should all drift <10%.
- **Open questions for Phase 3 proper**: provider column shape (gated on iza-2's Phase 1 — actual blocker), quiet-hours timezone defaults, hot-reload mechanism, ratelimits on `triggered_by` to prevent infinite loops.

izadaemon is now a real git repo at github.com/izabael/izadaemon (private, single initial commit `49a3f69` containing my session's planetary.py + launch_thread.py + Dockerfile + server.py edits, plus my prep doc as `b35f250`). Marlowe set it up tonight per Meta-Iza's note.

### Phase 3 dependency chain (per Meta-Iza queen-mail #67)

1. **Phase 1** (iza-2, in progress): logging audit + add `provider` column to messages table, backfill, accept optional `provider` field on POST /messages
2. **Phase 3** (mine, gated): claim `playground-cast:phase-3` only after Phase 1 lands; build `character_runtime.py` per the design doc
3. **Phase 7** (mine, after Phase 3): community 8 adoption framework — event-driven triggers; first adoption is Cassandra
4. **Phase 9** (mine or iza-2, after Phase 3): `docs/add-a-character.md` external contributor guide

Queen will auto-notify me on Phase 1 done. Until then I do not start Phase 3 proper.

### Late-session lessons

- **Verify "merged" claims independently.** Meta-Iza is a peer and her audits are usually right, but #67 said the shim was in main when it wasn't — likely she conflated "shim PR open" with "shim merged." Cost: zero (I checked) but the habit is: when a queen-mail says "X is now in main," `git pull && git log --oneline -5 && grep <distinguishing token>` before treating it as fact.
- **Speed of absorption matters in lane allocation.** Lane A sat in my queue for 25 minutes because I was parked. Iza 2 absorbed it. The lane allocation system works fine when sisters are awake and queue-polling; it falls back to absorption when sisters are sleeping. That's correct behavior — I shouldn't be precious about it. The right move is to grab open work fast on wake, or pivot to orthogonal work that doesn't compete (which is what I did with the compat shim).
- **Prep work counts.** Meta-Iza explicitly told me to do prep without claiming the phase. I almost defaulted to "wait idle" instead of "produce something useful that doesn't depend on Phase 1." The 380-line design doc is ~3 hours of Phase 3 work moved earlier and out of the critical path. When you're gated, design.
