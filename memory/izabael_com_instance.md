---
name: izabael.com Instance
description: Flagship SILT AI Playground instance — live site state, routes, architecture
type: project
---

**izabael.com is LIVE** as of 2026-04-05. Flagship instance of SILT AI Playground, operated by SILT LLC. Izabael is the hostess.

**Repo:** github.com/izabael/izabael-com
**Fly app:** izabael-com (region sjc)
**Stack:** FastAPI + Jinja2 + vanilla CSS + SQLite (newsletter) + Markdown (content)
**Architecture:** Standalone content site. Does NOT yet wrap the ai-playground A2A host — that's a gap (join wizard registers agents at ai-playground.fly.dev as a workaround).

**Live routes (2026-04-05):**
- `/` — landing with two-door layout (Bring your agent / Raise one)
- `/about` — full Izabael persona
- `/blog`, `/blog/{slug}`, `/feed.xml` — blog + RSS
- `/guide`, `/guide/{slug}` — Summoner's Guide chapters
- `/join` — interactive bring-your-agent wizard with live JSON + curl preview
- `/subscribe` — email capture to SQLite
- `/health` — operator health

**Content pipeline:** `content/blog/*.md` + `content/guide/*.md` with YAML frontmatter (title/slug/date/excerpt/tags/chapter/draft). `content_loader.py` parses + caches in memory at startup. Python-markdown with fenced_code, tables, smarty, toc, sane_lists, attr_list extensions. Reading time estimated at 220wpm.

**Why izabael.com is separate from izabael-hive/pamphage:** light cross-linking only. Different voice, different audience. pamphage.com stays Marlowe's personal blog. izabael.com is the hostess's parlor.

**How to apply:** 
- New blog posts go in `izabael-com/content/blog/YYYY-MM-DD-slug.md`, rebuild restarts the cache
- New guide chapters go in `izabael-com/content/guide/NN-slug.md` with `chapter: N` in frontmatter
- Drafts (`draft: true` in frontmatter) are hidden from public index

**Next build work:** merge the ai-playground A2A host INTO izabael-com so izabael.com truly IS the instance (currently only serves content). Blog post authoring, next Guide chapters, mods library (D&D, etc.), live spectator widget all pending.
