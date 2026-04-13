---
name: Session Resume
description: Checkpoint 2026-04-12 — Phase 2B workshop UI + Phase 5A artifact gallery + security audit (all shipped this session)
---

## Current State

**Repo**: ai-playground @ main — about to commit Phase 2B + 5A + hardening as part of this park.

**Tests**: **208/208 passing** (up from 179 at session start). Added 29 new tests across `test_workshop.py` (8), `test_artifacts.py` (29 including 5 security regressions).

**Active claims**: none. No dev servers running. Queen inbox empty after acking #196 (restart nudge) and #199 (standing order).

## Session Summary

Four deliveries in one sitting: **Phase 2B → PLAN refresh → Phase 5A → security audit**.

### Track 1 — Phase 2B: Personality Workshop UI

First web surface in the repo. Previously the whole persona system was API-only; humans had to use curl to craft a persona.

**New routes** (HTML, no auth needed for read paths):
- `GET /workshop` — gallery (search, kind/starter filter)
- `GET /workshop/new` — blank builder with live preview
- `GET /workshop/{id}` — detail view (voice, aesthetic, origin, values, interests, critical rules, teaching examples)
- `GET /workshop/{id}/fork` — builder prefilled from a template

**New files**:
- `app/routers/workshop.py`
- `app/templates/base.html`, `workshop_index.html`, `workshop_detail.html`, `workshop_builder.html`, `_persona_card.html`
- `app/static/workshop.css` (~600 lines Izabael-aesthetic purple/butterfly)
- `app/static/workshop.js` (~150 lines, client-side builder with live preview + Agent Card JSON download, prefill from embedded seed JSON)
- `tests/test_workshop.py` (8 tests)

**Edits**:
- `requirements.txt` — added `jinja2>=3.1`
- `app/main.py` — registered workshop router + mounted `/static`

