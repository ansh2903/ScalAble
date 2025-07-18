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


def generate_query_from_nl(nl_query: str, db_type, db_metadata: dict = {}, model="qwen2.5-coder:7b"):

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
        You are a professional {db_type} query generation expert. Your job is to convert natural language into executable {db_type} queries.

        Below is metadata about the user's database (tables, columns, etc.):
        {db_metadata}

        ---

        User Query:
        {nl_query}

        ---

        Strict Instructions:
        - ONLY return the final executable query (no explanations, no markdown, no comments).
        - Do NOT wrap the query in triple backticks.
        - Do NOT prefix with language (like "```sql" or "MongoDB query:").
        - Do NOT add any explanation, text, natural language, or notes.
        - Your entire response should be a single query string.

        Examples:
        Input: "Get first 5 rows from employee table"
        Output: SELECT * FROM employee LIMIT 5;

        Input: "Show employees with age > 30"
        Output: SELECT * FROM employee WHERE age > 30;

        Input: "Fetch documents with status 'active'"
        Output: db.collection.find({{ status: "active" }})

        If unsure, return an empty string.

        Now respond with the query only:
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
