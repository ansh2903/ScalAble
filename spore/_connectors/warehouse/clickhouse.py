"""
ClickHouse warehouse connector — columnar OLAP store.

Uses the official ``clickhouse-connect`` HTTP client (lazy-imported), which
exposes Arrow natively via ``query_arrow`` — ideal for fast pushdown preview
and Parquet ingest.
"""

from __future__ import annotations

import os
import time
from typing import Generator

from ..base import BaseSource, SourceCapabilities, SourceKind
from ..utils import (
    make_batch_sink,
    normalize_output_format,
    normalize_preview_limit,
    source_filename,
    strip_query_terminator,
    write_empty_dataset,
)
from spore._config.settings import settings
from spore._logger import logging


class ClickHouseSource(BaseSource):
    kind = SourceKind.WAREHOUSE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=False,
        needs_credentials=True,
    )

    def _create_connection(self, host: str, port: int | None):
        try:
            import clickhouse_connect
        except ImportError as e:
            raise RuntimeError(
                "clickhouse-connect is required for ClickHouse. "
                "pip install clickhouse-connect"
            ) from e

        c = self.config
        secure = bool(self.security_config.ssl_mode and self.security_config.ssl_mode != "disable")
        effective_port = int(port) if port else (8443 if secure else 8123)

        return clickhouse_connect.get_client(
            host=host,
            port=effective_port,
            username=c.get("user") or "default",
            password=c.get("password") or "",
            database=c.get("database") or "default",
            secure=secure,
            connect_timeout=self.connect_timeout,
        )

    def test_connection(self) -> tuple[bool, str]:
        try:
            with self.connection_context() as client:
                client.query("SELECT 1")
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            database = self.config.get("database") or "default"
            meta = {
                "db_type": "clickhouse",
                "database": database,
                "schema": database,
                "table_count": 0,
                "total_columns": 0,
                "tables": {},
            }
            with self.connection_context() as client:
                result = client.query(
                    "SELECT table, name, type FROM system.columns "
                    "WHERE database = %(db)s ORDER BY table, position",
                    parameters={"db": database},
                )
                for table_name, column_name, data_type in result.result_rows:
                    table = meta["tables"].setdefault(
                        table_name, {"columns": [], "column_types": {}}
                    )
                    table["columns"].append(column_name)
                    table["column_types"][column_name] = data_type
                    meta["total_columns"] += 1
            meta["table_count"] = len(meta["tables"])
            return True, meta
        except Exception as e:
            logging.error(f"[clickhouse] metadata failed: {e}")
            return False, {}

    def preview(self, query: str, limit: int = 100):
        preview_limit = normalize_preview_limit(limit, default=100)
        body = strip_query_terminator(query)
        try:
            with self.connection_context() as client:
                try:
                    count_res = client.query(f"SELECT COUNT(*) FROM ({body}) AS _c")
                    total_rows = count_res.result_rows[0][0]
                except Exception:
                    total_rows = "unknown"

                arrow = client.query_arrow(
                    f"SELECT * FROM ({body}) AS _q LIMIT {int(preview_limit)}"
                )
                rows = arrow.to_pylist()
                sample_rows = int(arrow.num_rows)
                sample_bytes = int(arrow.nbytes)
                est_total_bytes = (
                    round(sample_bytes / sample_rows * total_rows)
                    if isinstance(total_rows, int) and sample_rows > 0
                    else None
                )

                yield {"type": "columns", "content": arrow.schema.names}
                yield {
                    "type": "metadata",
                    "total_rows": total_rows,
                    "sample_rows": sample_rows,
                    "sample_bytes": sample_bytes,
                    "est_total_bytes": est_total_bytes,
                }
                yield {"type": "rows", "content": rows}
        except Exception as e:
            logging.error(f"[clickhouse] preview failed: {e}")
            yield {"type": "error", "content": str(e)}

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10_000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        """Stream ClickHouse native blocks to disk — never materialises the full result.

        ClickHouse has no DuckDB/ADBC bridge, so the workaround uses the driver's
        ``query_row_block_stream`` (server-side block iteration) and writes each
        block as it arrives, keeping memory bounded to a single block.
        """
        import pyarrow as pa

        fmt = normalize_output_format(output_format)
        dest = destination_path or settings.SPORE_DATA_DIR
        stream_dir = os.path.join(dest, "streams", stream_name)
        os.makedirs(stream_dir, exist_ok=True)
        source_path = os.path.join(stream_dir, source_filename(fmt))

        sink = None
        t0 = time.monotonic()
        body = strip_query_terminator(query)

        try:
            with self.connection_context() as client:
                head = client.query(f"SELECT * FROM ({body}) AS _h LIMIT 0")
                cols = list(head.column_names)

                try:
                    est_total_rows = client.query(
                        f"SELECT COUNT(*) FROM ({body}) AS _c"
                    ).result_rows[0][0]
                except Exception:
                    est_total_rows = None

                rows_so_far = 0
                bytes_so_far = 0
                batch_index = 0
                est_total_bytes = None
                start_sent = False

                with client.query_row_block_stream(body) as stream:
                    for block in stream:
                        if not block:
                            continue
                        batch = pa.RecordBatch.from_pydict(
                            {cols[i]: [r[i] for r in block] for i in range(len(cols))}
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

            logging.info(f"[clickhouse] ingested {rows_so_far} rows → {source_path}")
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
            logging.error(f"[clickhouse] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            if sink:
                sink.close()
