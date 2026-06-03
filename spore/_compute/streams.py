"""Resolve materialized stream paths under SPORE_DATA_DIR."""

from __future__ import annotations

import os
from pathlib import Path

from spore._config.settings import settings

STREAMS_ROOT = Path(settings.SPORE_DATA_DIR) / "streams"


def streams_root() -> Path:
    root = STREAMS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_stream_source(stream_name: str) -> tuple[str, str, float]:
    """
    Return (absolute_path, extension, version_mtime) for a stream's source file.
    """
    name = (stream_name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Invalid stream name")

    stream_dir = streams_root() / name
    if not stream_dir.is_dir():
        raise FileNotFoundError(f"Stream not found: {name}")

    for entry in sorted(stream_dir.iterdir()):
        if entry.is_file() and entry.name.startswith("source."):
            return str(entry.resolve()), entry.suffix.lstrip(".").lower(), entry.stat().st_mtime

    raise FileNotFoundError(f"No source file in stream: {name}")


def duckdb_read_expr(abs_path: str) -> str:
    """Safe DuckDB table expression for a stream source file."""
    path = os.path.abspath(abs_path)
    root = str(streams_root().resolve())
    if not path.startswith(root + os.sep):
        raise ValueError("Path escapes streams root")
    escaped = path.replace("'", "''")
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext == "parquet":
        return f"read_parquet('{escaped}')"
    if ext in ("csv", "tsv"):
        return f"read_csv_auto('{escaped}')"
    if ext == "json":
        return f"read_json_auto('{escaped}')"
    if ext in ("xlsx", "xls"):
        return f"read_csv_auto('{escaped}')"
    raise ValueError(f"Unsupported stream format: {ext}")
