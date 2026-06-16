"""Tests for bytes-safe file normalization used by inspect and push."""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pytest

from spore._connectors.db.postgresql import PostgreSQLSource
from spore._connectors.utils import (
    dataframe_to_arrow_table,
    infer_table_schema,
    make_json_safe,
    normalize_dataframe,
    normalize_scalar,
    read_pandas_file,
    sanitize_column_names,
)


def test_normalize_bytes_scalar_numeric_text():
    assert normalize_scalar(b"1") == 1
    assert normalize_scalar(b"0") == 0
    assert normalize_scalar(bytearray(b"42")) == 42
    assert normalize_scalar(memoryview(b"7")) == 7


def test_normalize_bytes_scalar_single_byte():
    assert normalize_scalar(b"\x01") == 1


def test_make_json_safe_nested_rows():
    payload = {"rows": [{"mode": b"1", "name": b"track"}]}
    safe = make_json_safe(payload)
    json.dumps(safe)
    assert safe["rows"][0]["mode"] == 1
    assert safe["rows"][0]["name"] == "track"


def test_infer_table_schema_xlsx_with_bytes_mode(tmp_path):
    xlsx_path = tmp_path / "songs.xlsx"
    xlsx_path.write_bytes(b"placeholder")

    raw_df = pd.DataFrame({"mode": [b"1", b"0"], "name": ["Song A", "Song B"]})
    raw_df.columns = sanitize_column_names(list(raw_df.columns))

    with patch("spore._connectors.utils.read_pandas_file", return_value=normalize_dataframe(raw_df)):
        schema_info = infer_table_schema(str(xlsx_path))

    json.dumps(schema_info["sample_rows"])
    assert schema_info["types"][schema_info["columns"].index("mode")] in ("INTEGER", "BIGINT")
    assert schema_info["sample_rows"][0]["mode"] in (0, 1)


def test_postgresql_iter_file_batches_normalizes_xlsx_mode(tmp_path):
    xlsx_path = tmp_path / "songs.xlsx"
    xlsx_path.write_bytes(b"placeholder")

    raw_df = normalize_dataframe(pd.DataFrame({"mode": [b"1"], "name": ["Song A"]}))
    raw_df.columns = sanitize_column_names(list(raw_df.columns))

    with patch("spore._connectors.utils.read_pandas_file", return_value=raw_df):
        src = PostgreSQLSource({}, use_ssh=False, use_ssl=False)
        batches = list(src._iter_file_batches(str(xlsx_path), batch_row_size=100))

    assert batches
    table = pa.Table.from_batches(batches)
    mode_field = table.schema.field("mode")
    assert not pa.types.is_binary(mode_field.type)
    assert table.column("mode").to_pylist()[0] in (0, 1, "1")


def test_read_pandas_file_sanitizes_columns(tmp_path):
    xlsx_path = tmp_path / "weird.xlsx"
    df = pd.DataFrame({"mode": [1], "select": [2]})
    df.to_excel(xlsx_path, index=False, engine="openpyxl")

    out = read_pandas_file(str(xlsx_path))
    assert "mode" in out.columns
    assert "select_col" in out.columns
