"""Tests for compute layer (streams, query, relations)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def streams_env(tmp_path, monkeypatch):
    streams = tmp_path / "streams"
    streams.mkdir()
    stream_dir = streams / "test_stream"
    stream_dir.mkdir()
    table = pa.table({"category": ["a", "b", "a"], "amount": [10, 20, 15]})
    pq.write_table(table, stream_dir / "source.parquet")
    monkeypatch.setenv("SPORE_DATA_DIR", str(tmp_path))
    from spore._config import settings as settings_mod

    settings_mod.settings.SPORE_DATA_DIR = str(tmp_path)
    import spore._compute.streams as streams_mod
    import spore._compute.relations as relations_mod

    streams_mod.STREAMS_ROOT = streams
    relations_mod.STREAMS_ROOT = streams
    yield tmp_path


def test_resolve_stream_source(streams_env):
    from spore._compute.streams import resolve_stream_source

    path, ext, ver = resolve_stream_source("test_stream")
    assert ext == "parquet"
    assert os.path.isfile(path)
    assert ver > 0


def test_query_stream_aggregate(streams_env):
    from spore._compute.query import query_stream

    result = query_stream(
        "test_stream",
        transform={
            "dimensions": ["category"],
            "measures": [{"field": "amount", "agg": "sum"}],
            "limit": 100,
        },
    )
    assert result["row_count"] >= 1
    assert "category" in result["columns"]
    assert result["version"] > 0


def test_scan_stream_and_reconcile(streams_env):
    from spore._compute.relations import scan_stream, reconcile_relations

    entry = scan_stream("test_stream")
    assert entry["name"] == "test_stream"
    assert "amount" in entry.get("columns", []) or entry.get("columns") == []
    assert entry.get("schema") and any(s["name"] == "amount" for s in entry["schema"])

    merged = reconcile_relations({})
    assert "test_stream" in merged["relations"]


def test_query_stream_count_measure_alias(streams_env):
    from spore._compute.query import query_stream

    result = query_stream(
        "test_stream",
        transform={
            "dimensions": ["category"],
            "measures": [{"field": "category", "agg": "count"}],
            "limit": 100,
        },
    )
    assert result["row_count"] >= 1
    assert result["columns"][0] == "category"
    assert result["columns"][1] == "category_count"


def test_list_datasets_and_resolve_path(streams_env):
    from spore._compute.relations import list_datasets
    from spore._compute.streams import resolve_source

    streams = Path(streams_env) / "streams"
    uploads = streams / "uploads"
    uploads.mkdir()
    (uploads / "data.csv").write_text("category,amount\nx,1\ny,2\n", encoding="utf-8")

    datasets = list_datasets()
    refs = {d["ref"] for d in datasets}
    assert "test_stream" in refs
    assert "uploads/data.csv" in refs

    path, ext, _, sheet = resolve_source("uploads/data.csv")
    assert ext == "csv"
    assert sheet is None
    assert os.path.isfile(path)


def test_quote_ident_special_column_names():
    from spore._compute.query import _quote_ident, build_transform_sql

    assert _quote_ident("Sub-Category") == '"Sub-Category"'
    assert _quote_ident("Order Date") == '"Order Date"'
    assert _quote_ident('Sales ("USD")') == '"Sales (""USD"")"'

    sql = build_transform_sql(
        "read_parquet('x')",
        {
            "dimensions": ["Sub-Category"],
            "measures": [{"field": "Order Date", "agg": "count"}],
            "limit": 10,
        },
    )
    assert '"Sub-Category"' in sql
    assert '"Order Date"' in sql
    assert "COUNT(" in sql


def test_query_stream_count_rows_measure(streams_env):
    from spore._compute.query import query_stream

    result = query_stream(
        "test_stream",
        transform={
            "measures": [{"field": "*", "agg": "count"}],
            "limit": 100,
        },
    )
    assert result["row_count"] == 1
    assert "count" in result["columns"]
    assert result["rows"][0]["count"] == 3


def test_list_xlsx_sheets(streams_env):
    import pandas as pd
    from spore._compute.relations import list_datasets
    from spore._compute.query import query_stream

    streams = Path(streams_env) / "streams"
    uploads = streams / "uploads"
    uploads.mkdir(exist_ok=True)
    xlsx_path = uploads / "book.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame({"region": ["East", "West"], "sales": [100, 200]}).to_excel(
            writer, sheet_name="Orders", index=False
        )
        pd.DataFrame({"region": ["North"], "sales": [50]}).to_excel(
            writer, sheet_name="Returns", index=False
        )

    datasets = list_datasets()
    refs = {d["ref"]: d for d in datasets}
    assert "uploads/book.xlsx::Orders" in refs
    assert "uploads/book.xlsx::Returns" in refs
    assert refs["uploads/book.xlsx::Orders"]["label"] == "uploads/book.xlsx (Orders)"

    result = query_stream(
        "uploads/book.xlsx::Orders",
        transform={
            "dimensions": ["region"],
            "measures": [{"field": "sales", "agg": "sum"}],
            "limit": 100,
        },
    )
    assert result["row_count"] == 2
    assert "region" in result["columns"]
    assert "sales" in result["columns"]


def test_query_stream_special_column_names(streams_env):
    from spore._compute.query import query_stream

    streams = Path(streams_env) / "streams"
    special = streams / "special_cols"
    special.mkdir()
    table = pa.table({
        "Sub-Category": ["A", "B", "A"],
        "Order Date": [1, 2, 3],
        "amount": [10.0, 20.0, 15.0],
    })
    pq.write_table(table, special / "source.parquet")

    result = query_stream(
        "special_cols",
        transform={
            "dimensions": ["Sub-Category"],
            "measures": [{"field": "amount", "agg": "sum"}],
            "limit": 100,
        },
    )
    assert result["row_count"] >= 1
    assert "Sub-Category" in result["columns"]
    assert "amount" in result["columns"]
