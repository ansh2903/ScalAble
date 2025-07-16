import psycopg2
from psycopg2 import OperationalError
import sys

from src.core.exception import CustomException
from src.core.logger import logging

def test_connection(config):
    try:
        conn = psycopg2.connect(
            host=config['host'],
            port=config['port'],
            user=config['username'],
            password=config['password'],
            dbname=config['database'],
            connect_timeout=5
        )
        logging.info("Connection successful")
        conn.close()
        return True, "Connection successful"
    except OperationalError as e:
        return False, CustomException(sys, str(e))
    
    
def connection(config):
    try:
        conn = psycopg2.connect(
            host=config['host'],
            port=config['port'],
            user=config['username'],
            password=config['password'],
            dbname=config['database'],
            connect_timeout=5
        )
        logging.info("PostgreSQL Connection successful")

        cursor = conn.cursor()

        db_metadata = {
            "db_type": "postgresql",
            "database": config['database'],
            "tables": {}
        }

        # Fetch all tables in public schema
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
        """)
        tables = cursor.fetchall()

        for (table_name,) in tables:
            # Get columns
            cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = %s;
            """, (table_name,))
            columns = [col[0] for col in cursor.fetchall()]

            # Get sample row
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 1;")
            sample = cursor.fetchone()
            sample_dict = dict(zip(columns, sample)) if sample else {}

            db_metadata["tables"][table_name] = {
                "fields": columns,
                "sample": sample_dict
            }

        cursor.close()
        conn.close()

        return True, db_metadata

    except OperationalError as e:
        return False, CustomException(sys, str(e))
    except Exception as e:
        return False, CustomException(sys, str(e))