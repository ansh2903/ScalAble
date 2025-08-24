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


def generate_query_from_nl(nl_query: str, db_type, db_metadata: dict = {}, model="qwen2.5-coder:1.5b"):

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
        You are a professional {db_type} query generation expert. Your job is to convert natural language into executable {db_type} queries and also behave like a friendly assistant.

        Below is metadata about the user's database (tables, columns, etc.):
        {db_metadata}

        ---

        User Query:
        {nl_query}

        ---

        ### Strict Instructions:
        - Always return output in **strict JSON**.
        - JSON must contain:
        - "query": (string) The final executable {db_type} query.  
            - MUST be a valid query string.  
            - Do NOT wrap in backticks or markdown.  
            - Do NOT include explanations, comments, or text.
            - SQL comments (`-- ...` or `/* ... */`) inside the query.
            - NUST ADD line breaks (`\n`) in the query wherever needed for readability.
  
        - "comment": (string) An optional **Markdown-formatted note** about the query, a friendly, human-style reply or explanation.
            - If you want to explain filtering, joins, or tips, do it here.  
            - Leave empty ("") if no comment is needed.  

        - Do NOT enclose the output in ('''json ''')
        - "query" is stricly for the executable query string. No explanations or comments should be included here.
        - "comment" is for any additional information or tips about the query or just as a chatbot like responses. The comment should feel Natural and helpful.
        - Do NOT include any other fields or metadata.

        ---

        Now return ONLY the JSON object as per the rules above:
        """

        payload = {
            'model': model,
            'prompt': prompt_text,
            'stream': False 
        }

        output = requests.post("http://localhost:11434/api/generate", json=payload)
        response = output.json()["response"].strip()

        if '```json' in response:
            response = response.strip('``` json')

        json_formatted_output = json.loads(response)

        query = json_formatted_output.get('query')
        comment = json_formatted_output.get("comment", "")

        return query, comment

    except Exception as e:
        raise CustomException(e, sys)
