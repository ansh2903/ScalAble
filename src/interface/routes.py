from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for, flash
import importlib
from src.pipeline.query_pipeline import process_query_pipeline

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

# All connections (like /connections)
@interface_blueprint.route('/connections')
def connections():
    connections = session.get("connections", [])
    return render_template('connections.html', connections=connections)

# Add new database (GET/POST form)
@interface_blueprint.route('/add-database', methods=['GET', 'POST'])
def add_database():
    if request.method == 'POST':
        form_data = request.form.to_dict()
        db_type = form_data.get("db_type")

        try:
            # Dynamically import the correct connector module
            connector_module = importlib.import_module(f"connectors.{db_type}")
            status, msg = connector_module.test_connection(form_data)
        except ModuleNotFoundError:
            flash(f"Connector for '{db_type}' not implemented.", "error")
            return redirect(url_for("interface.add_database"))
        except Exception as e:
            flash(f"Error during connection test: {str(e)}", "error")
            return redirect(url_for("interface.add_database"))

        if status:
            form_data["id"] = len(session.get("connections", [])) + 1
            connections = session.get("connections", [])
            connections.append(form_data)
            session["connections"] = connections
            flash("Database connected and added!", "success")
            return redirect(url_for("interface.connections"))
        else:
            flash(f"Connection failed: {msg}", "error")
            return redirect(url_for("interface.add_database"))

    return render_template("connections_new.html")

# App settings
@interface_blueprint.route('/settings')
def settings():
    return render_template('settings.html')


# Chat page stub (to be built later)
@interface_blueprint.route('/chat')
def chat():
    return render_template('chat.html')

# Run natural language query
logging.info("Defining the index route for the interface blueprint.")
@interface_blueprint.route('/run_query', methods=['POST'])
def run_query():
    try:
        db_config = {
            'uri': request.form.get('uri'),
            'database': request.form.get('database'),
            'collection': request.form.get('collection')
        }

        natural_query = request.form.get('nl_query')

        result_df, chart_html = process_query_pipeline(db_config, natural_query)

        logging.info("Query processed successfully, rendering result page.")
        return render_template('result.html',
                               table=result_df.to_html(classes='table table-bordered'),
                               chart=chart_html)
    except Exception as e:
        raise CustomException(f"An error occurred while processing the query: {str(e)}") from e

