'''
This module is responsible for, based on the user's choice of database selected
using the frontend, provide a solution to establish a connection
to the database
'''

import importlib
from src.core.utils import decrypt_creds
from src.core.logger import logging

class DatabaseConnector:
    def __init__(self, raw_data):
        self.raw = raw_data
        self.db_type = raw_data.get('db_type')
        self.strategy = raw_data.get('strategy')
        self.sslmode = raw_data.get('sslmode', None)
        self.creds = raw_data.get('credentials')
        self.connector = self._load_connector()

    def _load_connector(self):
        try:
            return importlib.import_module(f"src.connectors.{self.db_type}")
        except ModuleNotFoundError:
            raise Exception(f"Connector for '{self.db_type}' not implemented.")

    def test(self):
        status, msg = self.connector.test_connection(self.raw)
        logging.info(f"Connection test for {self.db_type} returned status: {status}, message: {msg}")
        return status, msg

    def fetch_metadata(self):
        status, metadata = self.connector.metadata(self.raw)
        logging.info(f"Metadata fetch for {self.db_type} returned status: {status}, metadata: {metadata}")
        return status, metadata
    
    def view_data_extraction(self, stream_name, query, memory_ceiling, batch_row_size):
        try:
            logging.info('Initiating data ingestion')
            
            creds = decrypt_creds(self.creds)
            status, path = self.connector.data_extraction(stream_name=stream_name, query=query, config=creds, memory_ceiling=memory_ceiling, batch_row_size=batch_row_size)

            return status, path

        except Exception as e:
            pass
    
    def preview_execute(self, query):
        try:
            logging.info(f"Generating preview of '{query}' on {self.db_type}")
            creds = decrypt_creds(self.creds)
            for chunk in self.connector.preview_execute(query, creds):
                 yield chunk
                 
        except Exception as e:
            logging.error(f"Execution failed: {str(e)}")
            yield {"type": "error", "content": f"Couldn't Execute {query} on {self.db_type}. Error: {str(e)}"}