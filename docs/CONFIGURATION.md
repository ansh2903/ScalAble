# Configuration

ScalAble reads configuration from environment variables (`.env`) and a JSON file for LLM runtime settings.

## Environment variables

Copy [.env.example](../.env.example) to `.env` at the repository root.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `scalable_secret_key` | Flask session signing key. Change in production. |
| `DEBUG` | `True` | Flask debug mode when `True`. |
| `APP_HOST` | `127.0.0.1` | Bind address for `python -m spore._app`. |
| `APP_PORT` | `5000` | HTTP port. |
| `REDIS_HOST` | `127.0.0.1` | Redis/KeyDB host for Flask-Session. |
| `REDIS_PORT` | `6379` | Redis/KeyDB port. |
| `REDIS_PASSWORD` | _(empty)_ | Optional Redis password. |
| `ALLOWED_ORIGINS` | `http://127.0.0.1:5000,http://localhost:5000` | Comma-separated CORS origins for Socket.IO. |
| `ENCRYPTION_KEY` | _(required)_ | Fernet key for encrypting DB credentials in session. |
| `SPORE_DATA_DIR` | `/data` | Directory for materialized Parquet and streams (Flask + kernel volume). |
| `KERNEL_DATA_MOUNT` | `/data` | Path visible inside the Jupyter kernel for relations. |
| `KERNEL_PYTHON_VERSION` | `3.12` | Python version tag for the sandbox kernel image (deploy-time). |
| `KERNEL_IMAGE` | `spore-kernel:3.12` | Docker image used for per-session notebook kernels. |
| `KERNEL_HOST` | `kernel-dind` | Hostname of the DinD daemon (ZMQ client target). |
| `KERNEL_VOLUME_BIND` | `/data` | Bind source inside DinD for the shared data volume. |
| `DOCKER_HOST` | _(empty)_ | Docker API URL (`tcp://kernel-dind:2375` in compose). |
| `KERNEL_MEM_LIMIT` | `1g` | Memory limit per kernel container. |
| `KERNEL_PIDS_LIMIT` | `256` | Process limit per kernel container. |
| `OLLAMA_BASE` | `http://localhost:11434` | Ollama API base URL. |
| `OLLAMA_ENDPOINT` | `http://localhost:11434/api/generate` | Legacy Ollama generate endpoint. |
| `LMSTUDIO_BASE` | `http://localhost:1234` | LM Studio API base. |
| `LMSTUDIO_ENDPOINT` | `http://localhost:1234` | LM Studio endpoint alias. |
| `OPENAI_API_KEY` | — | OpenAI API key. |
| `ANTHROPIC_API_KEY` | — | Anthropic API key. |
| `GOOGLE_API_KEY` | — | Google Gemini API key. |
| `SQLALCHEMY_URI` | — | Reserved for future persistent app database. |

Defined in [`spore/_config/settings.py`](../spore/_config/settings.py).

### Docker-specific

When running via [`docker/docker-compose.yml`](../docker/docker-compose.yml):

- `REDIS_HOST=redis` (KeyDB on an internal backend network; not exposed to the host)
- `DOCKER_HOST=tcp://kernel-dind:2375` (spawn kernels in rootless DinD)
- `KERNEL_IMAGE=spore-kernel:3.12` (built by the `kernel-image-builder` init service)
- `SPORE_DATA_DIR=/data` and `KERNEL_DATA_MOUNT=/data` (shared named volume `spore_volumes`)
- `OLLAMA_BASE=http://host.docker.internal:11434` (Ollama on the host)

Inside containers, `localhost` database hosts are rewritten to `host.docker.internal` when registering connections.

## LLM settings JSON

Runtime LLM provider and tuning live in:

**`spore/_config/settings.json`**

Resolved by `SETTINGS_FILE()` in [`spore/_utils.py`](../spore/_utils.py). A legacy path `config/settings.json` is used only if the primary file is missing.

Example structure:

```json
{
  "provider": "ollama",
  "model": "qwen3.5:0.8b",
  "keep_alive": "5m",
  "options": {
    "num_predict": 2048,
    "temperature": 0.7,
    "num_ctx": 2048
  }
}
```

| Field | Description |
|-------|-------------|
| `provider` | One of: `ollama`, `openai`, `anthropic`, `gemini`, `lmstudio`. |
| `model` | Model name for the selected provider. |
| `keep_alive` | Ollama-only: how long to keep the model loaded. |
| `options` | Provider-specific generation parameters (see `PROVIDER_FIELDS` in `settings.py`). |

After changing provider/model, restart the app or call `reset_engine()` if you add a settings UI that hot-reloads.

## Vendor connection forms

Connection wizard fields and vendor metadata are defined in `VENDOR_CONFIG` and `COMMON_LAYERS` in [`spore/_config/settings.py`](../spore/_config/settings.py):

- **Databases:** PostgreSQL, MySQL, SQLite (UI); PostgreSQL fully wired in `REGISTRY`.
- **Warehouses:** BigQuery, Snowflake (optional imports).
- **APIs:** REST API (form only).
- **Files:** CSV file (form only).

Vendor icons are served from `frontend/src/templates/pages/static/icons/`.

## Security notes

- **Never commit** `.env` or real `ENCRYPTION_KEY` values.
- Credentials are encrypted with Fernet before storage in the Flask session (Redis).
- There is **no user authentication** yet; anyone with network access to the app can use saved session connections.
