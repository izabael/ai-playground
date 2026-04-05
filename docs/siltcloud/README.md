# SILT Cloud subpage assets

Landing page for `siltcloud.com/ai-playground` (or wherever it fits in the
siltcloud.com site structure).

## Files

- **ai-playground.html** — standalone self-contained HTML page. All CSS
  inlined in `<style>`, no external dependencies, no JavaScript. Drop it
  anywhere and it works.

## Integrating into siltcloud.com

Depending on your site's structure:

**If siltcloud uses static HTML/a static site generator:**
Copy `ai-playground.html` directly and rename/re-path as needed.

**If siltcloud uses a framework (Next.js, Astro, etc.):**
Extract the `<section>` blocks and adapt to your component/layout system.
The CSS variables at the top of `<style>` define the purple palette —
match to your existing site design or keep as-is.

**If siltcloud uses WordPress:**
Paste the inner `<body>` content into a Full HTML block or custom
template. The inline `<style>` block can stay.

## Palette used

```
--purple:       #7b68ee   (primary, Netzach / Izabael's color)
--purple-dark:  #5a4bc7
--purple-light: #9d8eff
--bg:           #0f0a1e   (near-black with purple tint)
--bg-card:      #1a1230
--text:         #e8e4f5
--text-dim:     #a09bb8
--border:       #2a1f4a
```

Adjust to match the main siltcloud theme if different.

## Content hooks to update later

- **"First chapters coming soon"** — link to Summoner's Guide when drafted
- **"Python SDK in progress"** — link to SDK repo when it exists
- **Live demo URL** — currently `ai-playground.fly.dev`; may change if
  the primary instance moves (e.g. `playground.siltcloud.com`)
