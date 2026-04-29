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
    """
    Takes the original exception and builds a detailed report.
    """

    def __init__(self, error: Exception):
        super().__init__(str(error))
        self.detailed_message = get_error_message(error)

    def __repr__(self):
        return f"{self.__class__.__name__}(message='{self.detailed_message}')"

    def __str__(self):
        return self.detailed_message