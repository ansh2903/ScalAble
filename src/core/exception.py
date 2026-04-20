import sys

def get_error_message(error: Exception) -> str:
    """Extracts detailed information from the exception traceback."""
    _, _, exc_tb = sys.exc_info()
    
    if exc_tb is None:
        return str(error)
        
    file_name = exc_tb.tb_frame.f_code.co_filename
    line_number = exc_tb.tb_lineno
    
    error_message = (
        f"Error in [{file_name}] "
        f"at line [{line_number}]: "
        f"{str(error)}"
    )
    return error_message

class CustomException(Exception):
    def __init__(self, error_message: Exception):
        """
        Takes the original exception and builds a detailed report.
        """
        # Call the parent Exception class
        super().__init__(str(error_message))
        
        # Capture the detailed context immediately
        self.detailed_message = get_error_message(error_message)

    def __str__(self):
        return self.detailed_message