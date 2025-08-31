from flask import Blueprint, render_template, render_template_string, jsonify, request, session, redirect, url_for, flash
import importlib

from src.engine.text_to_query import generate_query_from_nl
from src.engine.query_executor import run_query
from src.core.utils import downloadable_json, downloadable_excel, downloadable_csv, render_result_table

from datetime import datetime
import uuid
import html
import json
import ast
import sys

from src.core.exception import CustomException
from src.core.logger import logging

interface_blueprint = Blueprint('interface', __name__)

# Landing page
@interface_blueprint.route('/')
def index():
    try:
        return render_template('New_index.html')
    except Exception as e:
        logging.error(f"Error loading index page: {str(e)}")
        return render_template('error.html', error_message="An error occurred while loading the index page.")

# Home page (for authenticated user)
@interface_blueprint.route('/home')
def home():
    try:
        user = session.get('user')
        databases = session.get('connections', []) if user else []
        return render_template('index.html', user=user, databases=databases)
    except Exception as e:
        logging.error(f"Error loading home page: {str(e)}")
        return render_template('error.html', error_message="An error occurred while loading the home page.")

# All connections
@interface_blueprint.route('/connections')
def connections():
    try:
        connections = session.get("connections", [])
        return render_template('connections.html', connections=connections)
    except Exception as e:
        logging.error(f"Error loading connections: {str(e)}")
        return render_template('error.html', error_message="An error occurred while loading the connections.")

# Add new database
@interface_blueprint.route('/add-database', methods=['GET', 'POST'])
def add_database():
    if request.method == 'POST':
        raw_form_data = request.form.to_dict()
        print("Raw Form Data:", raw_form_data)
        print('')

        db_type = raw_form_data.get("db_type")

        try:
            connector_module = importlib.import_module(f"connectors.{db_type}")

            status, msg = connector_module.test_connection(raw_form_data)
            if not status:
                flash(f"Connection failed: {msg}", "error")
                return redirect(url_for("interface.add_database"))

            metadata_status, metadata = connector_module.metadata(raw_form_data)
            if not metadata_status:
                flash(f"Metadata fetch failed: {metadata}", "error")
                return redirect(url_for("interface.add_database"))

            connection_id = len(session.get("connections", [])) + 1
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            connection_object = {
                "id": connection_id,
                "created_at": created_at,
                "db_type": db_type,
                "name": raw_form_data.get("name"),
                "credentials": {
                    key: raw_form_data[key]
                    for key in raw_form_data
                    if key not in ["id", "created_at", "metadata"]
                },
                "metadata": metadata
            }

            connections = session.get("connections", [])
            connections.append(connection_object)
            session["connections"] = connections

            flash("Database connected and metadata fetched!", "success")
            return redirect(url_for("interface.connections"))

        except ModuleNotFoundError:
            flash(f"Connector for '{db_type}' not implemented.", "error")
            return redirect(url_for("interface.add_database"))
        
        except Exception as e:
            flash(f"Error during database addition: {str(e)}", "error")
            return redirect(url_for("interface.add_database"))

    return render_template("connections_new.html")

# Delete database
@interface_blueprint.route('/delete-database/<int:db_id>', methods=['GET'])
def delete_database(db_id):
    try:
        connections = session.get("connections", [])
        connections = [conn for conn in connections if conn.get("id") != db_id]
        for index, conn in enumerate(connections, start=1):
            conn["id"] = index

        session["connections"] = connections
        flash("Database deleted successfully.", "success")
        return redirect(url_for('interface.connections'))
    except Exception as e:
        flash(f"Error deleting database: {str(e)}", "error")
        return redirect(url_for('interface.connections'))


# Edit database
@interface_blueprint.route('/edit-database/<int:db_id>', methods=['GET','POST'])
def edit_database(db_id):
    connections = session.get("connections", [])
    conn = next((c for c in connections if c['id'] == db_id), None)

    if not conn:
        flash("Database not found.", "error")
        return redirect(url_for('interface.connections'))

    if request.method == 'POST':
        updated_data = request.form.to_dict()
        updated_data['id'] = db_id
        updated_data['created_at'] = conn.get('created_at')
        connections = [updated_data if c['id'] == db_id else c for c in connections]
        session['connections'] = connections
        flash('Database updated', 'success')

        print(connections)
        return redirect(url_for('interface.connections'))

    return render_template('edit_database.html', conn=conn)

