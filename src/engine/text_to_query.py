"""
This module is responsible for taking in the natural language query from the user
and converting it into a database query based on the user's choice of database,
its metadata (schema, tables, fields), and the database type.
"""

import requests
import sys
import json

from src.core.exception import CustomException
from src.core.logger import logging


def generate_query_from_nl(nl_query: str, db_metadata: dict = {}, db_type: str = "generic", model="BahaSlama/llama3.1-finetuned:latest"):

    """
    Converts natural language query into database-specific query using a local LLM.

    Args:
        nl_query (str): Natural language input from the user.
        db_metadata (dict): Dictionary containing metadata about the database.
        db_type (str): Type of the database (e.g., 'mongodb', 'postgresql').
        model (str): The LLM model to use via Ollama.

    Returns:
        str: The generated database query string.
    """
    try:
        prompt_text = f"""
            You are an expert in writing database queries.

            Convert the following instruction into a valid {db_type.upper()} query:

            Instruction: {nl_query}

            Only return the query. No comments. No markdown.
            """

        payload = {
            'model': model,
            'prompt': prompt_text,
            'stream': False 
        }

        response = requests.post("http://localhost:11434/api/generate", json=payload)
        query = response.json()["response"].strip()
        return query

    except Exception as e:
        raise CustomException(e, sys)
