"""
Structured logging setup.

Key design decisions:
- Uses Python's built-in logging (no extra dependencies)
- Filters out sensitive data (API keys, tokens)
- Consistent format across all modules
- Log level controlled via environment variable
"""

import logging
import re
import sys

from app.core.config import settings


class SensitiveDataFilter(logging.Filter):
    """
    Prevents accidental logging of secrets.

    Even if a developer accidentally logs a variable containing a token,
    this filter will redact it before it reaches the log output.
    """

    # Patterns that look like API keys or tokens
    SENSITIVE_PATTERNS = [
        re.compile(r"(AIza[0-9A-Za-z_-]{35})"),           # Google API key
        re.compile(r"(\d+:[A-Za-z0-9_-]{35,})"),          # Telegram bot token
        re.compile(r"(postgresql\+asyncpg://[^\s]+)"),     # Database URL with password
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in self.SENSITIVE_PATTERNS:
                record.msg = pattern.sub("[REDACTED]", record.msg)
        return True


def setup_logging() -> None:
    """Configure application-wide logging."""

    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    console_handler.addFilter(SensitiveDataFilter())

    # Clear existing handlers to avoid duplicates on reload
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger for a module.

    Usage:
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Task created", extra={"task_id": 123})
    """
    return logging.getLogger(name)
