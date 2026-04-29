from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, Response, stream_with_context
from spore._utils import load_settings
from spore._logger import logging
from spore._connectors.connector import DatabaseConnector
from spore._engine.model_manager import get_engine
from spore._routes.utils import generate_blueprint
import json

workspace_blueprint = generate_blueprint('workspace')

@workspace_blueprint.route('/chat', methods = ['GET', 'POST'])
def chat():
    try:
        settings = load_settings() or {}
        provider, model = settings.get("provider", None), settings.get("model", None)

        connections = session.get('connections', [])
        print("Connections in session:", connections)

    except Exception as e:
        logging.error(f"Error fetching connections: {str(e)}")
        connections = {}

    return render_template("pages/chat.html", connections=connections, provider=provider, model=model)

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

@workspace_blueprint.route('/query-preview', methods=["POST"])
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

@workspace_blueprint.route('/view-data-extraction', methods=['POST'])
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
