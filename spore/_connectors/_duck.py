"""
Shared DuckDB streaming-ingest helper.

DuckDB streams a remote result set server-side via ``fetch_arrow_reader()``,
so an entire table is never materialised in memory — this is the exact
technique the PostgreSQL connector pioneered, lifted here so every
DuckDB-attachable source (PostgreSQL, MySQL, SQLite, …) shares one batch loop,
one sink, and one SSE chunk contract.

The caller owns the DuckDB connection lifecycle (open it, set the memory limit,
``INSTALL``/``LOAD`` the extension, ``ATTACH`` the remote, ``USE`` it) and then
delegates the streaming write to :func:`stream_duckdb_ingest`.
"""

from __future__ import annotations

import os
import time
from typing import Any, Generator

from .utils import (
    make_batch_sink,
    normalize_output_format,
    prepare_stream_dir,
    source_filename,
    strip_query_terminator,
    wrap_count_query,
    write_empty_dataset,
)
from spore._utils import data_runtime
from spore._logger import logging


def stream_duckdb_ingest(
    *,
    duck: Any,
    query: str,
    stream_name: str,
    destination_path: str | None = None,
    output_format: str = "parquet",
    batch_row_size: int = 10000,
    dialect: str = "duckdb",
    t0: float | None = None,
) -> Generator[dict, None, None]:
    """Stream ``query`` from a configured DuckDB connection to ``streams/<name>/source.<ext>``.

    Yields SSE chunks: ``start`` → ``progress`` (per batch) → ``done`` | ``error``.
    The ``duck`` connection must already have the remote source attached and
    selected (``USE``) so ``query`` resolves against it.
    """
    fmt = normalize_output_format(output_format)
    dest = destination_path or data_runtime()["data_dir"]
    stream_dir = prepare_stream_dir(os.path.join(dest, "streams", stream_name))
    source_path = os.path.join(stream_dir, source_filename(fmt))

    sink = None
    t0 = t0 if t0 is not None else time.monotonic()

    try:
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
            arrow_schema = duck.sql(query).arrow().schema
            write_empty_dataset(source_path, arrow_schema, fmt)

        logging.info(f"[{dialect}] ingested {rows_so_far} rows → {source_path}")
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
        logging.error(f"[{dialect}] duckdb ingest failed: {e}")
        yield {"type": "error", "content": str(e)}

    finally:
        if sink:
            sink.close()
