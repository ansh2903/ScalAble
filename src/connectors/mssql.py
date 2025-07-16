import pyodbc
import sys

from src.core.exception import CustomException
from src.core.logger import logging


def test_connection(config):
    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={config['host']},{config['port']};"
            f"DATABASE={config['database']};"
            f"UID={config['username']};"
            f"PWD={config['password']};"
            f"Connection Timeout=5;"
        )
        conn = pyodbc.connect(conn_str)
        logging.info("MSSQL connection successful")
        conn.close()
        return True, "Connection successful"
    except Exception as e:
        return False, CustomException(sys, str(e))


def connection(config):
    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={config['host']},{config['port']};"
            f"DATABASE={config['database']};"
            f"UID={config['username']};"
            f"PWD={config['password']};"
            f"Connection Timeout=5;"
        )
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        db_metadata = {
            "db_type": "mssql",
            "database": config['database'],
            "table_count": 0,
            "total_columns": 0,
            "tables": {}
        }

        # Get all user tables
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'dbo';
        """)
        tables = cursor.fetchall()
        db_metadata["table_count"] = len(tables)

        for (table_name,) in tables:
            # Columns and types
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = ?;
            """, table_name)
            columns_info = cursor.fetchall()
            column_names = [col[0] for col in columns_info]
            column_types = {col[0]: col[1] for col in columns_info}
            db_metadata["total_columns"] += len(column_names)

            # Row count
            cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            row_count = cursor.fetchone()[0]

            # Size (using sys.dm_db_partition_stats)
            cursor.execute(f"""
                SELECT SUM(reserved_page_count) * 8 
                FROM sys.dm_db_partition_stats 
                WHERE object_id = OBJECT_ID(?);
            """, table_name)
            size_kb = cursor.fetchone()[0] or 0
            size_bytes = size_kb * 1024
            size_pretty = f"{round(size_kb / 1024, 2)} MB"

            # Primary keys
            cursor.execute("""
                SELECT c.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu ON tc.CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
                JOIN INFORMATION_SCHEMA.COLUMNS c ON c.TABLE_NAME = ccu.TABLE_NAME AND c.COLUMN_NAME = ccu.COLUMN_NAME
                WHERE tc.TABLE_NAME = ? AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY';
            """, table_name)
            pk_columns = [row[0] for row in cursor.fetchall()]

            # First and last PK
            first_pk, last_pk = None, None
            if pk_columns:
                pk_col = pk_columns[0]
                cursor.execute(f"SELECT TOP 1 [{pk_col}] FROM [{table_name}] ORDER BY [{pk_col}] ASC")
                first = cursor.fetchone()
                first_pk = first[0] if first else None

                cursor.execute(f"SELECT TOP 1 [{pk_col}] FROM [{table_name}] ORDER BY [{pk_col}] DESC")
                last = cursor.fetchone()
                last_pk = last[0] if last else None

            # Unique keys
            cursor.execute("""
                SELECT c.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu ON tc.CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
                JOIN INFORMATION_SCHEMA.COLUMNS c ON c.TABLE_NAME = ccu.TABLE_NAME AND c.COLUMN_NAME = ccu.COLUMN_NAME
                WHERE tc.TABLE_NAME = ? AND tc.CONSTRAINT_TYPE = 'UNIQUE';
            """, table_name)
            unique_keys = [row[0] for row in cursor.fetchall()]

            # Foreign keys
            cursor.execute("""
                SELECT 
                    fk.COLUMN_NAME,
                    pk.TABLE_NAME AS foreign_table_name,
                    pk.COLUMN_NAME AS foreign_column_name
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE fk ON rc.CONSTRAINT_NAME = fk.CONSTRAINT_NAME
                JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE pk ON rc.UNIQUE_CONSTRAINT_NAME = pk.CONSTRAINT_NAME
                WHERE fk.TABLE_NAME = ?;
            """, table_name)
            foreign_keys = [{
                "column": row[0],
                "references_table": row[1],
                "references_column": row[2]
            } for row in cursor.fetchall()]

            # Normal form (stub)
            norm_form = "3NF (assumed)"

            db_metadata["tables"][table_name] = {
                "columns": column_names,
                "column_types": column_types,
                "row_count": row_count,
                "size_bytes": size_bytes,
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

    except Exception as e:
        return False, CustomException(sys, str(e))
