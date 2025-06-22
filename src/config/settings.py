import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY", "scalable_secret_key")
    DEBUG = os.getenv("DEBUG", "True") == "True"
    OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate")
    DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "BahaSlama/llama3.1-finetuned:latest")

settings = Settings()
