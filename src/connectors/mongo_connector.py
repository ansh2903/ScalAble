from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
from urllib.parse import quote_plus

import os, sys
from src.core.exception import CustomException
from src.core.logger import logging

load_dotenv()

MONGO_USER = quote_plus(os.getenv("MONGO_USER"))
MONGO_PASSWORD = quote_plus(os.getenv("MONGO_PASSWORD"))

uri = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@stockmarketdata.idn7b.mongodb.net/?retryWrites=true&w=majority&appName=StockMarketData"

client = MongoClient(uri, server_api = ServerApi('1'))

try:
    client.admin.command('ping')
    logging.info("MongoDB connection successful")
    print("MongoDB connection successful")
except Exception as e:
    logging.error("MongoDB connection failed")
    raise CustomException(e, sys)

