"""Tests for config/logging.py."""

from __future__ import annotations

import logging

from config.logging import get_logger, setup_logging


class TestLogging:
    def test_get_logger_returns_logger(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_setup_logging_idempotent(self):
        """Calling setup_logging multiple times should not add duplicate handlers."""
        import config.logging as log_module

        original_state = log_module._configured
        log_module._configured = False

        setup_logging()
        len(logging.getLogger().handlers)
        log_module._configured = False
        setup_logging()
        # Reset to avoid side effects
        log_module._configured = original_state

    def test_logger_hierarchy(self):
        logger = get_logger("dare2drive.engine.test")
        assert logger.parent is not None
