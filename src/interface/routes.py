from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for, flash
import importlib

from src.core.utils import get_connection_by_id
from src.engine.text_to_query import generate_query_from_nl
from src.engine.query_executor import run_query
from src.engine.visualizer import render_result_table

from datetime import datetime
import html
import json
import ast

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
        raw_form_data = request.form.to_dict()
        print("Raw Form Data:", raw_form_data)
        print('')

        db_type = raw_form_data.get("db_type")

        try:
            connector_module = importlib.import_module(f"connectors.{db_type}")

            # Step 1: Test connection using full form data
            status, msg = connector_module.test_connection(raw_form_data)
            if not status:
                flash(f"Connection failed: {msg}", "error")
                return redirect(url_for("interface.add_database"))

            # Step 2: Fetch metadata
            metadata_status, metadata = connector_module.connection(raw_form_data)
            if not metadata_status:
                flash(f"Metadata fetch failed: {metadata}", "error")
                return redirect(url_for("interface.add_database"))

            # Step 3: Build connection object with credentials nested
            connection_id = len(session.get("connections", [])) + 1
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            connection_object = {
                "id": connection_id,
                "created_at": created_at,
                "db_type": db_type,
                "name": raw_form_data.get("name"),  # Optional name/title for display
                "credentials": {
                    key: raw_form_data[key]
                    for key in raw_form_data
                    if key not in ["id", "created_at", "metadata"]
                },
                "metadata": metadata
            }

            print("\nFinal connection object:", connection_object)

            # Save in session
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
    
    # Prepare the available databases
    databases = {
        conn.get('id', '?'): {
            'name': conn.get('name', 'Unnamed'),
            'db_type': conn.get('db_type', 'Unknown').capitalize()
        }
        for conn in connections
    }

    result_output = ""
    selected_db_id = None
    message = ""

    if request.method == 'POST':
        form = request.form

        if "query" in form:
            # ✅ Run Query was submitted
            try:
                generated_query = form.get('query')
                db_type = form.get('db_type')
                print(generated_query)
                print('')
                print(db_type)

                credentials = form.get('credentials')
                update_credentials = ast.literal_eval(credentials)
                print(update_credentials)
                print(type(update_credentials))

                result = run_query(db_type=db_type, credentials=update_credentials, query=generated_query)
                print(result)
                print(type(result))
                print('')
                result_table_html = render_result_table(result)
                print(result_table_html)

                result_output = f"""
                    <div>
                        <pre class="message-content llm">{html.escape(generated_query)}</pre>
                        <div class='query-result mt-3'>{result_table_html}</div>
                    </div>
                """
            except Exception as e:
                result_output = f"<div class='error'>Error running query: {str(e)}</div>"
  
        else:
            # ✅ Generate Query was submitted
            try:
                message = form.get('message', '').strip()
                selected_db_id = form.get('selected_db_id')

                selected_conn = next((c for c in connections if str(c['id']) == str(selected_db_id)), None)
                if not selected_conn:
                    raise ValueError("Selected database connection not found.")

                credentials = selected_conn.get('credentials')
                metadata = selected_conn.get('metadata')
                db_type = selected_conn.get('db_type')       
                generated_response = generate_query_from_nl(message, db_type, metadata)
                safe_query = html.escape(generated_response.strip())

                result_output = f"""
                    <div>
                        <pre class="message-content llm">{safe_query}</pre>
                        <form method="POST" action="{url_for('interface.chat')}">
                            <input type="hidden" name="query" value="{generated_response}">
                            <input type="hidden" name="db_type" value="{html.escape(db_type)}">
                            <input type="hidden" name="credentials" value="{credentials}">
                            <button class="btn btn-sm btn-outline-light mt-2" type="submit">
                                <i class="fas fa-play"></i> Run Query
                            </button>
                        </form>
                    </div>
                """
            except Exception as e:
                result_output = f"<div class='error'>Error generating query: {str(e)}</div>"

    # Final page render
    return render_template(
        'chat.html',
        databases=databases,
        connections=connections,
        selected_db_id=selected_db_id,
        message=message,
        result_output=result_output
    )