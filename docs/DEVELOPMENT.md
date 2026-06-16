# Development guide

## Prerequisites

- **Python 3.12**
- **Redis or KeyDB** (Flask-Session backend)
- **Optional:** [Ollama](https://ollama.com/) or LM Studio for local LLMs
- **Optional:** Docker and Docker Compose for containerized runs

## Local setup

### 1. Clone and install

```bash
git clone https://github.com/ansh2903/spore.git
cd spore
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Generate an encryption key and set `ENCRYPTION_KEY` in `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Start Redis

```bash
# Example with Docker
docker run -d --name keydb -p 6379:6379 eqalpha/keydb:latest
```

Or use a local Redis instance and set `REDIS_HOST` / `REDIS_PORT` in `.env`.

### 4. Configure LLM

Edit [`spore/_config/settings.json`](../spore/_config/settings.json) with your provider and model. For Ollama:

```bash
ollama pull qwen3.5:0.8b   # or your chosen model
```

Ensure `OLLAMA_BASE` in `.env` matches your Ollama host.

### 5. Run the application

From the repository root:

```bash
python -m spore._app
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Docker development

From the **repository root**:

```bash
docker compose -f docker/docker-compose.yml up --build
```

This builds with context `..`, mounts the repo at `/app`, and starts KeyDB plus the Flask app on port 5000.

## Project layout

```
spore/
├── spore/                 # Backend (Flask app package)
│   ├── _app.py            # Entry point
│   ├── _routes/           # Blueprints: interface, connections, workspace
│   ├── _engine/           # LangChain NL→SQL
│   ├── _connectors/       # Data source connectors
│   ├── _compute/          # Session compute context
│   ├── _kernel/           # Jupyter kernels over Socket.IO
│   └── _config/           # settings.py, settings.json
├── frontend/src/templates/
│   ├── pages/             # Jinja page templates
│   └── pages/static/      # CSS, JS, MathJax, icons
├── docker/                # Dockerfile + compose
├── data/                  # Materialized Parquet (gitignored contents)
└── docs/                  # Documentation
```

## Common development tasks

### Add a new HTTP route

1. Create or extend a blueprint in `spore/_routes/`.
2. Use `generate_blueprint()` from `spore/_routes/utils.py`.
3. Register the blueprint in `spore/_app.py` → `register_blueprints()`.

### Add a database connector

See [CONNECTORS.md](CONNECTORS.md).

### Reset the inference engine

The LLM engine is a singleton (`spore/_engine/model_manager.py`). Restart the process after changing `settings.json`, or call `reset_engine()` from code when adding a settings reload endpoint.

## Frontend assets

Static files are served from `frontend/src/templates/pages/static/` at URL `/static/`.

Templates live under `frontend/src/templates/`. Page templates use the `pages/` prefix (e.g. `render_template("pages/chat.html")`).

### Offline CSS (Tailwind)

App pages use a pre-built stylesheet (`static/css/spore.css`) instead of the Tailwind Play CDN. Source files live under `frontend/src/css/`; the theme is in `frontend/tailwind.config.js`.

After editing templates or CSS sources, rebuild and commit the output:

```bash
cd frontend
npm ci          # first time only
npm run build:css
```

**Important:** Custom CSS `@import`s in `frontend/src/css/input.css` must come **before** the `@tailwind` directives so component classes (`.header-glass`, `.heavy-card`, etc.) are included in the build.

Runtime (`pip install -e .`, Docker) does **not** require Node — the built `spore.css` is committed.

### Vendored JS and fonts

Third-party scripts and fonts are vendored under `static/vendor/` and `static/fonts/`. To refresh pinned versions:

```bash
bash scripts/vendor_frontend_deps.sh
```

Shared head tags (fonts, `spore.css`, Alpine, htmx, highlight) are in `frontend/src/templates/partials/head_assets.html`.

The marketing landing page (`frontend/web_page/index.html`) and HTML export templates still use CDN assets by design.

## Testing

Minimal scripts exist under `test/`:

```bash
python test/test.py
```

There is no pytest suite yet. When adding tests, prefer pytest and mock Redis/session for route tests.

## Logging

Logging is configured in [`spore/_logger.py`](../spore/_logger.py). Runtime logs may appear under `logs/` (gitignored).

## Related docs

- [CONFIGURATION.md](CONFIGURATION.md) — environment and LLM JSON
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [API.md](API.md) — HTTP and WebSocket routes
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common issues
