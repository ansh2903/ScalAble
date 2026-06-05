"""Relation catalog: stream metadata + workspace data_json merge."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import duckdb

from spore._compute.streams import (
    EXCEL_EXTS,
    SUPPORTED_READ_EXTS,
    duckdb_read_source,
    list_excel_sheets,
    normalize_rel_path,
    resolve_dataset_source,
    resolve_stream_source,
    split_sheet_ref,
    streams_root,
)


def _probe_columns(
    abs_path: str,
    ext: str,
    sheet: str | None = None,
) -> tuple[list[str], list[dict[str, str]], int | None]:
    columns: list[str] = []
    schema: list[dict[str, str]] = []
    row_count: int | None = None
    try:
        con = duckdb.connect()
        read_expr = duckdb_read_source(con, abs_path, ext, sheet)
        meta = con.execute(f"SELECT COUNT(*) AS n FROM {read_expr} AS _t").fetchone()
        row_count = int(meta[0]) if meta else None
        try:
            desc = con.execute(f"DESCRIBE SELECT * FROM {read_expr} AS _t").fetchall()
            columns = [r[0] for r in desc]
            schema = [{"name": r[0], "type": str(r[1])} for r in desc]
        except Exception:
            probe = con.execute(f"SELECT * FROM {read_expr} AS _t LIMIT 1")
            if hasattr(probe, "fetch_arrow_table"):
                table = probe.fetch_arrow_table()
            else:
                table = probe.to_arrow_table()
            columns = list(table.schema.names)
            schema = [
                {"name": name, "type": str(table.schema.field(name).type)}
                for name in columns
            ]
        con.close()
    except Exception:
        pass
    return columns, schema, row_count


def _is_stream_rel(rel: str) -> bool:
    parts = rel.split("/")
    return len(parts) == 2 and bool(parts[0]) and parts[1].startswith("source.")


def _dataset_label(rel: str) -> str:
    return rel.split("/")[0] if _is_stream_rel(rel) else rel


def scan_dataset(rel_path: str) -> dict[str, Any]:
    """Inspect any supported file under streams root (optional ``::SheetName``)."""
    base_rel, sheet = split_sheet_ref(rel_path)
    rel = normalize_rel_path(base_rel)
    abs_path, ext, version = resolve_dataset_source(rel)
    columns, schema, row_count = _probe_columns(abs_path, ext, sheet)
    size_bytes = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0

    base_ref = rel.split("/")[0] if _is_stream_rel(rel) else rel
    if sheet:
        ref = f"{base_ref}::{sheet}"
        label = f"{_dataset_label(rel)} ({sheet})"
        path_rel = f"{rel}::{sheet}"
    else:
        ref = base_ref
        label = _dataset_label(rel)
        path_rel = rel

    return {
        "ref": ref,
        "name": ref,
        "label": label,
        "path_rel": path_rel,
        "is_stream": _is_stream_rel(rel),
        "version": version,
        "updated_at": datetime.fromtimestamp(version, tz=timezone.utc).isoformat(),
        "format": ext,
        "columns": columns,
        "schema": schema,
        "row_count": row_count,
        "size_bytes": size_bytes,
        "path": abs_path,
        "sheet": sheet,
    }


def list_datasets() -> list[dict[str, Any]]:
    """Walk streams root and return all queryable dataset files."""
    root = streams_root()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out

    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in SUPPORTED_READ_EXTS:
                continue
            abs_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(abs_path, root).replace("\\", "/")

            scan_targets: list[str]
            if ext in EXCEL_EXTS:
                try:
                    scan_targets = [f"{rel}::{name}" for name in list_excel_sheets(abs_path)]
                except Exception:
                    continue
            else:
                scan_targets = [rel]

            for scan_rel in scan_targets:
                try:
                    entry = scan_dataset(scan_rel)
                except (FileNotFoundError, ValueError):
                    continue
                ref = entry["ref"]
                if ref in seen:
                    continue
                seen.add(ref)
                out.append(entry)

    return sorted(out, key=lambda e: (not e.get("is_stream"), e.get("label", "")))


def scan_stream(stream_name: str) -> dict[str, Any]:
    """Inspect a stream on disk and return catalog entry."""
    abs_path, ext, version = resolve_stream_source(stream_name)
    columns, schema, row_count = _probe_columns(abs_path, ext, sheet=None)
    rel = f"{stream_name}/source.{ext}"
    size_bytes = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
    return {
        "ref": stream_name,
        "name": stream_name,
        "label": stream_name,
        "path_rel": rel,
        "is_stream": True,
        "version": version,
        "updated_at": datetime.fromtimestamp(version, tz=timezone.utc).isoformat(),
        "format": ext,
        "columns": columns,
        "schema": schema,
        "row_count": row_count,
        "size_bytes": size_bytes,
        "path": abs_path,
        "sheet": None,
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
