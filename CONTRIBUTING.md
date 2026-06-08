# Contributing to Spore

Thank you for your interest in contributing. This document covers how to set up a dev environment, where to make changes, and what we expect in pull requests.

## Getting started

1. Fork and clone the repository.
2. Follow [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for local setup.
3. Copy `.env.example` to `.env` and configure `ENCRYPTION_KEY` and Redis.
4. Create a branch from `main` for your work.

## What to work on

See [docs/ROADMAP.md](docs/ROADMAP.md) for planned features. Good first contributions:

- Wire an existing connector module into `REGISTRY`
- Fix UI/static path issues in templates
- Add tests for `BaseSource` or route handlers
- Improve documentation

## Code guidelines

### Backend (`spore/`)

- Use **`generate_blueprint()`** for new UI routes (`spore/_routes/utils.py`).
- Register new blueprints in **`spore/_app.py`** only.
- New data sources: subclass **`BaseSource`**, register in **`registry.py`**, update **`VENDOR_CONFIG`** — see [docs/CONNECTORS.md](docs/CONNECTORS.md).
- Do not re-enable **`endpoints.py`** without team review.
- Preserve the LLM **`<query>` / `<comment>`** contract in `inference_engine.py`.
- Use **`logging`** from `spore._logger`; avoid printing secrets.
- Raise **`CustomException`** for user-facing failures where appropriate.

### Frontend

- Templates: `frontend/src/templates/pages/`
- Static assets: `frontend/src/templates/pages/static/`
- Prefer `url_for('static', filename='...')` for asset URLs.

### Dependencies

- Add new packages to **`requirements.txt`** with a short comment if non-obvious.
- Run `pip install -e .` after pulling dependency changes.

## Pull requests

1. **Scope** — One logical change per PR when possible.
2. **Description** — What changed, why, and how to test.
3. **Secrets** — Never commit `.env`, keys, or real connection strings.
4. **Docs** — Update relevant `docs/` or root markdown if behavior changes.
5. **Tests** — Add or run tests when applicable (`python test/test.py` at minimum until pytest exists).

## Reporting issues

Include:

- OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Relevant log excerpts (redact credentials)

## Agent-assisted development

If you use AI coding assistants, read [CLAUDE.md](CLAUDE.md) or [AGENTS.md](AGENTS.md) for repository conventions.

## Code of conduct

Be respectful and constructive in issues and reviews. Focus feedback on the work, not the person.

## Questions

Open a GitHub issue for design questions or use discussions if enabled on the repository.
