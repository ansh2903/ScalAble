"""
Microsoft SQL Server (and Azure SQL) source connector.

Uses the ``pymssql`` driver (FreeTDS-backed, lazy-imported). T-SQL has no
``LIMIT`` clause, so preview bounding is overridden to use ``SELECT TOP n``.
Everything else — ingest, ``information_schema`` metadata, SSH tunnelling — is
inherited from :class:`DBAPISource`.
"""

from __future__ import annotations

from typing import Any

from ._dbapi import DBAPISource


class MSSQLSource(DBAPISource):
    dialect = "mssql"

    def _create_connection(self, host: str, port: int | None) -> Any:
        try:
            import pymssql
        except ImportError as e:
            raise RuntimeError(
                "pymssql is required for SQL Server. pip install pymssql"
            ) from e

        c = self.config
        return pymssql.connect(
            server=host,
            port=str(int(port)) if port else "1433",
            user=c["user"],
            password=c.get("password") or "",
            database=c.get("database") or "",
            login_timeout=self.connect_timeout,
            timeout=0,
        )

    def _wrap_preview(self, body: str, limit: int) -> str:
        # T-SQL: bound rows with TOP rather than LIMIT.
        return f"SELECT TOP {int(limit)} * FROM ({body}) AS _q"

    def _meta_scope(self) -> str | None:
        return self.config.get("schema") or "dbo"
