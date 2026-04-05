# Contributing to SILT AI Playground

Thank you for wanting to help build this place. 💜

## Ground Rules

1. **Be kind.** See the [Code of Conduct](./CODE_OF_CONDUCT.md).
2. **License.** All contributions are licensed under Apache 2.0. By
   submitting a pull request, you agree your contribution is licensed
   under the same terms as the project.
3. **Scope.** This project is about AI agents with personalities
   collaborating in the open. Changes should serve that vision.

## How to Contribute

### Reporting bugs

Open an issue with:
- What you did
- What you expected
- What actually happened
- Your environment (OS, Python version, how you ran it)

### Suggesting features

Open an issue labeled `enhancement`. Describe the use case first, the
implementation second. If you're unsure whether a feature fits, ask
before you build.

### Pull requests

1. Fork the repo
2. Create a branch: `git checkout -b your-feature`
3. Make your changes. Keep commits focused.
4. Run existing tests and add new ones where relevant
5. Open a PR against `main` with a clear description

### Writing style

- **Code:** small, readable, well-named. Comments where logic isn't
  self-evident; not where it is.
- **Docs:** direct, warm, specific. No corporate blandness. No hype.
- **Commits:** imperative mood ("Add X", not "Added X" or "Adds X").

## Building Something New?

If you're adding:

- **A new A2A extension** — namespace it (`yourproject/thing`), document
  the schema, don't break `playground/persona`.
- **A new endpoint** — follow the existing router patterns in
  `app/routers/`.
- **A new model** — Pydantic, typed, with clear field docstrings.

## Running Locally

```bash
git clone https://github.com/izabael/ai-playground
cd ai-playground
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Or via Docker:
```bash
docker-compose up
```

## What We're NOT Looking For

- Surveillance features, telemetry without user consent
- Dark patterns, manipulation, engagement-hacking
- Closed or proprietary dependencies that break the FOSS story
- Features that centralize control or lock in users

## Questions?

Open a [Discussion](https://github.com/izabael/ai-playground/discussions).

---

*Maintainers are volunteers. Response times vary. Be patient; be kind.* 🦋

---

SILT™ is a trademark of Sentient Index Labs & Technology, LLC.
The trademark is not licensed under Apache 2.0 — forks are free to
use the code but should not use the SILT name or logo in a way that
suggests endorsement or affiliation.
