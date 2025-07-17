from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for, flash
import importlib
from src.core.utils import get_connection_by_id
from src.engine.text_to_query import generate_query_from_nl
from datetime import datetime
import html

from src.core.exception import CustomException
from src.core.logger import logging

interface_blueprint = Blueprint('interface', __name__)

# Landing page
@interface_blueprint.route('/')
def index():
    return render_template('index.html')

# Home page (for authenticated user)
@interface_blueprint.route('/home')
def home():
    user = session.get('user')
    databases = session.get('connections', []) if user else []
    return render_template('home.html', user=user, databases=databases)

# All connections
@interface_blueprint.route('/connections')
def connections():
    connections = session.get("connections", [])
    return render_template('connections.html', connections=connections)

# Add new database
@interface_blueprint.route('/add-database', methods=['GET', 'POST'])
def add_database():
    if request.method == 'POST':
        form_data = request.form.to_dict()
        print(form_data)
        db_type = form_data.get("db_type")

        try:
            connector_module = importlib.import_module(f"connectors.{db_type}")

            # Step 1: Test connection
            status, msg = connector_module.test_connection(form_data)
            if not status:
                flash(f"Connection failed: {msg}", "error")
                return redirect(url_for("interface.add_database"))

            # Step 2: Fetch metadata (connection = connection + metadata)
            metadata_status, metadata = connector_module.connection(form_data)
            if not metadata_status:
                flash(f"Metadata fetch failed: {metadata}", "error")
                return redirect(url_for("interface.add_database"))

            # Step 3: Store connection details + metadata
            form_data["id"] = len(session.get("connections", [])) + 1
            form_data["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            form_data["metadata"] = metadata  # 🔥 metadata embedded here

            connections = session.get("connections", [])
            connections.append(form_data)
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
    connections = session.get("connections", [])
    connections = [conn for conn in connections if conn.get("id") != db_id]
    session["connections"] = connections
    flash("Database deleted successfully.", "success")
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
        return redirect(url_for('interface.connections'))

    return render_template('edit_database.html', conn=conn)

# App settings
@interface_blueprint.route('/settings')
def settings():
    return render_template('settings.html')


@interface_blueprint.route('/chat', methods=['GET', 'POST'])
def chat():
    connections = session.get('connections', [])

    databases = [
        f"{conn.get('db_type', 'Unknown').capitalize()} - {conn.get('name', 'Unnamed')} (ID={conn.get('id', '?')})"
        for conn in connections
    ]
    print(databases)

    result_output = None
    selected_db_id = None
    message = ""

    if request.method == 'POST':
        message = request.form.get('message')
        selected_db_id = request.form.get('selected_db_id')
        print(selected_db_id)

        selected_conn = next(
            (conn for conn in connections if str(conn['id']) == str(selected_db_id)), None
        )

        if selected_conn:
            metadata = selected_conn.get('metadata')
            print('metadata: ', metadata)
            db_type = selected_conn.get("db_type")
            
            try:
                generated_response = generate_query_from_nl(message, db_type, metadata)
                safe_query = html.escape(generated_response.strip())
                result_output = f"""
                <div>
                    <pre class="message-content llm">{safe_query}</pre>
                    <form method="POST" action="{url_for('interface.chat')}" style="margin-top: 0.5rem;">
                        <input type="hidden" name="generated_query" value="{safe_query}">
                        <input type="hidden" name="selected_db_id" value="{selected_db_id}">
                        <input type="hidden" name="message" value="{html.escape(message)}">
                        <button class="btn btn-sm btn-outline-light" type="submit" name="run_query" value="1">
                            <i class="fas fa-play"></i> Run Query
                        </button>
                    </form>
                </div>
                """

            except Exception as e:
                flash(f"Error: {str(e)}", "error")

    return render_template('chat.html',
                           databases=databases,
                           connections=connections,
                           selected_db_id=selected_db_id,
                           message=message,
                           result_output=result_output)

