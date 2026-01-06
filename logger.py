import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Ensure log directory exists
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
# Allow overriding log file name via environment (crucial for multi-process server/client)
log_filename = os.environ.get("LOG_FILENAME", "novelist.log")
LOG_FILE = os.path.join(LOG_DIR, log_filename)

# Default Format
FORMATTER = logging.Formatter(
    "%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def configure_logger(name: str = "novelist", level: int = logging.DEBUG) -> logging.Logger:
    """
    Get a configured logger with both File and Console handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent potential double-logging if function called multiple times
    if logger.handlers:
        return logger

    # 1. Console Handler (Standard Output) - Cleaner, less verbose
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s")) # Minimal for console
    logger.addHandler(console_handler)

    # 2. File Handler (Detailed, Rotating) - The "Black Box" recorder
    # Rotates at 5MB, keeps 3 backups
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(FORMATTER)
    logger.addHandler(file_handler)

    return logger

# Create the main global logger
logger = configure_logger()
