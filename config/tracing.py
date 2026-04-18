"""OpenTelemetry tracing setup — exports spans to Tempo via OTLP HTTP."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from config.logging import get_logger
from config.settings import settings

log = get_logger(__name__)


def _build_exporter() -> SpanExporter | None:
    if not settings.TEMPO_URL:
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=f"{settings.TEMPO_URL}/v1/traces")


def init_tracing(service_name: str) -> None:
    """Initialise the global TracerProvider.

    Call once at process startup (before any instrumentation hooks run).
    When TEMPO_URL is empty tracing is still active in-process — spans
    just won't be exported, keeping local dev lightweight.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter = _build_exporter()
    if exporter:
        provider.add_span_processor(BatchSpanProcessor(exporter))
        log.info("Tracing enabled — exporting to %s", settings.TEMPO_URL)
    else:
        log.info("Tracing enabled (no exporter — TEMPO_URL not set)")

    trace.set_tracer_provider(provider)
