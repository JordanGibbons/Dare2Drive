"""Unified logging configuration for Dare2Drive."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from config.settings import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s | traceID=%(otelTraceID)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _trace_context() -> tuple[str, str]:
    """Return the current (traceID, spanID) as hex strings, or empty strings."""
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.trace_id:
            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:
        pass
    return "", ""


class _TraceFilter(logging.Filter):
    """Inject OpenTelemetry trace context into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        trace_id, span_id = _trace_context()
        record.otelTraceID = trace_id  # type: ignore[attr-defined]
        record.otelSpanID = span_id  # type: ignore[attr-defined]
        return True


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Fluent Bit (and Loki) can ingest these directly without extra parsing rules.
    Fields ``traceID`` and ``spanID`` enable Loki → Tempo correlation in Grafana.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        trace_id = getattr(record, "otelTraceID", "")
        span_id = getattr(record, "otelSpanID", "")
        if trace_id:
            payload["traceID"] = trace_id
            payload["spanID"] = span_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level_override: Optional[str] = None) -> None:
    """Configure the root logger once. Idempotent — subsequent calls are no-ops."""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, (level_override or settings.LOG_LEVEL).upper(), logging.INFO)

    if settings.LOG_FORMAT == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_TraceFilter())

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
