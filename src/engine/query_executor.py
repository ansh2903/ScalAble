'''
This module is responsible for executing the query generated(based on
which database the user chose) by the model onto the database
'''

import psycopg2

from src.core.exception import CustomException
from src.core.logger import logging

def run_query(db_type: str, credentials, query: str):
    logging.info("run_query() Invoked")

    if db_type == 'postgresql':
        logging.info("For database 'postgresql'")

        conn = psycopg2.connect(
            database=credentials['database'], user=credentials['username'],
            password=credentials['password'], host=credentials['host'],
            port=credentials['port']
        )
        logging.info("Connection established")

        cursor = conn.cursor()
        cursor.execute(query)

        logging.info("Query Executed")

        headers = [desc[0] for desc in cursor.description]  # <-- Column names
        results = cursor.fetchall()
        conn.commit()
        conn.close()
        logging.info("Cursor closed")

        logging.info("Done with run_query()")
        return [headers] + results


if __name__ == "__main__":
    pass