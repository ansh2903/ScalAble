"""Shared helpers for source connectors."""

from __future__ import annotations

import json
import os
import re
import shutil
from enum import Enum
from typing import Protocol

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.json as pa_json
import pyarrow.parquet as pq

from werkzeug.utils import secure_filename

from spore._config.settings import settings
from spore._utils import ensure_kernel_writable_path, streams_dir


# ── connection secrets (volume-backed cert/key storage) ─────────────────────

SECRETS_SUBDIR = "secrets"
STREAMS_SUBDIR = "streams"

SECRET_FIELDS = frozenset({
    "sslrootcert",
    "sslcert",
    "sslkey",
    "ssh_private_key",
    "service_account_json",
    "private_key_file",
    "client_cert",
    "client_key",
    "ca_bundle",
})

DATA_FIELDS = frozenset({"file_path"})


def is_secret_field(name: str) -> bool:
    """Return True if ``name`` is a file-backed credential field (certs/keys)."""
    return name in SECRET_FIELDS


def is_data_field(name: str) -> bool:
    """Return True if ``name`` is an uploaded data file field (CSV, etc.)."""
    return name in DATA_FIELDS


def slugify_conn_name(name: str, fallback: str = "source") -> str:
    """Filesystem-safe slug from a connection display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or fallback


def connection_secrets_dir(conn_id: str) -> str:
    """Return (and create) the secrets directory for a connection."""
    path = os.path.join(settings.SPORE_DATA_DIR, SECRETS_SUBDIR, str(conn_id))
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def persist_upload(conn_id: str, field: str, file_storage) -> str:
    """Save an uploaded file to the connection secrets dir; return its path."""
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError(f"No file provided for field {field!r}")

    ext = os.path.splitext(file_storage.filename)[1] or ".pem"
    dest_dir = connection_secrets_dir(conn_id)
    dest_path = os.path.join(dest_dir, f"{field}{ext}")

    file_storage.save(dest_path)
    os.chmod(dest_path, 0o600)
    return dest_path


def purge_connection_secrets(conn_id: str) -> None:
    """Remove all persisted secret files for a connection."""
    path = os.path.join(settings.SPORE_DATA_DIR, SECRETS_SUBDIR, str(conn_id))
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def prepare_stream_dir(path: str) -> str:
    """Create a stream directory with kernel-writable permissions."""
    return str(ensure_kernel_writable_path(path, is_dir=True))


def connection_stream_dir(conn_name: str, conn_id: str) -> str:
    """Return (and create) ``streams/<slug>`` for uploaded data files."""
    base = slugify_conn_name(conn_name, fallback=str(conn_id))
    root = str(streams_dir(settings.SPORE_DATA_DIR))

    candidate = base
    suffix = 2
    while os.path.exists(os.path.join(root, candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1

    path = os.path.join(root, candidate)
    ensure_kernel_writable_path(path, is_dir=True)
    return path


def persist_data_file(stream_dir: str, field: str, file_storage) -> str:
    """Save an uploaded data file under a stream folder; return its path."""
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError(f"No file provided for field {field!r}")

    raw_name = file_storage.filename or "upload"
    name = secure_filename(raw_name) or "upload"
    dest_path = os.path.join(stream_dir, name)

    file_storage.save(dest_path)
    return dest_path


def purge_connection_data(stream_dir: str | None) -> None:
    """Remove a connection's uploaded data stream directory."""
    if stream_dir and os.path.isdir(stream_dir):
        shutil.rmtree(stream_dir, ignore_errors=True)


# ── preview limits ─────────────────────────────────────────────────────────


def normalize_preview_limit(limit: int | str | None, default: int = 100) -> int:
    """Return a positive integer preview limit, falling back to ``default``."""
    try:
        value = int(limit) if limit is not None else int(default)
    except (TypeError, ValueError):
        value = int(default)

    return value if value > 0 else int(default)


def strip_query_terminator(query: str) -> str:
    """Trim whitespace and trailing semicolons before embedding a query."""
    return query.strip().rstrip(";").strip()


