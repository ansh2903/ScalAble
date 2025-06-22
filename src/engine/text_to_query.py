import requests
import sys
import ast

from src.core.exception import CustomException
from src.core.logger import logging

def generate_mongo_query_from_nl(nl_query: str, model="BahaSlama/llama3.1-finetuned:latest"):
    try:
        prompt_text = f"""
            You are a MongoDB expert.

            Convert the following natural language instruction to a MongoDB query in Python dictionary format.

            ONLY output the dictionary. DO NOT explain anything. DO NOT use markdown. DO NOT prefix or suffix the answer.

            Optimize and minimize.

            Give extras only when asked.

            Instruction: {nl_query}
            """
        payload = {
            'model': model,
            'prompt': prompt_text,
            'stream': False 
        }
        logging.info(f"Generating MongoDB query from natural language: {nl_query}")

        response = requests.post("http://localhost:11434/api/generate", json=payload)
        raw = response.json()["response"].strip()

        # Parse safely
        parsed = ast.literal_eval(raw)

        # Clean patterns
        if "$query" in parsed:
            parsed = parsed["$query"]

        if len(parsed) == 1:
            key = next(iter(parsed))
            if key.startswith("$") and isinstance(parsed[key], dict):
                inner = parsed[key]
                if len(inner) == 1:
                    field = next(iter(inner))
                    return {field: {key: inner[field]}}

        return parsed

    except Exception as e:
        raise CustomException(e,sys)
    
"""    $body = @{
     model = "BahaSlama/llama3.1-finetuned:latest"
     prompt = "ONLY output a valid Python dictionary. No explanations. MongoDB query for: Get all users where age is greater than 25."  
     stream = $false
 }
 
 Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post -Body ($body | ConvertTo-Json) -ContentType "application/json"
 """