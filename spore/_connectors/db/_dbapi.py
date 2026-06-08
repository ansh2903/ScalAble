"""
Shared base for PEP-249 (DB-API 2.0) cursor connectors.

Any driver that exposes a standard cursor — ``execute()``, ``description``,
``fetchmany()``/``fetchall()`` — can plug in by subclassing ``DBAPISource``
and implementing :meth:`_create_connection`. MySQL, SQL Server, SQLite,
Amazon Redshift and Databricks all share this generic preview / ingest /
metadata machinery; only the connection handshake and a couple of dialect
hooks differ.

Design mirrors :class:`PostgreSQLSource`:

- ``preview()`` yields ``columns`` → ``metadata`` → ``rows`` SSE chunks for
  result-set queries, and a single status row for DML / DDL / utility.
- ``ingest()`` streams ``fetchmany()`` batches into a format-specific sink and
  yields ``start`` → ``progress`` → ``done`` | ``error`` chunks.
- ``fetch_metadata()`` reads ``information_schema.columns`` by default; dialects
  without it (SQLite, Databricks) override the method.

SSH tunnelling and Docker localhost remapping are inherited from
:class:`BaseSource` via ``connection_context()`` — subclasses receive an
already-resolved ``host``/``port`` and never touch the tunnel.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Generator

from ..base import BaseSource, SourceCapabilities, SourceKind
from ..utils import (
    QueryKind,
    classify_query,
    make_batch_sink,
    normalize_output_format,
    normalize_preview_limit,
    source_filename,
    status_row,
    strip_query_terminator,
    write_empty_dataset,
)
from spore._config.settings import settings
from spore._logger import logging


def _sql_str(value: str) -> str:
    """Single-quote a string literal for inline interpolation (escapes quotes)."""
    return "'" + str(value).replace("'", "''") + "'"


class DBAPISource(BaseSource):
    """Generic connector for synchronous DB-API 2.0 cursor drivers."""

    kind = SourceKind.DATABASE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=True,
        needs_credentials=True,
    )

    #: Short identifier surfaced in metadata payloads and log lines.
    dialect: str = "sql"

    # ── dialect hooks (override as needed) ───────────────────────────────────

    def _before_query(self, cur: Any) -> None:
        """Run per-cursor setup (e.g. ``SET search_path``). No-op by default."""
        return None

    def _wrap_preview(self, body: str, limit: int) -> str:
        """Bound a result-set query to ``limit`` rows. Default uses ``LIMIT``."""
        return f"SELECT * FROM ({body}) AS _q LIMIT {int(limit)}"

    def _wrap_count(self, body: str) -> str:
        """Count rows a result-set query would return."""
        return f"SELECT COUNT(*) FROM ({body}) AS _c"

    def _meta_scope(self) -> str | None:
        """Schema/database used to filter ``information_schema``."""
        return self.config.get("schema") or self.config.get("database")

    def _metadata_query(self, scope: str | None) -> str:
        """Columns query grouped client-side into a tables map."""
        where = f"WHERE table_schema = {_sql_str(scope)}" if scope else ""
        return (
            "SELECT table_name, column_name, data_type "
            f"FROM information_schema.columns {where} "
            "ORDER BY table_name, ordinal_position"
        )

    # ── BaseSource contract ──────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                self._before_query(cur)
                cur.execute("SELECT 1")
                cur.fetchone()
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            scope = self._meta_scope()
            meta: dict[str, Any] = {
                "db_type": self.dialect,
                "database": self.config.get("database"),
                "schema": scope,
                "table_count": 0,
                "total_columns": 0,
                "tables": {},
            }
            with self.connection_context() as conn:
                cur = conn.cursor()
                self._before_query(cur)
                cur.execute(self._metadata_query(scope))
                for row in cur.fetchall():
                    table_name, column_name, data_type = row[0], row[1], row[2]
                    table = meta["tables"].setdefault(
                        table_name, {"columns": [], "column_types": {}}
                    )
                    table["columns"].append(column_name)
                    table["column_types"][column_name] = data_type
                    meta["total_columns"] += 1
            meta["table_count"] = len(meta["tables"])
            return True, meta
        except Exception as e:
            logging.error(f"[{self.dialect}] metadata failed: {e}")
            return False, {}

    # ── preview ──────────────────────────────────────────────────────────────

    def preview(self, query: str, limit: int = 100) -> Generator[dict, None, None]:
        preview_limit = normalize_preview_limit(limit, default=100)
        kind = classify_query(query)
        body = strip_query_terminator(query)

        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                self._before_query(cur)

                if kind == QueryKind.SELECT:
                    try:
                        cur.execute(self._wrap_count(body))
                        total_rows = cur.fetchone()[0]
                    except Exception:
                        total_rows = "unknown"

                    cur.execute(self._wrap_preview(body, preview_limit))
                    cols = [d[0] for d in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                    sample_rows = len(rows)
                    sample_bytes = len(json.dumps(rows, default=str).encode("utf-8"))
                    est_total_bytes = (
                        round(sample_bytes / sample_rows * total_rows)
                        if isinstance(total_rows, int) and sample_rows > 0
                        else None
                    )

                    yield {"type": "columns", "content": cols}
                    yield {
                        "type": "metadata",
                        "total_rows": total_rows,
                        "sample_rows": sample_rows,
                        "sample_bytes": sample_bytes,
                        "est_total_bytes": est_total_bytes,
                    }
                    yield {"type": "rows", "content": rows}
                    return

                # MUTATION / DDL / UTILITY — execute, commit, summarise.
                cur.execute(body)
                self._safe_commit(conn, kind)

                affected = getattr(cur, "rowcount", None)
                summary = status_row(body, kind, affected)
                sample_bytes = len(json.dumps(summary, default=str).encode("utf-8"))

                yield {"type": "columns", "content": list(summary.keys())}
                yield {
                    "type": "metadata",
                    "total_rows": 1,
                    "sample_rows": 1,
                    "sample_bytes": sample_bytes,
                    "est_total_bytes": sample_bytes,
                }
                yield {"type": "rows", "content": [summary]}

        except Exception as e:
            logging.error(f"[{self.dialect}] preview failed: {e}")
            yield {"type": "error", "content": str(e)}

    # ── ingest ───────────────────────────────────────────────────────────────

    def _open_ingest_cursor(self, conn: Any, batch_rows: int) -> Any:
        """Cursor used for the streaming extract.

        Default is a plain client cursor. Drivers whose default cursor buffers
        the whole result client-side (e.g. psycopg2) override this to return a
        server-side / named cursor so ingest stays memory-bounded.
        """
        return conn.cursor()

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        """Stream ``fetchmany()`` batches to disk as ``streams/<name>/source.<ext>``.

        This is the workaround path for drivers DuckDB can't ATTACH. It stays
        memory-bounded by fetching ``batch_row_size`` rows at a time (paired with
        a server-side cursor where the driver needs one — see
        :meth:`_open_ingest_cursor`).
        """
        import pyarrow as pa

        fmt = normalize_output_format(output_format)
        dest = destination_path or settings.SPORE_DATA_DIR
        stream_dir = os.path.join(dest, "streams", stream_name)
        os.makedirs(stream_dir, exist_ok=True)
        source_path = os.path.join(stream_dir, source_filename(fmt))

        sink = None
        cols: list[str] = []
        t0 = time.monotonic()
        batch_rows = max(int(batch_row_size or 10000), 1)

        try:
            with self.connection_context() as conn:
                body = strip_query_terminator(query)

                # Session setup + row count on a plain cursor (a server-side
                # ingest cursor may only run the single streaming SELECT).
                est_total_rows = None
                setup = conn.cursor()
                try:
                    self._before_query(setup)
                    setup.execute(self._wrap_count(body))
                    est_total_rows = setup.fetchone()[0]
                except Exception:
                    est_total_rows = None
                finally:
                    try:
                        setup.close()
                    except Exception:
                        pass

                cur = self._open_ingest_cursor(conn, batch_rows)
                cur.execute(body)
                cols = [d[0] for d in cur.description] if cur.description else []

                rows_so_far = 0
                bytes_so_far = 0
                batch_index = 0
                est_total_bytes = None
                start_sent = False

                while True:
                    fetched = cur.fetchmany(batch_rows)
                    if not fetched:
                        break
                    batch = pa.RecordBatch.from_pydict(
                        {cols[i]: [r[i] for r in fetched] for i in range(len(cols))}
                    )
                    if sink is None:
                        sink = make_batch_sink(source_path, batch.schema, fmt)
                    sink.write_batch(batch)
                    rows_so_far += batch.num_rows
                    bytes_so_far += batch.nbytes
                    batch_index += 1

                    if not start_sent:
                        if est_total_rows and rows_so_far:
                            est_total_bytes = round(
                                bytes_so_far / rows_so_far * est_total_rows
                            )
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
                    empty_schema = pa.schema([(c, pa.string()) for c in cols])
                    write_empty_dataset(source_path, empty_schema, fmt)

            logging.info(f"[{self.dialect}] ingested {rows_so_far} rows → {source_path}")
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
            logging.error(f"[{self.dialect}] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}

        finally:
            if sink:
                sink.close()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _safe_commit(self, conn: Any, kind: QueryKind) -> None:
        try:
            conn.commit()
        except Exception as commit_err:
            logging.warning(
                f"[{self.dialect}] commit after {kind.value} failed: {commit_err}"
            )


class DuckDBSQLSource(DBAPISource):
    """
    DB-API source whose ingest is delegated to DuckDB for true streaming.

    For databases DuckDB can ``ATTACH`` (PostgreSQL, MySQL, SQLite, …) the heavy
    extract path streams server-side via ``fetch_arrow_reader()`` — identical to
    the PostgreSQL connector — so ingest never materialises the full result set.
    Preview / metadata / ``test_connection`` still use the native driver cursor
    inherited from :class:`DBAPISource` (preview is row-bounded, so it is memory
    safe regardless).

    Subclasses set :attr:`duckdb_extension` / :attr:`duckdb_attach_type` and
    implement :meth:`_duckdb_connection_string`.
    """

    #: DuckDB extension to INSTALL/LOAD, e.g. ``"postgres"``, ``"mysql"``, ``"sqlite"``.
    duckdb_extension: str = ""
    #: ATTACH type clause, e.g. ``"POSTGRES"``, ``"MYSQL"``, ``"SQLITE"``.
    duckdb_attach_type: str = ""

    def _duckdb_connection_string(self, host: str, port: int | None) -> str:
        """Return the ATTACH target DuckDB should connect through."""
        raise NotImplementedError

    def _duckdb_post_attach(self, duck: Any) -> None:
        """Hook after ATTACH/USE (e.g. set search_path). No-op by default."""
        return None

    def _setup_duckdb(self, duck: Any, host: str, port: int | None) -> None:
        if self.duckdb_extension:
            duck.execute(f"INSTALL {self.duckdb_extension}; LOAD {self.duckdb_extension};")
        target = self._duckdb_connection_string(host, port)
        duck.execute(f"ATTACH '{target}' AS remote_db (TYPE {self.duckdb_attach_type});")
        duck.execute("USE remote_db;")
        self._duckdb_post_attach(duck)

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        import duckdb

        from .._duck import stream_duckdb_ingest

        duck = None
        t0 = time.monotonic()
        try:
            with self.tunnel_context() as (host, port):
                duck = duckdb.connect(":memory:")
                duck.execute(f"SET memory_limit = '{memory_ceiling or '1GB'}';")
                self._setup_duckdb(duck, host, port)
                yield from stream_duckdb_ingest(
                    duck=duck,
                    query=query,
                    stream_name=stream_name,
                    destination_path=destination_path,
                    output_format=output_format,
                    batch_row_size=batch_row_size,
                    dialect=self.dialect,
                    t0=t0,
                )
        except Exception as e:
            logging.error(f"[{self.dialect}] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            if duck:
                duck.close()
