"""Job dispatcher: handler registry + per-job transaction wrapper."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from opentelemetry import trace
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.metrics import scheduler_jobs_total
from config.logging import get_logger
from db.models import JobState, JobType, ScheduledJob

log = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class NotificationButton:
    """Discord-agnostic description of a button to attach to a DM.

    The bot-side notification consumer materializes these into discord.ui.Button
    instances. `custom_id` must be parseable by a persistent View registered on
    the bot (see ExpeditionResponseView).
    """

    custom_id: str
    label: str
    style: str = "primary"  # one of: primary, secondary, success, danger


@dataclass
class NotificationRequest:
    user_id: str
    category: str
    title: str
    body: str
    correlation_id: str
    dedupe_key: str
    # Optional buttons. When present, the consumer sends this notification as
    # its own DM (no batching) so the buttons stay associated with the
    # narration that prompted them.
    components: list[NotificationButton] | None = None


@dataclass
class HandlerResult:
    notifications: list[NotificationRequest] = field(default_factory=list)


Handler = Callable[[AsyncSession, ScheduledJob], Awaitable[HandlerResult]]

# Handlers register themselves here. Imports below trigger registration.
HANDLERS: dict[JobType, Handler] = {}


def register(job_type: JobType, handler: Handler) -> None:
    HANDLERS[job_type] = handler


async def dispatch(job: ScheduledJob, session_maker: async_sessionmaker) -> None:
    """Execute one claimed job inside its own transaction."""
    handler = HANDLERS.get(job.job_type)
    if handler is None:
        log.error("no handler registered for job_type=%s", job.job_type)
        await _mark_failed(job, session_maker, error="no handler registered")
        scheduler_jobs_total.labels(job_type=job.job_type.value, result="failure").inc()
        return

    with tracer.start_as_current_span(f"scheduler.{job.job_type.value}") as span:
        span.set_attribute("d2d.job_id", str(job.id))
        span.set_attribute("d2d.job_type", job.job_type.value)
        span.set_attribute("d2d.user_id", job.user_id)
        span.set_attribute("d2d.attempts", job.attempts)

        notifications: list[NotificationRequest] = []
        try:
            async with session_maker() as session, session.begin():
                fresh = await session.get(ScheduledJob, job.id, with_for_update=True)
                if fresh is None or fresh.state != JobState.CLAIMED:
                    log.info(
                        "dispatch skipping job_id=%s state=%s",
                        job.id,
                        fresh.state if fresh else None,
                    )
                    return
                result = await handler(session, fresh)
                notifications = list(result.notifications)
            # Propagate the handler's state mutation back to the caller's object so
            # any session holding `job` in its identity map sees the updated state.
            job.state = fresh.state
            scheduler_jobs_total.labels(job_type=job.job_type.value, result="success").inc()
        except Exception as e:
            span.record_exception(e)
            await _mark_failed(job, session_maker, error=traceback.format_exc())
            scheduler_jobs_total.labels(job_type=job.job_type.value, result="failure").inc()
            log.exception("handler failed: job_id=%s", job.id)
            return

    # Emit notifications AFTER DB commit — accepted v1 trade if worker dies here.
    if notifications:
        from scheduler.notifications import emit_notification

        for n in notifications:
            try:
                await emit_notification(n)
            except Exception:
                log.exception("notification xadd failed for job_id=%s", job.id)


async def _mark_failed(job: ScheduledJob, session_maker: async_sessionmaker, *, error: str) -> None:
    truncated = error[:8000]
    async with session_maker() as session, session.begin():
        fresh = await session.get(ScheduledJob, job.id, with_for_update=True)
        if fresh is None:
            return
        fresh.state = JobState.FAILED
        fresh.last_error = truncated
        fresh.completed_at = func.now()
    # Propagate failure state back to the caller's object so any session holding
    # `job` in its identity map sees the updated state without re-querying.
    job.state = JobState.FAILED
    job.last_error = truncated
