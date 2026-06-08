"""
MySQL / MariaDB source connector.

Wire-compatible with MariaDB, so this single class serves both.

- Preview / metadata / test → ``mysql-connector-python`` cursor (preview is
  row-bounded, so memory safe).
- Ingest → DuckDB ``ATTACH ... (TYPE MYSQL)`` streaming via the shared
  :class:`DuckDBSQLSource` machinery — same fetch_arrow_reader() batch loop as
  PostgreSQL, so large exports never materialise in memory.

The driver is lazy-imported so the module loads even when it isn't installed.
"""

from __future__ import annotations

from typing import Any

from ._dbapi import DuckDBSQLSource


class MySQLSource(DuckDBSQLSource):
    dialect = "mysql"
    duckdb_extension = "mysql"
    duckdb_attach_type = "MYSQL"

    def _create_connection(self, host: str, port: int | None) -> Any:
        try:
            import mysql.connector
        except ImportError as e:
            raise RuntimeError(
                "mysql-connector-python is required for MySQL/MariaDB. "
                "pip install mysql-connector-python"
            ) from e

        c = self.config
        s = self.security_config

        kwargs: dict[str, Any] = {
            "host": host,
            "port": int(port) if port else 3306,
            "user": c["user"],
            "password": c.get("password") or "",
            "database": c.get("database"),
            "connection_timeout": self.connect_timeout,
            "charset": "utf8mb4",
        }

        if s.ssl_mode and s.ssl_mode != "disable":
            if s.ca_cert_path:
                kwargs["ssl_ca"] = s.ca_cert_path
            if s.client_cert_path:
                kwargs["ssl_cert"] = s.client_cert_path
            if s.client_key_path:
                kwargs["ssl_key"] = s.client_key_path
        else:
            kwargs["ssl_disabled"] = True

        return mysql.connector.connect(**kwargs)

    def _meta_scope(self) -> str | None:
        # In MySQL ``information_schema.columns.table_schema`` is the database.
        return self.config.get("database")

    def _duckdb_connection_string(self, host: str, port: int | None) -> str:
        c = self.config
        parts = [
            f"host={host}",
            f"port={int(port) if port else 3306}",
            f"user={c['user']}",
            f"database={c.get('database') or ''}",
        ]
        if c.get("password"):
            parts.append(f"password={c['password']}")
        return " ".join(parts)
