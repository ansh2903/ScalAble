from pymongo import MongoClient
from pymongo.errors import PyMongoError
from urllib.parse import urlparse
import sys

from src.core.exception import CustomException
from src.core.logger import logging


def test_connection(form_data):
    try:
        uri = form_data.get("uri")
        if not uri:
            return False, "No MongoDB URI provided."

        logging.info("Testing MongoDB connection...")
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
        logging.info("MongoDB connection successful.")
        return True, "MongoDB connection successful."

    except PyMongoError as e:
        return False, CustomException(sys, str(e))


def extract_db_name(uri: str) -> str:
    """
    Extracts the database name from the URI path (e.g. mongodb://.../dbname)
    """
    parsed = urlparse(uri)
    db_name = parsed.path.lstrip('/')  # Remove leading slash
    return db_name if db_name else None


def metadata(form_data):
    try:
        uri = form_data.get("uri")
        if not uri:
            raise ValueError("No MongoDB URI provided.")

        db_name = extract_db_name(uri)
        if not db_name:
            raise ValueError("Database name missing from URI.")

        logging.info(f"Connecting to MongoDB to fetch metadata for DB: {db_name}")
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")

        db = client[db_name]
        collections = db.list_collection_names()

        metadata = {
            "db_type": "mongodb",
            "database": db_name,
            "collections": {}
        }

        for collection_name in collections:
            collection = db[collection_name]
            sample_doc = collection.find_one() or {}
            fields = list(sample_doc.keys())

            metadata["collections"][collection_name] = {
                "fields": fields,
                "sample": sample_doc
            }

        logging.info(f"Metadata fetched for {db_name}: {list(metadata['collections'].keys())}")
        return metadata

    except Exception as e:
        logging.exception("Failed to fetch MongoDB metadata")
        raise CustomException(sys, str(e) or repr(e))



def connection(form_data):
    """
    Wrapper for metadata fetching with status.
    """
    try:
        meta = metadata(form_data)
        return True, meta
    except Exception as e:
        return False, e


def get_metadata(form_data):
    """
    Runtime version (e.g., for /chat) — just reuses connection().
    """
    status, result = connection(form_data)
    if status:
        return result
    else:
        raise result
