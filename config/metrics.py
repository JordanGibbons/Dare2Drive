"""Helpers for correlating Prometheus metrics with OpenTelemetry traces."""

from __future__ import annotations


def trace_exemplar() -> dict[str, str]:
    """Return ``{"traceID": "<hex>"}`` for the current span, or ``{}`` if none.

    Pass the result as the ``exemplar`` kwarg when calling ``.observe()`` or
    ``.inc()`` on a Prometheus Histogram or Counter so Grafana can jump from a
    metric data-point straight to the matching Tempo trace.
    """
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.trace_id:
            return {"traceID": format(ctx.trace_id, "032x")}
    except Exception:
        pass
    return {}
