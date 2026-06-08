from .db.postgresql import PostgreSQLSource
from .db.mysql import MySQLSource
from .db.mssql import MSSQLSource
from .db.sqlite import SQLiteSource
from .db.mongodb import MongoDBSource
from .warehouse.bigquery import BigQuerySource
from .warehouse.snowflake import SnowflakeSource
from .warehouse.redshift import RedshiftSource
from .warehouse.clickhouse import ClickHouseSource
from .warehouse.databricks import DatabricksSource
from .api.rest import RestAPISource
from .api.graphql import GraphQLAPISource
from .files.csv import CSVFileSource
from .files.excel import ExcelFileSource
from .files.json import JSONFileSource
from .files.parquet import ParquetFileSource

REGISTRY = {
    "postgresql": PostgreSQLSource,
    "mysql": MySQLSource,
    "mssql": MSSQLSource,
    "sqlite": SQLiteSource,
    "mongodb": MongoDBSource,
    "bigquery": BigQuerySource,
    "snowflake": SnowflakeSource,
    "redshift": RedshiftSource,
    "clickhouse": ClickHouseSource,
    "databricks": DatabricksSource,
    "rest_api": RestAPISource,
    "graphql_api": GraphQLAPISource,
    "csv_file": CSVFileSource,
    "excel_file": ExcelFileSource,
    "json_file": JSONFileSource,
    "parquet_file": ParquetFileSource,
}
