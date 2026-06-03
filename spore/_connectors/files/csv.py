from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Generator

from ..base import BaseSource, SourceCapabilities, SourceKind
from ._preview import ingest_csv, preview_csv
from ._utils import _column_types_from_arrow, _stat
from spore._logger import logging


@dataclass
class _NoopConn:
    def close(self) -> None:  # pragma: no cover
        return


class CSVFileSource(BaseSource):
    kind = SourceKind.FILE
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=False,
        needs_ssh=False,
        needs_credentials=False,
    )

    def _create_connection(self, host: str, port: int | None) -> Any:
        return _NoopConn()

    def test_connection(self) -> tuple[bool, str]:
        path = (self.config.get("file_path") or "").strip()
        if not path:
            return False, "Missing file_path"
        if not os.path.exists(path):
            return False, "File not found"
        return True, "File accessible"

    def fetch_metadata(self) -> tuple[bool, dict]:
        path = (self.config.get("file_path") or "").strip()
        if not path or not os.path.exists(path):
            return False, {}

        try:
            import pyarrow.csv as pa_csv

            delimiter = (self.config.get("delimiter") or ",")[:1]
            has_header = self.config.get("has_header", True)
            size_bytes, size_pretty = _stat(path)

            table = pa_csv.read_csv(
                path,
                parse_options=pa_csv.ParseOptions(delimiter=delimiter),
                read_options=pa_csv.ReadOptions(
                    autogenerate_column_names=not bool(has_header),
                    skip_rows=0,
                ),
                convert_options=pa_csv.ConvertOptions(check_utf8=False),
            )

            schema = table.schema
            return True, {
                "db_type": "csv_file",
                "kind": self.kind.value,
                "path": path,
                "entities": {
                    os.path.basename(path): {
                        "kind": "file",
                        "columns": schema.names,
                        "column_types": _column_types_from_arrow(schema),
                        "row_count": None,
                        "size_bytes": size_bytes,
                        "size_pretty": size_pretty,
                    }
                },
            }
        except Exception as e:
            logging.error(f"[csv_file] metadata failed: {e}")
            return False, {}

    def preview(self, query: str, limit: int = 100) -> Generator[dict, None, None]:
        yield from preview_csv(self.config, query, limit)

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        yield from ingest_csv(self.config, stream_name, output_format, batch_row_size)
