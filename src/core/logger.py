import logging
import os
import sys
from datetime import datetime

logs_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(logs_dir, exist_ok=True)

LOG_FILE = f"{datetime.now().strftime('ScalAble_%Y%m%d_%H%M%S')}.log" # appname_YYYYMMDD_HHMMSS
LOG_FILE_PATH = os.path.join(logs_dir, LOG_FILE)

no_of_files = len(os.listdir(logs_dir))
if no_of_files > 10:
    files = sorted(os.listdir(logs_dir))
    for file in files[:-10]:
        os.remove(os.path.join(logs_dir, file))

file_handler = logging.FileHandler(LOG_FILE_PATH)
console_handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter("[ %(asctime)s ] %(filename)s: %(funcName)s: %(lineno)d - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)

if __name__ == "__main__":
    logging.info("Logger initialized successfully.")
    print(f"Logs will be saved to: {LOG_FILE_PATH}")
