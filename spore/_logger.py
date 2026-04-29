import logging
import os
from logging.handlers import TimedRotatingFileHandler
from spore._config.settings import settings

logs_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(logs_dir, exist_ok=True)
log_path = os.path.join(logs_dir, "spore.log")

def get_logger(name="spore"):
    logger = logging.getLogger(name)
    
    if logger.hasHandlers():
        return logger

    file_handler = TimedRotatingFileHandler(
        log_path, when="D", interval=1, backupCount=10, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter(
        "[ %(asctime)s ] %(name)s | %(levelname)-8s | %(filename)s:%(lineno)d - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.setLevel(logging.INFO if not settings.DEBUG else logging.DEBUG)
    logger.propagate = False 
    
    return logger

logging = get_logger("spore")