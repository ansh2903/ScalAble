"""DuckDB queries over materialized streams for dashboard widgets."""

from __future__ import annotations

import re
from typing import Any

import duckdb

from spore._compute.streams import duckdb_read_expr, resolve_stream_source

_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MAX_LIMIT = 10_000


def _quote_ident(name: str) -> str:
    n = str(name).strip()
    if not _IDENT.match(n):
        raise ValueError(f"Invalid identifier: {name}")
    return f'"{n}"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("'", "''")
    return f"'{s}'"


def build_transform_sql(
    read_expr: str,
    transform: dict[str, Any] | None,
    *,
    limit: int | None = None,
) -> str:
    """Build SELECT from transform spec over read_expr subquery."""
    transform = transform or {}
    dims = transform.get("dimensions") or []
    measures = transform.get("measures") or []
    filters = transform.get("filters") or []
    order_by = transform.get("orderBy") or transform.get("order_by") or []
    row_limit = transform.get("limit") or limit or 1000
    row_limit = min(int(row_limit), _MAX_LIMIT)

    select_parts: list[str] = []
    group_cols: list[str] = []

    for d in dims:
        col = d if isinstance(d, str) else d.get("field")
        if not col:
            continue
        q = _quote_ident(col)
        select_parts.append(q)
        group_cols.append(q)

    for m in measures:
        if isinstance(m, str):
            field, agg = m, "count"
        else:
            field = m.get("field") or "*"
            agg = (m.get("agg") or "sum").lower()
        if field == "*" or not field:
            expr = "COUNT(*)"
            alias = "count"
        else:
            qf = _quote_ident(field)
            agg_map = {
                "sum": f"SUM({qf})",
                "avg": f"AVG({qf})",
                "mean": f"AVG({qf})",
                "min": f"MIN({qf})",
                "max": f"MAX({qf})",
                "count": f"COUNT({qf})",
                "count_distinct": f"COUNT(DISTINCT {qf})",
            }
            expr = agg_map.get(agg, f"SUM({qf})")
            alias = field if agg in ("sum", "avg", "mean", "min", "max") else f"{field}_{agg}"
        select_parts.append(f"{expr} AS {_quote_ident(alias)}")

    if not select_parts:
        select_parts = ["*"]

    where_clauses: list[str] = []
    for f in filters:
        field = f.get("field")
        op = (f.get("op") or "eq").lower()
        value = f.get("value")
        if not field:
            continue
        qf = _quote_ident(field)
        if op == "eq":
            where_clauses.append(f"{qf} = {_sql_literal(value)}")
        elif op == "neq":
            where_clauses.append(f"{qf} <> {_sql_literal(value)}")
        elif op == "gt":
            where_clauses.append(f"{qf} > {_sql_literal(value)}")
        elif op == "gte":
            where_clauses.append(f"{qf} >= {_sql_literal(value)}")
        elif op == "lt":
            where_clauses.append(f"{qf} < {_sql_literal(value)}")
        elif op == "lte":
            where_clauses.append(f"{qf} <= {_sql_literal(value)}")
        elif op == "contains":
            where_clauses.append(f"CAST({qf} AS VARCHAR) ILIKE '%' || {_sql_literal(str(value))} || '%'")

    order_clauses: list[str] = []
    for o in order_by:
        field = o.get("field") if isinstance(o, dict) else o
        direction = (o.get("dir") or "asc").upper() if isinstance(o, dict) else "ASC"
        if field:
            order_clauses.append(f"{_quote_ident(field)} {direction}")

    sql = f"SELECT {', '.join(select_parts)} FROM {read_expr} AS _src"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    if group_cols:
        sql += " GROUP BY " + ", ".join(group_cols)
    if order_clauses:
        sql += " ORDER BY " + ", ".join(order_clauses)
    sql += f" LIMIT {row_limit}"
    return sql


def query_stream(
    stream_name: str,
    *,
    transform: dict[str, Any] | None = None,
    sql: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Query a materialized stream. Returns columns, rows, row_count, version.
    """
    abs_path, _ext, version = resolve_stream_source(stream_name)
    read_expr = duckdb_read_expr(abs_path)

    if sql and str(sql).strip():
        raw = str(sql).strip()
        if ";" in raw:
            raise ValueError("Multiple statements not allowed")
        lowered = raw.lower()
        if not lowered.startswith("select"):
            raise ValueError("Only SELECT queries allowed")
        if "_src" in lowered:
            final_sql = raw.replace("_src", f"({read_expr}) AS _src")
        else:
            final_sql = f"SELECT * FROM ({read_expr}) AS _src WHERE ({raw})"
        if limit and "limit" not in lowered:
            final_sql += f" LIMIT {min(int(limit), _MAX_LIMIT)}"
    else:
        final_sql = build_transform_sql(read_expr, transform, limit=limit)

    con = duckdb.connect()
    try:
        rel = con.execute(final_sql)
        table = rel.to_arrow_table() if hasattr(rel, "to_arrow_table") else rel.fetch_arrow_table()
        columns = table.schema.names
        rows = table.to_pylist()
        return {
            "stream": stream_name,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "version": version,
            "sql": final_sql,
        }
    finally:
        con.close()
