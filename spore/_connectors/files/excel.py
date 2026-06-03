from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Generator

import pyarrow as pa

from ..base import BaseSource, SourceCapabilities, SourceKind
from ._preview import ingest_excel, preview_excel
from ._utils import _stat
from spore._logger import logging


@dataclass
class _NoopConn:
    def close(self) -> None:  # pragma: no cover
        return


class ExcelFileSource(BaseSource):
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
            import pandas as pd
        except ImportError:
            return False, {"error": "pandas is required for excel metadata"}  # type: ignore[return-value]

        try:
            size_bytes, size_pretty = _stat(path)
            xls = pd.ExcelFile(path, engine="openpyxl")

            entities: dict[str, dict] = {}
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet, nrows=200)
                cols = [str(c) for c in df.columns]
                dtypes = {str(k): str(v) for k, v in df.dtypes.to_dict().items()}
                entities[sheet] = {
                    "kind": "sheet",
                    "columns": cols,
                    "column_types": dtypes,
                    "row_count": None,
                    "size_bytes": size_bytes,
                    "size_pretty": size_pretty,
                }

            return True, {
                "db_type": "excel_file",
                "kind": self.kind.value,
                "path": path,
                "entities": entities,
            }
        except Exception as e:
            logging.error(f"[excel_file] metadata failed: {e}")
            return False, {}

    def preview(self, query: str, limit: int = 100) -> Generator[dict, None, None]:
        yield from preview_excel(self.config, query, limit)

    def ingest(
        self,
        stream_name: str,
        query: str,
        destination_path: str | None = None,
        memory_ceiling: str = "1GB",
        batch_row_size: int = 10000,
        output_format: str = "parquet",
    ) -> Generator[dict, None, None]:
        yield from ingest_excel(
            self.config, stream_name, query, output_format, batch_row_size
        )
