"""
Structured logging configuration with rotating file handler and console output.
"""
import os
import logging
import logging.handlers
from config.settings import settings


def setup_logging():
    """Configure application-wide logging."""
    # Ensure log directory exists
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter(settings.LOG_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Rotating file handler (5MB, keep 5 backups)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        root_logger.warning(f"Could not create log file: {e}")

    # Quiet noisy libraries
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Named loggers for each subsystem
    for name in ["bot", "browser", "booking", "cache", "monitor", "automation"]:
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    root_logger.info("Logging initialized [level=%s]", settings.LOG_LEVEL)
