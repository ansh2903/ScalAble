from flask import session
import uuid
import json
import dill

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

