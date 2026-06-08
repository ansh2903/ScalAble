"""Agent tool registry and server-side execution."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from spore._compute.query import query_stream
from spore._compute.relations import list_datasets, list_streams, profile_relation, scan_dataset, scan_stream
from spore._logger import logging

CLIENT_TOOLS = frozenset({
    "run_python",
    "add_notebook_cell",
    "add_dashboard_widget",
})

SERVER_TOOLS = frozenset({
    "propose_sql",
    "describe_relation",
    "query_relation",
    "render_chart",
})

ALL_TOOLS = CLIENT_TOOLS | SERVER_TOOLS

LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio"})


class PolicyError(Exception):
    """Raised when an agent tool violates execution policy."""


REMOTE_BLOCKED = frozenset({
    "execute_sql",
    "query_preview",
    "ingest",
    "materialize",
})


def tool_schemas() -> list[dict[str, Any]]:
    """JSON schemas for agent tools (native + XML paths)."""
    return [
        {
            "name": "propose_sql",
            "description": "Generate SQL for a remote data source using schema metadata only. Never executes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["question"],
            },
        },
        {
            "name": "describe_relation",
            "description": "Schema and profile stats for a local materialized relation (@ref).",
            "parameters": {
                "type": "object",
                "properties": {"ref": {"type": "string"}},
                "required": ["ref"],
            },
        },
        {
            "name": "query_relation",
            "description": "Query a local relation via DuckDB (SELECT/transform only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "transform": {"type": "object"},
                    "sql": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["ref"],
            },
        },
        {
            "name": "render_chart",
            "description": "Build a chart from local relation data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "chart_type": {"type": "string"},
                    "transform": {"type": "object"},
                    "x_field": {"type": "string"},
                    "y_field": {"type": "string"},
                },
                "required": ["ref"],
            },
        },
        {
            "name": "run_python",
            "description": "Execute Python in the workspace Jupyter kernel (client-side).",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
        {
            "name": "add_notebook_cell",
            "description": "Add a notebook cell (client-side, requires user approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["type", "code"],
            },
        },
        {
            "name": "add_dashboard_widget",
            "description": "Add a dashboard widget (client-side, requires user approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "ref": {"type": "string"},
                    "transform": {"type": "object"},
                    "title": {"type": "string"},
                },
                "required": ["type", "ref"],
            },
        },
    ]


def _build_echarts_option(
    rows: list[dict[str, Any]],
    columns: list[str],
    chart_type: str,
    x_field: str | None = None,
    y_field: str | None = None,
) -> dict[str, Any]:
    chart_type = (chart_type or "bar").lower()
    if not rows or not columns:
        return {"_placeholder": "No data to chart"}

    x_col = x_field if x_field in columns else columns[0]
    y_col = y_field if y_field in columns else (columns[1] if len(columns) > 1 else columns[0])

    x_data = [r.get(x_col) for r in rows]
    y_data = [r.get(y_col) for r in rows]

    if chart_type in ("pie",):
        return {
            "tooltip": {"trigger": "item"},
            "series": [{
                "type": "pie",
                "radius": "60%",
                "data": [{"name": str(x), "value": y} for x, y in zip(x_data, y_data)],
            }],
        }

    series_type = chart_type if chart_type in ("bar", "line", "area", "scatter") else "bar"
    if series_type == "area":
        series = {
            "type": "line",
            "data": y_data,
            "smooth": True,
            "areaStyle": {},
        }
    else:
        series = {
            "type": series_type,
            "data": y_data,
            "smooth": series_type == "line",
        }
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": [str(v) for v in x_data]},
        "yAxis": {"type": "value"},
        "series": [series],
    }


def _available_relation_refs() -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for entry in list_streams():
        ref = entry.get("ref") or entry.get("name")
        if ref and ref not in seen:
            refs.append(str(ref))
            seen.add(str(ref))
    try:
        for entry in list_datasets():
            ref = entry.get("ref")
            if ref and ref not in seen:
                refs.append(str(ref))
                seen.add(str(ref))
    except Exception:
        pass
    return refs


def resolve_ref(ref: str) -> str:
    """
    Map a possibly-mangled model-supplied ref to a known relation ref.

    Weak local models often emit variants like ``source.parquet``,
    ``engine_data.source.parquet`` or ``engine_data/source.parquet`` instead of
    the catalog ref ``engine_data``. This normalizes those to a known ref when
    one can be confidently identified; otherwise returns the input unchanged so
    callers raise a not-found error listing valid refs.
    """
    raw = (ref or "").strip()
    if not raw:
        return raw

    known = _available_relation_refs()
    if raw in known:
        return raw

    base = raw.split("::")[0].strip()
    if base in known:
        return base

    first_seg = base.split("/")[0]
    if first_seg in known:
        return first_seg

    # Mangled dotted form, e.g. "engine_data.source.parquet" -> "engine_data".
    dotted = base.replace("/", ".")
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in known:
            return candidate

    # Prefix match: known ref is the leading segment of the supplied ref.
    for k in known:
        if base == k or base.startswith(f"{k}.") or base.startswith(f"{k}/"):
            return k

    return raw


def _relation_not_found_message(ref: str) -> str:
    available = _available_relation_refs()
    if available:
        return f"Dataset not found: {ref}. Available relations: {', '.join(available)}"
    return (
        f"Dataset not found: {ref}. No local relations are loaded — "
        "use propose_sql for remote data or materialize data first."
    )


def _parse_tool_args(raw_args: str) -> dict[str, Any]:
    """Parse JSON tool arguments with fence stripping and brace extraction."""
    if not raw_args or not raw_args.strip():
        return {}

    text = raw_args.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Extract first balanced {...} substring
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    return {}


def _tool_arg_error(name: str, missing: str, hint: str = "") -> ValueError:
    msg = f"Tool '{name}' requires argument '{missing}'."
    if hint:
        msg += f" {hint}"
    return ValueError(msg)


def execute_server_tool(
    name: str,
    args: dict[str, Any],
    *,
    propose_sql_fn: Callable[[str, str | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a server-side tool. Raises PolicyError on blocked operations."""
    if name in REMOTE_BLOCKED:
        raise PolicyError(f"Tool '{name}' is blocked for agent execution on remote sources.")

    if name not in SERVER_TOOLS:
        raise PolicyError(f"Unknown or client-only tool: {name}")

    if name == "propose_sql":
        if not propose_sql_fn:
            raise ValueError("propose_sql_fn required")
        question = str(args.get("question") or "").strip()
        source_id = args.get("source_id")
        if not question:
            raise _tool_arg_error(
                name,
                "question",
                'Example: {"question": "show top customers", "source_id": "optional"}',
            )
        return propose_sql_fn(question, str(source_id) if source_id else None)

    if name == "describe_relation":
        ref = str(args.get("ref") or "").strip()
        if not ref:
            raise _tool_arg_error(
                name,
                "ref",
                'Use a relation ref from context.relations. Example: {"ref": "<relation_ref_from_context>"}',
            )
        ref = resolve_ref(ref)
        stream_name = ref.split("/")[0].split("::")[0]
        try:
            try:
                entry = scan_stream(stream_name)
            except (FileNotFoundError, ValueError):
                entry = scan_dataset(ref)
        except (FileNotFoundError, ValueError):
            raise ValueError(_relation_not_found_message(ref)) from None
        try:
            profile = profile_relation(ref)
        except Exception as exc:
            logging.warning("profile_relation failed for %s: %s", ref, exc)
            profile = []
        return {"relation": entry, "profile": profile}

    if name == "query_relation":
        ref = str(args.get("ref") or "").strip()
        if not ref:
            raise _tool_arg_error(
                name,
                "ref",
                'Example: {"ref": "<relation_ref_from_context>", "limit": 100}',
            )
        ref = resolve_ref(ref)
        transform = args.get("transform")
        sql = args.get("sql")
        limit = args.get("limit")
        try:
            return query_stream(ref, transform=transform, sql=sql, limit=limit)
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError(_relation_not_found_message(ref)) from exc

    if name == "render_chart":
        ref = str(args.get("ref") or "").strip()
        if not ref:
            raise _tool_arg_error(
                name,
                "ref",
                'Example: {"ref": "<relation_ref_from_context>", "chart_type": "bar", "x_field": "category", "y_field": "count"}',
            )
        ref = resolve_ref(ref)
        transform = args.get("transform") or {}
        chart_type = str(args.get("chart_type") or "bar")
        x_field = args.get("x_field")
        y_field = args.get("y_field")
        if not transform.get("dimensions") and x_field:
            transform = {
                **transform,
                "dimensions": [{"field": x_field}],
                "measures": [{"field": y_field or x_field, "agg": "sum"}],
            }
        try:
            result = query_stream(ref, transform=transform, limit=500)
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError(_relation_not_found_message(ref)) from exc
        option = _build_echarts_option(
            result.get("rows") or [],
            result.get("columns") or [],
            chart_type,
            x_field=x_field,
            y_field=y_field,
        )
        return {"chart_type": chart_type, "option": option, "query": result}

    raise ValueError(f"Unhandled tool: {name}")