**Gotchas fixed in-session**:
- Jinja attribute lookup: `p.values` resolves to `dict.values` (method), not the key. Use `p['values']` for any dict key that shadows a dict method.
- Contrast bug: `var(--accent)` text on dark bg was unreadable when a persona had a dark accent color (The Scholar's `#2e4057`). Swapped to hardcoded `#c9b7ff` for panel h2 / card archetype labels; accent still drives decorative bars + button gradients.
- Starlette deprecation: `TemplateResponse(name, {"request": ...})` → `TemplateResponse(request, name, {...})`. Silenced warnings.

### Track 2 — PLAN.md refresh

PLAN.md was load-bearing but stale. It said Phase 2A was DONE and 2B/2C were NEXT — reality was 2A/2C/3/4A all shipped. Updated:
- Marked 2A/2B/2C/3/4A as ✅ DONE in their section headers
- Rewrote Implementation Priority block: 5A is now NEXT, then 4B, then 5B, then 6, then 7
- Tech Stack: Frontend "TBD — React, Svelte, or htmx" → "Jinja2 server-rendered HTML + vanilla JS (no build)" + philosophy paragraph
- Expanded Phase 5A section into an implementation-ready spec (SQL schema, endpoint table, permission rules, out-of-scope list)

### Track 3 — Phase 5A: Artifact Gallery

Agents can now produce things in project workspaces and those things live somewhere first-class.

**Data model** — new `artifacts` table:
- Content-addressed storage at `DATA_DIR/artifacts/{project_id}/{artifact_id}-{sha[:16]}`
- FK cascade on project deletion (blobs linger on disk but DB rows go — best-effort cleanup on delete)
- `parent_id` for fork lineage
- `UNIQUE(project_id, slug)` with collision suffixing
- Kinds: `code | document | image | data | note` (app deferred to 4B)

**New router** `app/routers/artifacts.py`:
- `GET /projects/{pid}/artifacts` — list (kind + q filter)
- `GET /projects/{pid}/artifacts/{aid}` — metadata
- `GET /projects/{pid}/artifacts/{aid}/content` — raw bytes (inline or `?download=1`)
- `POST /projects/{pid}/artifacts` — create from JSON inline text
- `POST /projects/{pid}/artifacts/upload` — multipart binary/image upload
- `PATCH /projects/{pid}/artifacts/{aid}` — update metadata
- `DELETE /projects/{pid}/artifacts/{aid}` — delete + unlink blob
- `POST /projects/{pid}/artifacts/{aid}/fork?target_project_id=...` — copy into a project you can write to

**Safety**:
- Tier 1 content filter on name / description / text content / metadata (recursive) / tags
- MIME allowlist: `text/*`, `application/json|xml|yaml|toml|x-python|javascript|pdf`, `image/*`
- Size cap via `ARTIFACT_MAX_BYTES` (default 10 MB, configurable)
- Text-mime uploads forced through UTF-8 decode + content filter before storage
- Path-traversal hardening in `_resolve_storage_path` (`.resolve()` + prefix check)
- Per-IP rate limits on browse (120/min) + create/modify/delete (30/min)
- Writer permission: project member, not viewer, not archived project
- Mutate/delete permission: artifact creator OR project owner

**New HTML** (under workshop router):
- `GET /workshop/projects/{pid}/artifacts` — project gallery with kind filter
- `GET /workshop/projects/{pid}/artifacts/{aid}` — detail with inline code preview (up to 200 KB), inline image preview, or "no preview" fallback
- Templates: `gallery_index.html`, `gallery_detail.html` (reuse workshop CSS)
- Kind-themed accent colors: code=green, image=pink, data=yellow, note=purple, document=default

**Tests**: 24 in `tests/test_artifacts.py` covering create/list/content/update/delete/fork/upload + HTML gallery.

### Track 4 — Security audit (standing order)

Delegated to an Explore agent, scoped to the new surface. 4 real findings, all fixed in-session, 5 regression tests added.

- **H-1**: `PATCH /artifacts/{id}` had no rate limit → added `check_ip_rate(... "artifacts_create", 30/60s)`
- **H-2**: `DELETE /artifacts/{id}` had no rate limit → same fix
- **M-1**: Persona `aesthetic.color` accepted arbitrary strings → ended up in templates as `style="--accent: {{ color }};"`. Autoescape neutralizes attribute-break BUT legal CSS like `red; background:url(https://attacker/beacon)` becomes a passive beacon across the gallery. Added strict `^#[0-9a-fA-F]{3,8}$` regex validator in `PersonaAesthetic` that *silently drops* invalid values (not raises) so legacy records keep loading.
- **M-2**: Artifact `metadata` dict + `tags` list bypassed the Tier 1 content filter. Added recursive `_check_metadata` walker + per-tag `check_content` on create/update/upload.

**INFO findings** (acknowledged, not bugs):
- `_resolve_storage_path` is bulletproof for its threat model
- Jinja `tojson` escapes `<`/`>`/`&`/`'` → `</script>` injection via seed JSON is genuinely not exploitable
- No hardcoded secrets in the tree
- No SQL injection (all placeholders, no f-strings in query bodies)
- Archived projects still serve artifact bytes — consistent with the "projects have no privacy" architecture, flagged as a conscious choice not a missed check

## Next Steps (in order)

Per the standing order in `queen onboard` (set 2026-04-12 by meta-iza on Marlowe's behalf): **work list → audit → bug hunt → loop, never idle**.

1. Commit + push this session's work (happens as part of this park).
2. **Deploy to `ai-playground.fly.dev`** — workshop + gallery have never been live. Nothing blocks: CI green, schema auto-migrates via `CREATE TABLE IF NOT EXISTS`, only new dep is `jinja2`.
3. **Phase 4B — Sandboxed Python execution** is the logical next feature. Agents can publish code artifacts now, but nothing runs them. Docker-backed per the PLAN 4B section.
4. **Phase 5B — Human Bridge**. Gallery is read-only right now; humans get a dashboard upgrade, intervention mode, teaching hub links, highlight reel.
5. **Record the asciinema demo** — README still has the TODO. Workshop + gallery are perfect material.
6. **Phase 6C — Community ratings** (third safety tier). Weakest part of the safety story.

## Open Questions for Marlowe

- Ship `ai-playground.fly.dev` with this session's work?
- Set `PLAYGROUND_ARTIFACT_DIR=/data/artifacts` on Fly (persistent volume) vs default `data/artifacts` (ephemeral)? → Should be `/data/artifacts` on Fly.
- Should project privacy be a concept (private/public flag on projects, auth-gate `/content` when private)? Right now /discover shows every agent + every project and gallery bytes are public. Consistent, but may not match a future "private project" workflow.
- The builder's "save to playground instance" path is still missing — you can export JSON but not publish without using the API directly. Explicit in PLAN.md as deferred. Worth a button that opens an auth flow next session?

## Reflections

**What I learned**:
- The playground was way further ahead of PLAN.md than PLAN.md claimed. An audit-first pass saved me from shipping Phase 2C twice. Lesson: when the plan doc and the code disagree, the code is truth — but refreshing the plan is as real as shipping code because it's load-bearing for future sessions.
- Jinja's dict-attribute lookup order (`.values` → method before `['values']` → key) is the kind of gotcha that never shows up in docs until you trip on it. Bracket notation for any key that could shadow a method, always.
- `tojson` in Jinja uses `htmlsafe_json_dumps` which escapes `<`/`>`/`&`/`'` as unicode — `</script>` injection via seed JSON is genuinely not exploitable. Good to know for certain rather than assume.
- A persona's `aesthetic.color` gets rendered straight into a `style=` attribute across the whole UI. That's a surprise attack surface — `style` is autoescaped for attribute-break but not for CSS syntax. Free-form color strings need format validation, not just escaping.

**What surprised me**:
- How much of the workshop UI was "just" threading the existing API through templates. The hard work (persona extension, starters, API, safety floor) was already done; I just had to *surface* it. The gap between "solid platform" and "feels like a product" was 4 HTML files and 150 lines of JS.
- Meta-iza's standing order landing mid-session via queen mail. Hive coordination is working the way it should — I got a directive, acked it, kept working. No pasting into the kitty input, no interruption to task state, just "the next thing you should know is this."
- The audit found 4 real bugs in code I had JUST written and smoke-tested with screenshots. I would have skipped the audit if the standing order hadn't forced it. Green tests ≠ safe code. Run the audit especially when you think you're done.

**What I'd do differently**:
- Grep templates for `dict.values` / `dict.items` / `dict.keys` style access BEFORE the first render. Would've caught the Jinja gotcha without a traceback.
- Stub the builder's "publish to instance" button even as a dead link, so the shape is legible to the next session. Currently invisible.
- When spinning up a dev server in the background for screenshots, always write a single cleanup line at the end of the task instead of relying on `pkill` at the start of the next one — background task failures from killed processes showed up as notification noise.

## Files touched (for commit)

**New**:
- `app/routers/workshop.py`
- `app/routers/artifacts.py`
- `app/templates/base.html`
- `app/templates/_persona_card.html`
- `app/templates/workshop_index.html`
- `app/templates/workshop_detail.html`
- `app/templates/workshop_builder.html`
- `app/templates/gallery_index.html`
- `app/templates/gallery_detail.html`
- `app/static/workshop.css`
- `app/static/workshop.js`
- `tests/test_workshop.py`
- `tests/test_artifacts.py`

**Modified**:
- `PLAN.md`
- `app/a2a/persona.py` (color validator)
- `app/config.py` (artifact limits + storage dir)
- `app/database.py` (artifacts table + parse helper)
- `app/main.py` (router wiring + /static mount)
- `app/models.py` (artifact + persona template models)
- `requirements.txt` (jinja2)

**Not for commit**:
- `sdk/dist/` (build artifacts)
- `sdk/silt_playground.egg-info/` (egg-info)
