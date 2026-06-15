"""
Snowflake warehouse connector — remote pushdown preview + streaming ingest to Parquet.
"""

import json
import os
import time
from typing import Generator

from ..base import BaseSource, SourceKind, SourceCapabilities
from ..utils import (
    make_batch_sink,
    normalize_output_format,
    prepare_stream_dir,
    source_filename,
    write_empty_dataset,
)
from spore._config.settings import settings
from spore._logger import logging


def _load_snowflake_private_key(config: dict) -> bytes | None:
    """Load a PEM private key file into DER bytes for snowflake-connector-python."""
    key_path = config.get("private_key_file")
    if not key_path or not os.path.isfile(key_path):
        return None

    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
    except ImportError as e:
        raise RuntimeError(
            "cryptography is required for Snowflake key-pair auth. pip install cryptography"
        ) from e

    with open(key_path, "rb") as fh:
        key_data = fh.read()

    passphrase = config.get("private_key_passphrase")
    password = passphrase.encode() if passphrase else None

    p_key = serialization.load_pem_private_key(
        key_data,
        password=password,
        backend=default_backend(),
    )
    return p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class SnowflakeSource(BaseSource):
    kind = SourceKind.WAREHOUSE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=False,
        needs_credentials=True,
    )

    def _connect_kwargs(self) -> dict:
        c = self.config
        kwargs = {
            "account": c["account_identifier"],
            "user": c["user"],
            "warehouse": c.get("warehouse"),
            "database": c.get("database"),
            "schema": c.get("schema", "PUBLIC"),
        }

        private_key = _load_snowflake_private_key(c)
        if private_key is not None:
            kwargs["private_key"] = private_key
        elif c.get("password"):
            kwargs["password"] = c["password"]

        return kwargs

    def _create_connection(self, host: str, port: int):
        try:
            import snowflake.connector
        except ImportError as e:
            raise RuntimeError(
                "snowflake-connector-python is required. pip install snowflake-connector-python"
            ) from e
        return snowflake.connector.connect(**self._connect_kwargs())

    def _close_connection(self, conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def test_connection(self) -> tuple[bool, str]:
        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = CURRENT_SCHEMA()
                    AND table_type = 'BASE TABLE'
                    LIMIT 200
                    """
                )
                tables = {row[0]: {"columns": {}} for row in cur.fetchall()}
            return True, {
                "db_type": "snowflake",
                "database": self.config.get("database"),
                "tables": tables,
            }
        except Exception as e:
            logging.error(f"[snowflake] metadata failed: {e}")
            return False, {}

    def preview(self, query: str, limit: int = 500):
        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(f"SELECT COUNT(*) FROM ({query.rstrip(';')}) AS _c")
                    total_rows = cur.fetchone()[0]
                except Exception:
                    total_rows = "unknown"

                cur.execute(f"SELECT * FROM ({query.rstrip(';')}) AS _q LIMIT {int(limit)}")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
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
                    "preview_count": len(rows),
                    "sample_rows": sample_rows,
                    "sample_bytes": sample_bytes,
                    "est_total_bytes": est_total_bytes,
                }
                yield {"type": "rows", "content": rows}
        except Exception as e:
            logging.error(f"[snowflake] preview failed: {e}")
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
        """Stream Snowflake results as Arrow batches — bounded memory.

        Uses the connector's native ``fetch_arrow_batches()`` so result chunks
        arrive pre-encoded as Arrow and are written one at a time.
        """
        import pyarrow as pa

        fmt = normalize_output_format(output_format)
        dest = destination_path or settings.SPORE_DATA_DIR
        stream_dir = prepare_stream_dir(os.path.join(dest, "streams", stream_name))
        source_path = os.path.join(stream_dir, source_filename(fmt))

        sink = None
        t0 = time.monotonic()

        try:
            with self.connection_context() as conn:
                cur = conn.cursor()
                cur.execute(query)
                est_total_rows = getattr(cur, "rowcount", None)
                cols = [d[0] for d in cur.description]

                rows_so_far = 0
                bytes_so_far = 0
                batch_index = 0
                est_total_bytes = None
                start_sent = False

                for table in cur.fetch_arrow_batches():
                    if table.num_rows == 0:
                        continue
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
                    empty_schema = pa.schema([(c, pa.string()) for c in cols])
                    write_empty_dataset(source_path, empty_schema, fmt)

            logging.info(f"[snowflake] ingested {rows_so_far} rows → {source_path}")
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
            logging.error(f"[snowflake] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            if sink:
                sink.close()
