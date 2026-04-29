from flask import render_template, request, session, redirect, url_for, flash
from spore._routes.utils import generate_blueprint
from spore._utils import encrypt_creds, is_running_in_docker
from spore._connectors.connector import DatabaseConnector
from spore._config.settings import VENDOR_CONFIG
from datetime import datetime
from spore._logger import logging
import os
import tempfile

connections_blueprint = generate_blueprint('connections')

# Connections management (add, edit, delete)
@connections_blueprint.route('/connections', methods=['GET','POST'])
def connections():
    try:
        connections = session.get("connections", [])
        no_of_connections = len(connections) or 0
        return render_template('pages/connections.html', connections=connections, no_of_connections=no_of_connections)
    except Exception as e:
        logging.error(f"Error loading connections: {str(e)}")
        return render_template('pages/error.html', error_message="An error occurred while loading the connections.")

@connections_blueprint.route('/connections/new/<vendor>', methods=['GET', 'POST'])
def add_new_connection(vendor):
    try:
        db = VENDOR_CONFIG.get(vendor)
        if not db:
            flash(f"Unsupported database type: {vendor}", "error")
            return redirect(url_for("connections.add_new_connection", vendor=vendor))
        
        template_path = f'partials/db/{db.get("connection_type")}.html'
        return render_template(template_path, vendor=vendor, default_port=db.get("default_port"), has_schema=db.get("has_schema"), schema_default=db.get("schema_default"))
    
    except Exception as e:
        logging.error(f"Template for {vendor} not found: {str(e)}")
        return "<p class='text-red-500 text-xs p-10 text-center font-bold'>Coming Soon: Configuration for this database.</p>"
    
@connections_blueprint.route('/test-connection', methods=['POST'])
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

@connections_blueprint.route('/connections/new', methods=['GET', 'POST'])
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
                return redirect(url_for("connections.new_connector"))

            # [Fetch Metadata Logic Goes Here]
            m_status, metadata = db_manager.fetch_metadata()
            print(metadata)
            if not m_status:
                flash(f"Metadata fetch failed: {metadata}", "error")
                return redirect(url_for("connections.new_connector"))

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
            return redirect(url_for("connections.connections"))

        except Exception as e:
            flash(f"System Error: {str(e)}", "error")
            logging.error(f"System Error during connection: {str(e)}")
            return redirect(url_for("connections.new_connector"))
            
        finally:
            for temp_path in temp_file_paths:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception as cleanup_error:
                    logging.warning(f"Failed to clean up temp file {temp_path}: {cleanup_error}")

    return render_template("connections_new.html")

# Delete database
@connections_blueprint.route('/delete-database/<int:db_id>', methods=['GET'])
def delete_database(db_id):
    try:
        connections = session.get("connections", [])
        connections = [conn for conn in connections if conn.get("id") != db_id]
        for index, conn in enumerate(connections, start=1):
            conn["id"] = index

        session["connections"] = connections
        flash("Database deleted successfully.", "success")
        return redirect(url_for('connections.connections'))
    except Exception as e:
        flash(f"Error deleting database: {str(e)}", "error")
        return redirect(url_for('connections.connections'))


# Edit database
@connections_blueprint.route('/edit-database/<int:db_id>', methods=['GET','POST'])
def edit_database(db_id):
    connections = session.get("connections", [])
    conn = next((c for c in connections if c['id'] == db_id), None)

    if not conn:
        flash("Database not found.", "error")
        return redirect(url_for('connections.connections'))

    if request.method == 'POST':
        updated_data = request.form.to_dict()
        updated_data['id'] = db_id
        updated_data['created_at'] = conn.get('created_at')
        connections = [updated_data if c['id'] == db_id else c for c in connections]
        session['connections'] = connections
        flash('Database updated', 'success')

        print(connections)
        return redirect(url_for('connections.connections'))

    return render_template('edit_database.html', conn=conn)

