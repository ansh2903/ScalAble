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
    return isinstance(query, str) and len(query.strip()) > 0
