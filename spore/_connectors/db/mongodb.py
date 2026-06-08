"""
MongoDB source connector (NoSQL document store).

MongoDB has no SQL surface, so the ``query`` string is interpreted as either:

- a bare collection name — ``"orders"`` — which scans the collection, or
- a JSON query spec, e.g.::

      {"collection": "orders",
       "filter": {"status": "paid"},
       "projection": {"_id": 0, "total": 1},
       "sort": [["created_at", -1]],
       "limit": 100}

Documents are flattened for tabular display/ingest: ``ObjectId`` and other
BSON scalars become strings, and nested documents/arrays are JSON-encoded into
a single cell. Uses ``pymongo`` (lazy-imported).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Generator

from ..base import BaseSource, SourceCapabilities, SourceKind
from ..utils import (
    make_batch_sink,
    normalize_output_format,
    normalize_preview_limit,
    source_filename,
    write_empty_dataset,
)
from spore._config.settings import settings
from spore._logger import logging


def _normalize_value(value: Any) -> Any:
    """Coerce a BSON value into something JSON/Arrow-friendly."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _normalize_doc(doc: dict) -> dict:
    return {k: _normalize_value(v) for k, v in doc.items()}


def _ordered_columns(docs: list[dict]) -> list[str]:
    """Union of keys across docs, preserving first-seen order."""
    cols: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        for key in doc.keys():
            if key not in seen:
                seen.add(key)
                cols.append(key)
    return cols


class MongoDBSource(BaseSource):
    kind = SourceKind.DATABASE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=True,
        needs_credentials=True,
    )

    # ── connection ───────────────────────────────────────────────────────────

    def _create_connection(self, host: str, port: int | None) -> Any:
        try:
            from pymongo import MongoClient
        except ImportError as e:
            raise RuntimeError(
                "pymongo is required for MongoDB. pip install pymongo"
            ) from e

        c = self.config
        timeout_ms = self.connect_timeout * 1000

        uri = c.get("connection_string") or c.get("uri")
        if uri:
            return MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)

        kwargs: dict[str, Any] = {
            "host": host,
            "port": int(port) if port else 27017,
            "serverSelectionTimeoutMS": timeout_ms,
        }
        if c.get("user"):
            kwargs["username"] = c["user"]
            kwargs["password"] = c.get("password") or ""
        if c.get("auth_source"):
            kwargs["authSource"] = c["auth_source"]
        if self.security_config.ssl_mode and self.security_config.ssl_mode != "disable":
            kwargs["tls"] = True
            if self.security_config.ca_cert_path:
                kwargs["tlsCAFile"] = self.security_config.ca_cert_path

        return MongoClient(**kwargs)

    def _database(self, conn: Any):
        name = self.config.get("database")
        if not name:
            raise ValueError("MongoDB requires a database name")
        return conn[name]

    @staticmethod
    def _parse_query(query: str) -> dict:
        """Turn the query string into a normalised find-spec."""
        text = (query or "").strip()
        if not text:
            raise ValueError("Empty MongoDB query")

        spec: dict[str, Any]
        if text.startswith("{"):
            spec = json.loads(text)
        else:
            spec = {"collection": text}

        if not spec.get("collection"):
            raise ValueError("MongoDB query must specify a 'collection'")
        return spec

    # ── BaseSource contract ──────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        try:
            with self.connection_context() as conn:
                conn.admin.command("ping")
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            meta: dict[str, Any] = {
                "db_type": "mongodb",
                "database": self.config.get("database"),
                "schema": None,
                "table_count": 0,
                "total_columns": 0,
                "tables": {},
            }
            with self.connection_context() as conn:
                db = self._database(conn)
                for name in db.list_collection_names():
                    sample = db[name].find_one() or {}
                    columns = list(sample.keys())
                    meta["tables"][name] = {
                        "kind": "collection",
                        "columns": columns,
                        "column_types": {
                            k: type(v).__name__ for k, v in sample.items()
                        },
                    }
                    meta["total_columns"] += len(columns)
            meta["table_count"] = len(meta["tables"])
            return True, meta
        except Exception as e:
            logging.error(f"[mongodb] metadata failed: {e}")
            return False, {}

    # ── preview ──────────────────────────────────────────────────────────────

    def preview(self, query: str, limit: int = 100) -> Generator[dict, None, None]:
        preview_limit = normalize_preview_limit(limit, default=100)
        try:
            spec = self._parse_query(query)
            with self.connection_context() as conn:
                db = self._database(conn)
                coll = db[spec["collection"]]
                flt = spec.get("filter") or {}

                try:
                    total_rows = coll.count_documents(flt)
                except Exception:
                    total_rows = "unknown"

                cursor = coll.find(flt, spec.get("projection"))
                if spec.get("sort"):
                    cursor = cursor.sort([tuple(s) for s in spec["sort"]])
                cursor = cursor.limit(preview_limit)

                docs = [_normalize_doc(d) for d in cursor]
                cols = _ordered_columns(docs)
                rows = [{c: d.get(c) for c in cols} for d in docs]
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
        except Exception as e:
            logging.error(f"[mongodb] preview failed: {e}")
            yield {"type": "error", "content": str(e)}

    # ── ingest ───────────────────────────────────────────────────────────────

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
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
            spec = self._parse_query(query)
            with self.connection_context() as conn:
                db = self._database(conn)
                coll = db[spec["collection"]]
                flt = spec.get("filter") or {}

                est_total_rows = None
                try:
                    est_total_rows = coll.count_documents(flt)
                except Exception:
                    est_total_rows = None

                cursor = coll.find(flt, spec.get("projection"))
                if spec.get("sort"):
                    cursor = cursor.sort([tuple(s) for s in spec["sort"]])
                cursor = cursor.batch_size(batch_rows)

                rows_so_far = 0
                bytes_so_far = 0
                batch_index = 0
                start_sent = False
                buffer: list[dict] = []

                def flush(buf: list[dict]):
                    nonlocal sink, cols
                    docs = [_normalize_doc(d) for d in buf]
                    if not cols:
                        cols = _ordered_columns(docs)
                    table = {c: [d.get(c) for d in docs] for c in cols}
                    return pa.RecordBatch.from_pydict(table)

                for doc in cursor:
                    buffer.append(doc)
                    if len(buffer) < batch_rows:
                        continue
                    batch = flush(buffer)
                    buffer = []
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
                            "est_total_rows": est_total_rows,
                            "est_total_bytes": None,
                        }
                        start_sent = True
                    yield {
                        "type": "progress",
                        "rows_so_far": rows_so_far,
                        "bytes_so_far": bytes_so_far,
                        "batch_index": batch_index,
                    }

                if buffer:
                    batch = flush(buffer)
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
                            "est_total_rows": est_total_rows,
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
                            "est_total_rows": est_total_rows,
                            "est_total_bytes": None,
                        }
                    empty_schema = pa.schema([("_id", pa.string())])
                    write_empty_dataset(source_path, empty_schema, fmt)

            logging.info(f"[mongodb] ingested {rows_so_far} docs → {source_path}")
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
            logging.error(f"[mongodb] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            if sink:
                sink.close()
