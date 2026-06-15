from flask import stream_with_context, render_template, Response, jsonify, request, session, flash, current_app, send_file
from pathlib import Path
import importlib
import time

from spore._connectors import SourceConnector
from spore._engine.model_manager import get_engine
from spore._engine.query_executor import run_query
from spore._utils import file_size_fmt, decrypt_creds, downloadable_json, downloadable_excel, downloadable_csv, load_settings, context_limit_info
from spore._routes.utils import generate_blueprint
from spore._workspace.store import get_workspace_store
from spore._compute.query import query_stream
from spore._compute.relations import (
    delete_stream,
    profile_relation,
    reconcile_relations,
    scan_stream,
)
from spore._compute.streams import duckdb_read_source, resolve_source

import psutil
import time
import pandas as pd
import traceback
import json
import os
import tempfile
import duckdb
from io import BytesIO
import datetime as _dt
import decimal as _decimal

from spore._exception import CustomException
from spore._logger import logging

workspace_blueprint = generate_blueprint('workspace')

def _resolve_workspace(workspace_id: str | None):
    """Load workspace by id or ensure a default exists."""
    store = get_workspace_store()
    if workspace_id:
        ws = store.get_workspace(workspace_id)
        if ws:
            store.touch_workspace(workspace_id)
            return ws, store.get_state(workspace_id)
    ws = store.ensure_default_workspace()
    store.touch_workspace(ws["id"])
    return ws, store.get_state(ws["id"])


@workspace_blueprint.route('/chat', methods=['GET', 'POST'])
def chat():
    settings = load_settings() or {}
    try:
        provider, model = settings.get("provider", None), settings.get("model", None)
        connections = session.get('connections', [])
        workspace_id = request.args.get('workspace_id')
        workspace, workspace_state = _resolve_workspace(workspace_id)
    except Exception as e:
        logging.error(f"Error fetching connections: {str(e)}")
        connections = []
        workspace, workspace_state = _resolve_workspace(None)
        provider = settings.get("provider")
        model = settings.get("model")

    ctx_info = context_limit_info(settings)

    return render_template(
        "pages/chat.html",
        connections=connections,
        provider=provider,
        model=model,
        workspace=workspace,
        workspace_state=workspace_state,
        asset_version=int(time.time()),
        context_limit=ctx_info["effective"],
        context_show=ctx_info["show"],
    )

@workspace_blueprint.route('/chat/ask', methods=['POST'])
def ask():
    try:
        if request.method == 'POST':
            input = request.form.get('message')
            db_id = request.form.get('selected_db_id')
            selected_conn = next((c for c in session.get('connections', []) if str(c['id']) == str(db_id)), None)
            db_type=selected_conn.get("db_type")
            metadata = selected_conn.get("metadata", {})
            print(selected_conn)

            # Needs change - should not be initializing model on every request
            model = get_engine()

            def stream():
                
                try:
                    for token in model.generate(user_input=input, db_type=db_type, metadata=metadata):
                        print("Generated token:", token)
                        yield f"data: {json.dumps(token)}\n\n"
                except Exception as e:  
                    logging.error(f"Error during inference generation: {str(e)}")
                    yield f"data: {json.dumps({"type": "error", "content": "An error occurred during response generation."})}\n\n"
                
            return Response(stream(), mimetype='text/event-stream')

    except Exception as e:
        logging.error(f"Error in /chat/ask: {str(e)}")
        return jsonify({
            "error": "An error occurred while processing your request. Please try again."
        }), 500

@workspace_blueprint.route('/download/<fmt>', methods=['GET'])
def download(fmt):
    last_results = session.get('last_query_results')
    if not last_results:
        return "No data available", 400
    
    data = last_results.get('data')

    if fmt == 'csv':
        return downloadable_csv(data)
    if fmt == 'excel':
        return downloadable_excel(data)
    if fmt == 'json':
        return downloadable_json(data)
    else:
        return "Unsupported format", 400

@workspace_blueprint.route('/system-metrics')
def system_metrics():
    def generate():
        try:
            while True:
                data = {
                    "cpu": f"{psutil.cpu_percent(interval=1)}%",
                    "ram": f"{psutil.virtual_memory().used / (1024 ** 3):.2f} GB"
                }

                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(1)

        except Exception as e:
            logging.error(f"Error fetching system metrics: {str(e)}")
            return jsonify({"error": "Failed to fetch system metrics"}), 500

    return Response(generate(), mimetype='text/event-stream')

