import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY", "scalable_secret_key")
    DEBUG = os.getenv("DEBUG", "True") == "True"
    OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT")
    DEFAULT_MODEL = os.getenv("OLLAMA_LLM")
    APP_HOST = os.getenv("APP_HOST")

settings = Settings()
