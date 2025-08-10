'''
This module is responsible for executing the query generated(based on
which database the user chose) by the model onto the database
'''
import psycopg2 #postgresql
from psycopg2 import OperationalError, DatabaseError

from pymongo import MongoClient #mongodb
import pyodbc #mssql

import sys

from src.core.exception import CustomException
from src.core.logger import logging

def run_query(db_type: str, credentials, query: str, database: None = None, collection: None = None):
    logging.info("run_query() Invoked")

    # PostgreSQL
    if db_type == 'postgresql':
        try:
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

            if cursor.description:
                headers = [desc[0] for desc in cursor.description]  # <-- Column names
                results = cursor.fetchall()
                conn.commit()
                conn.close()
                logging.info("Cursor closed")

                return [headers] + results
            else:
                conn.commit()
                return [['Message'],['Query executed successfully']]
        
        except OperationalError as e:
            logging.error(f"OperationalError: {e}")
            return {"error": str(CustomException(sys, e))}
        
        except DatabaseError as e:
            logging.error(f"DatabaseError: {e}")
            return {"error": str(CustomException(sys, e))}
        
        except Exception as e:
            return {"error": str(CustomException(sys, e))}

    
    # MongoDB
    if db_type == 'mongodb':
        try:
            logging.info("for database 'mongodb'")
            client = MongoClient(credentials['uri'])
            db = client[database]
            collection = db[collection]
            
            cursor = query

            for doc in cursor:
                print(doc)
            
            return doc

        except Exception as e:
            raise CustomException(sys, e)
    
    # MSSQL
    if db_type == 'mssql':
        try:
            logging.info("for database 'mssql")
            conn_str = (
                f"Driver={credentials['driver']};"
                f"Server={credentials['server']};"
                f"Database={credentials['database']};"
                f"Trusted_Connection=yes;"
                f"Connection Timeout=5;"
            )
            conn = pyodbc.connect(conn_str)
            logging.info('Connected to database mssql')
            cursor = conn.cursor()
            cursor.execute(query)
            logging.info("Query Executed")
            if cursor.description:
                headers = [desc[0] for desc in cursor.description]  # <-- Column names
                results = cursor.fetchall()
                conn.commit()
                conn.close()
                logging.info("Cursor closed")
                
                return [headers] + results
            else:
                cursor.commit()
                return [['Message'], ['Query executed successfully']]

        except Exception as e:
            raise CustomException(sys, e)
        
if __name__ == "__main__":
    pass