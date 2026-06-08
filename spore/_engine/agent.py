"""Workspace agent: multi-step loop with bounded tools and execution policy."""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Callable, Iterator

from flask import session

from spore._compute.relations import list_datasets, reconcile_relations
from spore._engine.agent_history import get_agent_history
from spore._engine.agent_pending import is_interrupted, wait_result
from spore._engine.model_manager import get_engine
from spore._engine.tools import (
    ALL_TOOLS,
    CLIENT_TOOLS,
    PolicyError,
    execute_server_tool,
    parse_xml_tool_response,
)
from spore._logger import logging
from spore._utils import context_limit_info, provider_base_url
from spore._workspace.store import get_workspace_store


MAX_ITERATIONS = 6


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def _strip_credentials(conn: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in conn.items() if k != "credentials"}
    return out


def harvest_context(workspace_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble workspace + relations + connection metadata (no credentials)."""
    extra = extra or {}
    store = get_workspace_store()
    ws_state = store.get_state(workspace_id) or {}
    data = reconcile_relations(ws_state.get("data") or {})
    relations = data.get("relations") or {}

    connections = [_strip_credentials(c) for c in session.get("connections", [])]

    notebook = ws_state.get("notebook") or {}
    dashboard = ws_state.get("dashboard") or {}
    nb_cells = notebook.get("cells") or []
    widgets = []
    for page in (dashboard.get("pages") or [dashboard] if dashboard.get("widgets") is not None else []):
        if isinstance(page, dict):
            widgets.extend(page.get("widgets") or [])
    if dashboard.get("widgets"):
        widgets = dashboard.get("widgets") or widgets

    relation_summaries = []
    for ref, rel in relations.items():
        relation_summaries.append({
            "ref": ref,
            "columns": rel.get("columns") or [],
            "row_count": rel.get("row_count"),
            "format": rel.get("format"),
            "is_stream": rel.get("is_stream"),
        })

    seen = {r["ref"] for r in relation_summaries}
    for ds in list_datasets():
        ref = ds.get("ref")
        if not ref or ref in seen:
            continue
        relation_summaries.append({
            "ref": ref,
            "columns": ds.get("columns") or [],
            "row_count": ds.get("row_count"),
            "format": ds.get("format"),
            "is_stream": ds.get("is_stream"),
        })
        seen.add(ref)

    return {
        "workspace_id": workspace_id,
        "active_view": ws_state.get("active_view") or extra.get("active_view") or "data",
        "selected_connection_id": ws_state.get("selected_connection_id"),
        "relations": relation_summaries,
        "connections": connections,
        "notebook_cell_count": len(nb_cells),
        "notebook_cells_preview": [
            {"type": c.get("type"), "code_preview": (c.get("code") or "")[:200]}
            for c in nb_cells[:8]
        ],
        "dashboard_widget_count": len(widgets),
        "dashboard_widgets_preview": [
            {"type": w.get("type"), "title": w.get("title"), "ref": (w.get("source") or {}).get("ref")}
            for w in widgets[:8]
        ],
        "relation_ref": extra.get("relation_ref"),
        "source_id": extra.get("source_id"),
    }


def _context_block(ctx: dict[str, Any]) -> str:
    return json.dumps(ctx, default=str, indent=2)


_CHART_INTENT_RE = re.compile(
    r"\b(chart|graph|plot|visuali[sz]e|bar chart|line chart|pie chart|pie)\b",
    re.IGNORECASE,
)


def _detect_chart_intent(message: str) -> tuple[bool, str]:
    """Return (wants_chart, chart_type) from user message."""
    text = message or ""
    if not _CHART_INTENT_RE.search(text):
        return False, "bar"
    lower = text.lower()
    if "pie" in lower:
        return True, "pie"
    if "line" in lower:
        return True, "line"
    if "area" in lower:
        return True, "area"
    return True, "bar"


def _resolve_chart_ref(ctx: dict[str, Any], message: str) -> str | None:
    """Pick the best relation ref for a chart/table request."""
    if ctx.get("relation_ref"):
        return str(ctx["relation_ref"])
    mention = re.search(r"@([\w./:-]+)", message or "")
    if mention:
        return mention.group(1)
    relations = ctx.get("relations") or []
    if relations:
        return relations[0].get("ref")
    return None


_SMALLTALK_RE = re.compile(
    r"^\s*(hi|hey+|hello|yo|sup|thanks|thank you|how are you|who are you|"
    r"what can you do|what do you do|help)\b",
    re.IGNORECASE,
)
_NOTEBOOK_RE = re.compile(
    r"\b(notebook|run python|python code|in the notebook|analy[sz]e in notebook)\b",
    re.IGNORECASE,
)
_DASHBOARD_RE = re.compile(r"\b(dashboard|widget)\b", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"\b(table|preview|rows|sample|head|first \d+|top \d+|show me|list)\b",
    re.IGNORECASE,
)

# Compact tool descriptor for the model-fallback prompt (token-light vs full JSON).
_SLIM_TOOLS = "\n".join([
    'propose_sql {"question","source_id?"}',
    'describe_relation {"ref"}',
    'query_relation {"ref","limit?"}',
    'render_chart {"ref","chart_type":"bar|line|pie","x_field?","y_field?"}',
    'run_python {"code"}',
    'add_notebook_cell {"type":"python","code"}',
    'add_dashboard_widget {"type":"bar","ref","title?"}',
])


# Signatures of "the model provider isn't reachable" (local server down, bad
# base URL, DNS/timeout). Used to turn raw tracebacks into actionable guidance.
_CONN_ERR_RE = re.compile(
    r"(connection error|connection refused|failed to establish|max retries|"
    r"nodename nor servname|errno 111|name or service not known|"
    r"apiconnectionerror|connecterror|connecttimeout|read timed out|"
    r"timed? ?out|temporary failure in name resolution)",
    re.IGNORECASE,
)


def _provider_endpoint(provider: str) -> str | None:
    if provider in ("ollama", "lmstudio"):
        return provider_base_url(provider) or None
    return None


def _detect_deliverable(message: str, ctx: dict[str, Any]) -> str:
    """Phase 1 intent classification: what the user wants produced."""
    msg = message or ""
    has_rel = bool(ctx.get("relations"))
    wants_chart, _ = _detect_chart_intent(msg)

    if wants_chart and has_rel:
        return "chart"
    if _NOTEBOOK_RE.search(msg):
        return "notebook"
    if _DASHBOARD_RE.search(msg) and has_rel:
        return "dashboard"
    if _TABLE_RE.search(msg) and has_rel:
        return "table"
    if _SMALLTALK_RE.search(msg) or not has_rel:
        return "answer"
    return "model"


class WorkspaceAgent:
    """Runs the agent loop, yielding structured events for Socket.IO / SSE."""

    def __init__(
        self,
        workspace_id: str,
        session_id: str,
        emit_fn: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.workspace_id = workspace_id or "default"
        self.session_id = session_id
        self.emit_fn = emit_fn
        self.engine = get_engine()
        self.history = get_agent_history(self.workspace_id)

    def _propose_sql(self, question: str, source_id: str | None) -> dict[str, Any]:
        connections = session.get("connections", [])
        db_id = source_id
        if not db_id:
            ctx = harvest_context(self.workspace_id)
            db_id = ctx.get("selected_connection_id")
        selected = next((c for c in connections if str(c.get("id")) == str(db_id)), None)
        if not selected:
            return {"ok": False, "error": "No data source selected. Choose a connection or pass source_id."}

        db_type = selected.get("db_type") or selected.get("source_type") or "sql"
        metadata = selected.get("metadata") or {}
        full = ""
        for chunk in self.engine.generate(question, db_type, metadata):
            if chunk.get("type") == "token":
                full += chunk.get("content") or ""
        return {
            "ok": True,
            "sql_response": full,
            "source_id": str(selected.get("id")),
            "db_type": db_type,
        }

    def _run_server_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = execute_server_tool(
                name,
                args,
                propose_sql_fn=self._propose_sql,
            )
            return {"ok": True, "result": result}
        except (PolicyError, ValueError) as exc:
            # Expected, recoverable tool rejections (bad ref, missing arg, policy).
            # The loop self-corrects from the returned error; keep logs quiet.
            logging.warning("Tool %s rejected: %s", name, exc)
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logging.error("Tool %s failed: %s", name, exc, exc_info=True)
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ #
    # Context / event helpers                                            #
    # ------------------------------------------------------------------ #

    def _compact_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Token-light context for the model: refs + columns + connections only."""
        return {
            "active_view": ctx.get("active_view"),
            "selected_connection_id": ctx.get("selected_connection_id"),
            "relations": [
                {
                    "ref": r.get("ref"),
                    "columns": r.get("columns") or [],
                    "row_count": r.get("row_count"),
                }
                for r in (ctx.get("relations") or [])
            ],
            "connections": [
                {"id": c.get("id"), "name": c.get("name") or c.get("db_type")}
                for c in (ctx.get("connections") or [])
            ],
        }

    def _ctx_event(self, ctx_obj: dict[str, Any], history=None) -> dict[str, Any]:
        info = getattr(self, "_ctx_info", None) or context_limit_info()
        parts = [_context_block(ctx_obj)]
        for msg in history or []:
            parts.append(str(getattr(msg, "content", msg)))
        used = _estimate_tokens("\n".join(parts))
        return {
            "type": "context",
            "used": used,
            "limit": info["effective"],
            "model_max": info["model_max"],
            "configured": info["configured"],
            "clamped": info["clamped"],
            "show": info["show"],
        }

    def _finalize(self, comment: str) -> Iterator[dict[str, Any]]:
        comment = (comment or "").strip() or "Done."
        self.history.add_ai_message(f"<final><comment>{comment}</comment></final>")
        yield {"type": "final", "content": comment}
        yield {"type": "done"}

    def _provider_error_message(self, exc: Exception) -> str | None:
        """Return a friendly message if exc is a provider-connectivity failure."""
        text = f"{type(exc).__name__}: {exc}"
        if not _CONN_ERR_RE.search(text):
            return None
        provider = getattr(self.engine, "provider", "") or ""
        label = {"ollama": "Ollama", "lmstudio": "LM Studio"}.get(
            provider, provider or "the model provider"
        )
        endpoint = _provider_endpoint(provider)
        model = getattr(self.engine, "model_name", "") or ""
        where = f" at {endpoint}" if endpoint else ""
        model_hint = f" and the model '{model}' is loaded" if model else ""
        return (
            f"Can't reach {label}{where}. Make sure it's running{model_hint}, "
            "then send your message again."
        )

    # ------------------------------------------------------------------ #
    # Phase 1: goal definition                                           #
    # ------------------------------------------------------------------ #

    def _build_goal(self, user_msg: str, ctx: dict[str, Any]) -> dict[str, Any]:
        deliverable = _detect_deliverable(user_msg, ctx)
        wants_chart, chart_type = _detect_chart_intent(user_msg)
        criteria = {
            "chart": "a chart artifact is rendered",
            "table": "a data table is returned",
            "sql": "a SQL proposal is produced",
            "notebook": "a notebook cell is added",
            "dashboard": "a dashboard widget is added",
            "answer": "a direct reply is given",
            "model": "the request is satisfied",
        }
        return {
            "objective": user_msg,
            "deliverable": deliverable,
            "target_ref": _resolve_chart_ref(ctx, user_msg),
            "chart_type": chart_type if wants_chart else "bar",
            "success_criteria": criteria.get(deliverable, criteria["model"]),
        }

    # ------------------------------------------------------------------ #
    # Orchestrator                                                       #
    # ------------------------------------------------------------------ #

    def run(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        ctx = harvest_context(self.workspace_id, context)
        user_msg = message.strip()
        if not user_msg:
            yield {"type": "error", "content": "Empty message"}
            return

        # Per-run state for verification + loop guards.
        self._emitted = {k: False for k in ("chart", "table", "sql", "notebook", "dashboard")}
        self._executed_sigs: set[str] = set()
        self._repeat_count = 0
        self._ctx_info = context_limit_info()

        self.history.add_user_message(user_msg)

        try:
            # Explicit SQL proposal route (/source ... or source: ...).
            if user_msg.startswith("/") or user_msg.lower().startswith("source:"):
                yield self._ctx_event(self._compact_context(ctx), self.history.messages)
                yield from self._run_propose_route(user_msg, ctx)
                return

            goal = self._build_goal(user_msg, ctx)
            yield {"type": "plan_step", "step": 0, "content": f"Goal: {goal['deliverable']}"}

            compact = self._compact_context(ctx)
            yield self._ctx_event(compact, self.history.messages)

            deliverable = goal["deliverable"]
            if deliverable in ("chart", "table"):
                yield from self._run_deterministic(goal)
            elif deliverable == "answer":
                yield from self._run_answer(user_msg, compact)
            else:
                yield from self._run_model_loop(user_msg, compact, goal)
        except Exception as exc:
            friendly = self._provider_error_message(exc)
            if not friendly:
                raise
            # Expected when a local model server is down; keep logs quiet.
            logging.warning("Model provider unreachable: %s", exc)
            yield {"type": "error", "content": friendly}
            yield {"type": "done"}

    # ------------------------------------------------------------------ #
    # Phase 2-4 (deterministic): plan -> execute -> verify               #
    # ------------------------------------------------------------------ #

    def _render_chart(self, ref: str, chart_type: str) -> tuple[str, dict[str, Any]]:
        """Render with a small chart_type fallback so a chart almost always appears."""
        outcome: dict[str, Any] = {"ok": False, "error": "no attempt"}
        tried: list[str] = []
        for ct in (chart_type, "bar", "line"):
            if ct in tried:
                continue
            tried.append(ct)
            outcome = self._run_server_tool("render_chart", {"ref": ref, "chart_type": ct})
            if outcome.get("ok"):
                return ct, outcome
        return chart_type, outcome

    def _run_deterministic(self, goal: dict[str, Any]) -> Iterator[dict[str, Any]]:
        ref = goal.get("target_ref")
        if not ref:
            yield from self._finalize(
                "I couldn't find a dataset to use. Reference one with @name (type @ to pick)."
            )
            return

        if is_interrupted(self.session_id):
            yield {"type": "interrupted", "content": "Agent stopped by user"}
            return

        if goal["deliverable"] == "chart":
            chart_type = goal.get("chart_type", "bar")
            yield {"type": "plan_step", "step": 1, "content": f"Rendering {chart_type} chart for @{ref}"}
            yield {
                "type": "tool_call",
                "tool": "render_chart",
                "args": {"ref": ref, "chart_type": chart_type},
                "step": 1,
            }
            used_type, outcome = self._render_chart(ref, chart_type)
            if outcome.get("ok"):
                result = outcome.get("result") or {}
                self._emitted["chart"] = True
                yield {"type": "tool_result", "tool": "render_chart", "ok": True}
                yield {
                    "type": "artifact",
                    "artifact": "chart",
                    "chart_type": result.get("chart_type"),
                    "option": result.get("option"),
                }
                cols = (result.get("query") or {}).get("columns") or []
                if len(cols) >= 2:
                    summary = f"Rendered a {used_type} chart of {cols[1]} by {cols[0]} for @{ref}."
                else:
                    summary = f"Rendered a {used_type} chart for @{ref}."
                yield from self._finalize(summary)
            else:
                yield {"type": "tool_result", "tool": "render_chart", "ok": False, "error": outcome.get("error")}
                yield from self._finalize(f"I couldn't render a chart for @{ref}: {outcome.get('error')}")
            return

        # table
        yield {"type": "plan_step", "step": 1, "content": f"Querying @{ref}"}
        yield {"type": "tool_call", "tool": "query_relation", "args": {"ref": ref, "limit": 100}, "step": 1}
        outcome = self._run_server_tool("query_relation", {"ref": ref, "limit": 100})
        if outcome.get("ok"):
            result = outcome.get("result") or {}
            self._emitted["table"] = True
            yield {"type": "tool_result", "tool": "query_relation", "ok": True}
            yield {
                "type": "artifact",
                "artifact": "table",
                "columns": result.get("columns"),
                "rows": (result.get("rows") or [])[:100],
                "row_count": result.get("row_count"),
            }
            yield from self._finalize(f"Showing {result.get('row_count', 0)} rows from @{ref}.")
        else:
            yield {"type": "tool_result", "tool": "query_relation", "ok": False, "error": outcome.get("error")}
            yield from self._finalize(f"I couldn't query @{ref}: {outcome.get('error')}")

    def _run_answer(self, user_msg: str, compact: dict[str, Any]) -> Iterator[dict[str, Any]]:
        yield {"type": "plan_step", "step": 1, "content": "Replying"}
        full = ""
        for chunk in self.engine.converse(user_msg, compact, self.history.messages[-6:]):
            if is_interrupted(self.session_id):
                yield {"type": "interrupted", "content": "Agent stopped by user"}
                return
            if chunk.get("type") == "token":
                token = chunk.get("content") or ""
                full += token
                yield {"type": "token", "content": token}
        yield from self._finalize(full or "How can I help with your data?")

    # ------------------------------------------------------------------ #
    # General path: hardened model loop (dedup + verify + auto-finalize) #
    # ------------------------------------------------------------------ #

    def _verify(self, goal: dict[str, Any]) -> bool:
        d = goal.get("deliverable")
        if d in self._emitted:
            return self._emitted[d]
        return False

    def _auto_summary(self, goal: dict[str, Any]) -> str:
        if self._emitted.get("chart"):
            return "Here's the chart you asked for."
        if self._emitted.get("table"):
            return "Here's the data you asked for."
        if self._emitted.get("sql"):
            return "Here's the SQL proposal."
        if self._emitted.get("notebook"):
            return "Added the cell to your notebook."
        if self._emitted.get("dashboard"):
            return "Added the widget to your dashboard."
        return "Done."

    def _run_model_loop(
        self,
        user_msg: str,
        compact: dict[str, Any],
        goal: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        system_ctx = _context_block(compact)
        tool_list = _SLIM_TOOLS

        for step_idx in range(MAX_ITERATIONS):
            if is_interrupted(self.session_id):
                yield {"type": "interrupted", "content": "Agent stopped by user"}
                return

            yield {"type": "plan_step", "step": step_idx + 1, "content": f"Thinking (step {step_idx + 1})…"}

            parsed = None
            raw_response = ""
            for chunk in self.engine.agent_step(
                system_context=system_ctx,
                tool_schemas=tool_list,
                history=self.history.messages,
                latest_message=user_msg,
            ):
                if is_interrupted(self.session_id):
                    yield {"type": "interrupted", "content": "Agent stopped by user"}
                    return
                if chunk.get("type") == "token":
                    token = chunk.get("content") or ""
                    raw_response += token
                    yield {"type": "token", "content": token}
                elif chunk.get("type") == "tool_calls":
                    parsed = chunk.get("parsed")
                    raw_response = chunk.get("raw") or raw_response

            if not parsed:
                parsed = parse_xml_tool_response(raw_response)

            yield self._ctx_event(compact, self.history.messages)

            if parsed.get("kind") == "final":
                yield from self._emit_final(parsed, raw_response)
                return

            if parsed.get("kind") == "tool":
                finished = yield from self._handle_parsed(parsed, step_idx, raw=raw_response)
                if finished:
                    return
                # Phase 4: deterministic verification gate closes the loop.
                if self._verify(goal):
                    yield from self._finalize(self._auto_summary(goal))
                    return
                if self._repeat_count >= 2:
                    yield from self._finalize(self._auto_summary(goal))
                    return
                continue

            if raw_response.strip():
                yield from self._emit_final(
                    {"kind": "final", "comment": raw_response.strip(), "thought": ""},
                    raw_response,
                )
                return

        # Exhausted steps: finalize with whatever was produced rather than erroring.
        yield from self._finalize(self._auto_summary(goal))

    def _emit_final(self, parsed: dict[str, Any], raw: str | None) -> Iterator[dict[str, Any]]:
        comment = parsed.get("comment") or ""
        if parsed.get("thought"):
            yield {"type": "thought", "content": parsed["thought"], "step": 0}
        if raw:
            self.history.add_ai_message(raw)
        else:
            self.history.add_ai_message(f"<final><comment>{comment}</comment></final>")
        yield {"type": "final", "content": comment}
        yield {"type": "done"}

    def _run_propose_route(self, user_msg: str, ctx: dict[str, Any]) -> Iterator[dict[str, Any]]:
        text = user_msg.lstrip("/").strip()
        if text.lower().startswith("source"):
            text = text[6:].strip()
        elif " " in text:
            parts = text.split(" ", 1)
            if parts[0].isdigit() or len(parts[0]) < 40:
                ctx = {**ctx, "source_id": parts[0]}
                text = parts[1].strip()

        yield {"type": "plan_step", "step": 1, "content": "Generating SQL proposal (no execution)…"}
        if is_interrupted(self.session_id):
            yield {"type": "interrupted", "content": "Agent stopped by user"}
            return
        outcome = self._propose_sql(text, ctx.get("source_id") or ctx.get("selected_connection_id"))
        if not outcome.get("ok"):
            yield {"type": "error", "content": outcome.get("error", "propose_sql failed")}
            return
        raw = outcome.get("sql_response") or ""
        self.history.add_ai_message(raw)
        yield {
            "type": "sql_proposal",
            "content": raw,
            "source_id": outcome.get("source_id"),
            "db_type": outcome.get("db_type"),
        }
        yield {"type": "done"}

    def _handle_parsed(
        self,
        parsed: dict[str, Any],
        step_idx: int,
        raw: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Handle one tool step. Returns True if agent should stop."""
        if is_interrupted(self.session_id):
            yield {"type": "interrupted", "content": "Agent stopped by user"}
            return True

        if parsed.get("thought"):
            yield {"type": "thought", "content": parsed["thought"], "step": step_idx + 1}

        name = (parsed.get("name") or "").strip()
        args = parsed.get("args") or {}

        if not name or name.upper() == "TOOL_NAME" or name not in ALL_TOOLS:
            err = (
                f"Invalid tool name '{name or '(empty)'}'. "
                f"Use one of: {', '.join(sorted(ALL_TOOLS))}."
            )
            yield {"type": "tool_result", "tool": name or "unknown", "ok": False, "error": err}
            self.history.add_ai_message(f'<tool_result name="{name}">error: {err}</tool_result>')
            return False

        # Dedup guard: skip identical (name, args) calls so a weak model can't loop.
        sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if sig in getattr(self, "_executed_sigs", set()):
            self._repeat_count = getattr(self, "_repeat_count", 0) + 1
            note = (
                "Already ran this tool with the same arguments. If the result answers "
                "the request, reply with <final>."
            )
            yield {"type": "tool_result", "tool": name, "ok": False, "error": note}
            self.history.add_ai_message(f'<tool_result name="{name}">{note}</tool_result>')
            return False
        self._executed_sigs.add(sig)

        yield {"type": "tool_call", "tool": name, "args": args, "step": step_idx + 1}

        if name == "propose_sql":
            outcome = self._run_server_tool(name, args)
            if outcome.get("ok"):
                result = outcome["result"]
                raw_sql = result.get("sql_response") or ""
                self._emitted["sql"] = True
                self.history.add_ai_message(
                    f'<tool_result name="{name}">{raw_sql[:500]}</tool_result>'
                )
                yield {
                    "type": "sql_proposal",
                    "content": raw_sql,
                    "source_id": result.get("source_id"),
                }
            else:
                yield {"type": "tool_result", "tool": name, "ok": False, "error": outcome.get("error")}
            return False

        if name in CLIENT_TOOLS:
            request_id = str(uuid.uuid4())
            from spore._engine.agent_pending import register_wait

            register_wait(self.session_id, request_id)
            yield {
                "type": "client_tool_request",
                "request_id": request_id,
                "tool": name,
                "args": args,
                "requires_approval": True,
            }
            result = wait_result(self.session_id, request_id, timeout=180.0)
            if result.get("ok"):
                if name == "add_notebook_cell":
                    self._emitted["notebook"] = True
                elif name == "add_dashboard_widget":
                    self._emitted["dashboard"] = True
            yield {"type": "tool_result", "tool": name, **result}
            self.history.add_ai_message(
                f'<tool_result name="{name}">{json.dumps(result, default=str)[:2000]}</tool_result>'
            )
            return False

        outcome = self._run_server_tool(name, args)
        if outcome.get("ok"):
            # Slim success signal; artifacts below carry the displayable payload.
            yield {"type": "tool_result", "tool": name, "ok": True}
        else:
            yield {"type": "tool_result", "tool": name, "ok": False, "error": outcome.get("error")}

        if outcome.get("ok"):
            result = outcome.get("result") or {}
            if name == "query_relation":
                self._emitted["table"] = True
                yield {
                    "type": "artifact",
                    "artifact": "table",
                    "columns": result.get("columns"),
                    "rows": (result.get("rows") or [])[:100],
                    "row_count": result.get("row_count"),
                }
            elif name == "render_chart":
                self._emitted["chart"] = True
                yield {
                    "type": "artifact",
                    "artifact": "chart",
                    "chart_type": result.get("chart_type"),
                    "option": result.get("option"),
                }
            self.history.add_ai_message(
                f'<tool_result name="{name}">{json.dumps(result, default=str)[:2000]}</tool_result>'
            )
        else:
            self.history.add_ai_message(
                f'<tool_result name="{name}">error: {outcome.get("error")}</tool_result>'
            )
        return False
