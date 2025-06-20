import requests
import sys
import ast

from src.core.exception import CustomException
from src.core.logger import logging

def generate_mongo_query_from_nl(nl_query: str, model="huihui_ai/deepseek-r1-abliterated:8b"):
    try:
        prompt_text = f"""
            You are a MongoDB expert.

            Convert the following natural language instruction to a MongoDB query in Python dictionary format.

            ONLY output the dictionary. DO NOT explain anything. DO NOT use markdown. DO NOT prefix or suffix the answer.

            Instruction: {nl_query}
            """
        payload = {
            'model': model,
            'prompt': prompt_text,
            'stream': False 
        }
        logging.info(f"Generating MongoDB query from natural language: {nl_query}")

        response = requests.post("http://localhost:11434/api/generate", json=payload)
        result = response.json()

        # Clean up and parse
        text = result["response"].strip()
        # If markdown code block accidentally added, remove it
        if text.startswith("```"):
            text = text.strip("```").split("\n")[-1]

        # Eval to convert string to dict
        mongo_query = eval(text)
        return mongo_query

    except Exception as e:
        raise CustomException(e,sys)
    