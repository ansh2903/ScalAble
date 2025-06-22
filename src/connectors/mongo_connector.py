from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
from urllib.parse import quote_plus
import pandas as pd
import os, sys
from src.core.exception import CustomException
from src.core.logger import logging

load_dotenv()

class MongoDBConnector:
    def __init__(self, config=None):
        self.client = MongoClient(uri, server_api=ServerApi('1'))

    def list_databases(self):
        return self.client.list_database_names()

    def list_collections(self, db_name):
        return self.client[db_name].list_collection_names()

    def run_query(self, query: dict):
        return pd.DataFrame(list(self.collection.find(query)))