@workspace_blueprint.route('/api/metadata/<string:db_id>')
def get_db_metadata(db_id):
    connections = session.get('connections', [])
    selected_conn = next((c for c in connections if str(c['id']) == str(db_id)), None)
    
    if not selected_conn:
        return jsonify({"error": "Not found"}), 404
        
    return jsonify({"metadata": selected_conn.get('metadata', {})})


# ── Workspace management API ────────────────────────────────────────────────


@workspace_blueprint.route('/api/workspaces', methods=['GET'])
def api_list_workspaces():
    store = get_workspace_store()
    return jsonify({"workspaces": store.list_workspaces()})


@workspace_blueprint.route('/api/workspaces', methods=['POST'])
def api_create_workspace():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    description = (data.get("description") or "").strip()
    store = get_workspace_store()
    ws = store.create_workspace(name, description)
    return jsonify({"workspace": ws}), 201


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>', methods=['GET'])
def api_get_workspace(workspace_id):
    store = get_workspace_store()
    ws = store.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "workspace": ws,
        "state": store.get_state(workspace_id),
    })


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>', methods=['PATCH'])
def api_patch_workspace(workspace_id):
    data = request.get_json(silent=True) or {}
    store = get_workspace_store()
    ws = store.update_workspace(
        workspace_id,
        name=data.get("name"),
        description=data.get("description"),
    )
    if not ws:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"workspace": ws})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>', methods=['DELETE'])
def api_delete_workspace(workspace_id):
    store = get_workspace_store()
    if not store.delete_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    remaining = store.list_workspaces()
    if not remaining:
        store.create_workspace("Default Workspace", "Your first analysis workspace")
    return jsonify({"ok": True})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/activate', methods=['POST'])
