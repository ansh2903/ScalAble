"""Relation catalog: stream metadata + workspace data_json merge."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import duckdb

from spore._compute.streams import duckdb_read_expr, resolve_stream_source, streams_root


def scan_stream(stream_name: str) -> dict[str, Any]:
    """Inspect a stream on disk and return catalog entry."""
    abs_path, ext, version = resolve_stream_source(stream_name)
    columns: list[str] = []
    row_count: int | None = None
    try:
        con = duckdb.connect()
        read_expr = duckdb_read_expr(abs_path)
        meta = con.execute(f"SELECT COUNT(*) AS n FROM ({read_expr}) AS _t").fetchone()
        row_count = int(meta[0]) if meta else None
        desc = con.execute(f"DESCRIBE SELECT * FROM ({read_expr}) AS _t").fetchall()
        columns = [r[0] for r in desc]
        con.close()
    except Exception:
        pass

    size_bytes = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
    return {
        "name": stream_name,
        "version": version,
        "updated_at": datetime.fromtimestamp(version, tz=timezone.utc).isoformat(),
        "format": ext,
        "columns": columns,
        "row_count": row_count,
        "size_bytes": size_bytes,
        "path": abs_path,
    }


def list_streams() -> list[dict[str, Any]]:
    """List all streams discovered on disk."""
    root = streams_root()
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        stream_dir = root / name
        if not stream_dir.is_dir():
            continue
        try:
            out.append(scan_stream(name))
        except FileNotFoundError:
            continue
    return out


def reconcile_relations(catalog: dict[str, Any] | None) -> dict[str, Any]:
    """
    Merge persisted catalog with filesystem streams. Filesystem wins on version.
    """
    catalog = dict(catalog or {})
    relations = dict(catalog.get("relations") or {})
    for entry in list_streams():
        name = entry["name"]
        disk_ver = entry["version"]
        existing = relations.get(name) or {}
        if not existing or disk_ver >= float(existing.get("version") or 0):
            relations[name] = {**existing, **entry}
    catalog["relations"] = relations
    return catalog
