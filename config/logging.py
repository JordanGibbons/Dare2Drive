"""Unified logging configuration for Dare2Drive."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from config.settings import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level_override: Optional[str] = None) -> None:
    """Configure the root logger once. Idempotent — subsequent calls are no-ops."""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, (level_override or settings.LOG_LEVEL).upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Quieten noisy third-party loggers
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger with the given name, setting up root if needed."""
    setup_logging()
    return logging.getLogger(name)
