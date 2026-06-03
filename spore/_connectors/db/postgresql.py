"""
PostgreSQL source connector for Spore.

Preview   → ADBC  (limited rows, materialising is fine)
Ingest    → DuckDB postgres_scan + fetch_arrow_reader()
            Only way to get true server-side batch streaming.
SSH       → Handled entirely by BaseSource.connection_context().
            _create_connection() receives already-resolved host/port.
File      → PyArrow → ADBC adbc_ingest(). No psycopg2 COPY.

IMPORTANT — ADBC bind parameter limitation:
  adbc_driver_postgresql does NOT support %s / $1 bind params for
  queries that return result sets (SELECTs). Only non-result-set
  statements (INSERT/UPDATE/DELETE) support them.
  All metadata SELECTs use _qi() / _qs() interpolation to stay safe.
  Ref: https://arrow.apache.org/adbc/current/python/recipe/postgresql.html
"""

import json
import os
import time
import urllib.parse
import duckdb
from typing import Any, Generator

import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.csv as pa_csv
import pyarrow.json as pa_json
import pandas as pd
import adbc_driver_postgresql.dbapi as pg

from ..base import BaseSource, SourceKind, SourceCapabilities
from ..utils import (
    QueryKind,
    classify_query,
    make_batch_sink,
    normalize_output_format,
    normalize_preview_limit,
    source_filename,
    status_row,
    strip_query_terminator,
    wrap_count_query,
    wrap_preview_query,
    write_empty_dataset,
)
from spore._logger import logging
from spore._config.settings import settings


def _qi(name: str) -> str:
    """
    Double-quote a PostgreSQL identifier (schema, table, column).
    Escapes internal double-quotes per SQL standard.
    Used instead of bind params for result-set queries — ADBC does
    not support parameterisation on SELECTs.
    """
    return '"' + name.replace('"', '""') + '"'


def _qs(value: str) -> str:
    """
    Single-quote a PostgreSQL string literal.
    Used where a string value (not identifier) must be interpolated
    into a result-set query.
    """
    return "'" + value.replace("'", "''") + "'"


