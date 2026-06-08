"""
Amazon Redshift warehouse connector.

Redshift speaks the PostgreSQL wire protocol and reuses the generic
:class:`DBAPISource` cursor machinery via ``psycopg2`` (already a dependency).

DuckDB's postgres scanner is unreliable against Redshift's forked catalog, so
ingest uses the reliable *workaround*: a psycopg2 **server-side (named) cursor**
with ``itersize`` batching. psycopg2's default cursor buffers the whole result
client-side, which would defeat memory safety — the named cursor streams rows
from the leader node instead. Preview is row-bounded, so the plain cursor is fine.
"""

from __future__ import annotations

from typing import Any

from ..base import SourceKind
from ..db._dbapi import DBAPISource


class RedshiftSource(DBAPISource):
    kind = SourceKind.WAREHOUSE
    dialect = "redshift"

    def _create_connection(self, host: str, port: int | None) -> Any:
        try:
            import psycopg2
        except ImportError as e:
            raise RuntimeError(
                "psycopg2 is required for Redshift. pip install psycopg2-binary"
            ) from e

        c = self.config
        return psycopg2.connect(
            host=host,
            port=int(port) if port else 5439,
            dbname=c.get("database"),
            user=c["user"],
            password=c.get("password") or "",
            connect_timeout=self.connect_timeout,
            sslmode=self.security_config.ssl_mode or "prefer",
        )

    def _before_query(self, cur: Any) -> None:
        schema = self.config.get("schema")
        if schema:
            safe = schema.replace('"', '""')
            cur.execute(f'SET search_path TO "{safe}"')

    def _open_ingest_cursor(self, conn: Any, batch_rows: int) -> Any:
        # Named cursor → server-side streaming (psycopg2 default buffers all rows).
        cur = conn.cursor(name="spore_redshift_stream")
        cur.itersize = batch_rows
        return cur

    def _meta_scope(self) -> str | None:
        return self.config.get("schema") or "public"
