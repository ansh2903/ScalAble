# Spore

**A lightweight data platform & intelligent notebook environment.** Query SQL/NoSQL
databases in natural language, materialize results to local Parquet via DuckDB, and
analyze them in a sandboxed Python notebook — with full support for local LLMs.

## Screenshots

### Workspace
The entry point — connect to a data source and start querying.

![Spore workspace](https://raw.githubusercontent.com/ansh2903/spore/main/docs/assets/spore%20main.png)

### Data Materialization
Preview, filter, and materialize remote query results into local files.

![Spore data materialization](https://raw.githubusercontent.com/ansh2903/spore/main/docs/assets/spore%20data.png)

### Notebook
Analyze materialized data in a rich Python notebook with live Jupyter kernels.

![Spore notebook](https://raw.githubusercontent.com/ansh2903/spore/main/docs/assets/spore%20notebook.png)

### Dashboard
Build and share interactive reports from your analysis.

![Spore dashboard](https://raw.githubusercontent.com/ansh2903/spore/main/docs/assets/spore%20dash.png)

## `docker pull` alone won't run this

Spore is **not a single container**. It's a small stack:

- `spore` — the Flask app (this image)
- `redis` — session store (isolated, internal network only)
- `kernel-dind` — a rootless Docker-in-Docker daemon that spawns **isolated, per-session
  Python kernels** (this is the sandbox that keeps your code execution off the host)
- `anshsharma2903/spore-kernel:<pyversion>` — the kernel image, pulled into DinD

So you run it with **Docker Compose**, not a bare `docker run`.

## Run it

**Linux / macOS**

```bash
# 1. Grab the run-only compose file (no source checkout needed)
curl -fsSL https://raw.githubusercontent.com/ansh2903/spore/main/docker/docker-compose.hub.yml -o docker-compose.yml

# 2. Start the stack
docker compose up -d
```

**Windows (PowerShell)**

```powershell
# 1. Grab the run-only compose file (no source checkout needed)
curl.exe -fsSL https://raw.githubusercontent.com/ansh2903/spore/main/docker/docker-compose.hub.yml -o docker-compose.yml

# 2. Start the stack
docker compose up -d
```

Then open **http://localhost:5000**.

To stop: `docker compose down` (add `-v` to also wipe the data volume).

## Configuration (optional)

Drop a `.env` file next to `docker-compose.yml`:

```bash
# Pick the sandbox Python version. A matching kernel tag must exist:
#   anshsharma2903/spore-kernel:3.11 / :3.12 / :3.13
KERNEL_PYTHON_VERSION=3.12

# Point at your own LLM endpoints.
# NOTE: host-side Ollama/LM Studio must listen on 0.0.0.0 (not 127.0.0.1),
# and your host firewall must allow the Docker bridge subnet.
OLLAMA_BASE=http://host.docker.internal:11434
LMSTUDIO_BASE=http://host.docker.internal:1234
OPENAI_BASE=https://api.openai.com/v1

# Session/credential encryption key. A shared default ships for zero-friction
# trials, but for any real/shared deployment set your own:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=
```

## Updating

```bash
docker compose pull
docker compose up -d
```

The app updates immediately. To refresh the kernel image inside the DinD sandbox:

```bash
docker exec spore-kernel-dind docker pull anshsharma2903/spore-kernel:3.12
```

## Tags

- `anshsharma2903/spore:latest` — the application
- `anshsharma2903/spore-kernel:3.12` — the sandboxed Python kernel (companion image)

## Notes

- Kernels run with dropped capabilities, `no-new-privileges`, and memory/PID limits.
- Redis is on an internal-only network, reachable solely by the app.
- LLM credentials and DB connections never leave your machine unless you point Spore
  at a remote provider.

## Source & docs

GitHub: https://github.com/ansh2903/spore