def wrap_preview_query(query: str, limit: int | str | None, default_limit: int = 100) -> str:
    """Wrap a result-set query so connectors can fetch a bounded preview."""
    preview_limit = normalize_preview_limit(limit, default=default_limit)
    return f"SELECT * FROM ({strip_query_terminator(query)}) AS _q LIMIT {preview_limit}"


def wrap_count_query(query: str) -> str:
    """Wrap a result-set query so connectors can count the rows it would return."""
    return f"SELECT COUNT(*) FROM ({strip_query_terminator(query)}) AS _c"


# ── statement classification ────────────────────────────────────────────────
#
# Drives whether a preview can be wrapped in `SELECT * FROM (...) LIMIT n`,
# whether it must be executed directly and read as a result set (DML with
# RETURNING), or whether it has no result set at all and just needs a
# summary row (UPDATE/DELETE without RETURNING, DDL, utility statements).


class QueryKind(str, Enum):
    """How a single statement should be executed for a preview."""

    SELECT = "select"                # SELECT / WITH / TABLE / VALUES / SHOW / EXPLAIN
    DML_RETURNING = "dml_returning"  # INSERT/UPDATE/DELETE/MERGE … RETURNING …
    MUTATION = "mutation"            # INSERT/UPDATE/DELETE/MERGE without RETURNING
    DDL = "ddl"                      # CREATE / DROP / ALTER / TRUNCATE / GRANT / REVOKE / …
    UTILITY = "utility"              # SET / RESET / BEGIN / COMMIT / VACUUM / ANALYZE / …


_RESULT_SET_LEADING = {"SELECT", "WITH", "TABLE", "VALUES", "SHOW", "EXPLAIN"}
_MUTATION_LEADING = {"INSERT", "UPDATE", "DELETE", "MERGE"}
_DDL_LEADING = {
    "CREATE", "DROP", "ALTER", "TRUNCATE",
    "COMMENT", "GRANT", "REVOKE", "RENAME", "REINDEX",
}
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.IGNORECASE)


def _strip_sql_comments(text: str) -> str:
    """Drop leading SQL comments so we can read the first real keyword."""
    s = text.lstrip()
    while True:
        if s.startswith("--"):
            newline = s.find("\n")
            s = "" if newline == -1 else s[newline + 1:].lstrip()
        elif s.startswith("/*"):
            end = s.find("*/")
            s = "" if end == -1 else s[end + 2:].lstrip()
        else:
            return s


def classify_query(query: str) -> QueryKind:
    """Best-effort classification of the *first* statement in ``query``.

    The classifier is heuristic — it inspects only the leading keyword
    (after comments) plus a substring check for ``RETURNING`` — so pathological
    inputs (e.g. ``RETURNING`` appearing inside a string literal) may be
    misclassified.  Callers should treat the result as a routing hint and
    still handle execution errors gracefully.
    """
    body = _strip_sql_comments(strip_query_terminator(query))
    if not body:
        return QueryKind.UTILITY

    head = body.split(None, 1)[0].upper()
    if head in _RESULT_SET_LEADING:
        return QueryKind.SELECT
    if head in _MUTATION_LEADING:
        return QueryKind.DML_RETURNING if _RETURNING_RE.search(body) else QueryKind.MUTATION
    if head in _DDL_LEADING:
        return QueryKind.DDL
    return QueryKind.UTILITY


def status_row(query: str, kind: QueryKind, rows_affected: int | None) -> dict:
    """Build a single-row summary for statements that have no result set."""
    body = strip_query_terminator(query)
    operation = body.split(None, 1)[0].upper() if body else kind.value.upper()
    if isinstance(rows_affected, int) and rows_affected >= 0:
        affected: int | str = rows_affected
    else:
        affected = "—"
    return {"operation": operation, "rows_affected": affected, "status": "OK"}


# ── ingest output formats ───────────────────────────────────────────────────
#
# Connector ingest pipelines write the resulting rows to disk as
# ``streams/<name>/source.<ext>``. The user picks the format from the data
# panel; this module owns the mapping plus a uniform per-batch sink so the
# connector layer doesn't care which writer it's talking to.

