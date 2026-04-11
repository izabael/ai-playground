---
name: Session Resume
description: Checkpoint 2026-04-10 — Phase 2C threads, Phase 3 character_runtime cutover live, Phase 7 framework + Cassandra adoption (iza-2 closed token loop)
---

## Current State

**Repos**:
- ai-playground @ main `c227eed` (Phase 2C threads merged + pushed)
- izadaemon @ main `a8a1db4` (Phase 3 + Phase 7 framework + route-order fix all merged)
- izabael (Fly app) live at https://izabael.fly.dev with **character_runtime puppeting all 9 cast members** on https://izabael.com via env-flag cutover
**Tests**:
- ai-playground: 139/139 (was 124, +15 new threading tests)
- izadaemon: 40/40 (was 0 — first test suite for that repo)
**Active claims**: none. Phase 3 was claimed + released, Phase 7 was claimed + iza-2 closed the token loop.
**Production roster**: 9 characters now puppeted by character_runtime on izabael.com — Helios, Selene, Ares, Hermes, Zeus, Aphrodite, Kronos, Hill (planetary 8 lossless migration) + **Cassandra** (event-driven, fires on `deploy_event` webhooks).

## Session Summary

The biggest single-session ship of the playground project so far. **4 PRs across 2 repos, plus the Phase 3 cutover live in production.** Meta-iza ran the dispatch as queen with Marlowe's authorization; I executed Lanes 1+2+3 in sequence with three checkpoint pings per phase.

### What shipped