def api_activate_workspace(workspace_id):
    store = get_workspace_store()
    ws = store.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Not found"}), 404
    store.touch_workspace(workspace_id)
    return jsonify({
        "workspace": store.get_workspace(workspace_id),
        "state": store.get_state(workspace_id),
    })


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/state', methods=['GET'])
def api_get_workspace_state(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    state = store.get_state(workspace_id)
    return jsonify({"state": state})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/state', methods=['PATCH'])
def api_patch_workspace_state(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    state = store.patch_state(workspace_id, data)
    return jsonify({"state": state})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/history', methods=['GET'])
def api_list_history(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"history": store.list_history(workspace_id, limit=limit)})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/history', methods=['POST'])
def api_append_history(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"error": "entry payload required"}), 400
    entry = store.append_history(workspace_id, data)
    return jsonify({"entry": entry}), 201


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/history', methods=['DELETE'])
def api_clear_history(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    store.clear_history(workspace_id)
    return jsonify({"ok": True})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/relations', methods=['GET'])
def api_workspace_relations(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    state = store.get_state(workspace_id) or {}
    data = reconcile_relations(state.get("data") or {})
    store.patch_state(workspace_id, {"data": data})
    return jsonify({"relations": data.get("relations") or {}})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/relations/register', methods=['POST'])
def api_register_relation(workspace_id):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    body = request.get_json(silent=True) or {}
    stream_name = (body.get("stream_name") or body.get("name") or "").strip()
    if not stream_name:
        return jsonify({"error": "stream_name required"}), 400
    try:
        entry = scan_stream(stream_name)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 404
    if body.get("conn_id"):
        entry["source"] = {
            "conn_id": str(body["conn_id"]),
            "query": body.get("query"),
        }
    if body.get("cell_id"):
        entry["source"] = {"cell_id": str(body["cell_id"])}

    state = store.get_state(workspace_id) or {}
    data = reconcile_relations(state.get("data") or {})
    relations = data.get("relations") or {}
    relations[stream_name] = {**(relations.get(stream_name) or {}), **entry}
    data["relations"] = relations
    store.patch_state(workspace_id, {"data": data})
    return jsonify({"relation": entry})


def _safe_download_name(ref: str, ext: str) -> str:
    base = (ref or "export").replace("/", "_").replace("\\", "_").replace("::", "_")
    return f"{base}.{ext}"


def _relation_download_response(ref: str, fmt: str):
    fmt = (fmt or "parquet").lower().strip()
    if fmt == "xlsx":
        fmt = "excel"

    if fmt not in ("csv", "json", "excel", "parquet"):
        return jsonify({"error": "Unsupported format"}), 400

    try:
        abs_path, ext, _version, sheet = resolve_source(ref)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 404

    download_name = _safe_download_name(ref, "xlsx" if fmt == "excel" else fmt)

    if fmt == "parquet" and ext == "parquet" and not sheet:
        return send_file(
            abs_path,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/octet-stream",
        )

    con = duckdb.connect()
    try:
        read_expr = duckdb_read_source(con, abs_path, ext, sheet)

        if fmt == "excel":
            df = con.execute(f"SELECT * FROM {read_expr} AS _src").fetchdf()
            buf = BytesIO()
            df.to_excel(buf, index=False, engine="openpyxl")
            buf.seek(0)
            return send_file(
                buf,
                as_attachment=True,
                download_name=download_name,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        fd, tmp_path = tempfile.mkstemp(suffix=f".{fmt}")
        os.close(fd)
        escaped = tmp_path.replace("'", "''")
        duck_fmt = fmt.upper()
        con.execute(
            f"COPY (SELECT * FROM {read_expr} AS _src) TO '{escaped}' (FORMAT {duck_fmt})"
        )
        mimetypes = {
            "csv": "text/csv",
            "json": "application/json",
            "parquet": "application/octet-stream",
        }
        return send_file(
            tmp_path,
            as_attachment=True,
            download_name=download_name,
            mimetype=mimetypes.get(fmt, "application/octet-stream"),
        )
    except Exception as e:
        logging.error(f"relation download error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


@workspace_blueprint.route(
    '/api/workspaces/<string:workspace_id>/relations/<string:ref>/preview',
    methods=['GET'],
)
def api_relation_preview(workspace_id, ref):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    limit = min(int(request.args.get("limit", 100)), 10_000)
    try:
        data = query_stream(ref, limit=limit)
        return jsonify({
            "ref": ref,
            "columns": data.get("columns") or [],
            "rows": data.get("rows") or [],
            "row_count": data.get("row_count"),
        })
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logging.error(f"relation preview error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@workspace_blueprint.route(
    '/api/workspaces/<string:workspace_id>/relations/<string:ref>/profile',
    methods=['GET'],
)
def api_relation_profile(workspace_id, ref):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    try:
        columns = profile_relation(ref)
        return jsonify({"ref": ref, "columns": columns})
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logging.error(f"relation profile error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@workspace_blueprint.route(
    '/api/workspaces/<string:workspace_id>/relations/<string:ref>/download',
    methods=['GET'],
)
def api_relation_download(workspace_id, ref):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    fmt = request.args.get("format", "parquet")
    return _relation_download_response(ref, fmt)


@workspace_blueprint.route(
    '/api/workspaces/<string:workspace_id>/relations/<string:ref>',
    methods=['DELETE'],
)
def api_delete_relation(workspace_id, ref):
    store = get_workspace_store()
    if not store.get_workspace(workspace_id):
        return jsonify({"error": "Not found"}), 404
    try:
        delete_stream(ref)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    state = store.get_state(workspace_id) or {}
    data = reconcile_relations(state.get("data") or {})
    relations = dict(data.get("relations") or {})
    relations.pop(ref, None)
    data["relations"] = relations
    store.patch_state(workspace_id, {"data": data})
    return jsonify({"ok": True, "ref": ref})


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/dashboard/export', methods=['GET'])
def api_dashboard_export(workspace_id):
    store = get_workspace_store()
    ws = store.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Not found"}), 404
    state = store.get_state(workspace_id) or {}
    dashboard = state.get("dashboard") or {}
    max_rows = 500

    # Support both the legacy single-page model (top-level `widgets`) and the
    # multi-page model (`pages: [{ id, name, widgets }]`).
    pages = dashboard.get("pages")
    if not pages:
        pages = [{
            "id": dashboard.get("activePageId") or "page-1",
            "name": "Page 1",
            "widgets": dashboard.get("widgets") or [],
        }]

    def _jsonable(v):
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, dict):
            return {str(_jsonable(k)): _jsonable(val) for k, val in v.items()}
        if isinstance(v, (list, tuple, set)):
            return [_jsonable(item) for item in v]
        if isinstance(v, (bytes, bytearray, memoryview)):
            try:
                return bytes(v).decode("utf-8", "replace")
            except Exception:
                return str(v)
        if isinstance(v, _dt.datetime) or isinstance(v, _dt.date) or isinstance(v, _dt.time):
            return v.isoformat()
        if isinstance(v, _decimal.Decimal):
            return float(v)
        return str(v)

    def export_widget(w):
        wtype = (w.get("type") or "bar").lower()
        if wtype == "slicer":
            return None
        if wtype == "button":
            return {
                "id": w.get("id"),
                "type": "button",
                "title": w.get("title"),
                "layout": w.get("layout") or {},
                "nav": w.get("nav") or {},
            }
        if wtype == "parameter":
            return {
                "id": w.get("id"),
                "type": "parameter",
                "title": w.get("title"),
                "layout": w.get("layout") or {},
                "param": w.get("param") or {},
                "style": w.get("style") or {},
            }
        if wtype == "text":
            return {
                "id": w.get("id"),
                "type": "text",
                "title": w.get("title"),
                "layout": w.get("layout") or {},
                "text": w.get("text") or "",
            }
        src = w.get("source") or {}
        ref = src.get("ref") or src.get("stream")
        if not ref:
            return None
        try:
            data = query_stream(ref, transform=w.get("transform"), limit=max_rows)
            return {
                "id": w.get("id"),
                "type": w.get("type"),
                "title": w.get("title"),
                "encoding": w.get("encoding") or {},
                "style": w.get("style") or {},
                "layout": w.get("layout") or {},
                "transform": w.get("transform") or {},
                "wells": w.get("wells") or {},
                "source": {"ref": ref},
                "data": {
                    "columns": data.get("columns"),
                    "rows": [
                        _jsonable(row)
                        for row in (data.get("rows") or [])[:max_rows]
                    ],
                },
            }
        except Exception as e:
            logging.warning(f"export widget {w.get('id')} skipped: {e}")
            return None

    export_pages = []
    for i, page in enumerate(pages):
        page_widgets = []
        for w in (page.get("widgets") or []):
            ew = export_widget(w)
            if ew is not None:
                page_widgets.append(ew)
        export_pages.append({
            "id": page.get("id") or f"page-{i + 1}",
            "name": page.get("name") or f"Page {i + 1}",
            "widgets": page_widgets,
        })

    # Flat list kept for backward-compatible template fallbacks.
    export_widgets = [w for p in export_pages for w in p["widgets"]]

    # Embed the raw (un-aggregated) rows for every source referenced on the
    # dashboard so the exported file can re-aggregate client-side. This is what
    # powers offline cross-filtering / slicing: clicking a category recomputes
    # the affected widgets from these rows without contacting a backend.
    # Deduplicated per source ref and capped to keep the file size sane.
    raw_max_rows = 20000
    used_refs = {
        (w.get("source") or {}).get("ref")
        for w in export_widgets
        if (w.get("source") or {}).get("ref")
    }
    datasets = {}
    for ref in used_refs:
        try:
            raw = query_stream(ref, transform=None, limit=raw_max_rows)
            datasets[ref] = {
                "columns": _jsonable(raw.get("columns")),
                "rows": [
                    _jsonable(row)
                    for row in (raw.get("rows") or [])[:raw_max_rows]
                ],
            }
        except Exception as e:
            logging.warning(f"export dataset {ref} skipped: {e}")

    static_root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "templates" / "pages" / "static"
    vendor_dir = static_root / "js" / "vendor"
    echarts_path = vendor_dir / "echarts.min.js"
    echarts_inline = ""
    if echarts_path.is_file():
        echarts_inline = echarts_path.read_text(encoding="utf-8", errors="replace")

    # Inline the GeoJSON for each bundled map scope actually used, so those map
    # charts render on air-gapped machines without a CDN fetch. Non-bundled
    # scopes (other countries) load from the internet in the exported file.
    map_scope_files = {
        "world": ("world", "world.json"),
        "usa": ("USA", "usa.json"),
        "india": ("india", "india.json"),
    }
    used_scopes = {
        (w.get("style") or {}).get("mapScope") or "world"
        for w in export_widgets
        if (w.get("type") or "").lower() == "map"
    }
    maps_inline = []
    for scope in used_scopes:
        entry = map_scope_files.get(scope)
        if not entry:
            continue
        map_name, file_name = entry
        map_path = vendor_dir / file_name
        if map_path.is_file():
            maps_inline.append({
                "name": map_name,
                "json": map_path.read_text(encoding="utf-8", errors="replace"),
            })

    html = render_template(
        "pages/dashboard_export.html",
        workspace=ws,
        dashboard=dashboard,
        pages=_jsonable(export_pages),
        widgets=_jsonable(export_widgets),
        datasets=_jsonable(datasets),
        echarts_inline=echarts_inline,
        maps_inline=maps_inline,
    )

    from io import BytesIO
    buf = BytesIO(html.encode("utf-8"))
    export_name = (dashboard.get("title") or ws.get("name") or "dashboard")
    filename = f"{export_name}.dash.html".replace(" ", "_")
    return send_file(
        buf,
        mimetype="text/html",
        as_attachment=True,
        download_name=filename,
    )