SOURCE_EXT: dict[str, str] = {
    "parquet": "parquet",
    "csv": "csv",
    "tsv": "tsv",
    "json": "json",
    "excel": "xlsx",
}


def normalize_output_format(fmt: str | None) -> str:
    """Coerce an arbitrary user-supplied label into a known format key."""
    key = (fmt or "parquet").strip().lower()
    aliases = {
        "xlsx": "excel",
        "xls": "excel",
        "ndjson": "json",
        "jsonl": "json",
    }
    key = aliases.get(key, key)
    return key if key in SOURCE_EXT else "parquet"


def source_filename(output_format: str) -> str:
    """``source.<ext>`` for the given format key."""
    return f"source.{SOURCE_EXT[normalize_output_format(output_format)]}"


class BatchSink(Protocol):
    """Per-batch writer used by streaming ingest paths."""

    def write_batch(self, batch: pa.RecordBatch) -> None: ...
    def close(self) -> None: ...


class _ParquetSink:
    def __init__(self, path: str, schema: pa.Schema):
        self._writer = pq.ParquetWriter(path, schema, compression="snappy")

    def write_batch(self, batch: pa.RecordBatch) -> None:
        self._writer.write_batch(batch)

    def close(self) -> None:
        self._writer.close()


class _CSVSink:
    def __init__(self, path: str, schema: pa.Schema, delimiter: str = ","):
        self._writer = pa_csv.CSVWriter(
            path,
            schema,
            write_options=pa_csv.WriteOptions(
                include_header=True,
                delimiter=delimiter,
            ),
        )

    def write_batch(self, batch: pa.RecordBatch) -> None:
        self._writer.write_batch(batch)

    def close(self) -> None:
        self._writer.close()


class _JSONLSink:
    """Newline-delimited JSON. Writes one row per line; safe for huge result sets."""

    def __init__(self, path: str, schema: pa.Schema):
        self._fh = open(path, "w", encoding="utf-8")

    def write_batch(self, batch: pa.RecordBatch) -> None:
        for row in batch.to_pylist():
            self._fh.write(json.dumps(row, default=str))
            self._fh.write("\n")

    def close(self) -> None:
        self._fh.close()


class _ExcelSink:
    """openpyxl write-only mode — append rows as they arrive, save on close."""

    def __init__(self, path: str, schema: pa.Schema):
        from openpyxl import Workbook  # type: ignore

        self._path = path
        self._wb = Workbook(write_only=True)
        self._ws = self._wb.create_sheet("data")
        self._ws.append([f.name for f in schema])

    @staticmethod
    def _coerce(value):
        # openpyxl accepts numbers, strings, datetimes; anything else gets stringified.
        import datetime as _dt

        if value is None or isinstance(
            value, (str, int, float, bool, _dt.datetime, _dt.date, _dt.time)
        ):
            return value
        return str(value)

    def write_batch(self, batch: pa.RecordBatch) -> None:
        for row in batch.to_pylist():
            self._ws.append([self._coerce(v) for v in row.values()])

    def close(self) -> None:
        self._wb.save(self._path)


def make_batch_sink(path: str, schema: pa.Schema, output_format: str) -> BatchSink:
    """Build a per-batch writer for ``output_format`` rooted at ``path``."""
    fmt = normalize_output_format(output_format)
    if fmt == "parquet":
        return _ParquetSink(path, schema)
    if fmt == "csv":
        return _CSVSink(path, schema, delimiter=",")
    if fmt == "tsv":
        return _CSVSink(path, schema, delimiter="\t")
    if fmt == "json":
        return _JSONLSink(path, schema)
    if fmt == "excel":
        return _ExcelSink(path, schema)
    raise ValueError(f"Unsupported output format: {output_format!r}")


def write_empty_dataset(path: str, schema: pa.Schema, output_format: str) -> None:
    """Write a zero-row dataset for the given format. Closes the sink immediately."""
    sink = make_batch_sink(path, schema, output_format)
    try:
        empty = pa.RecordBatch.from_pylist([], schema=schema)
        sink.write_batch(empty)
    finally:
        sink.close()


