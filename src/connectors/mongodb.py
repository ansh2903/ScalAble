from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import sys
from collections import defaultdict

from src.core.exception import CustomException
from src.core.logger import logging


def test_connection(config):
    try:
        uri = config["uri"]
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.server_info()
        logging.info("MongoDB connection successful")
        return True, "Connection successful"
    except ConnectionFailure as e:
        return False, CustomException(sys, str(e))


def metadata(config):
    try:
        uri = config["uri"]
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)

        db_metadata = {
            "db_type": "mongodb",
            "database_count": 0,
            "databases": {},
            "table_count": 0,
            "total_columns": 0
        }

        database_names = client.list_database_names()
        db_metadata["database_count"] = len(database_names)

        for db_name in database_names:
            db = client[db_name]
            db_entry = {
                "tables": {},
                "table_count": 0,
                "total_columns": 0
            }

            collection_names = db.list_collection_names()
            db_entry["table_count"] = len(collection_names)
            db_metadata["table_count"] += len(collection_names)

            for collection_name in collection_names:
                collection = db[collection_name]

                # Row count
                row_count = collection.estimated_document_count()

                # First and last _id
                first_pk, last_pk = None, None
                try:
                    first_doc = collection.find({}, {"_id": 1}).sort("_id", 1).limit(1)
                    last_doc = collection.find({}, {"_id": 1}).sort("_id", -1).limit(1)
                    first_pk = str(next(first_doc, {}).get("_id"))
                    last_pk = str(next(last_doc, {}).get("_id"))
                except Exception:
                    pass

                # Column detection & type inference
                field_types = defaultdict(set)
                try:
                    for doc in collection.find().limit(20):
                        for k, v in doc.items():
                            field_types[k].add(type(v).__name__)
                except Exception:
                    pass

                # Flatten field types to single type if possible
                final_types = {
                    k: list(v)[0] if len(v) == 1 else list(v)
                    for k, v in field_types.items()
                }

                column_names = list(final_types.keys())
                db_entry["total_columns"] += len(column_names)
                db_metadata["total_columns"] += len(column_names)

                # Storage size
                try:
                    stats = db.command("collstats", collection_name)
                    size_bytes = stats.get("size", 0)
                    size_pretty = f"{round(size_bytes / 1024, 2)} KB"
                except Exception:
                    size_bytes = 0
                    size_pretty = "0 KB"

                # Build metadata for this collection
                db_entry["tables"][collection_name] = {
                    "columns": column_names,
                    "column_types": final_types,
                    "row_count": row_count,
                    "size_bytes": size_bytes,
                    "size_pretty": size_pretty,
                    "primary_keys": ["_id"],
                    "row_bounds": {
                        "first_pk": first_pk,
                        "last_pk": last_pk
                    },
                    "unique_keys": ["_id"],
                    "candidate_keys": ["_id"]
                }

            db_metadata["databases"][db_name] = db_entry

        client.close()
        return True, db_metadata

    except ConnectionFailure as e:
        return False, CustomException(sys, str(e))
    except Exception as e:
        return False, CustomException(sys, str(e))
