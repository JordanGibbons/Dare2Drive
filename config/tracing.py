"""OpenTelemetry tracing setup — exports spans to Tempo via OTLP HTTP."""

from __future__ import annotations

import functools
import inspect
import typing
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode

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


def traced_command(func: Callable) -> Callable:
    """Decorator that wraps a discord app_commands handler in an OpenTelemetry span.

    Apply below @app_commands.command (or @group.command) so tracing wraps the
    raw coroutine before discord.py processes it:

        @app_commands.command(name="daily", ...)
        @traced_command
        async def daily(self, interaction): ...
    """

    @functools.wraps(func)
    async def wrapper(self: Any, interaction: Any, *args: Any, **kwargs: Any) -> Any:
        command_name = getattr(getattr(interaction, "command", None), "name", func.__name__)
        tracer = trace.get_tracer(func.__module__)
        with tracer.start_as_current_span(f"discord.command.{command_name}") as span:
            span.set_attribute("discord.command", command_name)
            span.set_attribute("discord.user_id", str(interaction.user.id))
            if interaction.guild_id:
                span.set_attribute("discord.guild_id", str(interaction.guild_id))
            try:
                return await func(self, interaction, *args, **kwargs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

    # discord.py calls inspect.signature(callback).parameters and then resolves each annotation
    # string via eval(..., callback.__globals__). Since wrapper lives in config.tracing (not the
    # cog module), discord.Member etc. would be missing from its __globals__.
    #
    # Fix: set wrapper.__signature__ to the original function's signature with annotations
    # pre-resolved to actual type objects (via typing.get_type_hints, which uses func.__globals__).
    # inspect.signature() uses __signature__ directly when present, bypassing __wrapped__.
    try:
        resolved_hints = typing.get_type_hints(func)
        orig_sig = inspect.signature(func, follow_wrapped=False)
        new_params = [
            param.replace(annotation=resolved_hints.get(name, param.annotation))
            for name, param in orig_sig.parameters.items()
        ]
        wrapper.__signature__ = orig_sig.replace(
            parameters=new_params,
            return_annotation=resolved_hints.get("return", orig_sig.return_annotation),
        )
    except Exception:
        pass

    return wrapper