# chat interface
@interface_blueprint.route('/chat', methods=['GET', 'POST'])
def chat():
    connections = session.get('connections', [])
    databases = {conn.get('id'): conn for conn in connections}
    selected_db_id = None
    chat_html = ""

    if request.method == 'POST':
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        form = request.form

        try:
            if "query" in form:
                generated_query = form.get('query')
                db_type = form.get('db_type')
                credentials = ast.literal_eval(form.get('credentials'))
                unique_id = form.get('unique_id')

                result = run_query(db_type=db_type, credentials=credentials, query=generated_query)

                print('results: ', result)
                if isinstance(result, dict) and "error" in result:
                    return jsonify({"error": result["error"]}), 500

                result_html, row_count, column_count = render_result_table(result)
                
                session['last_query_results'] = {
                    'query': generated_query,
                    'data': result,
                    'html_data': result_html,
                    'db_type': db_type,
                    'unique_id': unique_id
                }

                table_block = render_template_string("""
                    <div class="message-content">
                        <div class="result-header">
                            <div class="result-count">
                                Showing <strong>{{ rows_count }}</strong> rows, <strong>{{ column_count }}</strong> columns
                            </div>
                        </div>

                        <div class='table-scroll'>{{ table|safe }}</div>
                        
                        <div class="btn-group">
                            <form class="execute-query-form" method="POST" onsubmit="return false;">
                                <input type="hidden" name="unique_id" value="{{ unique_id }}">
                                <input type="hidden" name="table" value="{{ table }}">
                                <button class="analyse-btn" type="button" data-uid="{{ unique_id }}">
                                    Analyse Data
                                </button>
                            </form>
                        </div>
                    </div>
                """, table=result_html, rows_count=row_count, column_count=column_count, unique_id=unique_id)

                if is_ajax:
                    return jsonify({
                        "unique_id": unique_id,
                        "table_html": table_block,
                        "success": True
                    })

                chat_html += table_block

            elif "table" in form:
                data = session.get('last_query_results').get('data')
                html_data = session['last_query_results'].get('html_data')
                

                if is_ajax:
                    return jsonify({
                        "data": data,
                        "html_data": html_data
                    })

            else:
                message = form.get("message")
                selected_db_id = form.get("selected_db_id")
                selected_conn = next((c for c in connections if str(c['id']) == str(selected_db_id)), None)

                if not selected_conn:
                    raise ValueError("Invalid database selection.")

                db_type = selected_conn.get("db_type")
                credentials = selected_conn.get("credentials")
                metadata = selected_conn.get("metadata")

                print(metadata)

                generated_query, generated_comment = generate_query_from_nl(message, db_type, metadata)

                time = datetime.now().strftime("%H:%M:%S")

                # Generate unique ID for this query block
                unique_id = str(uuid.uuid4())[:8]

                user_block = render_template_string("""
                    <div class="message user">
                        <div class="msg-text">{{ message }}</div>
                        <span class="msg-time">{{ time }}</span>
                    </div>
                """, message=message, time=time)

                query_block = render_template_string("""
                    <div class="message bot" data-query-id="{{ unique_id }}">
                                                     
                        {% if comment %}
                        <div class="msg-comment">{{ comment|safe }}</div>
                        {% endif %}
                        
                        {% if query %}                                                     
                        <div class="db-type">
                            {{ db_type }}
                        </div>

                        <div class="message-bot-query">
                                                                                 
                            <pre id="queryText_{{ unique_id }}" class="msg-text">{{ query }}</pre>
                            
                            <div class="edit-btn-container">
                                <button class="edit-btn" onclick="toggleEdit('{{ unique_id }}')">
                                    <i class="fas fa-edit"></i> Edit
                                </button>
                            </div>
                                                     
                            <div class="edit-controls" id="editControls_{{ unique_id }}" style="display: none;">
                                <button class="save-btn" onclick="saveEdit('{{ unique_id }}')">
                                    Save
                                </button>
                                    
                                <button class="cancel-btn" onclick="cancelEdit('{{ unique_id }}')">
                                    Cancel
                                </button>

                            </div>

                              <div class="btn-group">
                                <form class="run-query-form" method="POST" onsubmit="return false;">
                                    <input type="hidden" name="unique_id" value="{{ unique_id }}">
                                    <input type="hidden" name="query" id="hiddenQuery_{{ unique_id }}" value="{{ generated_query }}">
                                    <input type="hidden" name="db_type" value="{{ db_type }}">
                                    <input type="hidden" name="credentials" value="{{ credentials }}">
                                    <input type="hidden" name="selected_db_id" value="{{ selected_db_id }}">
                                    <button class="run-query-btn" type="button" data-uid="{{ unique_id }}">
                                        Execute
                                    </button>
                                </form>
                            </div>
                        </div>
                        {% endif %}
                        
                        <div class="table-container" id="tableContainer_{{ unique_id }}">
                            <!-- Query results will be injected here -->
                        </div>
                    </div>
                """, query=generated_query, comment = generated_comment, db_type=db_type, credentials=credentials, selected_db_id=selected_db_id, generated_query=generated_query, unique_id=unique_id)
                                
                chat_html += user_block + query_block

            if is_ajax:
                return jsonify({"chat_html": chat_html})

        except Exception as e:
            error_message = ""
            if isinstance(e, dict) and "error" in e:
                error_message = e["error"]
            else:
                error_message = str(e)

            return jsonify({
                "chat_html": f"<div class='error'>Error: {error_message}</div>"
            }), 500

    return render_template("chat.html", connections=connections, selected_db_id=selected_db_id, table_block=table_block if 'table_block' in locals() else "")

@interface_blueprint.route('/download/<fmt>', methods=['GET'])
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

@interface_blueprint.route('/model_settings', methods=['GET', 'POST'])
def model_settings():
    pass 

@interface_blueprint.route('/upload_file', methods=['POST'])
def upload_file():
    pass

# App settings
@interface_blueprint.route('/settings')
def settings():
    return render_template('settings.html')
