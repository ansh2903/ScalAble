from src.connectors.mongo_connector import MongoDBConnector
import pandas as pd
import sys
from src.core.exception import CustomException
from src.core.logger import logging

def run_mongo_query(config:dict, query: dict) -> pd.DataFrame:
    try:
        connector = MongoDBConnector(config)
        logging.info(f"Running MongoDB query: {query}")
        return connector.run_query(query)
    except Exception as e:
        raise CustomException(e, sys)