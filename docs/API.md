# API reference

HTTP routes are served by Flask blueprints. Streaming endpoints use **Server-Sent Events** (`text/event-stream`). Real-time notebook execution uses **Socket.IO**.

Base URL (local): `http://127.0.0.1:5000`

## Interface blueprint

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page (`pages/index.html`) |

## Connections blueprint

| Method | Path | Description |
|--------|------|-------------|
| GET | `/connections` | List saved connections |
| GET | `/connections/new` | New connection wizard |
| GET | `/connections/new/<vendor>` | HTMX partial: vendor connection form |
| POST | `/test-connection` | Test credentials without saving |
| GET | `/delete-connector/<conn_id>` | Remove a connection from session |
| POST | `/registry` | Test, fetch metadata, save connection to session |

### POST `/test-connection`

**Form fields:** `kind`, `source_type`, `name`, `desc`, `use_ssh`, `use_ssl`, plus vendor-specific fields from `VENDOR_CONFIG`.

**Response (JSON):**

```json
{ "status": true, "msg": "Connection successful" }
```

### POST `/registry`

Same form shape as test. On success, appends to `session['connections']` and redirects to `/connections`.

## Workspace blueprint

| Method | Path | Description |
|--------|------|-------------|
| GET | `/chat` | Chat / notebook UI |
| POST | `/chat/ask` | SSE: stream LLM tokens for NL→SQL |
| POST | `/query-preview` | SSE: stream query result preview |
| POST | `/materialize` | Materialize query results to Parquet |
| POST | `/view-data-extraction` | Legacy alias for `/materialize` |
| GET | `/relations` | List materialized relations |
| GET | `/relations/<relation_id>` | Get one relation by ID |

### POST `/chat/ask`

**Form fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `message` | Yes | User natural-language input |
| `selected_db_id` | Yes | Connection ID from session |
| `context_sql` | No | Current notebook SQL context |

**Response:** `text/event-stream`

Each event: `data: {"type": "token"|"stats"|"error", ...}\n\n`

The frontend parses `<query>` and `<comment>` tags from token content.

### POST `/query-preview`

**Form fields:**

| Field | Default | Description |
|-------|---------|-------------|
| `query` | — | SQL to execute |
| `id` | — | Connection ID |
| `limit` | `500` | Max rows |

**Response:** SSE chunks with `type` fields from the connector preview generator.

### POST `/materialize`

**Form fields:**

| Field | Description |
|-------|-------------|
| `query` | SQL to materialize |
| `id` | Connection ID |
| `stream_name` | Optional Parquet stream name |
| `relation_id` | Optional existing relation ID |

**Response (JSON):**

```json
{
  "status": "success",
  "relation_id": "...",
  "stream_name": "stream_...",
  "path": "/host/path/to/file.parquet",
  "kernel_path": "/data/stream_....parquet"
}
```

### GET `/relations`

**Response:**

```json
{
  "relations": [
    {
      "relation_id": "...",
      "connection_id": "...",
      "stream_name": "...",
      "sql": "...",
      "materialized": {
        "path": "...",
        "kernel_path": "...",
        "format": "parquet"
      }
    }
  ]
}
```

## Socket.IO events

Registered in [`spore/_kernel/socket_events.py`](../spore/_kernel/socket_events.py).

### Server → client

| Event | Payload | When |
|-------|---------|------|
| `kernel_status` | `{ status, session_id? }` | Connect, interrupt, restart; `busy` / `idle` reflect per-session execution queue state |
| `kernel_output` | Chunk with `cell_id`, stream content | During `kernel_execute` |
| `kernel_list` | `{ kernels: [...] }` | Response to `kernel_list` |

### Client → server

| Event | Payload | Description |
|-------|---------|-------------|
| `kernel_execute` | `{ code, cell_id }` | Run Python in session kernel (serialized per Socket.IO session via an internal FIFO queue) |
| `kernel_interrupt` | — | Interrupt running kernel |
| `kernel_restart` | `{ kernel_name?: "python3" }` | Destroy and recreate kernel |
| `kernel_list` | — | List available Jupyter kernelspecs |

`kernel_execute` requests for a given Socket.IO session are processed **one at a time** in FIFO order. Duplicate pending submissions for the same `cell_id` are coalesced (latest code wins). The server emits `kernel_status` `busy` when execution starts and `idle` when the queue is empty.

### `kernel_output` chunk types

Emitted by `DockerKernel.execute()` — typically includes stdout, stderr, execute_result, display_data (e.g. Plotly figures). Each chunk includes `cell_id` for the requesting notebook cell.

## Static assets

| URL prefix | Filesystem |
|------------|------------|
| `/static/` | `frontend/src/templates/pages/static/` |

Examples: `/static/css/base.css`, `/static/js/notebook.js`, `/static/icons/postgres.png`

## Error handling

- JSON routes return `{ "error": "..." }` or `{ "status": "error", "message": "..." }` with appropriate HTTP status codes.
- SSE routes embed errors as `data: {"type": "error", "content": "..."}` events.
- Unhandled exceptions in app init raise `CustomException` (`spore/_exception.py`).

## Authentication

**None.** All endpoints assume a trusted local or private network. Session cookies identify the browser session only.