# ── file push: schema inference + DDL ───────────────────────────────────────

import re as _re

_PG_RESERVED = frozenset({
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "asymmetric",
    "authorization", "between", "bigint", "binary", "bit", "boolean", "both", "case",
    "cast", "char", "character", "check", "coalesce", "collate", "column", "constraint",
    "create", "cross", "current_date", "current_role", "current_time", "current_timestamp",
    "current_user", "date", "day", "dec", "decimal", "default", "deferrable", "desc",
    "distinct", "do", "else", "end", "except", "exists", "false", "fetch", "float",
    "for", "foreign", "from", "full", "grant", "group", "having", "hour", "if", "in",
    "index", "inner", "insert", "int", "integer", "intersect", "interval", "into", "is",
    "join", "key", "leading", "left", "like", "limit", "localtime", "localtimestamp",
    "minute", "month", "natural", "new", "not", "null", "numeric", "of", "offset", "old",
    "on", "only", "or", "order", "outer", "overlaps", "placing", "primary", "references",
    "returning", "right", "row", "select", "session_user", "set", "similar", "smallint",
    "some", "table", "then", "time", "timestamp", "to", "trailing", "true", "union",
    "unique", "update", "user", "using", "values", "varchar", "variadic", "when", "where",
    "window", "with", "without", "year",
})


def sanitize_column_name(name: str) -> str:
    """Normalise a raw column name for safe SQL identifiers."""
    cleaned = str(name).strip().replace(" ", "_")
    cleaned = _re.sub(r"[^a-zA-Z0-9_]", "_", cleaned)
    cleaned = _re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"col_{cleaned}" if cleaned else "col"
    if cleaned.lower() in _PG_RESERVED:
        cleaned = f"{cleaned}_col"
    return cleaned


def sanitize_column_names(names: list[str]) -> list[str]:
    """Sanitize and de-duplicate a sequence of column names."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for raw in names:
        base = sanitize_column_name(raw)
        key = base.lower()
        count = seen.get(key, 0)
        seen[key] = count + 1
        out.append(base if count == 0 else f"{base}_{count + 1}")
    return out


def _arrow_type_to_postgres(field: pa.Field) -> str:
    """Map a PyArrow field to a PostgreSQL column type."""
    t = field.type
    if pa.types.is_int8(t) or pa.types.is_int16(t) or pa.types.is_int32(t):
        return "INTEGER"
    if pa.types.is_int64(t):
        return "BIGINT"
    if pa.types.is_uint8(t) or pa.types.is_uint16(t) or pa.types.is_uint32(t):
        return "INTEGER"
    if pa.types.is_uint64(t):
        return "BIGINT"
    if pa.types.is_float16(t) or pa.types.is_float32(t):
        return "REAL"
    if pa.types.is_float64(t):
        return "DOUBLE PRECISION"
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    if pa.types.is_timestamp(t):
        return "TIMESTAMP"
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_time(t):
        return "TIME"
    if pa.types.is_decimal(t):
        return f"NUMERIC({t.precision},{t.scale})"
    if pa.types.is_binary(t):
        return "BYTEA"
    return "TEXT"


def _qi_pg(name: str) -> str:
    """Double-quote a PostgreSQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def build_postgres_ddl(
    table_name: str,
    columns: list[str],
    arrow_types: list[str],
    schema: str = "public",
) -> str:
    """Build a CREATE TABLE statement from inferred column metadata."""
    qualified = f"{_qi_pg(schema)}.{_qi_pg(table_name)}"
    col_defs = []
    for col, pg_type in zip(columns, arrow_types):
        col_defs.append(f"    {_qi_pg(col)} {pg_type}")
    body = ",\n".join(col_defs)
    return f"CREATE TABLE IF NOT EXISTS {qualified} (\n{body}\n);"


