import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

# Global settings and configuration for the application
class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY", "scalable_secret_key")
    SQLALCHEMY_URI = os.getenv("SQLALCHEMY_URI")
    DEBUG = os.getenv("DEBUG", "True") == "True"
    OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT")
    LMSTUDIO_ENDPOINT = os.getenv("LMSTUDIO_ENDPOINT")
    DEFAULT_MODEL = os.getenv("OLLAMA_LLM")
    APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
    APP_PORT = int(os.getenv("APP_PORT", 5000))

    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    
settings = Settings()

# Connector-specific configurations and utilities
VENDOR_CONFIG = {
    "postgresql": {"default_port": 5432,  "connection_type": "standard", "has_schema": True,  "schema_default": "public"},
    "mysql":      {"default_port": 3306,  "connection_type": "standard", "has_schema": False, "schema_default": None},
    "mariadb":    {"default_port": 3306,  "connection_type": "standard", "has_schema": False, "schema_default": None},
    "mssql":      {"default_port": 1433,  "connection_type": "standard", "has_schema": True,  "schema_default": "dbo"},
    "oracle":     {"default_port": 1521,  "connection_type": "standard", "has_schema": True,  "schema_default": None},
    "clickhouse": {"default_port": 9000,  "connection_type": "standard", "has_schema": True,  "schema_default": "default"},
    "redshift":   {"default_port": 5439,  "connection_type": "standard", "has_schema": True,  "schema_default": "public"},
    "mongodb":    {"default_port": 27017, "connection_type": "uri",      "has_schema": False, "schema_default": None},
    "sqlite":     {"default_port": None,  "connection_type": "file",     "has_schema": False, "schema_default": None},
    "bigquery":   {"default_port": None,  "connection_type": "bigquery", "has_schema": True,  "schema_default": None},
    "snowflake":  {"default_port": 443,   "connection_type": "snowflake","has_schema": True,  "schema_default": "PUBLIC"},
}

PROVIDER_FIELDS = {
    "ollama": ["model", "keep_alive", "num_predict", "num_ctx", "num_batch", "num_thread", "num_gpu", "top_k", "top_p", "temperature", "repeat_penalty", "use_mmap", "use_mlock"],
    "openai": ["model", "num_predict", "temperature", "top_p", "frequency_penalty", "presence_penalty"],
    "anthropic": ["model", "num_predict", "temperature", "top_p", "top_k"],
    "gemini": ["model", "num_predict", "temperature", "top_p", "top_k"],
    "lmstudio": ["model", "num_predict", "temperature", "top_p"],
}
