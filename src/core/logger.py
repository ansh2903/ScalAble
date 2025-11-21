import logging
import os
import sys
from datetime import datetime

logs_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(logs_dir, exist_ok=True)

LOG_FILE = f"{datetime.now().strftime('%m_%d_%Y_%H_%M_%S')}.log"
LOG_FILE_PATH = os.path.join(logs_dir, LOG_FILE)

file_handler = logging.FileHandler(LOG_FILE_PATH)
console_handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter("[ %(asctime)s ] %(lineno)d %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)

if __name__ == "__main__":
    logging.info("Logger initialized successfully.")
    print(f"Logs will be saved to: {LOG_FILE_PATH}")
