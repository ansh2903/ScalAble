"""Resolve materialized stream paths under SPORE_DATA_DIR."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from spore._config.settings import settings

STREAMS_ROOT = Path(settings.SPORE_DATA_DIR) / "streams"

SUPPORTED_READ_EXTS = frozenset({"parquet", "csv", "tsv", "json", "xlsx"})
EXCEL_EXTS = frozenset({"xlsx"})

# Cache parsed Excel tables so dashboards with many widgets don't re-read workbooks.
_excel_cache: dict[tuple[str, float, str | None], Any] = {}


def streams_root() -> Path:
    root = STREAMS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def split_sheet_ref(ref: str) -> tuple[str, str | None]:
    """Split ``relpath::SheetName`` into base path and optional sheet name."""
    ref = (ref or "").strip()
    if "::" in ref:
        base, sheet = ref.rsplit("::", 1)
        sheet = sheet.strip() or None
        return base.strip(), sheet
    return ref, None


def normalize_rel_path(rel: str) -> str:
    """Normalize a relative path under streams root; reject traversal."""
    rel = (rel or "").strip().replace("\\", "/").strip("/")
    parts: list[str] = []
    for part in rel.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("Invalid path")
        parts.append(part)
    return "/".join(parts)


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


def resolve_dataset_source(rel_path: str) -> tuple[str, str, float]:
    """Resolve any supported file under streams root by relative path."""
    rel = normalize_rel_path(rel_path)
    if not rel:
        raise ValueError("Path is required")

    root = streams_root().resolve()
    abs_path = (root / rel).resolve()
    if not str(abs_path).startswith(str(root) + os.sep):
        raise ValueError("Path escapes streams root")
    if not abs_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {rel}")

    ext = abs_path.suffix.lstrip(".").lower()
    if ext not in SUPPORTED_READ_EXTS:
        raise ValueError(f"Unsupported dataset format: {ext}")

    return str(abs_path), ext, abs_path.stat().st_mtime


def resolve_source(ref: str) -> tuple[str, str, float, str | None]:
    """
    Resolve a dashboard data reference: stream name (no slash), relative file
    path, or ``relpath::SheetName`` for Excel workbooks. Returns
    (absolute_path, extension, version_mtime, sheet_name_or_none).
    """
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("Reference is required")

    base_ref, sheet = split_sheet_ref(ref)

    if "/" not in base_ref and "\\" not in base_ref:
        stream_dir = streams_root() / base_ref
        if stream_dir.is_dir():
            try:
                abs_path, ext, version = resolve_stream_source(base_ref)
                return abs_path, ext, version, sheet
            except FileNotFoundError:
                pass

    abs_path, ext, version = resolve_dataset_source(base_ref)
    return abs_path, ext, version, sheet


def read_excel_table(abs_path: str, sheet: str | None = None):
    """Load an Excel sheet into a pandas DataFrame (cached by path/mtime/sheet)."""
    import pandas as pd

    mtime = os.path.getmtime(abs_path)
    key = (abs_path, mtime, sheet)
    cached = _excel_cache.get(key)
    if cached is not None:
        return cached

    if sheet:
        df = pd.read_excel(abs_path, sheet_name=sheet, engine="openpyxl")
    else:
        df = pd.read_excel(abs_path, sheet_name=0, engine="openpyxl")

    _excel_cache[key] = df
    return df


def list_excel_sheets(abs_path: str) -> list[str]:
    """Return sheet names for an .xlsx workbook."""
    import pandas as pd

    return list(pd.ExcelFile(abs_path, engine="openpyxl").sheet_names)


def duckdb_read_expr(abs_path: str) -> str:
    """Safe DuckDB table expression for a non-Excel stream source file."""
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
    if ext in EXCEL_EXTS:
        raise ValueError("Excel sources must be read via duckdb_read_source()")
    raise ValueError(f"Unsupported stream format: {ext}")


def duckdb_read_source(con, abs_path: str, ext: str, sheet: str | None = None) -> str:
    """
    Return a DuckDB-readable subquery for *abs_path*. Excel workbooks are
    registered on *con* as ``_xl_src``; other formats use native readers.
    """
    if ext in EXCEL_EXTS:
        df = read_excel_table(abs_path, sheet)
        con.register("_xl_src", df)
        return "(SELECT * FROM _xl_src)"
    return duckdb_read_expr(abs_path)
