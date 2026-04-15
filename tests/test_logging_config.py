"""Tests for supervisor.logging_config module."""

import logging
from unittest.mock import patch

from supervisor.logging_config import setup_logging


class TestSetupLogging:
    def setup_method(self):
        """Clean up supervisor logger handlers before each test."""
        root = logging.getLogger("supervisor")
        root.handlers.clear()

    def teardown_method(self):
        root = logging.getLogger("supervisor")
        root.handlers.clear()

    def test_creates_file_handler(self, tmp_path):
        log_file = tmp_path / "test.log"
        with (
            patch("supervisor.logging_config._LOG_DIR", tmp_path),
            patch("supervisor.logging_config._LOG_FILE", log_file),
        ):
            setup_logging(debug=False)

        root = logging.getLogger("supervisor")
        assert any(hasattr(h, "baseFilename") for h in root.handlers)

    def test_file_is_writable(self, tmp_path):
        log_file = tmp_path / "test.log"
        with (
            patch("supervisor.logging_config._LOG_DIR", tmp_path),
            patch("supervisor.logging_config._LOG_FILE", log_file),
        ):
            setup_logging(debug=False)

        test_logger = logging.getLogger("supervisor.test")
        test_logger.debug("test message")

        # Flush handlers
        for h in logging.getLogger("supervisor").handlers:
            h.flush()

        assert log_file.exists()
        assert "test message" in log_file.read_text()

    def test_debug_adds_stream_handler(self, tmp_path):
        log_file = tmp_path / "test.log"
        with (
            patch("supervisor.logging_config._LOG_DIR", tmp_path),
            patch("supervisor.logging_config._LOG_FILE", log_file),
        ):
            setup_logging(debug=True)

        root = logging.getLogger("supervisor")
        stream_handlers = [
            h for h in root.handlers if isinstance(h, logging.StreamHandler) and not hasattr(h, "baseFilename")
        ]
        assert len(stream_handlers) == 1

    def test_no_stream_handler_without_debug(self, tmp_path):
        log_file = tmp_path / "test.log"
        with (
            patch("supervisor.logging_config._LOG_DIR", tmp_path),
            patch("supervisor.logging_config._LOG_FILE", log_file),
        ):
            setup_logging(debug=False)

        root = logging.getLogger("supervisor")
        stream_handlers = [
            h for h in root.handlers if isinstance(h, logging.StreamHandler) and not hasattr(h, "baseFilename")
        ]
        assert len(stream_handlers) == 0
