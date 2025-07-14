from pymongo import MongoClient
from pymongo.errors import PyMongoError

def test_connection(form_data):
    try:
        uri = form_data.get("uri")
        if not uri:
            return False, "No MongoDB URI provided."

        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        # Force a server check
        client.admin.command('ping')
        return True, "MongoDB connection successful."

    except PyMongoError as e:
        return False, str(e)
