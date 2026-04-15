import requests

from src.core.logger import logging

from flask import session, Response
from openpyxl import Workbook
from io import StringIO, BytesIO
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

import os
import ast
import csv
import uuid
import json
import dill

load_dotenv()

def _get_cipher():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY not set in environment")
    return Fernet(key.encode())

def encrypt_creds(creds):
    return _get_cipher().encrypt(str(creds).encode()).decode()

def decrypt_creds(encrypted_creds):
    try:
        print('bisnboshbubsrh')
        cipher = _get_cipher()
        decrypted_bytes = cipher.decrypt(encrypted_creds.encode())
        decrypted_str = decrypted_bytes.decode()
        print(f"Decrypted string: {decrypted_str}")
        return ast.literal_eval(decrypted_str)
    except Exception as e:
        # repr(e) will show you the CLASS of the error (e.g., InvalidToken)
        logging.error(f"Decryption failed specifically at: {repr(e)}")
        raise e
    
def generate_id():
    """
    Generate a unique identifier.
    
    Returns:
        str: A unique identifier as a string.
    """
    return str(uuid.uuid4()).hex

def is_valid_json(json_string):
    """
    Check if a string is a valid JSON.
    
    Args:
        json_string (str): The string to check.
        
    Returns:
        bool: True if the string is valid JSON, False otherwise.
    """
    try:
        json.loads(json_string)
        return True
    except ValueError:
        return False
    
def serialize_object(obj):
    """
    Serialize an object to a byte stream using dill.
    
    Args:
        obj: The object to serialize.
        
    Returns:
        bytes: The serialized object as a byte stream.
    """
    return dill.dumps(obj)


def validate_query(query: str) -> bool:
    '''
    Validate if the provided query is a non-empty string.
    
    Args:
        query (str): The query string to validate.
    
    Returns:
        bool: True if the query is a non-empty string, False otherwise.
    '''
    return isinstance(query, str) and len(query.strip()) > 0

def get_connection_by_id(conn_id):
    connections = session.get("connections", [])
    return next((conn for conn in connections if str(conn["id"]) == str(conn_id)), None)

def render_result_table(result):
    if not result:
        return "<p>No results found.</p>"
    
    if isinstance(result[0], (list, tuple)):
        headers = result[0]
        rows = result[1:]
    elif isinstance(result[0], (list, tuple)):
        headers = [f"Column {i+1}" for i in range(len(result[0]))]
        rows = result
    else:
        return "<p>Unknown result format.</p>"

    rows_count = 0
    column_count = len(headers)

    table_html = "<table class='table table-bordered table-sm table-hover table-striped'>"
    # Header row
    table_html += "<thead class='thead'><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>"
    # Data rows
    table_html += "<tbody>"
    for row in rows:
        table_html += "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        rows_count += 1

    table_html += "</tbody></table>"

    return table_html, rows_count, column_count

def downloadable_csv(raw_data):
    '''
    This function is used to create a downloadable csv file, this is done
    via data streaming to ensure that if the user wants to download a large
    amount of data, it doesn't overflow their ram and crash the system.
    '''
    def generator():
        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer)

        for row in raw_data:
            if isinstance(row, tuple):
                row = list(row)

            writer.writerow(row)
            yield csv_buffer.getvalue()
            csv_buffer.seek(0)
            csv_buffer.truncate(0)
                
    return Response(
        generator(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=data.csv"}
    )

def downloadable_excel(raw_data):
    '''
    This function is used to create a downloadable excel file for the frontend
    '''
    excel_buffer = BytesIO()
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()

    for row in raw_data:
        if isinstance(row, tuple):
            row = list(row)
        ws.append(row)

    wb.save(excel_buffer)
    excel_buffer.seek(0)

    return Response(
        excel_buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment;filename=data.xlsx"}
    )

def downloadable_json(raw_data):
    '''
    This function is used to create a downloadable json file for the frontend
    '''
    data = []

    for row in raw_data:
        if isinstance(row,tuple):
            row = list(row)
        data.append(row)

    headers = data[0]
    rows = data[1:]

    json_data = {
        'headers': headers,
        'rows': rows
    }

    data = json.dumps(json_data)
            
    return Response(
        data,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=data.json"}
    )

def SETTINGS_FILE():
    p = Path(__file__).parents[1] / "config" / "settings.json"
    return p

def load_settings():
    logging.info("inside load_settings()")
    if os.path.exists(SETTINGS_FILE()):
        with open(SETTINGS_FILE(), "r") as settings:
            logging.info("loaded settings")
            return json.load(settings)
    return {}

def save_settings(data):
    settings_path = SETTINGS_FILE()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as new_settings:
        json.dump(data, new_settings, indent=2)

def is_running_in_docker():
    """Check if the app is running inside a Docker container."""
    path = "/proc/self/cgroup"
    if os.path.exists("/.dockerenv"):
        return True
    if os.path.isfile(path):
        with open(path) as f:
            return any("docker" in line for line in f)
    return False

def model_ls(provider):
    if provider == "ollama":
        return ollama_model_ls()
    elif provider == "lmstudio":
        return lmstudio_model_ls()
    else:
        return []
    
def ollama_model_ls():
    OLLAMA_BASE = os.getenv('OLLAMA_BASE')
    OLLAMA_TAGS = (f'{OLLAMA_BASE}/api/tags')
    tag_data = requests.get(OLLAMA_TAGS).json()['models']

    models = []
    for row in tag_data:
        model = {
            'model':row.get('model'),
            'model_size':row.get('size'),
            'paramater_size': row['details'].get('parameter_size')
        }
        models.append(model)

    return models

def lmstudio_model_ls():
    LMSTUDIO_BASE = os.getenv('LMSTUDIO_BASE')
    LMSTUDIO_TAGS = (f'{LMSTUDIO_BASE}/api/v1/models')

    tag_data = requests.get(LMSTUDIO_TAGS).json()

    models = []
    print(tag_data)
    for unit in tag_data.get('models'):
        if unit.get('type') == 'llm':
            model = {
                'model':unit.get('key'),
                'model_size': int(unit.get('size_bytes')),
                'paramater_size': unit.get('params_string')
            }
            models.append(model)
    return models