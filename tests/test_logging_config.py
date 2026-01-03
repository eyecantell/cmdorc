"""Tests for logging configuration utilities."""

import logging
from pathlib import Path

import pytest

from cmdorc.logging_config import disable_logging, get_log_file_path, setup_logging


@pytest.fixture(autouse=True)
def reset_cmdorc_logger():
    """Reset cmdorc logger to default state after each test."""
    yield
    # Cleanup: remove all handlers except NullHandler and reset state
    logger = logging.getLogger("cmdorc")
    logger.handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def test_setup_logging_default():
    """Test default setup: console only, INFO level."""
    logger = setup_logging()

    assert logger.name == "cmdorc"
    assert logger.level == logging.INFO
    assert logger.propagate is True

    # Should have StreamHandler + NullHandler
    handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert handlers[0].level == logging.INFO


def test_setup_logging_with_file(tmp_path):
    """Test file logging with rotation."""
    log_dir = tmp_path / "logs"
    logger = setup_logging(level="DEBUG", file=True, log_dir=log_dir)

    # Should have both StreamHandler and RotatingFileHandler
    handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(handlers) == 2

    handler_types = {type(h).__name__ for h in handlers}
    assert "StreamHandler" in handler_types
    assert "RotatingFileHandler" in handler_types

    # Check log file created
    log_file = log_dir / "cmdorc.log"
    assert log_file.parent.exists()


def test_setup_logging_idempotent(tmp_path):
    """Test calling setup_logging twice doesn't duplicate handlers."""
    log_dir = tmp_path / "logs"

    # First call
    setup_logging(level="DEBUG", file=True, log_dir=log_dir)
    logger = logging.getLogger("cmdorc")
    handlers_count_1 = len(
        [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    )

    # Second call - should replace handlers
    setup_logging(level="INFO", file=True, log_dir=log_dir)
    handlers_count_2 = len(
        [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    )

    assert handlers_count_1 == handlers_count_2 == 2


def test_setup_logging_level_string():
    """Test level can be specified as string."""
    logger = setup_logging(level="DEBUG")
    assert logger.level == logging.DEBUG

    logger = setup_logging(level="WARNING")
    assert logger.level == logging.WARNING


def test_setup_logging_does_not_affect_root():
    """Test setup_logging doesn't modify root logger."""
    root_logger = logging.getLogger()
    original_handlers_count = len(root_logger.handlers)
    original_level = root_logger.level

    setup_logging(level="DEBUG")

    # Root logger unchanged
    assert len(root_logger.handlers) == original_handlers_count
    assert root_logger.level == original_level


def test_setup_logging_propagate_true():
    """Test logs propagate to root when propagate=True."""
    logger = setup_logging(propagate=True)
    assert logger.propagate is True


def test_setup_logging_propagate_false():
    """Test logs don't propagate when propagate=False."""
    logger = setup_logging(propagate=False)
    assert logger.propagate is False


def test_setup_logging_custom_format_string():
    """Test custom format string works."""
    custom_format = "%(message)s"
    logger = setup_logging(format_string=custom_format)

    handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(handlers) == 1
    assert handlers[0].formatter._fmt == custom_format


def test_setup_logging_detailed_format():
    """Test detailed format includes file:line."""
    logger = setup_logging(format="detailed")

    handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(handlers) == 1
    assert "[%(filename)s:%(lineno)d]" in handlers[0].formatter._fmt


def test_setup_logging_console_level():
    """Test console_level parameter."""
    logger = setup_logging(level="DEBUG", console_level="WARNING")

    handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(handlers) == 1
    assert handlers[0].level == logging.WARNING


def test_setup_logging_no_console(tmp_path):
    """Test disabling console output."""
    log_dir = tmp_path / "logs"
    logger = setup_logging(console=False, file=True, log_dir=log_dir)

    handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(handlers) == 1
    assert handlers[0].__class__.__name__ == "RotatingFileHandler"


def test_disable_logging():
    """Test disable_logging removes handlers and resets state."""
    # Setup logging first
    setup_logging(level="DEBUG", file=False)
    logger = logging.getLogger("cmdorc")

    # Verify handlers exist
    non_null_handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(non_null_handlers) > 0

    # Disable logging
    disable_logging()

    # Only NullHandler should remain
    non_null_handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    assert len(non_null_handlers) == 0

    # State reset
    assert logger.level == logging.NOTSET
    assert logger.propagate is True


def test_disable_logging_preserves_nullhandler():
    """Test disable_logging keeps the NullHandler."""
    # Ensure NullHandler exists
    logger = logging.getLogger("cmdorc")
    null_handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    initial_null_count = len(null_handlers)

    # Setup and disable
    setup_logging()
    disable_logging()

    # NullHandler should still be there
    null_handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    assert len(null_handlers) == initial_null_count


def test_get_log_file_path():
    """Test get_log_file_path returns correct path."""
    path = get_log_file_path()
    assert path == Path(".cmdorc/logs/cmdorc.log")

    custom_path = get_log_file_path(log_dir="/tmp/logs", log_filename="custom.log")
    assert custom_path == Path("/tmp/logs/custom.log")


def test_nullhandler_present_by_default():
    """Test cmdorc logger has NullHandler on import."""
    logger = logging.getLogger("cmdorc")
    null_handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    assert len(null_handlers) > 0


def test_setup_logging_creates_log_directory(tmp_path):
    """Test setup_logging creates log directory if it doesn't exist."""
    log_dir = tmp_path / "nested" / "logs"
    assert not log_dir.exists()

    setup_logging(file=True, log_dir=log_dir)

    assert log_dir.exists()
    assert log_dir.is_dir()


def test_setup_logging_rotation_config(tmp_path):
    """Test file rotation configuration."""
    log_dir = tmp_path / "logs"
    max_bytes = 5 * 1024 * 1024  # 5MB
    backup_count = 3

    setup_logging(file=True, log_dir=log_dir, max_bytes=max_bytes, backup_count=backup_count)

    logger = logging.getLogger("cmdorc")
    rotating_handlers = [
        h for h in logger.handlers if h.__class__.__name__ == "RotatingFileHandler"
    ]

    assert len(rotating_handlers) == 1
    handler = rotating_handlers[0]
    assert handler.maxBytes == max_bytes
    assert handler.backupCount == backup_count
