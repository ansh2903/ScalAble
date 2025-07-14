'''
This module is responsible for executing the query generated(based on
which database the user chose) by the model onto the database
'''

import pandas as pd
from pymongo import MongoClient
from pymongo.server_api import ServerApi

def run_mongo_query(config, mongo_query):
    """
    Execute a MongoDB query and return the results as a DataFrame.
    :param config: dict with keys 'uri', 'database', 'collection'
    :param mongo_query: dict representing the MongoDB query
    :return: pandas.DataFrame with the query results
    """
    client = MongoClient(config['uri'], server_api=ServerApi("1"))
    db = client[config['database']]
    collection = db[config['collection']]
    cursor = collection.find(mongo_query)
    data = list(cursor)
    if data and '_id' in data[0]:
        for doc in data:
            doc.pop('_id', None)
    return pd.DataFrame(data)