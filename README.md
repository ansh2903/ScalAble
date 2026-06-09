<div align="center">
  <img src="docs/assets/image_a0b8a9.png" alt="Spore Logo" width="350"/>

  # Spore
  **A Local first and Lightweight Data Platform & Intelligent Notebook Environment**
</div>

**Spore** is a lightweight web based platform for interacting with a verity of data sources ranging from DB/warehousing to local files. Query remote databases to filter, preprocess, sample data from SQL/NoSQL sources, materialize data to local files via DuckDB using batching to counter memory bottlenecks, analyze it instantly in a rich Python notebook—all while keeping your data strictly under your control and create interactive shareable reports at the end (including full support for local LLMs).

**Spore is still under development and some extra helping would be appriciated, the platform is completely open-source and free of cost**

---

## 📸 Screenshots

<div align="center">

### Workspace
The entry point — connect to a data source and start querying.

<img src="docs/assets/spore%20main.png" alt="Spore workspace" width="800"/>

### Data Materialization
Preview, filter, and materialize remote query results into local files.

<img src="docs/assets/spore%20data.png" alt="Spore data materialization" width="800"/>

### Notebook
Analyze materialized data in a rich Python notebook with live Jupyter kernels.

<img src="docs/assets/spore%20notebook.png" alt="Spore notebook" width="800"/>

### Dashboard
Build and share interactive reports from your analysis.

<img src="docs/assets/spore%20dash.png" alt="Spore dashboard" width="800"/>

</div>

---

## ✨ Features

- **Seamless Data Materialization** — Stream remote SQL queries directly into local files via DuckDB for memory-efficient Python analysis.
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
