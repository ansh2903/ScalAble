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

    merged = reconcile_relations({})
    assert "test_stream" in merged["relations"]
