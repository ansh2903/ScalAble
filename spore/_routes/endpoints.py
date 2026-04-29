from flask import Blueprint, stream_with_context, render_template, Response, jsonify, request, session, redirect, url_for, flash, current_app
import importlib

from spore._connectors.connector import DatabaseConnector
from spore._engine.model_manager import get_engine, reset_engine
from spore._engine.query_executor import run_query
from spore._utils import file_size_fmt, model_ls, encrypt_creds, downloadable_json, downloadable_excel, downloadable_csv, load_settings, save_settings, is_running_in_docker
from spore._config.settings import VENDOR_CONFIG, PROVIDER_FIELDS

import psutil
import time
import pandas as pd
from datetime import datetime
import tempfile
import traceback
import json
import os

from spore._exception import CustomException
from spore._logger import logging

endpoints_blueprint = Blueprint('endpoints', __name__)

# All connections

# Connections management (add, edit, delete)
@endpoints_blueprint.route('/connections', methods=['GET','POST'])
def connections():
    try:
        connections = session.get("connections", [])
        no_of_connections = len(connections) or 0
        return render_template('connections.html', connections=connections, no_of_connections=no_of_connections)
    except Exception as e:
        logging.error(f"Error loading connections: {str(e)}")
        return render_template('error.html', error_message="An error occurred while loading the connections.")

@endpoints_blueprint.route('/connections/new/<vendor>', methods=['GET', 'POST'])
def add_new_connection(vendor):
    try:
        db = VENDOR_CONFIG.get(vendor)
        if not db:
            flash(f"Unsupported database type: {vendor}", "error")
            return redirect(url_for("endpoints.add_database"))
        
        template_path = f'partials/db/{db.get("connection_type")}.html'
        return render_template(template_path, vendor=vendor, default_port=db.get("default_port"), has_schema=db.get("has_schema"), schema_default=db.get("schema_default"))
    
    except Exception as e:
        logging.error(f"Template for {vendor} not found: {str(e)}")
        return "<p class='text-red-500 text-xs p-10 text-center font-bold'>Coming Soon: Configuration for this database.</p>"
    
@endpoints_blueprint.route('/test-connection', methods=['POST'])
def test_connection():
    # Get connection details from the form
    if request.method == 'POST':
        raw_form_data = request.form.to_dict()

        # Handle Docker edge case
        if is_running_in_docker() and raw_form_data.get("host") in ["localhost", "127.0.0.1"]:
            raw_form_data["host"] = "host.docker.internal"

    try:
        db_manager = DatabaseConnector(raw_form_data)
        status, msg = db_manager.test()

        # test_db_connection(db_uri)
        return "Connection successful! The matrix is full-rank and ready for queries."
    except Exception as e:
        return f"Connection failed: {str(e)}. Check your credentials or SSL settings."

