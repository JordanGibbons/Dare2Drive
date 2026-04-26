"""Worker-internal periodic task: reset stuck claims, retry capped failures."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.logging import get_logger
from config.settings import settings
from db.models import JobState, ScheduledJob

log = get_logger(__name__)


async def recovery_sweep(session_maker: async_sessionmaker) -> int:
    """Reset stuck-claimed and retryable-failed jobs back to pending.

    Returns the total rows updated across both passes.
    """
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS
    )
    total = 0

    async with session_maker() as session, session.begin():
        # Stuck claims: claimed too long ago, push back to pending.
        result = await session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.state == JobState.CLAIMED)
            .where(ScheduledJob.claimed_at < stuck_cutoff)
            .values(state=JobState.PENDING, claimed_at=None)
        )
        total += result.rowcount or 0

        # Failed-but-retryable.
        result = await session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.state == JobState.FAILED)
            .where(ScheduledJob.attempts < settings.SCHEDULER_MAX_ATTEMPTS)
            .values(state=JobState.PENDING, last_error=None)
        )
        total += result.rowcount or 0

    if total:
        log.info("recovery_sweep_reset_count count=%d", total)
    return total


async def run_forever(
    session_maker: async_sessionmaker,
    *,
    shutdown_event: asyncio.Event,
) -> None:
    interval = settings.SCHEDULER_RECOVERY_INTERVAL_SECS
    while not shutdown_event.is_set():
        try:
            await recovery_sweep(session_maker)
        except Exception:
            log.exception("recovery_sweep failed")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