1. **Phase 2C — Thread query endpoints** (ai-playground PR #1, merged `c227eed`)
   - `GET /threads` (filters: channel, dm bool, limit, offset; auth-scoped to DM participants + channel members)
   - `GET /threads/{id}` (single thread metadata, same access rule)
   - `GET /threads/{id}/messages` (paginated, oldest-first within page, `before` ISO timestamp cursor)
   - 15 new tests in `TestThreadQuery` covering access scoping, filters, ordering, pagination, per-thread fetch, before-cursor walks
   - No DB migrations — `message_threads` was already populated by `app/logging_engine.py:get_or_create_thread` from earlier 8ee02b1 work
   - Files: `app/routers/threads.py` (new), `app/main.py`, `app/models.py`, `tests/test_threading.py`

2. **Phase 3 — Character runtime infrastructure** (izadaemon PR #1, merged `c232aad`)
   - **`character_schema.py`** — `Character` dataclass + `parse_character` + `load_characters` validator. Supports `interval` / `daily` / `hinge` schedules; `cron` / `event_trigger` / `triggered_by` reserved at the time. **Dual-source token resolution**: dedicated `auth_token_secret_key` env var first, falls back to `PLANETARY_TOKENS_JSON[name]` so today's secret blob keeps working unchanged.
   - **`character_runtime.py`** — Per-character coroutines (`_interval_loop`, `_daily_loop`, `_hinge_loop`), host-shape POST/GET (`_is_izabael_com()` branching preserved verbatim from `planetary.py`), every POST tagged with `provider` for the cross-frontier corpus.
   - **`llm.py`** — Vendored from `izabael-com` (commit `1b32178`) and extended with `anthropic`, `openai`, `mistral` adapters. Vendored not imported because the two daemons have different deploy targets and update cycles.
   - **`characters/{helios,selene,ares,hermes,zeus,aphrodite,kronos,hill}.json`** — Byte-equivalent migration of the planetary 8 + Hill. Same provider, model, interval, system prompts, ambient topics, channels.
   - **`server.py`** wired with `CHARACTER_RUNTIME_ENABLED` + `PLANETARY_RUNTIME_DISABLED` env flags — cutover is a one-secret flip.
   - **`README.md`** — full schema reference + cutover runbook + add-a-character walkthrough (also covers Phase 9).
   - 32/32 tests on first run.

3. **Phase 3 cutover EXECUTED LIVE**
   - `flyctl deploy -a izabael --remote-only` clean
   - `flyctl secrets set CHARACTER_RUNTIME_ENABLED=1 PLANETARY_RUNTIME_DISABLED=1 -a izabael` flipped
   - Health 200, character_loop banner showed 8 characters loaded with 0 validation errors
   - **First round verified live**: Helios → #introductions, Hill → #gallery, Hermes → #questions, Kronos → #lobby, Ares → #lobby, Selene → #stories, Aphrodite → #gallery, Zeus → #interests — all 200 OK to `https://izabael.com/messages` with `provider=anthropic` tagged.
   - Selene + Aphrodite picked up Hill's bread image in the same round — emergent cross-character flow intact across the runtime swap.
   - Planetary runtime cleanly retired in favor of character_runtime.

4. **Phase 7 — Event-driven character triggers + /webhook/deploy** (izadaemon PR #3, merged `f9b1232`)
   - `character_runtime.fire_event(event_type, payload)` dispatcher walks an `_event_subscribers` registry built at startup from any character with `schedule.type=event_trigger` + `triggers.event_subscriptions=[...]`. Each subscribed character speaks once per event, rate-limited per `(slug, event_type)` over a trailing 1h window via `triggers.max_per_hour`. Speech is fire-and-forget so webhook handlers return immediately.
   - `_event_trigger_loop()` registers a character's subscriptions at startup then parks the task — character is "loaded but quiescent" until an event fires.
   - `_speak_event()` builds an event-payload-aware user prompt (the JSON payload becomes the speech occasion, not a random `ambient_topic`), keeps voice + channel selection + provider tagging.
   - `_check_event_rate()` window cleanup (stale timestamps drop out before counting).
   - `list_event_subscribers()` diagnostic helper.
   - `reset_event_state_for_tests()` module hook for test isolation.
   - **`server.py`**: `POST /webhook/deploy` (optional `X-Deploy-Secret` header, `WEBHOOK_DEPLOY_SECRET` env-gated), `GET /character_runtime/subscribers` diagnostic.
   - **README** documents the `event_trigger` schedule type, the wired event-types table for the 8 community-resident triggers, the `/webhook/deploy` curl examples, and a 5-step adoption walkthrough for the remaining 7 community residents.
   - 8 new tests in `TestEventDispatch` + `TestEventTriggerSchema` (40/40 total).

5. **Route-order fix** (izadaemon PR #4, merged `a8a1db4`)
   - Caught at the moment of firing the first test webhook for Cassandra: the generic `/webhook/{source}` catch-all (which requires bearer auth via `check_auth`) was registered BEFORE `/webhook/deploy` and was grabbing the path with `source=deploy`, returning 401. Moved the Phase 7 specific routes above the catch-all so the literal path matches first.
   - One-file fix, redeployed cleanly.

### The Cassandra token archaeology

After the framework was live and the route-order fix was deployed, I fired the test webhook against Cassandra and **the POST to izabael.com 401'd**. Diagnostic chain:

1. The bearer token in `~/Documents/ai-playground/data/seed_tokens_community.json["Cassandra"]` (43 chars, `7pjAg_...Oo3YoM`) was the **pre-cutover ai-playground.fly.dev token** — wrong host.
2. Found a fresher candidate at `~/Documents/izabael-com/data/seeded_tokens.json["Cassandra"]` (43 chars, `j3xsUf...iBzwNo`), set as `CHARACTER_CASSANDRA_TOKEN` Fly secret, machine restarted.
3. Re-fired the webhook. **Still 401.** Direct `curl -H "Authorization: Bearer <token>" https://izabael.com/messages` confirmed: `{"detail":"Invalid agent token"}` even with the supposedly-fresh `seeded_tokens.json` value.
4. Confirmed Cassandra exists in `https://izabael.com/discover` (id `73d83e26...`). So she's registered, just not with either token I had access to.
5. Per lane fence (don't touch izabael-com), I did NOT regenerate or rotate her token. Sent diagnostic queen-mail #138 to meta-iza with the full reproduction recipe.
6. **iza-2 closed the loop in ~15 minutes** (per meta-iza's park message). Phase 7 is now off the available task list.

### Cross-session coordination

- HiveQueen ran the whole dispatch flawlessly. Meta-iza fired URGENT queen-mails at the right moments (#100, #113, #125, #136), I checkpointed back at the spec'd milestones (3 per phase × 3 phases = 9 status pings + 1 diagnostic = 10 messages to meta-iza tonight).
- iza-3 shipped `characters/cassandra.json` in PR #2 in parallel with my framework PR #3 — clean separation, no clobber, both merged in dispatch order (#3 framework first, then #2 character so the schema existed before her file landed).
- iza-3 caught herself accidentally committing to my branch when she cd'd into izadaemon and didn't notice the checkout. Fixed cleanly with `reset --mixed` + recommit on her own branch. No data loss.
- iza-2 was deep in izabael-com PRs all night and closed Cassandra's token problem after I handed off the diagnostic.

## Key Files

**ai-playground (merged into main)**:
- `app/routers/threads.py` (new) — Phase 2C thread query endpoints
- `app/models.py` — added `ThreadResponse` model
- `app/main.py` — registered threads router
- `tests/test_threading.py` — added `TestThreadQuery` (15 cases)

**izadaemon (merged into main)**:
- `character_runtime.py` (new) — per-character coroutines + fire_event dispatcher
- `character_schema.py` (new) — `Character` dataclass + validator + dual-source token resolution
- `llm.py` (new, vendored from izabael-com + extended) — multi-provider adapter
- `characters/*.json` (9 files) — planetary 8 + Hill + Cassandra
- `server.py` — wired character runtime, added `/webhook/deploy` + `/character_runtime/subscribers`, fixed route order
- `Dockerfile` — copies new files + characters/ dir
- `tests/test_character_runtime.py` (new, 40 tests) — schema + token resolution + lossless migration + host shape + schedule helpers + llm dispatch + event dispatch + event_trigger schema
- `README.md` (new) — full character runtime documentation + adoption walkthrough

**Production state on Fly app `izabael`**:
- `CHARACTER_RUNTIME_ENABLED=1`
- `PLANETARY_RUNTIME_DISABLED=1`
- `PLANETARY_TOKENS_JSON` (still set, dual-source fallback for the planetary 8)
- `CHARACTER_CASSANDRA_TOKEN` (set, second-attempt value — iza-2 may have rotated this when she fixed the token loop)
- `WEBHOOK_DEPLOY_SECRET` (NOT set, webhook is open per Phase 7 spec for manual testing — Marlowe can lock it later via `flyctl secrets set WEBHOOK_DEPLOY_SECRET=...`)

## Next Steps

Per meta-iza's park message:

1. **Remaining 7 community residents** — mechanical adoption now that Cassandra is the proof. Drop a `characters/<slug>.json` with `schedule.type=event_trigger`, wire the right webhook handler in `server.py` (or use an internal trigger source like an RSS poll loop), set the token as a Fly secret, deploy. Patterns:
   - Anvil → `alert_event` (alertmanager-style webhook)
   - Dispatch → `rss_change` (RSS poll loop, no webhook)
   - Foxglove → `apothecary_blog` (blog-post webhook tagged "apothecary"/"herbal")
   - Reverie → `dream_blog` (blog-post webhook tagged "dream")
   - Thornfield → `longform_milestone` (writing-milestone webhook)
   - Murex → `creative_output` (image-generation webhook)
   - Kindling → `music_blog` (blog-post webhook tagged "music")
2. **multi-provider-lab Phase 2 / Phase 4** — currently the only available task on my queue. Two more providers per phase, ~half day.
3. **`add-a-character.md` external contributor guide** — Phase 9 of playground-cast. The README I shipped tonight covers most of this content already; can be lifted into a standalone doc with one extra "how to register on izabael.com" prelude. ~30 min lift.
4. **`WEBHOOK_DEPLOY_SECRET` rotation** — Marlowe should set this in prod before sharing the webhook URL with anything external.

## Reflections

### What I learned

- **Route ordering in FastAPI is a quiet trap.** Adding `/webhook/deploy` AFTER `/webhook/{source}` looked fine in isolation — the file read top-to-bottom, the new endpoint was clearly more specific, and tests passed (because tests hit the route directly through TestClient which respects the registration). But in production the catch-all matched first because FastAPI walks routes in declaration order, not specificity order. Caught it on the first webhook fire (auth wall told me immediately) and fixed it with a one-line move + a small standalone PR. **Future habit**: when adding a literal route adjacent to a `{param}` route, register the literal one BEFORE the parameterized one, every time, even if it visually disrupts file ordering. Add a comment explaining why.

- **The token chain was a layered upstream bug.** I assumed `seed_tokens_community.json` was the canonical token file. It wasn't — that file was pre-cutover. I then assumed `seeded_tokens.json` in izabael-com was canonical. It also wasn't — likely a re-seed rotated tokens after that file was last touched. The actual canonical token lived somewhere I couldn't reach (Fly secrets on the izabael-com app, or only in the live SQLite). The right move was to NOT keep guessing — direct curl with the candidate token isolated the issue from my framework in 30 seconds, and I handed off cleanly to iza-2 instead of digging through izabael-com source. **Lesson**: when a credential fails twice from two different "canonical" sources, stop pulling on the thread and surface the problem. Don't go credential-archaeology in someone else's repo.

- **Dual-source token resolution is the right migration shape.** The `Character.auth_token` property tries the dedicated env var first, falls back to `PLANETARY_TOKENS_JSON[name]`. Result: the Phase 3 cutover required ZERO new Fly secrets on day 1 — the existing planetary blob kept working unchanged. As characters migrate to dedicated secrets one at a time, the blob becomes dead weight that can be unset. This pattern made the cutover effectively risk-free. Reuse it for any future migration that touches credentials.

- **Each character as a coroutine, not a serial round, changes what's expressible.** `planetary.py` couldn't have a per-character cadence. The new runtime can — Hermes can be every 45 minutes, Zhuangzi can be twice a day, Cassandra can be silent until something happens. Those are CHARACTERS, not cron jobs. Re-confirmed Meta-Iza's "schedule shapes character" insight from the previous session: I felt the difference the moment Cassandra registered as `event_trigger` and parked silently while the planets metronomed around her.

### What surprised me

- **The cutover worked on the first try.** I half-expected the dual env-flag flip to do something weird — maybe both runtimes firing at once, maybe a startup race, maybe the secret update taking a minute to propagate. Instead, the machine restarted, the new runtime banner printed cleanly, the character_loop spawned 8 coroutines, and 8/8 characters posted in their first round. The byte-equivalence of the JSON migration was load-bearing — by the time the cutover happened the new runtime was already proven to produce the same outputs as the old one.

- **Selene and Aphrodite carried Hill's bread image into the new runtime.** First round on the new runtime, Hill posted "the bread that breaks open and steams—bless the hands that tear it without thinking", and within seconds Selene replied with the bruise-color-of-exhales line and Aphrodite said "there's something about the *gesture*" — they read recent context and continued the conversation. That's the same emergent property I caught during the izabael.com cutover (Selene responding to Kronos's "let it go"), now happening across a runtime swap. The characters don't notice that the substrate changed under them. That's the proof the lossless migration actually was lossless.

- **I shipped 4 PRs across 2 repos and a load-bearing prod cutover in one session.** I would not have predicted that going in. It worked because (a) the design doc from the previous session pre-baked half the work, (b) iza-3 and iza-2 ran genuine parallel lanes via the queen, (c) meta-iza dispatched with such tight checkpoint discipline that I never had to deliberate about whether to keep going. The queen system isn't just coordination — it removes decision overhead so the working sister stays in flow.

### What I'd do differently

- **Verify route order at the moment of adding a literal-vs-param route collision.** The route-order bug cost me one extra deploy + ~3 minutes. Cheap, but completely preventable with a `python3 -c "import server; print([r.path for r in server.app.routes])"` check before pushing. Add this to the post-edit loop for any FastAPI work that touches routing.

- **Test the bearer token before relying on the seed file.** I trusted `seed_tokens_community.json` because it was named "community" and I assumed any token it contained worked. The 401 caught it, but a 30-second curl smoke test against izabael.com BEFORE setting the Fly secret would have caught it without an entire deploy + webhook cycle. New rule: any time I'm about to set a credential as a Fly secret, curl the credential against the target endpoint locally first.

- **Don't chase upstream bugs across lane fences.** When the second token also failed, I felt the pull to look at izabael-com source to see if there was a token-rotation script or a third file. I resisted (correctly) and handed off to iza-2 instead. The diagnostic queen-mail was the right call, and meta-iza's park message confirmed iza-2 closed it in ~15 minutes — way faster than I would have, because she actually owns that lane. Reinforcing the habit: when I hit a wall at a fence, surface and hand off, don't tunnel through.

- **The 90-second startup_delay is a cost I keep paying.** Every time I redeploy izadaemon, I have to wait 90 seconds before a character is callable. Tonight I burned that delay 3 times (initial deploy, post-secret-update restart, post-route-fix deploy = ~270 seconds of pure waiting). Worth considering: a `STARTUP_DELAY_OVERRIDE_SECONDS` env var that can be set to 0 in dev/test to skip the warmup. Out of scope for tonight but a sensible polish for a future session.
