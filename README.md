<div align="center">
  <img src="spore/static/image_a0b8a9.png" alt="Spore Logo" width="350"/>

  # Spore
  **A Lightweight Data Platform & Intelligent Notebook Environment**
</div>

**Spore** is a lightweight, extensible web application for interacting with SQL and NoSQL databases. It bridges the gap between **natural language querying** and raw code execution. Query remote databases, materialize data to local Parquet files via DuckDB, and analyze it instantly in a rich Python notebook—all while keeping your data strictly under your control (including full support for local LLMs).

---

## ✨ Features

- **Seamless Data Materialization** — Stream remote SQL queries directly into local Parquet files via DuckDB for memory-efficient Python analysis.
- **Intelligent Notebook UI** — Built-in Monaco Editor with auto-scaling, custom Spore syntax highlighting, and intelligent autocomplete.
- **Rich Visual Execution** — Real-time Jupyter kernels running securely in sandboxed Docker containers, communicating over WebSockets. Native MIME-type rendering for Plotly charts, Pandas DataFrames, JSON, and LaTeX.
- **Multi-Database Support** — PostgreSQL (fully wired); MySQL, BigQuery, Snowflake, and more in progress.
- **Local & Cloud AI** — Natural language generation via Ollama, LM Studio, plus OpenAI, Anthropic, and Gemini.
- **Smart Metadata** — Automatic schema inspection, keys, types, and sample stats for better LLM context.
- **Session-Based Security** — Encrypted credentials in Redis/KeyDB-backed sessions.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12
- Redis or KeyDB
- Docker (for sandboxed kernel execution)
- *Optional:* [Ollama](https://ollama.com/) for local LLMs

### Run with Docker (recommended)

No checkout required. Grab the run-only compose file and start the full stack
(app + Redis + a sandboxed Python kernel), then open `http://localhost:5000`.

```bash
curl -fsSL https://raw.githubusercontent.com/ansh2903/spore/main/docker/docker-compose.hub.yml -o docker-compose.yml
docker compose up -d
```

Optional tweaks via a `.env` file next to the compose file:

```bash
# Pick the sandbox Python version (a matching spore-kernel tag must be published)
KERNEL_PYTHON_VERSION=3.12
# Point at your own LLM endpoints (host providers must listen on 0.0.0.0)
OLLAMA_BASE=http://host.docker.internal:11434
LMSTUDIO_BASE=http://host.docker.internal:1234
# Override the session encryption key (recommended for shared/production use)
ENCRYPTION_KEY=
```

To update later: `docker compose pull && docker compose up -d`.

### Run from source

```bash
git clone https://github.com/ansh2903/spore.git
cd spore

# Set up virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
cp .env.example .env

# Edit .env: set ENCRYPTION_KEY (see docs/CONFIGURATION.md)

# Start KeyDB dependency
docker run -d --name keydb -p 6379:6379 eqalpha/keydb:latest

# Launch Spore
python -m spore._app
```
