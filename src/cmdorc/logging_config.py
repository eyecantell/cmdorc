"""Optional logging configuration utilities for cmdorc."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

__all__ = ["setup_logging", "disable_logging", "get_log_file_path"]

_DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DETAILED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]"


def setup_logging(
    level: int | str = logging.INFO,
    *,
    console: bool = True,
    console_level: int | str | None = None,
    file: bool = False,
    log_dir: Path | str = ".cmdorc/logs",
    log_filename: str = "cmdorc.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    format: Literal["simple", "detailed"] = "simple",
    format_string: str | None = None,
    propagate: bool = True,
) -> logging.Logger:
    """
    Configure logging for the cmdorc library.

    Only affects cmdorc.* loggers - does not modify your application's logging.
    Safe to call multiple times (idempotent).

    Args:
        level: Minimum log level for cmdorc (default: INFO)
        console: Log to stderr (default: True)
        console_level: Console log level, defaults to `level`
        file: Log to rotating file (default: False)
        log_dir: Directory for log files (default: .cmdorc/logs)
        log_filename: Name of log file (default: cmdorc.log)
        max_bytes: Max size before rotation (default: 10MB)
        backup_count: Number of backup files (default: 5)
        format: "simple" or "detailed" (includes file:line)
        format_string: Custom format string (overrides `format` parameter)
        propagate: Whether logs propagate to root logger (default: True).
            Set to False to prevent double-logging if root has handlers.

    Returns:
        The configured cmdorc logger.

    Example:
        >>> from cmdorc import setup_logging
        >>> setup_logging(level="DEBUG", file=True)  # Enable debug + file logging
        >>> setup_logging(format_string="%(message)s")  # Custom format
    """
    logger = logging.getLogger("cmdorc")

    # Convert string levels
    if isinstance(level, str):
        level = getattr(logging, level.upper())
    if isinstance(console_level, str):
        console_level = getattr(logging, console_level.upper())
    if console_level is None:
        console_level = level

    logger.setLevel(level)

    # Choose format: custom > preset
    if format_string is not None:
        fmt = format_string
    else:
        fmt = _DETAILED_FORMAT if format == "detailed" else _DEFAULT_FORMAT
    formatter = logging.Formatter(fmt)

    # Remove existing handlers to ensure idempotency (except NullHandler)
    logger.handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]

    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler (rotating)
    if file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path / log_filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Control propagation to root logger
    logger.propagate = propagate

    return logger


def disable_logging() -> None:
    """
    Remove all cmdorc log handlers and reset to default state.

    Removes all handlers from the 'cmdorc' logger except NullHandler,
    including any handlers added directly by user code. If you need to
    preserve custom handlers, remove them before calling this function
    and re-add them afterward.

    Useful for tests or temporarily silencing cmdorc logs.
    After calling this, only the NullHandler remains (no output).
    """
    logger = logging.getLogger("cmdorc")
    logger.handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def get_log_file_path(
    log_dir: Path | str = ".cmdorc/logs", log_filename: str = "cmdorc.log"
) -> Path:
    """Return the path to the cmdorc log file (for users to find/send logs)."""
    return Path(log_dir) / log_filename
