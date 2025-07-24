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
    
def metadata(config):
    try:
        conn = psycopg2.connect(
            host=config['host'],
            port=config['port'],
            user=config['username'],
            password=config['password'],
            dbname=config['database'],
            connect_timeout=5
        )
        cursor = conn.cursor()

        db_metadata = {
            "db_type": "postgresql",
            "database": config['database'],
            "table_count": 0,
            "total_columns": 0,
            "tables": {}
        }

        # Get all table names in public schema
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
        """)
        tables = cursor.fetchall()
        db_metadata["table_count"] = len(tables)

        for (table_name,) in tables:
            # Get column names and types
            cursor.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = %s;
            """, (table_name,))
            columns_info = cursor.fetchall()
            column_names = [col[0] for col in columns_info]
            column_types = {col[0]: col[1] for col in columns_info}
            db_metadata["total_columns"] += len(column_names)

            # Row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            row_count = cursor.fetchone()[0]

            # Table size
            cursor.execute("SELECT pg_total_relation_size(%s);", (table_name,))
            size_bytes = cursor.fetchone()[0]

            # Storage size (formatted)
            cursor.execute("SELECT pg_size_pretty(pg_total_relation_size(%s));", (table_name,))
            readable_size = cursor.fetchone()[0]

            # Primary keys
            cursor.execute("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s::regclass AND i.indisprimary;
            """, (table_name,))
            pk_columns = [row[0] for row in cursor.fetchall()]

            # First and last PK values
            first_pk, last_pk = None, None
            if pk_columns:
                pk_col = pk_columns[0]
                cursor.execute(f"SELECT {pk_col} FROM {table_name} ORDER BY {pk_col} ASC LIMIT 1;")
                first = cursor.fetchone()
                first_pk = first[0] if first else None

                cursor.execute(f"SELECT {pk_col} FROM {table_name} ORDER BY {pk_col} DESC LIMIT 1;")
                last = cursor.fetchone()
                last_pk = last[0] if last else None

            # Unique constraints
            cursor.execute("""
                SELECT a.attname
                FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'u' AND t.relname = %s;
            """, (table_name,))
            unique_keys = [row[0] for row in cursor.fetchall()]

            # Foreign keys
            cursor.execute("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM 
                    information_schema.table_constraints AS tc 
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                WHERE constraint_type = 'FOREIGN KEY' AND tc.table_name = %s;
            """, (table_name,))
            foreign_keys = [{
                "column": row[0],
                "references_table": row[1],
                "references_column": row[2]
            } for row in cursor.fetchall()]

            # Dummy normalization form stub (optional real analysis later)
            norm_form = "3NF (assumed)"

            # Add to metadata
            db_metadata["tables"][table_name] = {
                "columns": column_names,
                "column_types": column_types,
                "row_count": row_count,
                "size_bytes": size_bytes,
                "size_pretty": readable_size,
                "primary_keys": pk_columns,
                "row_bounds": {
                    "first_pk": first_pk,
                    "last_pk": last_pk
                },
                "unique_keys": unique_keys,
                "foreign_keys": foreign_keys,
                "candidate_keys": list(set(pk_columns + unique_keys)),
                "normalized_form": norm_form
            }

        cursor.close()
        conn.close()
        return True, db_metadata

    except OperationalError as e:
        return False, CustomException(sys, str(e))
    except Exception as e:
        return False, CustomException(sys, str(e))
