from pymongo import MongoClient
from pymongo.errors import PyMongoError
import sys

from src.core.exception import CustomException
from src.core.logger import logging

def test_connection(form_data):
    try:
        uri = form_data.get("uri")
        if not uri:
            return False, "No MongoDB URI provided."

        logging.info('Connecting to MongoDB')
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
        logging.info('MongoDB Connection successful')
        return True, "MongoDB connection successful."

    except PyMongoError as e:
        return False, CustomException(sys, str(e))

def connection(form_data):
    try:
        uri = form_data.get('uri')
        if not uri:
            return False, "No MongoDB URI provided."
        
        logging.info('Connecting to MongoDB')
        client = MongoClient(uri, serverSelectedTimeoutMS=3000)
        client.admin.command('ping')
        logging.info('MongoDB Connection successful.')

        db_name = form_data.get('database')
        if not db_name:
            return False, "Database name not provided."

        db = client[db_name]
        collections = db.list_collection_names()

        db_metadata = {
            "db_type": "mongodb",
            "database": db_name,
            "collections": {}
        }

        for collection_name in collections:
            collection = db[collection_name]
            
            # Get sample document
            sample_doc = collection.find_one()
            sample_doc = sample_doc if sample_doc else {}

            # Get field names
            fields = list(sample_doc.keys())

            db_metadata["collections"][collection_name] = {
                "fields": fields,
                "sample": sample_doc
            }

        return True, db_metadata

    except PyMongoError as e:
        return False, CustomException(sys, str(e))