class PostgreSQLSource(BaseSource):
    kind = SourceKind.DATABASE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=True,
        needs_credentials=True,
    )

    # ── BaseSource contract ───────────────────────────────────────────────────

    def _postgres_uri(self, host: str, port: int | None) -> str:
        """Build a PostgreSQL connection URI with URL-encoded credentials and SSL params."""
        c = self.config
        s = self.security_config
        user = urllib.parse.quote_plus(c["user"])
        password = urllib.parse.quote_plus(c["password"])
        database = urllib.parse.quote_plus(c.get("database") or c.get("dbname", ""))
        effective_port = port if port is not None else 5432
        uri = f"postgresql://{user}:{password}@{host}:{effective_port}/{database}"

        params = {"sslmode": s.ssl_mode}
        if s.ca_cert_path:
            params["sslrootcert"] = s.ca_cert_path
        if s.client_cert_path:
            params["sslcert"] = s.client_cert_path
        if s.client_key_path:
            params["sslkey"] = s.client_key_path
        return uri + "?" + urllib.parse.urlencode(params)

    def _create_connection(self, host: str, port: int | None) -> Any:
        """
        Receives already-resolved host/port from connection_context().
        SSH tunnel binding and local Docker routing are handled upstream.
        Uses ADBC for columnar format
        """
        return pg.connect(self._postgres_uri(host, port))

    # ── test_connection ───────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                schema = self.config.get("schema")
                if schema:
                    cur.execute(f"SET search_path TO {schema};")
                cur.execute("SELECT 1;")
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    # ── fetch_metadata ────────────────────────────────────────────────────────

    def fetch_metadata(self) -> tuple[bool, dict]:
            """
            Rich schema metadata: columns, types, row counts, sizes,
            PKs, FKs, unique constraints, PK value bounds.

            All SELECTs use _qi()/_qs() — NOT %s bind params.
            ADBC does not support bind params for result-set queries.
            Schema name comes from user config and is sanitised via _qs().
            Table/column names come from information_schema after the first
            query so are trusted identifiers, quoted via _qi().
            """
            try:
                with self.connection_context() as conn:
                    cur    = conn.cursor()
                    schema = self.config.get("schema") or "public"
                    s_lit  = _qs(schema)
                    s_qi   = _qi(schema)

                    meta = {
                        "db_type":       "postgresql",
                        "database":      self.config["database"],
                        "schema":        schema,
                        "table_count":   0,
                        "total_columns": 0,
                        "tables":        {},
                    }

                    # Removed trailing semicolon
                    cur.execute(f"""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = {s_lit}
                        AND table_type   = 'BASE TABLE'
                    """)
                    tables = cur.fetchall()
                    meta["table_count"] = len(tables)

                    for (table_name,) in tables:
                        t_lit     = _qs(table_name)
                        t_qi      = _qi(table_name)
                        qualified = f"{s_qi}.{t_qi}"
                        regclass  = _qs(f"{schema}.{table_name}")

                        # columns — Removed trailing semicolon
                        cur.execute(f"""
                            SELECT column_name, data_type
                            FROM information_schema.columns
                            WHERE table_schema = {s_lit}
                            AND table_name   = {t_lit}
                        """)
                        cols         = cur.fetchall()
                        column_names = [c[0] for c in cols]
                        column_types = {c[0]: c[1] for c in cols}
                        meta["total_columns"] += len(column_names)

                        # row count — Removed trailing semicolon
                        cur.execute(f"SELECT COUNT(*) FROM {qualified}")
                        row_count = cur.fetchone()[0]

                        # sizes — Removed trailing semicolons
                        cur.execute(f"SELECT pg_total_relation_size({regclass})")
                        size_bytes = cur.fetchone()[0]
                        cur.execute(f"SELECT pg_size_pretty(pg_total_relation_size({regclass}))")
                        size_pretty = cur.fetchone()[0]

                        # primary keys — Removed trailing semicolon
                        cur.execute(f"""
                            SELECT a.attname
                            FROM pg_index    i
                            JOIN pg_attribute a
                            ON a.attrelid = i.indrelid
                            AND a.attnum   = ANY(i.indkey)
                            WHERE i.indrelid    = {regclass}::regclass
                            AND i.indisprimary
                        """)
                        pk_columns = [r[0] for r in cur.fetchall()]

                        # PK bounds — Removed trailing semicolons
                        first_pk = last_pk = None
                        if pk_columns:
                            pk_qi = _qi(pk_columns[0])
                            cur.execute(f"SELECT {pk_qi} FROM {qualified} ORDER BY {pk_qi} ASC  LIMIT 1")
                            r = cur.fetchone(); first_pk = r[0] if r else None
                            cur.execute(f"SELECT {pk_qi} FROM {qualified} ORDER BY {pk_qi} DESC LIMIT 1")
                            r = cur.fetchone(); last_pk  = r[0] if r else None

                        # unique constraints — Removed trailing semicolon
                        cur.execute(f"""
                            SELECT a.attname
                            FROM pg_constraint c
                            JOIN pg_class      t ON c.conrelid = t.oid
                            JOIN pg_namespace  n ON n.oid      = t.relnamespace
                            JOIN pg_attribute  a ON a.attrelid = t.oid
                                            AND a.attnum    = ANY(c.conkey)
                            WHERE c.contype = 'u'
                            AND t.relname  = {t_lit}
                            AND n.nspname  = {s_lit}
                        """)
                        unique_keys = [r[0] for r in cur.fetchall()]

                        # foreign keys — Removed trailing semicolon
                        cur.execute(f"""
                            SELECT kcu.column_name,
                                ccu.table_name  AS ref_table,
                                ccu.column_name AS ref_column
                            FROM information_schema.table_constraints       tc
                            JOIN information_schema.key_column_usage        kcu
                            ON tc.constraint_name = kcu.constraint_name
                            AND tc.table_schema    = kcu.table_schema
                            JOIN information_schema.constraint_column_usage ccu
                            ON ccu.constraint_name = tc.constraint_name
                            WHERE tc.constraint_type = 'FOREIGN KEY'
                            AND tc.table_schema     = {s_lit}
                            AND tc.table_name        = {t_lit}
                        """)
                        foreign_keys = [
                            {
                                "column":            r[0],
                                "references_table":  r[1],
                                "references_column": r[2],
                            }
                            for r in cur.fetchall()
                        ]

                        meta["tables"][table_name] = {
                            "columns":        column_names,
                            "column_types":   column_types,
                            "row_count":      row_count,
                            "size_bytes":     size_bytes,
                            "size_pretty":    size_pretty,
                            "primary_keys":   pk_columns,
                            "row_bounds":     {"first_pk": first_pk, "last_pk": last_pk},
                            "unique_keys":    unique_keys,
                            "foreign_keys":   foreign_keys,
                            "candidate_keys": list(set(pk_columns + unique_keys)),
                        }

                return True, meta

            except Exception as e:
                logging.error(f"[postgresql] metadata failed: {e}")
                return False, {}    

    # ── preview ───────────────────────────────────────────────────────────────

    def preview(self, query: str, limit: int = 100) -> Generator[dict, None, None]:
        """
        Yields three chunks: columns → metadata → rows.

        Result-set queries (SELECT / WITH / TABLE / VALUES / SHOW / EXPLAIN)
        are wrapped in ``SELECT * FROM (...) LIMIT n`` so materialising via
        fetch_arrow_table() is safe.

        DML with RETURNING (``UPDATE … RETURNING``, ``INSERT … RETURNING`` …)
        cannot be wrapped as a subquery, so it is executed directly and the
        result is truncated client-side to ``limit`` rows.

        Plain INSERT / UPDATE / DELETE / MERGE, DDL (CREATE / DROP / ALTER
        / TRUNCATE / …) and utility statements (SET / VACUUM / …) have no
        result set; they are executed, committed on a best-effort basis,
        and surfaced as a single status row so the UI behaves identically
        to a successful query.
        """
        preview_limit = normalize_preview_limit(limit, default=100)
        kind = classify_query(query)
        body = strip_query_terminator(query)

        try:
            with self.connection_context() as conn:
                cur    = conn.cursor()
                schema = self.config.get("schema")
                if schema:
                    cur.execute(f"SET search_path TO {schema};")

                if kind == QueryKind.SELECT:
                    try:
                        cur.execute(wrap_count_query(body))
                        total_rows = cur.fetchone()[0]
                    except Exception:
                        total_rows = "unknown"

                    cur.execute(wrap_preview_query(body, preview_limit, default_limit=100))
                    arrow_table = cur.fetch_arrow_table()
                    sample_rows = int(arrow_table.num_rows)
                    sample_bytes = int(arrow_table.nbytes)
                    est_total_bytes = (
                        round(sample_bytes / sample_rows * total_rows)
                        if isinstance(total_rows, int) and sample_rows > 0
                        else None
                    )

                    yield {"type": "columns",  "content": arrow_table.schema.names}
                    yield {
                        "type": "metadata",
                        "total_rows": total_rows,
                        "sample_rows": sample_rows,
                        "sample_bytes": sample_bytes,
                        "est_total_bytes": est_total_bytes,
                    }
                    yield {"type": "rows",     "content": arrow_table.to_pylist()}
                    return

                if kind == QueryKind.DML_RETURNING:
                    cur.execute(body)
                    arrow_table = cur.fetch_arrow_table()
                    rows = arrow_table.to_pylist()
                    returned = len(rows)
                    sample_rows = int(arrow_table.num_rows)
                    sample_bytes = int(arrow_table.nbytes)

                    yield {"type": "columns",  "content": arrow_table.schema.names}
                    yield {
                        "type": "metadata",
                        "total_rows": returned,
                        "sample_rows": sample_rows,
                        "sample_bytes": sample_bytes,
                        "est_total_bytes": sample_bytes,
                    }
                    yield {"type": "rows", "content": rows}

                    try:
                        conn.commit()
                    except Exception as commit_err:
                        logging.warning(
                            f"[postgresql] commit after DML RETURNING failed: {commit_err}"
                        )
                    return

                # MUTATION / DDL / UTILITY — execute, commit, return a summary row.
                cur.execute(body)
                try:
                    conn.commit()
                except Exception as commit_err:
                    logging.warning(
                        f"[postgresql] commit after {kind.value} failed: {commit_err}"
                    )

                affected = getattr(cur, "rowcount", None)
                summary = status_row(body, kind, affected)
                sample_bytes = len(json.dumps(summary, default=str).encode("utf-8"))

                yield {"type": "columns",  "content": list(summary.keys())}
                yield {
                    "type": "metadata",
                    "total_rows": 1,
                    "sample_rows": 1,
                    "sample_bytes": sample_bytes,
                    "est_total_bytes": sample_bytes,
                }
                yield {"type": "rows",     "content": [summary]}

        except Exception as e:
            logging.error(f"[postgresql] preview failed: {e}")
            yield {"type": "error", "content": str(e)}

    # ── ingest ────────────────────────────────────────────────────────────────

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = '1GB',
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        """
        True streaming ingest via DuckDB fetch_arrow_reader().

        Yields SSE chunks: start → progress (per batch) → done | error.
        Writes ``streams/<name>/source.<ext>`` where ``<ext>`` is determined
        by ``output_format`` (parquet/csv/tsv/json/excel).
        """
        fmt = normalize_output_format(output_format)
        dest = destination_path or settings.SPORE_DATA_DIR
        stream_dir = os.path.join(dest, "streams", stream_name)
        os.makedirs(stream_dir, exist_ok=True)
        source_path = os.path.join(stream_dir, source_filename(fmt))

        sink = duck = None
        c = self.config
        t0 = time.monotonic()

        try:
            with self.tunnel_context() as (host, port):
                pg_uri = self._postgres_uri(host, port)

                duck = duckdb.connect(":memory:")
                duck.execute(f"SET memory_limit = '{memory_ceiling if memory_ceiling else '1GB'}';")
                duck.execute("INSTALL postgres; LOAD postgres;")
                duck.execute(f"ATTACH '{pg_uri}' AS remote_db (TYPE POSTGRES);")
                duck.execute("USE remote_db;")

                schema = c.get("schema")
                if schema:
                    duck.execute(f"SET search_path = {_qi(schema)};")

                body = strip_query_terminator(query)
                try:
                    est_total_rows = duck.sql(wrap_count_query(body)).fetchone()[0]
                except Exception:
                    est_total_rows = None

                reader = duck.sql(query).fetch_arrow_reader(batch_row_size)
                rows_so_far = 0
                bytes_so_far = 0
                batch_index = 0
                est_total_bytes = None
                start_sent = False

                for batch in reader:
                    if sink is None:
                        sink = make_batch_sink(source_path, batch.schema, fmt)
                    sink.write_batch(batch)
                    rows_so_far += batch.num_rows
                    bytes_so_far += batch.nbytes
                    batch_index += 1

                    if not start_sent:
                        if est_total_rows and rows_so_far:
                            est_total_bytes = round(bytes_so_far / rows_so_far * est_total_rows)
                        yield {
                            "type": "start",
                            "stream_name": stream_name,
                            "format": fmt,
                            "est_total_rows": est_total_rows,
                            "est_total_bytes": est_total_bytes,
                        }
                        start_sent = True

                    yield {
                        "type": "progress",
                        "rows_so_far": rows_so_far,
                        "bytes_so_far": bytes_so_far,
                        "batch_index": batch_index,
                    }

                if sink is None:
                    if not start_sent:
                        yield {
                            "type": "start",
                            "stream_name": stream_name,
                            "format": fmt,
                            "est_total_rows": est_total_rows,
                            "est_total_bytes": None,
                        }
                        start_sent = True

                    arrow_schema = duck.sql(query).arrow().schema
                    write_empty_dataset(source_path, arrow_schema, fmt)

            logging.info(f"[postgresql] ingested {rows_so_far} rows → {source_path}")
            yield {
                "type": "done",
                "path": stream_dir,
                "format": fmt,
                "filename": os.path.basename(source_path),
                "total_rows": rows_so_far,
                "total_bytes": bytes_so_far,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }

        except Exception as e:
            logging.error(f"[postgresql] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}

        finally:
            if sink:
                sink.close()
            if duck:
                duck.close()

    # ── file_to_db ────────────────────────────────────────────────────────────

    def file_to_db(self, file_path: str, table_name: str) -> dict:
        """
        Upload a local file into an existing Postgres table.
        Reads file → Arrow, then bulk-inserts via ADBC adbc_ingest().
        Supported: .csv .tsv .txt .json .ndjson .xls .xlsx .parquet
        """
        schema = self.config.get("schema") or "public"
        ext    = os.path.splitext(file_path)[1].lower()

        try:
            if ext in (".csv", ".tsv", ".txt"):
                arrow_table = pa_csv.read_csv(
                    file_path,
                    parse_options=pa_csv.ParseOptions(
                        delimiter="\t" if ext == ".tsv" else ","
                    ),
                )
            elif ext in (".json", ".ndjson"):
                try:
                    arrow_table = pa_json.read_json(file_path)
                except Exception:
                    df = pd.read_json(file_path)
                    df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
                    arrow_table = pa.Table.from_pandas(df)
            elif ext in (".xls", ".xlsx"):
                df = pd.read_excel(file_path, engine="openpyxl")
                df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
                arrow_table = pa.Table.from_pandas(df)
            elif ext == ".parquet":
                arrow_table = pq.read_table(file_path)
            else:
                return {"ok": False, "error": f"Unsupported file type: {ext}"}

        except Exception as e:
            return {"ok": False, "error": f"Failed to read file: {e}"}

        try:
            with self.connection_context() as conn:
                conn.adbc_ingest(f"{schema}.{table_name}", arrow_table, mode="append")
                conn.commit()
                return {"ok": True, "rows_inserted": len(arrow_table)}
        except Exception as e:
            logging.error(f"[postgresql] file_to_db failed: {e}")
            return {"ok": False, "error": str(e)}