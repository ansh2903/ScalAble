from flask import stream_with_context, render_template, Response, jsonify, request, session, flash, current_app
import importlib

from spore._connectors import SourceConnector
from spore._engine.model_manager import get_engine
from spore._engine.query_executor import run_query
from spore._utils import file_size_fmt, decrypt_creds, downloadable_json, downloadable_excel, downloadable_csv, load_settings, data_runtime
from spore._routes.utils import generate_blueprint

import psutil
import time
import pandas as pd
import traceback
import json
import os

from spore._exception import CustomException
from spore._logger import logging

data_blueprint = generate_blueprint('data')


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
