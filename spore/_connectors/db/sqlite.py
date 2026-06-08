"""
SQLite source connector.

The simplest possible database to connect: a single local file, no server,
no credentials. The DB file is provided through the ``file_path`` field
(uploaded via the connection wizard like other local files).

- Preview / metadata / test → standard-library ``sqlite3`` (no extra deps;
  preview is row-bounded, so memory safe).
- Ingest → DuckDB ``ATTACH ... (TYPE SQLITE)`` streaming via the shared
  :class:`DuckDBSQLSource` machinery, so large exports never materialise in memory.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from ._dbapi import DuckDBSQLSource
from ..base import SourceCapabilities
from spore._logger import logging


class SQLiteSource(DuckDBSQLSource):
    dialect = "sqlite"
    duckdb_extension = "sqlite"
    duckdb_attach_type = "SQLITE"
    capabilities = SourceCapabilities(
        can_preview=True,
        can_ingest=True,
        can_stream=True,
        needs_ssh=False,
        needs_credentials=False,
    )

    def _db_path(self) -> str:
        return (self.config.get("file_path") or self.config.get("database") or "").strip()

    def _create_connection(self, host: str, port: int | None) -> Any:
        path = self._db_path()
        if not path:
            raise ValueError("SQLite requires a database file path")
        if not os.path.exists(path):
            raise FileNotFoundError(f"SQLite database not found at {path!r}")
        return sqlite3.connect(path, timeout=self.connect_timeout)

    def _duckdb_connection_string(self, host: str, port: int | None) -> str:
        path = self._db_path()
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"SQLite database not found at {path!r}")
        return path

    def test_connection(self) -> tuple[bool, str]:
        path = self._db_path()
        if not path:
            return False, "Missing database file path"
        if not os.path.exists(path):
            return False, "Database file not found"
        return super().test_connection()

    def fetch_metadata(self) -> tuple[bool, dict]:
        try:
            meta: dict[str, Any] = {
                "db_type": "sqlite",
                "database": os.path.basename(self._db_path()),
                "schema": None,
                "table_count": 0,
                "total_columns": 0,
                "tables": {},
            }
            with self.connection_context() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
                table_names = [r[0] for r in cur.fetchall()]

                for table_name in table_names:
                    # PRAGMA can't be parameterised; identifier is double-quoted.
                    safe = table_name.replace('"', '""')
                    cur.execute(f'PRAGMA table_info("{safe}")')
                    cols = cur.fetchall()  # (cid, name, type, notnull, dflt, pk)
                    column_names = [c[1] for c in cols]
                    column_types = {c[1]: (c[2] or "") for c in cols}
                    pk_columns = [c[1] for c in cols if c[5]]
                    meta["total_columns"] += len(column_names)
                    meta["tables"][table_name] = {
                        "columns": column_names,
                        "column_types": column_types,
                        "primary_keys": pk_columns,
                    }
            meta["table_count"] = len(meta["tables"])
            return True, meta
        except Exception as e:
            logging.error(f"[sqlite] metadata failed: {e}")
            return False, {}
