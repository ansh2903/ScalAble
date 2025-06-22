from flask import Blueprint, render_template, jsonify, request, session
from src.pipeline.query_pipeline import process_query_pipeline

from pymongo.server_api import ServerApi
from pymongo import MongoClient
from src.connectors.mongo_connector import MongoDBConnector

from src.core.exception import CustomException
from src.core.logger import logging


interface_blueprint = Blueprint('interface', __name__)

# Home page
@interface_blueprint.route('/')
def index():
    return render_template('index.html')


@interface_blueprint.route("/list_databases", methods=["POST"])
def list_databases():
    try:
        uri = request.json["uri"]
        client = MongoClient(uri, server_api=ServerApi("1"))
        dbs = client.list_database_names()
        return jsonify({"databases": dbs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@interface_blueprint.route("/list_collections", methods=["POST"])
def list_collections():
    try:
        uri = request.json["uri"]
        db_name = request.json["database"]
        client = MongoClient(uri, server_api=ServerApi("1"))
        colls = client[db_name].list_collection_names()
        return jsonify({"collections": colls})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@interface_blueprint.route('/api/databases', methods=['POST'])
def get_databases():
    connector = MongoDBConnector()
    dbs = connector.list_databases()
    return jsonify(dbs)

@interface_blueprint.route('/api/collections/<db_name>', methods=['GET'])
def get_collections(db_name):
    connector = MongoDBConnector()
    collections = connector.list_collections(db_name)
    return jsonify(collections)

@interface_blueprint.route('/home')
def home():
    user = session.get('user')
    if user:
        user_data = users.get(user)
        databases = user_data.get('databases', [])
        return render_template('home.html', user=user, databases=databases)
    return render_template('home.html', user=None, databases=[])
