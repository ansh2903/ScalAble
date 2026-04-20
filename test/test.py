from src.core.logger import logging
from src.core.exception import CustomException
import sys

def test_logic():
    try:
        # Simulate a typical "stupid user" or data error
        a = 1 / 0
    except Exception as e:
        # Create our detailed exception
        custom_err = CustomException(e)
        
        # Log the detailed message via your logger
        logging.error(custom_err)
        
        # Re-raise it if you want the app to stop
        raise custom_err

if __name__ == "__main__":
    test_logic()