def parse_xml_tool_response(text: str) -> dict[str, Any]:
    """Parse agent LLM XML step output."""
    text = text or ""
    thought_match = re.search(r"<thought>([\s\S]*?)</thought>", text)
    final_match = re.search(r"<final>([\s\S]*?)</final>", text)
    tool_match = re.search(
        r'<tool\s+name="([^"]+)">\s*([\s\S]*?)\s*</tool>',
        text,
        re.IGNORECASE,
    )

    thought = thought_match.group(1).strip() if thought_match else ""
    if final_match:
        body = final_match.group(1)
        comment_match = re.search(r"<comment>([\s\S]*?)</comment>", body)
        return {
            "kind": "final",
            "thought": thought,
            "comment": (comment_match.group(1).strip() if comment_match else body.strip()),
        }

    if tool_match:
        name = tool_match.group(1).strip()
        if name.upper() == "TOOL_NAME":
            name = ""
        raw_args = tool_match.group(2).strip()
        args = _parse_tool_args(raw_args)
        if name:
            return {"kind": "tool", "thought": thought, "name": name, "args": args}

    # Fallback: "Tool: describe_relation" followed by JSON block
    loose_tool = re.search(
        r"(?:Tool:\s*|tool\s+name=\")([a-z_]+)\"?\s*[\n\r]*([\s\S]*)",
        text,
        re.IGNORECASE,
    )
    if loose_tool and not tool_match:
        name = loose_tool.group(1).strip()
        if name in ALL_TOOLS:
            args = _parse_tool_args(loose_tool.group(2).strip())
            return {"kind": "tool", "thought": thought, "name": name, "args": args}

    # Streaming partial: thought only
    if "<thought>" in text and "</thought>" not in text:
        partial = text.split("<thought>", 1)[1]
        return {"kind": "partial", "thought": partial}

    return {"kind": "text", "content": text.strip()}
