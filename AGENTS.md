# AGENTS.md — Cursor agent guide

This file helps Cursor and other AI agents work effectively in the Spore repository.

> For the same conventions in Claude Code, see [CLAUDE.md](CLAUDE.md).

## Project summary

**Spore** is a web app for querying SQL/NoSQL databases with natural language. The backend package is **`spore`** (Flask + LangChain + Redis sessions). The UI is server-rendered Jinja templates with JavaScript for chat streaming and Jupyter kernels over Socket.IO.

**Primary user flow:** connect database → chat (NL→SQL) → review generated SQL → preview or materialize → optional notebook analysis.

## Repository map

```
spore/                          # Backend application
  _app.py                       # Entry: python -m spore._app
  _routes/                      # interface, connections, workspace blueprints
  _engine/                      # InferenceEngine, model_manager
  _connectors/                  # BaseSource, REGISTRY, SourceConnector
  _compute/context.py           # Session connectors & relations
  _kernel/                      # Jupyter over Socket.IO
  _config/settings.py           # VENDOR_CONFIG, env Settings
  _config/settings.json         # LLM provider + model
frontend/src/templates/
  pages/                        # *.html
  pages/static/                 # CSS, JS, icons (served at /static/)
docker/                         # Dockerfile + docker-compose.yml
data/                           # Materialized Parquet (SPORE_DATA_DIR)
docs/                           # Detailed documentation
```

## Run commands

**Local (from repo root):**

```bash
cp .env.example .env          # set ENCRYPTION_KEY, Redis
pip install -e .
python -m spore._app
```

**Docker:**

```bash
docker compose -f docker/docker-compose.yml up --build
```

Requires Redis/KeyDB. Ollama on host: `OLLAMA_BASE=http://host.docker.internal:11434`.

## Conventions (must follow)

### New database connector

1. Subclass `BaseSource` in `spore/_connectors/`.
2. Register in `spore/_connectors/registry.py`.
3. Add form fields to `VENDOR_CONFIG` in `spore/_config/settings.py`.
4. Add icon to `frontend/src/templates/pages/static/icons/`.

See [docs/CONNECTORS.md](docs/CONNECTORS.md).

### New HTTP routes

- Use `generate_blueprint()` from `spore/_routes/utils.py`.
- Register in `spore/_app.py` → `register_blueprints()`.
- Render templates as `pages/<name>.html`.

### NL→SQL

- Keep XML output contract in `inference_engine.py`: `<query>` and `<comment>`.
- Frontend parses tags in `frontend/src/templates/pages/static/js/notebook.js`.
- Do not change to raw JSON-in-stream without updating the parser.

### Session state

- Connections: `session['connections']` (Fernet-encrypted creds via `encrypt_creds`).
- Relations: `session['relations']` (materialized Parquet).
- **No user authentication** exists yet.

### Static files

- Served from `frontend/src/templates/pages/static/` (not `frontend/src/static/`).

## Do not

- Commit `.env`, API keys, or `ENCRYPTION_KEY` values.
- Re-enable `spore/_routes/endpoints.py` without explicit review (legacy, unregistered).
- Add large vendored assets unless necessary (MathJax is already bundled).
- Force-push to `main`.
- Expand scope unrelated to the task (minimal diffs preferred).

## Active vs legacy

| Active | Legacy |
|--------|--------|
| `workspace.py` | `endpoints.py` |
| `SourceConnector` + `REGISTRY` | `query_executor.py` direct drivers |
| `pages/chat.html` | `frontend/web_page/` |

**REGISTRY today:** `postgresql`, optional `bigquery`, `snowflake`.

## Key files

| Task | File |
|------|------|
| App entry | `spore/_app.py` |
| Chat / SSE | `spore/_routes/workspace.py` |
| Connections | `spore/_routes/connections.py` |
| LLM | `spore/_engine/inference_engine.py` |
| Connectors | `spore/_connectors/registry.py` |
| Frontend paths | `spore/_routes/utils.py` |
| Settings JSON | `spore/_config/settings.json` |

## Cursor-specific notes

- Prefer reading `DESIGN.md` and `docs/ARCHITECTURE.md` before large refactors.
- Use project rules in `.cursor/rules/` when present; they extend this guide.
- For UI verification, the app must be running with Redis and valid `.env`.

## Documentation index

- [DESIGN.md](DESIGN.md) — product and design decisions
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — setup and dev workflow
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars and LLM JSON
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture
- [docs/API.md](docs/API.md) — HTTP and Socket.IO routes
- [docs/CONNECTORS.md](docs/CONNECTORS.md) — adding connectors
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — common issues
- [CONTRIBUTING.md](CONTRIBUTING.md) — PR guidelines
