"""
BigQuery warehouse connector — remote pushdown preview + streaming ingest to Parquet.
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


class BigQuerySource(BaseSource):
    kind = SourceKind.WAREHOUSE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=False,
        needs_credentials=True,
    )

    def _client(self):
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError as e:
            raise RuntimeError(
                "google-cloud-bigquery is required. pip install google-cloud-bigquery"
            ) from e

        c = self.config
        key_path = c.get("service_account_json")
        if key_path:
            if not os.path.isfile(key_path):
                raise FileNotFoundError(
                    f"Service account key not found at {key_path!r}. "
                    "Re-create the connection and upload the JSON key again."
                )
            creds = service_account.Credentials.from_service_account_file(key_path)
            return bigquery.Client(project=c["project_id"], credentials=creds)

        if c.get("service_account_json_text"):
            info = json.loads(c["service_account_json_text"])
            creds = service_account.Credentials.from_service_account_info(info)
            return bigquery.Client(project=c["project_id"], credentials=creds)

        return bigquery.Client(project=c["project_id"])

    def _create_connection(self, host: str, port: int):
        return self._client()

    def test_connection(self) -> tuple[bool, str]:
        try:
            client = self._client()
            list(client.list_datasets(max_results=1))
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            client = self._client()
            dataset = self.config.get("dataset_id")
            tables_ref = client.list_tables(f"{client.project}.{dataset}")
            tables = {t.table_id: {"columns": {}} for t in tables_ref}
            return True, {
                "db_type": "bigquery",
                "project": self.config.get("project_id"),
                "dataset": dataset,
                "tables": tables,
            }
        except Exception as e:
            logging.error(f"[bigquery] metadata failed: {e}")
            return False, {}

    def preview(self, query: str, limit: int = 500):
        try:
            client = self._client()
            job = client.query(f"SELECT * FROM ({query.rstrip(';')}) LIMIT {int(limit)}")
            table = job.result()
            arrow = table.to_arrow()
            rows = arrow.to_pylist()
            sample_rows = int(arrow.num_rows)
            sample_bytes = int(arrow.nbytes)

            count_job = client.query(f"SELECT COUNT(*) AS cnt FROM ({query.rstrip(';')})")
            try:
                total_rows = list(count_job.result())[0]["cnt"]
            except Exception:
                total_rows = "unknown"

            est_total_bytes = (
                round(sample_bytes / sample_rows * total_rows)
                if isinstance(total_rows, int) and sample_rows > 0
                else None
            )

            yield {"type": "columns", "content": arrow.schema.names}
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
            logging.error(f"[bigquery] preview failed: {e}")
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
        """Stream BigQuery results as Arrow batches — never materialises the full table.

        Uses ``RowIterator.to_arrow_iterable()`` so only one batch is held in
        memory at a time, instead of the previous full ``to_arrow()`` load.
        """
        fmt = normalize_output_format(output_format)
        dest = destination_path or settings.SPORE_DATA_DIR
        stream_dir = prepare_stream_dir(os.path.join(dest, "streams", stream_name))
        source_path = os.path.join(stream_dir, source_filename(fmt))

        sink = None
        t0 = time.monotonic()

        try:
            client = self._client()
            row_iter = client.query(query).result()
            est_total_rows = getattr(row_iter, "total_rows", None)

            rows_so_far = 0
            bytes_so_far = 0
            batch_index = 0
            est_total_bytes = None
            start_sent = False
            last_schema = None

            for batch in row_iter.to_arrow_iterable():
                last_schema = batch.schema
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
                schema = last_schema or row_iter.to_arrow().schema
                write_empty_dataset(source_path, schema, fmt)

            logging.info(f"[bigquery] ingested {rows_so_far} rows → {source_path}")
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
            logging.error(f"[bigquery] ingest failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            if sink:
                sink.close()