def _read_file_sample(file_path: str, sample_rows: int) -> pa.Table:
    """Read up to ``sample_rows`` from a supported file for schema inference."""
    import pandas as pd

    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".csv", ".tsv", ".txt"):
        # Use the same PyArrow reader as the streaming loader so inferred
        # column names match the ingest path exactly (pandas and PyArrow label
        # blank/duplicate headers differently, which would desync the DDL from
        # the COPY column list).
        delimiter = "\t" if ext == ".tsv" else ","
        reader = pa_csv.open_csv(
            file_path,
            read_options=pa_csv.ReadOptions(block_size=max(sample_rows, 1) * 1024),
            parse_options=pa_csv.ParseOptions(delimiter=delimiter),
        )
        try:
            first_batch = reader.read_next_batch()
        except StopIteration:
            raise ValueError("File appears to be empty")
        table = pa.Table.from_batches([first_batch])
        names = sanitize_column_names(table.schema.names)
        return table.rename_columns(names).slice(0, sample_rows)

    if ext in (".json", ".ndjson"):
        try:
            table = pa_json.read_json(file_path)
        except Exception:
            import pandas as pd
            df = pd.read_json(file_path, lines=(ext == ".ndjson"), nrows=sample_rows)
            df.columns = sanitize_column_names([str(c) for c in df.columns])
            return pa.Table.from_pandas(df)
        return table.slice(0, sample_rows)

    if ext in (".xls", ".xlsx"):
        import pandas as pd
        df = pd.read_excel(file_path, engine="openpyxl", nrows=sample_rows)
        df.columns = sanitize_column_names([str(c) for c in df.columns])
        return pa.Table.from_pandas(df)

    if ext == ".parquet":
        pf = pq.ParquetFile(file_path)
        return pf.read_row_group(0).slice(0, sample_rows)

    raise ValueError(f"Unsupported file extension for inference: {ext}")


def estimate_file_rows(file_path: str) -> int | None:
    """Best-effort row count estimate without loading the full file."""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".parquet":
            pf = pq.ParquetFile(file_path)
            return pf.metadata.num_rows
        if ext in (".csv", ".tsv", ".txt"):
            # Fast line count for text files
            count = 0
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    count += chunk.count(b"\n")
            return max(0, count - 1)  # subtract header
    except Exception:
        pass
    return None


def infer_table_schema(file_path: str, sample_rows: int = 200) -> dict:
    """
    Infer column names, PostgreSQL types, and sample rows from a local file.

    Returns:
        {
            "columns": [...],
            "types": [...],          # postgres type strings
            "arrow_types": [...],    # arrow type strings (for reference)
            "sample_rows": [...],    # list of dicts
            "file_ext": ".csv",
            "file_size": 12345,
        }
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    table = _read_file_sample(file_path, sample_rows)
    columns = sanitize_column_names(table.schema.names)
    arrow_types = [str(f.type) for f in table.schema]
    pg_types = [_arrow_type_to_postgres(f) for f in table.schema]

    # Rename columns in the table to sanitized names
    renamed = table.rename_columns(columns)
    sample = renamed.slice(0, min(sample_rows, renamed.num_rows)).to_pylist()

    return {
        "columns": columns,
        "types": pg_types,
        "arrow_types": arrow_types,
        "sample_rows": sample,
        "file_ext": os.path.splitext(file_path)[1].lower(),
        "file_size": os.path.getsize(file_path),
    }


# ── HTTP TLS helpers (REST / GraphQL) ───────────────────────────────────────


def requests_tls_kwargs(config: dict) -> dict:
    """Build ``verify`` and ``cert`` kwargs for ``requests`` from connection config."""
    verify: bool | str = config.get("verify_ssl", "true")
    if isinstance(verify, str):
        verify = verify.lower() not in ("false", "0", "no")

    ca = config.get("ca_bundle")
    if ca and os.path.isfile(ca):
        verify = ca

    kwargs: dict = {"verify": verify}

    client_cert = config.get("client_cert")
    client_key = config.get("client_key")
    if (
        client_cert and os.path.isfile(client_cert)
        and client_key and os.path.isfile(client_key)
    ):
        kwargs["cert"] = (client_cert, client_key)

    return kwargs
