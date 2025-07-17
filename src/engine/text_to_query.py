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
            You are a professional {db_type} SQL expert. Your job is to help users query or understand their database using natural language.

            The following is the database metadata (tables, columns, sample values):
            {db_metadata}

            ---

            User Instruction:
            {nl_query}

            ---

            Instructions:
            1. If the user is asking to generate a query:
            - ONLY return the final SQL query.
            - Use correct SQL syntax for {db_type}.
            - Do NOT include explanations, comments, or markdown unless explicitly requested.
            - Ensure valid table and column references based on the metadata above.
            - Return in a <code> format, HTML friendly.

            2. If the user is asking a question or inspecting something (like "what is the schema", "list all tables", etc.):
            - Return a short, accurate natural language response.
            - If SQL is required, provide the relevant query but explain briefly and clearly.
            - Return in a Markdown format, HTML friendly

            Respond accordingly:
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
