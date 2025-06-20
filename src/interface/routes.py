from flask import Blueprint, render_template, request
from src.pipeline.query_pipeline import process_query_pipeline
from src.core.exception import CustomException
from src.core.logger import logging

interface_blueprint = Blueprint('interface', __name__)

logging.INFO("Initializing the interface blueprint for handling routes.")
@interface_blueprint.route('/')
def index():
    return render_template('index.html')

logging.INFO("Defining the index route for the interface blueprint.")
@interface_blueprint.route('/run_query', methods=['POST'])
def run_query():
    try:
        db_config = {
            'host': request.form.get('host'),
            'port': int(request.form.get('port')),
            'database': request.form.get('database'),
            'collection': request.form.get('collection')
        }

        natural_query = request.form.get('nl_query')

        result_df, chart_html = process_query_pipeline(db_config, natural_query)

        logging.INFO("Query processed successfully, rendering result page.")
        return render_template('result.html',
                               table=result_df.to_html(classes = 'table table-bordered'),
                               chart=chart_html,)
    except Exception as e:
        raise CustomException(f"An error occurred while processing the query: {str(e)}") from e