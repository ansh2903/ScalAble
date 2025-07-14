import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY", "scalable_secret_key")
    SQLALCHEMY_URI = os.getenv("SQLALCHEMY_URI")
    DEBUG = os.getenv("DEBUG", "True") == "True"
    OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT")
    DEFAULT_MODEL = os.getenv("OLLAMA_LLM")
    APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
    APP_PORT = int(os.getenv("APP_PORT", 5000))

settings = Settings()
