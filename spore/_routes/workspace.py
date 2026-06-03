from flask import stream_with_context, render_template, Response, jsonify, request, session, flash, current_app, send_file
from pathlib import Path
import importlib

from spore._connectors import SourceConnector
from spore._engine.model_manager import get_engine
from spore._engine.query_executor import run_query
from spore._utils import file_size_fmt, decrypt_creds, downloadable_json, downloadable_excel, downloadable_csv, load_settings
from spore._routes.utils import generate_blueprint
from spore._workspace.store import get_workspace_store
from spore._compute.query import query_stream
from spore._compute.relations import reconcile_relations, scan_stream

import psutil
import time
import pandas as pd
import traceback
import json
import os

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
    try:
        settings = load_settings() or {}
        provider, model = settings.get("provider", None), settings.get("model", None)
        connections = session.get('connections', [])
        workspace_id = request.args.get('workspace_id')
        workspace, workspace_state = _resolve_workspace(workspace_id)
    except Exception as e:
        logging.error(f"Error fetching connections: {str(e)}")
        connections = []
        workspace, workspace_state = _resolve_workspace(None)

    return render_template(
        "pages/chat.html",
        connections=connections,
        provider=provider,
        model=model,
        workspace=workspace,
        workspace_state=workspace_state,
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

@workspace_blueprint.route('/uploadfile', methods=['POST'])
def uploadfile():
    if not request.is_json:
        return jsonify({"error": "Expected JSON payload with file_path, selected_db_id and table_name"}), 400

    data = request.get_json(silent=True) or {}
    file_path = (data.get("file_path") or "").strip()
    table_name = (data.get("table_name") or "").strip()
    selected_db_id = data.get("selected_db_id")

    if not file_path or not selected_db_id or not table_name:
        return jsonify({"error": "file_path, table_name and selected_db_id are required"}), 400

    file_path = file_path.strip('"').strip("'")
    if ".." in file_path:
        return jsonify({"error": "Invalid file_path"}), 400

    connections = session.get("connections", [])
    selected_conn = next((c for c in connections if str(c.get("id")) == str(selected_db_id)), None)
    if not selected_conn:
        return jsonify({"error": "Selected database not found in user session"}), 404

    db_type = selected_conn.get("db_type")
    credentials = selected_conn.get("credentials")

    if not os.path.exists(file_path):
        return jsonify({"error": f"File path does not exist on the system: {file_path}"}), 400

    if 'metadata' not in selected_conn or not isinstance(selected_conn['metadata'], dict):
        selected_conn['metadata'] = {}
    if 'tables' not in selected_conn['metadata'] or not isinstance(selected_conn['metadata']['tables'], dict):
        selected_conn['metadata']['tables'] = {}

    inferred_sql = None
    llm_comment = None
    try:
        table_structure = selected_conn['metadata']['tables'].get(table_name)
        if not table_structure:
            logging.info(f"Table {table_name} not found in metadata, inferring structure using LLM.")
            ext = os.path.splitext(file_path)[-1].lower()
            if ext == ".csv" or ext == ".txt":
                sample_df = pd.read_csv(file_path, nrows=4, encoding="latin1")
            elif ext in [".xls", ".xlsx"]:
                sample_df = pd.read_excel(file_path, nrows=4)
            elif ext == ".json":
                try:
                    sample_df = pd.read_json(file_path, lines=True, nrows=4)
                except ValueError:
                    sample_df = pd.read_json(file_path, nrows=4)
            else:
                return jsonify({"error": f"Unsupported file extension: {ext}"}), 400
            
            sample_str = sample_df.to_json(orient="records")
            
            file_prompt = f"""
                The user uploaded a file and requested a new table named `{table_name}`. Database type: {db_type}.

                Here are up to the first 4 rows and all the columns of the file of type `{ext}`:
                {sample_str}

                Task:
                1) Return ONLY a valid and executable Table structure defination statement for `{table_name}` suitable for {db_type}, to create table.
                2) Be sure to be concise and syntactically correct and make the complete query for the task.
                3) Extreme caution and accuracy is required to ensure the query runs without errors.
                4) Use appropriate data types for each column based on the sample data.

                Important: Do not use reserved SQL keywords as column names. If necessary, rename them with a suffix like _col.

                ### Strict Instructions:
                - Always return output in **strict JSON**.
                - JSON must contain:
                - "query": (string) The final executable {db_type} query.  
                    - MUST be a valid query string.  
                    - Do NOT wrap in backticks or markdown.  
                    - Do NOT include explanations, comments, or text.
                    - SQL comments (`-- ...` or `/* ... */`) inside the query.
                    - NUST ADD line breaks (`\n`) in the query wherever needed for readability.
        
                - "comment": (string) **Markdown-formatted note**  
                    - Leave it empty (""), no comment is needed.

                - Do NOT enclose the output in ('''json ''')
                - "query" is stricly for the executable query string. No explanations or comments should be included here.
                - "comment" does not need anything in it.
                - Do NOT include any other fields or metadata.

                ---

                Now return ONLY the JSON object as per the rules above:
                """
            session['file_prompt'] = file_prompt

            created_query, llm_comment = generate_query_from_nl(
                nl_query=f"Generate table for {table_name} using sample data.",
                db_type=db_type,
                db_metadata=selected_conn.get('metadata', {})
            )
            logging.info(f"LLM generated CREATE TABLE query: {created_query}")

            session.pop('file_prompt', None)

            if not created_query or not isinstance(created_query, str):
                raise ValueError(
                    "LLM did not return a valid CREATE TABLE string. "
                    f"LLM output: query={repr(created_query)}, comment={repr(llm_comment)}"
                )
            run_query(db_type=db_type, credentials=credentials, query=created_query)
            logging.info(f"Created new table {table_name} in {db_type} using LLM-generated SQL.")

        try:
            connector_module = importlib.import_module(f"src.connectors.{db_type}")
        except Exception as e:
            return jsonify({"error": f"Connector module not found for db_type '{db_type}': {str(e)}"}), 500

        result = connector_module.file_to_db(credentials=credentials, file_path=file_path, table_name=table_name, ext=ext)
        logging.info(f"file_to_db result: {result}")
        if isinstance(result, dict) and result.get("ok") is False:
            print(result)
            return jsonify({"error": "file_to_db failed", "detail": result}), 500
        
        metadata_status, metadata = connector_module.metadata(credentials)
        if not metadata_status:
            flash(f"Metadata fetch failed: {metadata}", "error")

        for c in connections:
            if str(c['id']) == str(selected_db_id):
                c['metadata'] = metadata
        session['connections'] = connections

        logging.info(f"Updated session metadata for connection ID {selected_db_id} after file upload.")

    except Exception as e:
        tb = traceback.format_exc()
        current_app.logger.error("Uploadfile error: %s\n%s", str(e), tb)
        return jsonify({"error": "Error while processing file", "details": str(e), "trace": tb}), 500

    return jsonify({
        "message": "File processed",
        "detail": result,
        "inferred_sql": inferred_sql,
        "llm_comment": llm_comment,
        "table_name": table_name
    }), 200


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


@workspace_blueprint.route('/api/workspaces/<string:workspace_id>/dashboard/export', methods=['GET'])
def api_dashboard_export(workspace_id):
    store = get_workspace_store()
    ws = store.get_workspace(workspace_id)
    if not ws:
        return jsonify({"error": "Not found"}), 404
    state = store.get_state(workspace_id) or {}
    dashboard = state.get("dashboard") or {}
    widgets = dashboard.get("widgets") or []
    export_widgets = []
    max_rows = 500

    for w in widgets:
        src = w.get("source") or {}
        ref = src.get("ref") or src.get("stream")
        if not ref:
            continue
        try:
            data = query_stream(
                ref,
                transform=w.get("transform"),
                limit=max_rows,
            )
            export_widgets.append({
                "id": w.get("id"),
                "type": w.get("type"),
                "title": w.get("title"),
                "encoding": w.get("encoding") or {},
                "style": w.get("style") or {},
                "layout": w.get("layout") or {},
                "data": {
                    "columns": data.get("columns"),
                    "rows": (data.get("rows") or [])[:max_rows],
                },
            })
        except Exception as e:
            logging.warning(f"export widget {w.get('id')} skipped: {e}")

    static_root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "templates" / "pages" / "static"
    echarts_path = static_root / "js" / "vendor" / "echarts.min.js"
    echarts_inline = ""
    if echarts_path.is_file():
        echarts_inline = echarts_path.read_text(encoding="utf-8", errors="replace")

    html = render_template(
        "pages/dashboard_export.html",
        workspace=ws,
        dashboard=dashboard,
        widgets=export_widgets,
        echarts_inline=echarts_inline,
    )

    from io import BytesIO
    buf = BytesIO(html.encode("utf-8"))
    filename = f"{ws.get('name', 'dashboard')}.dash.html".replace(" ", "_")
    return send_file(
        buf,
        mimetype="text/html",
        as_attachment=True,
        download_name=filename,
    )