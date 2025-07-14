import psycopg2
from psycopg2 import OperationalError
from src.core.logger import logging

def test_connection(config):
    try:
        conn = psycopg2.connect(
            host=config['host'],
            port=config['port'],
            user=config['username'],
            password=config['password'],
            dbname=config['name'],
            connect_timeout=5
        )
        logging.info("Connection successful")
        conn.close()
        return True, "Connection successful"
    except OperationalError as e:
        return False, str(e)
    
