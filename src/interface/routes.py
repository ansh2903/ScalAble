from flask import Blueprint, render_template, render_template_string, jsonify, request, session, redirect, url_for, flash
import importlib

from src.engine.text_to_query import generate_query_from_nl
from src.engine.query_executor import run_query
from src.core.utils import render_result_table

from datetime import datetime
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

# App settings
@interface_blueprint.route('/settings')
def settings():
    return render_template('settings.html')

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
                result = run_query(db_type=db_type, credentials=credentials, query=generated_query)

                if isinstance(result, dict) and "error" in result:
                    return jsonify({
                        "chat_html": f"<div class='error'>Error: {result['error']}</div>"
                    }), 500

                result_html = render_result_table(result)
                
                # Store query results in session for visualization
                session['last_query_results'] = {
                    'query': generated_query,
                    'data': result,
                    'html_data': result_html
                }
                print(session['last_query_results'])

                visualize_url = url_for('interface.visualize_data')

                table_block = render_template_string("""
                <div class="message-row llm-msg">
                    <img class="sidebar-brand" src="{{ url_for('static', filename='images/logo.png') }}" alt="ScalAble Logo">
                    <div class="message-content">
                        <div class='data-table mt-3'>{{ table|safe }}</div>
                        <button class="btn btn-sm btn-outline-light mt-2 visualize-data-btn" data-url="{{ visualize_url }}">
                            <i class="fas fa-chart-bar"></i> Analyse Data
                        </button>
                    </div>
                </div>
                <!-- Iframe Container -->
                <div id="iframe-container" class="iframe-container">
                    <!-- Iframe will be dynamically inserted here -->
                """, query=generated_query, table=result_html, visualize_url=visualize_url)
                chat_html += table_block

            else:
                message = form.get("message")
                selected_db_id = form.get("selected_db_id")
                selected_conn = next((c for c in connections if str(c['id']) == str(selected_db_id)), None)

                if not selected_conn:
                    raise ValueError("Invalid database selection.")

                db_type = selected_conn.get("db_type")
                credentials = selected_conn.get("credentials")
                metadata = selected_conn.get("metadata")

                generated_query = generate_query_from_nl(message, db_type, metadata)

                time = datetime.now().strftime("%H:%M:%S")

                user_block = render_template_string("""
                    <div class="message-row user-msg">
                        <div class="message-content">
                            {{ message }}
                            <span class="msg-time">{{ time }}</span>
                        </div>
                        <fluent-avatar>
                        <svg
                            fill="currentColor"
                            aria-hidden="true"
                            width="2em"
                            height="2em"
                            viewBox="0 0 20 20"
                            xmlns="http://www.w3.org/2000/svg"
                        >
                            <path
                            d="M10 3a1.5 1.5 0 100 3 1.5 1.5 0 000-3zM7.5 4.5a2.5 2.5 0 115 0 2.5 2.5 0 01-5 0zm8-.5a1 1 0 100 2 1 1 0 000-2zm-2 1a2 2 0 114 0 2 2 0 01-4 0zm-10 0a1 1 0 112 0 1 1 0 01-2 0zm1-2a2 2 0 100 4 2 2 0 000-4zm.6 12H5a2 2 0 01-2-2V9.25c0-.14.11-.25.25-.25h1.76c.04-.37.17-.7.37-1H3.25C2.56 8 2 8.56 2 9.25V13a3 3 0 003.4 2.97 4.96 4.96 0 01-.3-.97zm9.5.97A3 3 0 0018 13V9.25C18 8.56 17.44 8 16.75 8h-2.13c.2.3.33.63.37 1h1.76c.14 0 .25.11.25.25V13a2 2 0 01-2.1 2c-.07.34-.17.66-.3.97zM7.25 8C6.56 8 6 8.56 6 9.25V14a4 4 0 008 0V9.25C14 8.56 13.44 8 12.75 8h-5.5zM7 9.25c0-.14.11-.25.25-.25h5.5c.14 0 .25.11.25.25V14a3 3 0 11-6 0V9.25z"
                            fill="currentColor"
                            ></path>
                        </svg>
                        </fluent-avatar>
                    </div>
                """, message=message, time=time)

                query_block = render_template_string("""
                    <div class="message-row llm-msg">
                        <img class="sidebar-brand" src="{{ url_for('static', filename='images/logo.png') }}" alt="ScalAble Logo">
                        <div class="message-content">
                            <div contenteditable="true">
                                <pre class="message-content llm">{{ query }}</pre>
                            </div>
                            <form class="d-inline-block" method="POST">
                                <input type="hidden" name="query" value="{{ generated_query }}">
                                <input type="hidden" name="db_type" value="{{ db_type }}">
                                <input type="hidden" name="credentials" value="{{ credentials }}">
                                <input type="hidden" name="selected_db_id" value="{{ selected_db_id }}">
                                <button class="btn btn-sm btn-outline-light mt-2 run-query-btn" type="submit">
                                    <i class="fas fa-play"></i> Run Query
                                </button>
                            </form>
                        </div>
                    </div>
                """, query=generated_query, db_type=db_type, credentials=credentials, selected_db_id=selected_db_id, generated_query=generated_query)

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

    return render_template("New_chat.html", connections=connections, selected_db_id=selected_db_id, table_block=table_block if 'table_block' in locals() else "")

@interface_blueprint.route('/upload_file', methods=['POST'])
def upload_file():
    pass

@interface_blueprint.route('/visualize_data', methods=['GET','POST'])
def visualize_data():
    # Get the last query results from session
    query_results = session.get('last_query_results')
    
    if not query_results:
        return render_template('visualize_data.html', no_data=True)
    
    html_data = query_results.get('html_data')
    if not html_data:
        return render_template('visualize_data.html', no_data=True)

    data = query_results.get('data', [])
    data = [list(row) if isinstance(row, tuple) else row for row in data]
    csv_data = ""
    
    for row in data:
        csv_data += ",".join(map(str, row)) + "\n"
    
    return render_template('visualize_data.html', csv_data=csv_data, query_info=query_results, html_data=html_data)


@interface_blueprint.route('/model_settings', methods=['GET', 'POST'])
def model_settings():
    pass 
