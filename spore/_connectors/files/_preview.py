"""Shared preview / ingest helpers for local file connectors."""

from __future__ import annotations

import os
import shutil
import time
from typing import Any, Generator

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.json as pa_json
import pyarrow.parquet as pq

from spore._config.settings import settings
from spore._connectors.utils import (
    make_batch_sink,
    normalize_output_format,
    normalize_preview_limit,
    prepare_stream_dir,
    source_filename,
    write_empty_dataset,
)
from spore._logger import logging


def _table_to_chunks(table: pa.Table, limit: int) -> Generator[dict, None, None]:
    """Yield columns → metadata → rows SSE chunks from an Arrow table."""
    if table.num_rows > limit:
        table = table.slice(0, limit)

    rows = table.to_pylist()
    sample_bytes = len(str(rows).encode("utf-8")) if rows else 0

    yield {"type": "columns", "content": table.schema.names}
    yield {
        "type": "metadata",
        "total_rows": table.num_rows,
        "sample_rows": table.num_rows,
        "sample_bytes": sample_bytes,
        "est_total_bytes": sample_bytes,
    }
    yield {"type": "rows", "content": rows}


def preview_csv(config: dict, query: str, limit: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    if not path or not os.path.exists(path):
        yield {"type": "error", "content": "File not found"}
        return

    preview_limit = normalize_preview_limit(limit, default=100)
    delimiter = (config.get("delimiter") or ",")[:1]
    has_header = config.get("has_header", True)

    try:
        table = pa_csv.read_csv(
            path,
            parse_options=pa_csv.ParseOptions(delimiter=delimiter),
            read_options=pa_csv.ReadOptions(
                autogenerate_column_names=not bool(has_header),
            ),
            convert_options=pa_csv.ConvertOptions(check_utf8=False),
        )
        yield from _table_to_chunks(table, preview_limit)
    except Exception as e:
        logging.error(f"[csv_file] preview failed: {e}")
        yield {"type": "error", "content": str(e)}


def preview_json(config: dict, query: str, limit: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    if not path or not os.path.exists(path):
        yield {"type": "error", "content": "File not found"}
        return

    preview_limit = normalize_preview_limit(limit, default=100)
    try:
        table = pa_json.read_json(path)
        yield from _table_to_chunks(table, preview_limit)
    except Exception as e:
        logging.error(f"[json_file] preview failed: {e}")
        yield {"type": "error", "content": str(e)}


def preview_parquet(config: dict, query: str, limit: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    if not path or not os.path.exists(path):
        yield {"type": "error", "content": "File not found"}
        return

    preview_limit = normalize_preview_limit(limit, default=100)
    try:
        pf = pq.ParquetFile(path)
        batch = next(pf.iter_batches(batch_size=preview_limit), None)
        if batch is None:
            table = pa.table({})
        else:
            table = pa.Table.from_batches([batch])
        total = pf.metadata.num_rows if pf.metadata else table.num_rows
        rows = table.to_pylist()
        sample_bytes = int(table.nbytes)

        yield {"type": "columns", "content": table.schema.names}
        yield {
            "type": "metadata",
            "total_rows": total,
            "sample_rows": table.num_rows,
            "sample_bytes": sample_bytes,
            "est_total_bytes": sample_bytes,
        }
        yield {"type": "rows", "content": rows}
    except Exception as e:
        logging.error(f"[parquet_file] preview failed: {e}")
        yield {"type": "error", "content": str(e)}


def preview_excel(config: dict, query: str, limit: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    if not path or not os.path.exists(path):
        yield {"type": "error", "content": "File not found"}
        return

    preview_limit = normalize_preview_limit(limit, default=100)
    sheet = (query or "").strip() or config.get("sheet_name") or "Sheet1"

    try:
        import pandas as pd

        df = pd.read_excel(path, sheet_name=sheet, nrows=preview_limit, engine="openpyxl")
        table = pa.Table.from_pandas(df, preserve_index=False)
        yield from _table_to_chunks(table, preview_limit)
    except Exception as e:
        logging.error(f"[excel_file] preview failed: {e}")
        yield {"type": "error", "content": str(e)}


def ingest_file_batches(
    path: str,
    stream_name: str,
    output_format: str,
    batch_row_size: int,
    read_batches: Any,
    *,
    copy_if_same_ext: str | None = None,
) -> Generator[dict, None, None]:
    """Generic ingest loop: ``read_batches`` yields Arrow record batches."""
    fmt = normalize_output_format(output_format)
    dest = settings.SPORE_DATA_DIR
    stream_dir = prepare_stream_dir(os.path.join(dest, "streams", stream_name))
    source_path = os.path.join(stream_dir, source_filename(fmt))

    if copy_if_same_ext and path.lower().endswith(copy_if_same_ext.lower()):
        shutil.copy2(path, source_path)
        try:
            size = os.path.getsize(source_path)
            pf = pq.ParquetFile(path) if copy_if_same_ext == ".parquet" else None
            total_rows = pf.metadata.num_rows if pf and pf.metadata else None
        except Exception:
            size = os.path.getsize(source_path)
            total_rows = None
        yield {
            "type": "start",
            "stream_name": stream_name,
            "format": fmt,
            "est_total_rows": total_rows,
            "est_total_bytes": size,
        }
        yield {
            "type": "done",
            "path": stream_dir,
            "format": fmt,
            "filename": os.path.basename(source_path),
            "total_rows": total_rows,
            "total_bytes": size,
            "elapsed_ms": 0,
        }
        return

    sink = None
    t0 = time.monotonic()
    rows_so_far = 0
    bytes_so_far = 0
    batch_index = 0
    start_sent = False

    try:
        for batch in read_batches:
            if sink is None:
                sink = make_batch_sink(source_path, batch.schema, fmt)
            sink.write_batch(batch)
            rows_so_far += batch.num_rows
            bytes_so_far += batch.nbytes
            batch_index += 1

            if not start_sent:
                yield {
                    "type": "start",
                    "stream_name": stream_name,
                    "format": fmt,
                    "est_total_rows": None,
                    "est_total_bytes": None,
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
                    "est_total_rows": 0,
                    "est_total_bytes": 0,
                }
            write_empty_dataset(source_path, pa.schema([]), fmt)
        else:
            sink.close()
            sink = None

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
        logging.error(f"file ingest failed: {e}")
        yield {"type": "error", "content": str(e)}
    finally:
        if sink:
            sink.close()


def ingest_csv(config: dict, stream_name: str, output_format: str, batch_row_size: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    delimiter = (config.get("delimiter") or ",")[:1]
    has_header = config.get("has_header", True)
    fmt = normalize_output_format(output_format)

    if fmt == "csv" and path.lower().endswith(".csv"):
        yield from ingest_file_batches(
            path, stream_name, output_format, batch_row_size, iter(()),
            copy_if_same_ext=".csv",
        )
        return

    def _batches():
        table = pa_csv.read_csv(
            path,
            parse_options=pa_csv.ParseOptions(delimiter=delimiter),
            read_options=pa_csv.ReadOptions(
                autogenerate_column_names=not bool(has_header),
            ),
            convert_options=pa_csv.ConvertOptions(check_utf8=False),
        )
        for offset in range(0, table.num_rows, batch_row_size):
            end = min(offset + batch_row_size, table.num_rows)
            yield table.slice(offset, end - offset).to_batches()[0]

    yield from ingest_file_batches(path, stream_name, output_format, batch_row_size, _batches())


def ingest_json(config: dict, stream_name: str, output_format: str, batch_row_size: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()

    def _batches():
        table = pa_json.read_json(path)
        for offset in range(0, table.num_rows, batch_row_size):
            yield table.slice(offset, min(batch_row_size, table.num_rows - offset)).to_batches()[0]

    yield from ingest_file_batches(path, stream_name, output_format, batch_row_size, _batches())


def ingest_parquet(config: dict, stream_name: str, output_format: str, batch_row_size: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    fmt = normalize_output_format(output_format)

    if fmt == "parquet" and path.lower().endswith(".parquet"):
        yield from ingest_file_batches(
            path, stream_name, output_format, batch_row_size, iter(()),
            copy_if_same_ext=".parquet",
        )
        return

    def _batches():
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=batch_row_size):
            yield batch

    yield from ingest_file_batches(path, stream_name, output_format, batch_row_size, _batches())


def ingest_excel(config: dict, stream_name: str, query: str, output_format: str, batch_row_size: int) -> Generator[dict, None, None]:
    path = (config.get("file_path") or "").strip()
    sheet = (query or "").strip() or config.get("sheet_name") or "Sheet1"

    def _batches():
        import pandas as pd

        df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        table = pa.Table.from_pandas(df, preserve_index=False)
        for offset in range(0, table.num_rows, batch_row_size):
            end = min(offset + batch_row_size, table.num_rows)
            yield table.slice(offset, end - offset).to_batches()[0]

    yield from ingest_file_batches(path, stream_name, output_format, batch_row_size, _batches())
