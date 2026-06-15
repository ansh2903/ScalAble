"""
Databricks (Lakehouse / SQL Warehouse) connector.

Connects through the ``databricks-sql-connector`` driver (lazy-imported), which
exposes a standard DB-API cursor, so preview / ingest are inherited from
:class:`DBAPISource`. Authentication uses a personal access token against a SQL
warehouse / cluster HTTP path. Metadata is read via ``SHOW TABLES`` since the
catalog/schema scoping differs from classic ``information_schema``.
"""

from __future__ import annotations

import os
import time
from typing import Any, Generator

from ..base import SourceKind
from ..db._dbapi import DBAPISource
from ..utils import (
    make_batch_sink,
    normalize_output_format,
    prepare_stream_dir,
    source_filename,
    strip_query_terminator,
    wrap_count_query,
    write_empty_dataset,
)
from spore._config.settings import settings
from spore._logger import logging


class DatabricksSource(DBAPISource):
    kind = SourceKind.WAREHOUSE
    dialect = "databricks"

    def _create_connection(self, host: str, port: int | None) -> Any:
        try:
            from databricks import sql as databricks_sql
        except ImportError as e:
            raise RuntimeError(
                "databricks-sql-connector is required for Databricks. "
                "pip install databricks-sql-connector"
            ) from e

        c = self.config
        kwargs: dict[str, Any] = {
            "server_hostname": c.get("server_hostname") or c.get("host"),
            "http_path": c["http_path"],
            "access_token": c["access_token"],
        }
        if c.get("catalog"):
            kwargs["catalog"] = c["catalog"]
        if c.get("schema"):
            kwargs["schema"] = c["schema"]
        return databricks_sql.connect(**kwargs)

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        """Stream Arrow batches via the driver's ``fetchmany_arrow`` — bounded memory.

        Databricks has no DuckDB/ADBC bridge, so the workaround pulls native
        Arrow chunks (cloud-fetch) ``batch_row_size`` rows at a time instead of
        materialising the whole result.
        """
        fmt = normalize_output_format(output_format)
        dest = destination_path or settings.SPORE_DATA_DIR
        stream_dir = prepare_stream_dir(os.path.join(dest, "streams", stream_name))
        source_path = os.path.join(stream_dir, source_filename(fmt))

        sink = None
        t0 = time.monotonic()
        batch_rows = max(int(batch_row_size or 10000), 1)
        body = strip_query_terminator(query)

        try:
            with self.connection_context() as conn:
                est_total_rows = None
                try:
                    ccur = conn.cursor()
                    ccur.execute(wrap_count_query(body))
                    est_total_rows = ccur.fetchone()[0]
                except Exception:
                    est_total_rows = None

                cur = conn.cursor()
                cur.execute(body)

                rows_so_far = 0
                bytes_so_far = 0
                batch_index = 0
                est_total_bytes = None
                start_sent = False
                last_schema = None

                while True:
                    table = cur.fetchmany_arrow(batch_rows)
                    if table is None or table.num_rows == 0:
                        break
                    last_schema = table.schema
                    if sink is None:
                        sink = make_batch_sink(source_path, table.schema, fmt)
                    for batch in table.to_batches():
                        sink.write_batch(batch)
                    rows_so_far += table.num_rows
                    bytes_so_far += table.nbytes
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
                    import pyarrow as pa

                    schema = last_schema or pa.schema(
                        [(d[0], pa.string()) for d in (cur.description or [])]
                    )
                    write_empty_dataset(source_path, schema, fmt)

            logging.info(f"[databricks] ingested {rows_so_far} rows → {source_path}")
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
            logging.error(f"[databricks] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            if sink:
                sink.close()

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            schema = self.config.get("schema")
            meta: dict[str, Any] = {
                "db_type": "databricks",
                "database": self.config.get("catalog"),
                "schema": schema,
                "table_count": 0,
                "total_columns": 0,
                "tables": {},
            }
            with self.connection_context() as conn:
                cur = conn.cursor()
                stmt = f"SHOW TABLES IN {schema}" if schema else "SHOW TABLES"
                cur.execute(stmt)
                for row in cur.fetchall():
                    # rows: (database, tableName, isTemporary)
                    table_name = row[1] if len(row) > 1 else row[0]
                    meta["tables"][table_name] = {"columns": [], "column_types": {}}
            meta["table_count"] = len(meta["tables"])
            return True, meta
        except Exception as e:
            logging.error(f"[databricks] metadata failed: {e}")
            return False, {}
