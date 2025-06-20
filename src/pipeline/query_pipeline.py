from src.engine.text_to_query import generate_mongo_query_from_nl
from src.engine.query_executor import run_mongo_query
from engine.visualizer import generate_plot
import pandas as pd
import sys
from src.core.exception import CustomException
from src.core.logger import logging

def process_query_pipeline(config: dict, natural_query: str):
    try:
        mongo_query = generate_mongo_query_from_nl(natural_query)
        df = run_mongo_query(config, mongo_query)
        if df.empty:
            logging.info("No data returned from the query.")
            return None
        chart_html = generate_plot(df)
        return df, chart_html
    
    except Exception as e:
        raise CustomException(e, sys)
    
