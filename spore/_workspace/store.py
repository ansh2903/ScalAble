"""SQLite-backed workspace catalog with WAL."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spore._config.settings import settings
from spore._utils import generate_id

DEFAULT_NOTEBOOK = {"name": "", "cells": [], "cell_counter": 0}
DEFAULT_DASHBOARD = {
    "title": "",
    "widgets": [],
    "layout": {"columns": 12},
    "metadata": {},
}
DEFAULT_DATA_STATE = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class WorkspaceStore:
    """Thread-local SQLite access for workspace CRUD and panel state."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path | None = None) -> None:
        root = Path(settings.SPORE_DATA_DIR)
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else root / "workspaces.db"
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    def initialize(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_opened_at TEXT
            );

            CREATE TABLE IF NOT EXISTS workspace_state (
                workspace_id TEXT PRIMARY KEY,
                active_view TEXT NOT NULL DEFAULT 'data',
                selected_connection_id TEXT,
                data_json TEXT NOT NULL DEFAULT '{}',
                notebook_json TEXT NOT NULL DEFAULT '{}',
                dashboard_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS query_history (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_query_history_workspace_ts
                ON query_history(workspace_id, timestamp DESC);
            """
        )
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
        conn.commit()

    def list_workspaces(self) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            """
            SELECT id, name, description, created_at, updated_at, last_opened_at
            FROM workspaces
            ORDER BY COALESCE(last_opened_at, updated_at) DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            """
            SELECT id, name, description, created_at, updated_at, last_opened_at
            FROM workspaces WHERE id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return dict(row) if row else None

    def create_workspace(
        self,
        name: str,
        description: str = "",
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        wid = workspace_id or generate_id()
        now = _utc_now()
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO workspaces (id, name, description, created_at, updated_at, last_opened_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (wid, name.strip(), (description or "").strip(), now, now, now),
        )
        conn.execute(
            """
            INSERT INTO workspace_state (
                workspace_id, active_view, selected_connection_id,
                data_json, notebook_json, dashboard_json, updated_at
            ) VALUES (?, 'data', NULL, ?, ?, ?, ?)
            """,
            (
                wid,
                json.dumps(DEFAULT_DATA_STATE),
                json.dumps(DEFAULT_NOTEBOOK),
                json.dumps(DEFAULT_DASHBOARD),
                now,
            ),
        )
        conn.commit()
        return self.get_workspace(wid)  # type: ignore[return-value]

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        if name is not None:
            ws["name"] = name.strip()
        if description is not None:
            ws["description"] = description.strip()
        now = _utc_now()
        ws["updated_at"] = now
        self._conn().execute(
            """
            UPDATE workspaces
            SET name = ?, description = ?, updated_at = ?
            WHERE id = ?
            """,
            (ws["name"], ws["description"], now, workspace_id),
        )
        self._conn().commit()
        return ws

    def delete_workspace(self, workspace_id: str) -> bool:
        cur = self._conn().execute(
            "DELETE FROM workspaces WHERE id = ?", (workspace_id,)
        )
        self._conn().commit()
        return cur.rowcount > 0

    def touch_workspace(self, workspace_id: str) -> None:
        now = _utc_now()
        self._conn().execute(
            """
            UPDATE workspaces
            SET last_opened_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, workspace_id),
        )
        self._conn().commit()

    def get_state(self, workspace_id: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            """
            SELECT workspace_id, active_view, selected_connection_id,
                   data_json, notebook_json, dashboard_json, updated_at
            FROM workspace_state WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "workspace_id": row["workspace_id"],
            "active_view": row["active_view"],
            "selected_connection_id": row["selected_connection_id"],
            "data": _parse_json(row["data_json"], DEFAULT_DATA_STATE),
            "notebook": _parse_json(row["notebook_json"], DEFAULT_NOTEBOOK),
            "dashboard": _parse_json(row["dashboard_json"], DEFAULT_DASHBOARD),
            "updated_at": row["updated_at"],
        }

    def patch_state(self, workspace_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_state(workspace_id)
        if not current:
            return None

        if "active_view" in patch and patch["active_view"]:
            current["active_view"] = str(patch["active_view"])
        if "selected_connection_id" in patch:
            val = patch["selected_connection_id"]
            current["selected_connection_id"] = str(val) if val else None
        if "data" in patch and isinstance(patch["data"], dict):
            current["data"] = {**current.get("data", {}), **patch["data"]}
        if "notebook" in patch and isinstance(patch["notebook"], dict):
            current["notebook"] = {**current.get("notebook", {}), **patch["notebook"]}
        if "dashboard" in patch and isinstance(patch["dashboard"], dict):
            current["dashboard"] = {**current.get("dashboard", {}), **patch["dashboard"]}

        now = _utc_now()
        self._conn().execute(
            """
            UPDATE workspace_state
            SET active_view = ?, selected_connection_id = ?,
                data_json = ?, notebook_json = ?, dashboard_json = ?, updated_at = ?
            WHERE workspace_id = ?
            """,
            (
                current["active_view"],
                current["selected_connection_id"],
                json.dumps(current["data"]),
                json.dumps(current["notebook"]),
                json.dumps(current["dashboard"]),
                now,
                workspace_id,
            ),
        )
        self._conn().execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?",
            (now, workspace_id),
        )
        self._conn().commit()
        current["updated_at"] = now
        return current

    def list_history(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            """
            SELECT id, workspace_id, timestamp, payload_json
            FROM query_history
            WHERE workspace_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = _parse_json(row["payload_json"], {})
            payload.setdefault("id", row["id"])
            payload.setdefault("timestamp", row["timestamp"])
            out.append(payload)
        return out

    def append_history(
        self, workspace_id: str, entry: dict[str, Any], limit: int = 50
    ) -> dict[str, Any]:
        entry_id = entry.get("id") or f"q_{generate_id()}"
        ts = float(entry.get("timestamp") or datetime.now(timezone.utc).timestamp() * 1000)
        payload = {k: v for k, v in entry.items() if k not in ("id", "timestamp")}
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO query_history (id, workspace_id, timestamp, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (entry_id, workspace_id, ts, json.dumps(payload)),
        )
        # Trim old rows beyond limit
        conn.execute(
            """
            DELETE FROM query_history
            WHERE workspace_id = ? AND id NOT IN (
                SELECT id FROM query_history
                WHERE workspace_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            )
            """,
            (workspace_id, workspace_id, limit),
        )
        conn.execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?",
            (_utc_now(), workspace_id),
        )
        conn.commit()
        return {"id": entry_id, "timestamp": ts, **payload}

    def clear_history(self, workspace_id: str) -> None:
        self._conn().execute(
            "DELETE FROM query_history WHERE workspace_id = ?",
            (workspace_id,),
        )
        self._conn().commit()

    def ensure_default_workspace(self) -> dict[str, Any]:
        """Create a default workspace if none exist."""
        existing = self.list_workspaces()
        if existing:
            return existing[0]
        return self.create_workspace("Default Workspace", "Your first analysis workspace")

    def journal_mode(self) -> str:
        row = self._conn().execute("PRAGMA journal_mode").fetchone()
        return row[0] if row else "unknown"


_store: WorkspaceStore | None = None
_store_lock = threading.Lock()


def get_workspace_store() -> WorkspaceStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = WorkspaceStore()
            _store.initialize()
        return _store
