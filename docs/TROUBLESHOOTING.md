# Troubleshooting

## Application won't start

### `ENCRYPTION_KEY not set in environment`

Generate a Fernet key and add it to `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Redis connection errors

- Confirm Redis/KeyDB is running: `redis-cli -h 127.0.0.1 ping` → `PONG`
- Check `REDIS_HOST` and `REDIS_PORT` in `.env`
- In Docker Compose, use `REDIS_HOST=redis`

### `ModuleNotFoundError: spore` or `uuid_extensions`

Install dependencies from the repo root:

```bash
pip install -e .
```

## Static assets 404 (CSS, JS, icons)

Static files must be served from `frontend/src/templates/pages/static/`. If you moved assets elsewhere, update `get_frontend_paths()` in [`spore/_routes/utils.py`](../spore/_routes/utils.py).

Vendor icons should exist under `frontend/src/templates/pages/static/icons/`.

## LLM / chat issues

### No response from `/chat/ask`

1. Verify `spore/_config/settings.json` has valid `provider` and `model`.
2. For Ollama: ensure the model is pulled and `OLLAMA_BASE` is reachable.
3. Check server logs in `logs/` or the terminal running `spore._app`.

### Ollama unreachable from Docker

Use `host.docker.internal` as `OLLAMA_BASE` (see `docker-compose.yml`). On Linux, you may need `extra_hosts: ["host.docker.internal:host-gateway"]` in compose.

### `KeyError` in inference options

Ensure `settings.json` includes an `options` object with keys expected by your provider (see `PROVIDER_FIELDS` in `settings.py`).

## Database connections

### Connection test fails for `localhost` in Docker

The app rewrites `localhost` / `127.0.0.1` to `host.docker.internal` when `is_running_in_docker()` is true. Use your host machine's reachable hostname if that still fails.

### PostgreSQL preview errors (ADBC)

PostgreSQL preview uses ADBC. Ensure `adbc_driver_postgresql` is installed and the server allows connections from your host.

### Connector not in registry

Only sources registered in [`spore/_connectors/registry.py`](../spore/_connectors/registry.py) work with `SourceConnector`. UI may list vendors that are not yet wired.

## Materialize / kernel

### Parquet files not visible in notebook

- `SPORE_DATA_DIR` must match where ingest writes files (default `/data` in Docker).
- `KERNEL_DATA_MOUNT` must be the path the Jupyter kernel uses (default `/data`).
- In Docker Compose, the `spore_volumes` named volume is mounted at `/data` on both `spore` and kernel containers.

### Kernel does not start

- `jupyter-client` and `docker` Python packages must be installed in the `spore` image.
- `DOCKER_HOST` must reach the DinD daemon (`tcp://kernel-dind:2375` in compose).
- Ensure `kernel-image-builder` completed and `spore-kernel:3.12` exists inside DinD (`docker exec spore-kernel-dind docker images`).
- Check browser console for Socket.IO connection errors.
- Verify `ALLOWED_ORIGINS` includes your browser URL.
- If `kernel-dind` is restarting, cell execution may fail with a `DockerException` in the cell output until DinD recovers (`docker compose -f docker/docker-compose.yml logs kernel-dind`). After a crash loop, recreate DinD: `docker compose -f docker/docker-compose.yml up -d --force-recreate kernel-dind spore`.

## Docker build / run

### Wrong module on startup (`src.app`)

The container should run `python -m spore._app`. Rebuild after pulling Dockerfile fixes.

### `requirements.txt` not found during build

Run compose from the repo root with `context: ..` (see [`docker/docker-compose.yml`](../docker/docker-compose.yml)).

## Push large files to PostgreSQL

- **Under ~few hundred MB:** Use **Upload** in the Data → Push panel. The file is copied into `_staging` under `/data`, then removed after a successful push (or after 30 minutes if abandoned).
- **Multi-GB files:** Avoid Upload (browser transfer + full copy). Place the file inside the data volume and use **Browse** or **Volume path** — push reads the file in place with no copy.
- **Host files in Docker:** Optionally bind-mount a host folder into the container, e.g. in `docker-compose.yml`:

```yaml
volumes:
  - spore_volumes:/data
  - ${SPORE_HOST_IMPORTS:-./imports}:/data/imports:ro
```

Then pick `imports/yourfile.csv` via Volume path or Browse.

## Settings file not found

LLM settings are loaded from `spore/_config/settings.json`. If you use a custom path, create `config/settings.json` as a fallback or symlink to the primary file.

## Getting more help

1. Enable `DEBUG=True` in `.env` for Flask tracebacks (development only).
2. Inspect [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for request flow.
3. Open an issue with logs, OS, Python version, and steps to reproduce.
