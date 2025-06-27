from src.engine.text_to_query import generate_mongo_query_from_nl
from src.engine.query_executor import run_mongo_query
# from src.engine.visualizer import generate_plot

import pandas as pd
import sys

from src.core.exception import CustomException
from src.core.logger import logging

def process_query_pipeline(config: dict, natural_query: str):
    """
    Process the query pipeline to convert a natural language query into a MongoDB query,
    execute it, and return the results.
    
    :param config: Configuration dictionary containing database connection details.
    :param natural_query: Natural language query string.
    :return: DataFrame containing the query results or None if no data is returned.
    """
    try:
        # Convert natural language query to MongoDB query
        mongo_query = generate_mongo_query_from_nl(natural_query)
        
        # Execute the MongoDB query and get the results as a DataFrame
        df = run_mongo_query(config, mongo_query)
        
        # Check if the DataFrame is empty
        if df.empty:
            logging.info("No data returned from the query.")
            return None
        
        # Optionally generate a plot (currently commented out)
        # chart_html = generate_plot(df)
        
        # Return the DataFrame and optionally the chart HTML
        return df,  # chart_html
    
    except Exception as e:
        # Log the error with more details
        logging.error(f"Error processing query pipeline: {e}")
        raise CustomException(e, sys)