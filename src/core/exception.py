import sys
from src.core.logger import logging

def error_message_detail(error,error_detail:sys):
    _,_,exc_tb=sys.exc_info() #_ is the first argument, __ is the second argument, and exc_tb is the third argument and it is the traceback object which provides on while file the exception has occured and on which line
    file_name=exc_tb.tb_frame.f_code.co_filename
    error_message="Error occured in python script name [{0}] line number [{1}] error message[{2}]".format(
        file_name,exc_tb.tb_lineno,str(error)
    )
    return error_message

class CustomException(Exception):
    def __init__(self,error_message,error_detail:sys):
        super().__init__(error_message)
        self.error_message = error_message_detail(error_message,error_detail=error_detail)
    
    def __str__(self):
        return self.error_message
