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
        return render_template('index.html')
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
                result_html = render_result_table(result)

                table_block = render_template_string("""
                    <div class="message-row llm-msg">
                        <img src="{{ url_for('static', filename='img/bot-avatar.png') }}" class="avatar">
                        <div class="message-content">
                            <pre class="message-content llm">{{ query }}</pre>
                            <div class='query-result mt-3'>{{ table|safe }}</div>
                            <span class="msg-time">Just now</span>
                        </div>
                    </div>
                """, query=generated_query, table=result_html)

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
                query_escaped = html.escape(generated_query.strip())

                user_block = render_template_string("""
                    <div class="message-row user-msg">
                        <div class="message-content">{{ message }}</div>
                        <img src="{{ url_for('static', filename='img/user-avatar.png') }}" class="avatar">
                    </div>
                """, message=message)

                query_block = render_template_string("""
                    <div class="message-row llm-msg">
                        <img src="{{ url_for('static', filename='img/bot-avatar.png') }}" class="avatar">
                        <div class="message-content">
                            <pre class="message-content llm">{{ query }}</pre>
                            <form class="d-inline-block" method="POST">
                                <input type="hidden" name="query" value="{{ generated_query }}">
                                <input type="hidden" name="db_type" value="{{ db_type }}">
                                <input type="hidden" name="credentials" value="{{ credentials }}">
                                <input type="hidden" name="selected_db_id" value="{{ selected_db_id }}">
                                <button class="btn btn-sm btn-outline-light mt-2 run-query-btn" type="submit">
                                    <i class="fas fa-play"></i> Run Query
                                </button>
                            </form>
                            <span class="msg-time">Just now</span>
                        </div>
                    </div>
                """, query=query_escaped, db_type=db_type, credentials=credentials, selected_db_id=selected_db_id, generated_query=generated_query)

                chat_html += user_block + query_block

            if is_ajax:
                return jsonify({"chat_html": chat_html})

        except Exception as e:
            return jsonify({"chat_html": f"<div class='error'>Error: {str(e)}</div>"}), 500

    return render_template("chat.html", connections=connections, selected_db_id=selected_db_id)