@endpoints_blueprint.route('/connections/new', methods=['GET', 'POST'])
def new_connector():
    if request.method == 'POST':
        raw_form_data = request.form.to_dict()

        temp_file_paths = []
        
        if request.files:
            for file_key in request.files:
                uploaded_file = request.files[file_key]
                # If the user actually selected a file
                if uploaded_file.filename != '':
                    # Create a secure temporary file on the OS
                    fd, temp_path = tempfile.mkstemp(suffix=".pem")
                    with os.fdopen(fd, 'wb') as f:
                        uploaded_file.save(f)
                    
                    # Inject the file path into the config so the connector can find it
                    raw_form_data[file_key] = temp_path
                    temp_file_paths.append(temp_path)

        # Handle Docker edge case
        if is_running_in_docker() and raw_form_data.get("host") in ["localhost", "127.0.0.1"]:
            raw_form_data["host"] = "host.docker.internal"

        # 3. Test the connection
        try:
            print("raw_form_data",raw_form_data)

            db_manager = DatabaseConnector(raw_form_data)
            status, msg = db_manager.test()
            print(msg)
            
            if not status:
                flash(f"Connection failed: {msg}", "error")
                logging.error(f"Connection test failed: {msg}")
                return redirect(url_for("endpoints.new_connector"))

            # [Fetch Metadata Logic Goes Here]
            m_status, metadata = db_manager.fetch_metadata()
            print(metadata)
            if not m_status:
                flash(f"Metadata fetch failed: {metadata}", "error")
                return redirect(url_for("endpoints.new_connector"))

            # [Save to Session / DB Logic Goes Here]
            connection = session.get("connections", [])
            print(connection)
            connection.append({
                "id": len(connection) + 1,
                "db_type": raw_form_data.get("db_type"),
                "credentials": encrypt_creds(raw_form_data),
                "metadata": metadata,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            session["connections"] = connection

            flash("System Linked Successfully!", "success")
            return redirect(url_for("endpoints.connections"))

        except Exception as e:
            flash(f"System Error: {str(e)}", "error")
            logging.error(f"System Error during connection: {str(e)}")
            return redirect(url_for("endpoints.new_connector"))
            
        finally:
            for temp_path in temp_file_paths:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception as cleanup_error:
                    logging.warning(f"Failed to clean up temp file {temp_path}: {cleanup_error}")

    return render_template("connections_new.html")

# Delete database
@endpoints_blueprint.route('/delete-database/<int:db_id>', methods=['GET'])
def delete_database(db_id):
    try:
        connections = session.get("connections", [])
        connections = [conn for conn in connections if conn.get("id") != db_id]
        for index, conn in enumerate(connections, start=1):
            conn["id"] = index

        session["connections"] = connections
        flash("Database deleted successfully.", "success")
        return redirect(url_for('endpoints.connections'))
    except Exception as e:
        flash(f"Error deleting database: {str(e)}", "error")
        return redirect(url_for('endpoints.connections'))


# Edit database
@endpoints_blueprint.route('/edit-database/<int:db_id>', methods=['GET','POST'])
def edit_database(db_id):
    connections = session.get("connections", [])
    conn = next((c for c in connections if c['id'] == db_id), None)

    if not conn:
        flash("Database not found.", "error")
        return redirect(url_for('endpoints.connections'))

    if request.method == 'POST':
        updated_data = request.form.to_dict()
        updated_data['id'] = db_id
        updated_data['created_at'] = conn.get('created_at')
        connections = [updated_data if c['id'] == db_id else c for c in connections]
        session['connections'] = connections
        flash('Database updated', 'success')

        print(connections)
        return redirect(url_for('endpoints.connections'))

    return render_template('edit_database.html', conn=conn)

# ---------------------------------------------------------------------------------
# chat interface

@endpoints_blueprint.route('/chat', methods = ['GET', 'POST'])
def chat():
    try:
        settings = load_settings() or {}
        provider, model = settings.get("provider", None), settings.get("model", None)

        connections = session.get('connections', [])
        print("Connections in session:", connections)

    except Exception as e:
        logging.error(f"Error fetching connections: {str(e)}")
        connections = {}

    return render_template("chat.html", connections=connections, provider=provider, model=model)

@endpoints_blueprint.route('/chat/ask', methods=['POST'])
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

@endpoints_blueprint.route('/query-preview', methods=["POST"])
def preview():
    try:
        if request.method == "POST":
            query = request.form.get("query")
            selected_id = request.form.get("id")
            connection = session.get("connections", [])
            raw_data = next((conn for conn in connection if str(conn['id']) == str(selected_id)), None)
            
            if not raw_data:
                return jsonify({"status": "error", "message": "Connection not found"}), 404

            db_manager = DatabaseConnector(raw_data)
            def generate_stream():
                try:
                    # This loop actually triggers the execution in DuckDB
                    for chunk in db_manager.preview_execute(query=query):
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

@endpoints_blueprint.route('/view-data-extraction', methods=['POST'])
def extraction():
    try:
        query = request.form.get('query')
        dbid = request.form.get('id')
        stream_name = request.form.get('stream_name')
        connection = session.get("connections", [])
        raw_data = next((c for c in connection if str(c['id']) == str(dbid)), None)
        batch_row_size=None
        memory_ceiling=None
        
        if not raw_data:
            return jsonify({"status": "error", "message": "Connection not found"}), 404

        db_manager = DatabaseConnector(raw_data)
        status, path = db_manager.view_data_extraction(query=query, stream_name=stream_name, memory_ceiling=memory_ceiling if memory_ceiling else None, batch_row_size=batch_row_size if batch_row_size else None)

        if status != 'success':
            return jsonify({'status': status, 'message': 'failed to collect data from view'})
        
        return jsonify({
            "status": status,
            "path": path
        })

    except Exception as e:
        logging.error(f"data-stream error: {str(e)}", exc_info=True)  # exc_info gives you the full traceback
        return jsonify({"status": "error", "message": str(e)}), 500

@endpoints_blueprint.route('/download/<fmt>', methods=['GET'])
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

@endpoints_blueprint.route('/uploadfile', methods=['POST'])
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

@endpoints_blueprint.route('/settings', methods=['GET', 'POST'])
def settings():
    settings = load_settings() or {}
    provider, model = settings.get("provider", None), settings.get("model", None)

    if request.method == "POST":
        try:
            provider = request.form.get("provider")

            new_data = {
                "provider": provider,
                "model": request.form.get("model", settings.get("model")),
                "keep_alive": request.form.get("keep_alive", "5m"),
                "options": {
                    "num_predict":       int(request.form.get("num_predict", 256)),
                    "top_k":             int(request.form.get("top_k", 40)),
                    "top_p":             float(request.form.get("top_p", 0.9)),
                    "temperature":       float(request.form.get("temperature", 0.7)),
                    "num_ctx":           int(request.form.get("num_ctx", 2048)),
                    "num_batch":         int(request.form.get("num_batch", 4)),
                    "num_thread":        int(request.form.get("num_thread", 8)),
                    "num_gpu":           int(request.form.get("num_gpu", 0)),
                    "repeat_penalty":    float(request.form.get("repeat_penalty", 1.1)),
                    "use_mmap":          request.form.get("use_mmap") == "true",
                    "use_mlock":         request.form.get("use_mlock") == "false",
                    "frequency_penalty": float(request.form.get("frequency_penalty", 0.0)),
                    "presence_penalty":  float(request.form.get("presence_penalty", 0.0)),
                }
            }

            save_settings(new_data)
            reset_engine()
            flash("Settings updated successfully!", "success")
  
        except Exception as e:
            logging.error(f"Error saving settings: {str(e)}")
            flash("Failed to save settings. Please check the logs for details.", "error")
            return redirect(url_for('endpoints.settings'))
    
    return render_template(
        'settings.html',
        settings=settings,
        provider_fields=PROVIDER_FIELDS,
        current_provider=provider,
        current_model=model,
        all_providers=list(PROVIDER_FIELDS.keys()),
    )
    
# ----------------------------------------------------------------------------------------------------
# Helper endpoints

@endpoints_blueprint.route('/system-metrics')
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

@endpoints_blueprint.route('/models_list')
def models_list():
    provider = request.args.get("provider")
    if not provider:
        return jsonify({"error": "No provider specified"}), 400
        
    try:
        models = model_ls(provider)
        return jsonify(models)
    except Exception as e:
        logging.error(f"Failed to fetch models for {provider}: {e}")
        return jsonify({"error": "Could not connect to provider"}), 500
    
@endpoints_blueprint.route('/streams')
def files():
    try:
        base_path = 'src/temp'
        streams = []
        MEMORY_THRESHOLD = 1 * 1024**3 # 1GB

        if not os.path.exists(base_path):
            return jsonify([])

        for stream_name in os.listdir(base_path):
            stream_path = os.path.join(base_path, stream_name)
            if os.path.isdir(stream_path):
                stream_info = {"name": stream_name, "files": {}}
                
                for file_name in ['source.parquet']:
                    file_path = os.path.join(stream_path, file_name)
                    if os.path.exists(file_path):
                        size = os.path.getsize(file_path)
                        stream_info["files"][file_name] = {
                            "size_bytes": size,
                            "size_pretty": file_size_fmt(size), # Helper for backend display
                            "memory_safe": size < MEMORY_THRESHOLD
                        }

                if stream_info["files"]:
                    streams.append(stream_info)
                    
        return jsonify(streams)
    except Exception as e:
        pass

@endpoints_blueprint.route('/api/metadata/<int:db_id>')
def get_db_metadata(db_id):
    connections = session.get('connections', [])
    selected_conn = next((c for c in connections if c['id'] == db_id), None)
    
    if not selected_conn:
        return jsonify({"error": "Not found"}), 404
        
    # Optional: You could trigger a fresh DatabaseConnector(selected_conn).get_metadata() 
    # here if you want it to be truly 'live' upon refresh. For now no since it is expensive on db I/O
    
    return jsonify({"metadata": selected_conn.get('metadata', {})})