import mysql.connector
from mysql.connector import Error
import sys

from src.core.exception import CustomException
from src.core.logger import logging

def test_connection(config):
    try:
        conn = mysql.connector.connect(
            host=config['host'],
            port=int(config['port']),
            user=config['username'],
            password=config['password'],
            database=config['database'],
            connection_timeout=5
        )
        logging.info("MySQL connection successful")
        conn.close()
        return True, "Connection successful"
    except Error as e:
        return False, CustomException(sys, str(e))


def metadata(config):
    try:
        conn = mysql.connector.connect(
            host=config['host'],
            port=int(config['port']),
            user=config['username'],
            password=config['password'],
            database=config['database'],
            connection_timeout=5
        )
        cursor = conn.cursor()

        db_metadata = {
            "db_type": "mysql",
            "database": config['database'],
            "table_count": 0,
            "total_columns": 0,
            "tables": {}
        }

        # Get tables
        cursor.execute("SHOW TABLES;")
        tables = [row[0] for row in cursor.fetchall()]
        db_metadata["table_count"] = len(tables)

        for table_name in tables:
            # Column names & types
            cursor.execute(f"SHOW COLUMNS FROM {table_name};")
            columns_info = cursor.fetchall()
            column_names = [col[0] for col in columns_info]
            column_types = {col[0]: col[1] for col in columns_info}
            db_metadata["total_columns"] += len(column_names)

            # Row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            row_count = cursor.fetchone()[0]

            # Storage size
            cursor.execute(f"""
                SELECT ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024, 2)
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s;
            """, (config['database'], table_name))
            size_kb = cursor.fetchone()[0] or 0
            size_pretty = f"{size_kb} KB"

            # Primary keys
            cursor.execute(f"""
                SELECT COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = 'PRIMARY';
            """, (config['database'], table_name))
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

            # Unique keys
            cursor.execute(f"""
                SELECT DISTINCT COLUMN_NAME
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND NON_UNIQUE = 0 AND INDEX_NAME != 'PRIMARY';
            """, (config['database'], table_name))
            unique_keys = [row[0] for row in cursor.fetchall()]

            # Foreign keys
            cursor.execute(f"""
                SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND REFERENCED_TABLE_NAME IS NOT NULL;
            """, (config['database'], table_name))
            foreign_keys = [{
                "column": row[0],
                "references_table": row[1],
                "references_column": row[2]
            } for row in cursor.fetchall()]

            # Normalization form (dummy placeholder)
            norm_form = "3NF (assumed)"

            db_metadata["tables"][table_name] = {
                "columns": column_names,
                "column_types": column_types,
                "row_count": row_count,
                "size_kb": size_kb,
                "size_pretty": size_pretty,
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

    except Error as e:
        return False, CustomException(sys, str(e))
    except Exception as e:
        return False, CustomException(sys, str(e))
