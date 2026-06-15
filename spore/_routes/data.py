from flask import stream_with_context, render_template, Response, jsonify, request, session, flash, current_app
import importlib
import re
import uuid

from werkzeug.utils import secure_filename

from spore._connectors import SourceConnector
from spore._connectors.utils import (
    build_postgres_ddl,
    estimate_file_rows,
    infer_table_schema,
)
from spore._engine.model_manager import get_engine
from spore._engine.query_executor import run_query
from spore._utils import file_size_fmt, decrypt_creds, downloadable_json, downloadable_excel, downloadable_csv, load_settings, data_runtime
from spore._routes.utils import generate_blueprint
from spore._routes.fs import _safe_resolve, ROOT as FS_ROOT

import psutil
import time
import pandas as pd
import traceback
import json
import os

from spore._exception import CustomException
from spore._logger import logging

data_blueprint = generate_blueprint('data')

STAGING_ROOT = os.path.join(FS_ROOT, "_staging")


def _reject_agent_execution():
    if request.headers.get("X-Agent-Request"):
        return jsonify({
            "status": "error",
            "message": "Agent cannot execute queries against remote data sources. Use the Data panel.",
        }), 403
    return None


@data_blueprint.route('/query-preview', methods=["POST"])
def preview():
    try:
        blocked = _reject_agent_execution()
        if blocked:
            return blocked
        if request.method == "POST":
            query = request.form.get("query")
            selected_id = request.form.get("id")
            limit = request.form.get("limit")
            
            connection = session.get("connections", [])
            raw_data = next((conn for conn in connection if str(conn['id']) == str(selected_id)), None)
            
            if not raw_data:
                return jsonify({"status": "error", "message": "Connection not found"}), 404

            kind = raw_data.get('kind')
            source_type = raw_data.get('source_type')
            creds = raw_data.get('credentials')
            use_ssh = raw_data.get('use_ssh')
            use_ssl = raw_data.get('use_ssl')

            manager = SourceConnector(kind=kind, source_type=source_type, creds=creds, use_ssh=use_ssh, use_ssl=use_ssl)
            def generate_stream():
                try:
                    # This loop actually triggers the execution in DuckDB
                    for chunk in manager.preview(query=query, limit=limit):
                        # IN FUTURE MAKE SURE TO FIND ANOTHER WAY OTHER THAN default=str THING
                        yield f"data: {json.dumps(chunk, default=str)}\n\n"
                        
                except Exception as e:
                    logging.error(f"Stream error: {str(e)}")
                    err_chunk = {"type": "error", "content": str(e)}
                    yield f"data: {json.dumps(err_chunk)}\n\n"

        # 2. Return the stream directly to the frontend
            return Response(stream_with_context(generate_stream()), mimetype='text/event-stream')
    except Exception as e:
        logging.error(f"Query execution error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@data_blueprint.route('/ingest', methods=['POST'])
def ingest():
    try:
        blocked = _reject_agent_execution()
        if blocked:
            return blocked
        query = request.form.get('query')
        dbid = request.form.get('id')
        stream_name = request.form.get('stream_name')
        memory_ceiling = request.form.get('memory_ceiling') or '1GB'
        batch_row_size = int(request.form.get('batch_row_size') or data_runtime()["batch_row_size"])
        output_format = request.form.get('format') or 'parquet'

        connection = session.get("connections", [])
        raw_data = next((c for c in connection if str(c['id']) == str(dbid)), None)

        if not raw_data:
            return jsonify({"status": "error", "message": "Connection not found"}), 404

        kind = raw_data.get('kind')
        source_type = raw_data.get('source_type')
        creds = raw_data.get('credentials')
        use_ssh = raw_data.get('use_ssh')
        use_ssl = raw_data.get('use_ssl')

        manager = SourceConnector(
            kind=kind,
            source_type=source_type,
            creds=creds,
            use_ssh=use_ssh,
            use_ssl=use_ssl,
        )

        def generate_stream():
            try:
                for chunk in manager.ingest(
                    query=query,
                    stream_name=stream_name,
                    memory_ceiling=memory_ceiling,
                    batch_row_size=batch_row_size,
                    output_format=output_format,
                ):
                    yield f"data: {json.dumps(chunk, default=str)}\n\n"
            except Exception as e:
                logging.error(f"ingest stream error: {str(e)}", exc_info=True)
                err_chunk = {"type": "error", "content": str(e)}
                yield f"data: {json.dumps(err_chunk)}\n\n"

        return Response(stream_with_context(generate_stream()), mimetype='text/event-stream')

    except Exception as e:
        logging.error(f"data-stream error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Push file → database ────────────────────────────────────────────────────


def _push_staging() -> dict:
    return session.setdefault("push_staging", {})


def _get_staged_path(token: str) -> str | None:
    entry = _push_staging().get(token)
    if not entry:
        return None
    path = entry.get("path")
    if path and os.path.isfile(path):
        return path
    return None


def _connection_by_id(conn_id: str):
    connections = session.get("connections", [])
    return next((c for c in connections if str(c.get("id")) == str(conn_id)), None)


def _connector_for_conn(raw_data: dict) -> SourceConnector:
    return SourceConnector(
        kind=raw_data.get("kind"),
        source_type=raw_data.get("source_type"),
        creds=raw_data.get("credentials"),
        use_ssh=raw_data.get("use_ssh"),
        use_ssl=raw_data.get("use_ssl"),
    )


def _extract_xml_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", text or "")
    return (match.group(1) if match else "").strip()


@data_blueprint.route("/push/stage", methods=["POST"])
def push_stage():
    blocked = _reject_agent_execution()
    if blocked:
        return blocked

    try:
        token = uuid.uuid4().hex
        staging = _push_staging()

        uploaded = request.files.get("file")
        if uploaded and uploaded.filename:
            os.makedirs(STAGING_ROOT, exist_ok=True)
            name = secure_filename(uploaded.filename) or "upload"
            dest_dir = os.path.join(STAGING_ROOT, token)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, name)
            uploaded.save(dest_path)
            staging[token] = {
                "path": dest_path,
                "filename": name,
                "size": os.path.getsize(dest_path),
            }
            session["push_staging"] = staging
            return jsonify({
                "token": token,
                "filename": name,
                "size": staging[token]["size"],
                "size_pretty": file_size_fmt(staging[token]["size"]),
            })

        data = request.get_json(silent=True) or {}
        rel_path = (data.get("path") or request.form.get("path") or "").strip()
        if not rel_path:
            return jsonify({"error": "Provide a file upload or a volume path"}), 400

        abs_path = _safe_resolve(rel_path)
        if not os.path.isfile(abs_path):
            return jsonify({"error": f"File not found: {rel_path}"}), 404

        staging[token] = {
            "path": abs_path,
            "filename": os.path.basename(abs_path),
            "size": os.path.getsize(abs_path),
        }
        session["push_staging"] = staging
        return jsonify({
            "token": token,
            "filename": staging[token]["filename"],
            "size": staging[token]["size"],
            "size_pretty": file_size_fmt(staging[token]["size"]),
        })

    except Exception as e:
        logging.error(f"push/stage error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@data_blueprint.route("/push/inspect", methods=["POST"])
def push_inspect():
    blocked = _reject_agent_execution()
    if blocked:
        return blocked

    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    table_name = (data.get("table_name") or "").strip()
    conn_id = data.get("id")

    if not token or not table_name or not conn_id:
        return jsonify({"error": "token, table_name and id are required"}), 400

    raw_data = _connection_by_id(conn_id)
    if not raw_data:
        return jsonify({"error": "Connection not found"}), 404

    if raw_data.get("source_type") != "postgresql":
        return jsonify({"error": "Push is only supported for PostgreSQL connections"}), 400

    file_path = _get_staged_path(token)
    if not file_path:
        return jsonify({"error": "Staged file not found or expired"}), 404

    try:
        schema_info = infer_table_schema(file_path)
        pg_schema = (raw_data.get("metadata") or {}).get("schema") or "public"
        suggested_ddl = build_postgres_ddl(
            table_name=table_name,
            columns=schema_info["columns"],
            arrow_types=schema_info["types"],
            schema=pg_schema,
        )
        est_rows = estimate_file_rows(file_path)

        return jsonify({
            "columns": schema_info["columns"],
            "types": schema_info["types"],
            "sample_rows": schema_info["sample_rows"][:20],
            "suggested_ddl": suggested_ddl,
            "est_rows": est_rows,
            "file_size": schema_info["file_size"],
            "file_size_pretty": file_size_fmt(schema_info["file_size"]),
            "filename": _push_staging().get(token, {}).get("filename"),
        })

    except Exception as e:
        logging.error(f"push/inspect error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@data_blueprint.route("/push/suggest-ddl", methods=["POST"])
def push_suggest_ddl():
    blocked = _reject_agent_execution()
    if blocked:
        return blocked

    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    table_name = (data.get("table_name") or "").strip()
    conn_id = data.get("id")

    if not token or not table_name or not conn_id:
        return jsonify({"error": "token, table_name and id are required"}), 400

    raw_data = _connection_by_id(conn_id)
    if not raw_data:
        return jsonify({"error": "Connection not found"}), 404

    if raw_data.get("source_type") != "postgresql":
        return jsonify({"error": "Push is only supported for PostgreSQL connections"}), 400

    file_path = _get_staged_path(token)
    if not file_path:
        return jsonify({"error": "Staged file not found or expired"}), 404

    try:
        schema_info = infer_table_schema(file_path, sample_rows=50)
        sample_json = json.dumps(schema_info["sample_rows"][:10], default=str)
        prompt = (
            f"The user wants to push a file into PostgreSQL as table `{table_name}`.\n\n"
            f"Columns and inferred types from sample data:\n"
            f"{json.dumps(list(zip(schema_info['columns'], schema_info['types'])), indent=2)}\n\n"
            f"Sample rows (up to 10):\n{sample_json}\n\n"
            f"Task: Return a valid CREATE TABLE statement for `{table_name}` suitable for PostgreSQL. "
            f"Use appropriate data types. Quote identifiers that need it. "
            f"Do not use reserved SQL keywords as column names — rename with _col suffix if needed.\n"
            f"Use CREATE TABLE IF NOT EXISTS."
        )

        engine = get_engine()
        metadata = raw_data.get("metadata") or {}
        full_response = ""
        for chunk in engine.generate(
            user_input=prompt,
            db_type="postgresql",
            metadata=metadata,
        ):
            if chunk.get("type") == "token":
                full_response += chunk.get("content", "")

        ddl = _extract_xml_tag(full_response, "query")
        comment = _extract_xml_tag(full_response, "comment")

        if not ddl:
            return jsonify({"error": "LLM did not return a valid CREATE TABLE query"}), 500

        return jsonify({"ddl": ddl, "comment": comment})

    except Exception as e:
        logging.error(f"push/suggest-ddl error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@data_blueprint.route("/push/execute", methods=["POST"])
def push_execute():
    blocked = _reject_agent_execution()
    if blocked:
        return blocked

    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    table_name = (data.get("table_name") or "").strip()
    conn_id = data.get("id")
    ddl = (data.get("ddl") or "").strip()
    batch_row_size = int(data.get("batch_row_size") or data_runtime()["batch_row_size"])

    if not token or not table_name or not conn_id:
        return jsonify({"error": "token, table_name and id are required"}), 400

    raw_data = _connection_by_id(conn_id)
    if not raw_data:
        return jsonify({"error": "Connection not found"}), 404

    if raw_data.get("source_type") != "postgresql":
        return jsonify({"error": "Push is only supported for PostgreSQL connections"}), 400

    file_path = _get_staged_path(token)
    if not file_path:
        return jsonify({"error": "Staged file not found or expired"}), 404

    manager = _connector_for_conn(raw_data)

    def generate_stream():
        try:
            if ddl:
                for chunk in manager.preview(query=ddl, limit=1):
                    if chunk.get("type") == "error":
                        yield f"data: {json.dumps(chunk, default=str)}\n\n"
                        return

            for chunk in manager.file_to_db(
                file_path=file_path,
                table_name=table_name,
                batch_row_size=batch_row_size,
            ):
                if chunk.get("type") == "done":
                    ok, metadata = manager.fetch_metadata()
                    if ok:
                        connections = session.get("connections", [])
                        for c in connections:
                            if str(c.get("id")) == str(conn_id):
                                c["metadata"] = metadata
                        session["connections"] = connections
                        chunk["metadata_refreshed"] = True

                yield f"data: {json.dumps(chunk, default=str)}\n\n"

        except Exception as e:
            logging.error(f"push/execute stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, default=str)}\n\n"

    return Response(stream_with_context(generate_stream()), mimetype="text/event-stream")
