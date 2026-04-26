"""accrual_tick handler — yield computation + self-rescheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from config.settings import settings
from db.models import (
    CrewMember,
    JobState,
    JobType,
    RewardSourceType,
    ScheduledJob,
    StationAssignment,
)
from engine.rewards import apply_reward
from engine.station_types import get_station
from scheduler.dispatch import HandlerResult, NotificationRequest, register
from scheduler.enqueue import enqueue_accrual_tick

log = get_logger(__name__)


async def handle_accrual_tick(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    # Idempotency: ledger row keyed off the job id ensures double-fire is a no-op.
    applied = await apply_reward(
        session,
        user_id=job.user_id,
        source_type=RewardSourceType.ACCRUAL_TICK,
        source_id=f"accrual_tick:{job.id}",
        delta={},  # bookkeeping; pending_* increments are below.
    )
    if not applied:
        # Already processed — close out the job without re-incrementing.
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    rows = (
        (
            await session.execute(
                select(StationAssignment)
                .where(StationAssignment.user_id == job.user_id)
                .where(StationAssignment.recalled_at.is_(None))
            )
        )
        .scalars()
        .all()
    )

    notifications: list[NotificationRequest] = []
    if not rows:
        # No active assignments — terminate the cycle.
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    now = datetime.now(timezone.utc)
    threshold_user_total = 0
    for sa in rows:
        elapsed = (now - sa.last_yield_tick_at).total_seconds()
        ticks_eq = elapsed / (settings.ACCRUAL_TICK_INTERVAL_MINUTES * 60)
        station = get_station(sa.station_type)

        crew = await session.get(CrewMember, sa.crew_id)
        bonus = 0.0
        if crew and station["preferred_archetype"] == crew.archetype.value:
            bonus = station["archetype_bonus_pct"] / 100.0
        mult = ticks_eq * (1.0 + bonus)

        sa.pending_credits += int(station["yields_per_tick"]["credits"] * mult)
        sa.pending_xp += int(station["yields_per_tick"]["xp"] * mult)
        sa.last_yield_tick_at = now
        threshold_user_total += sa.pending_credits

    # Threshold notification (one per user per tick if it crosses the bar).
    if threshold_user_total >= settings.ACCRUAL_NOTIFICATION_THRESHOLD:
        notifications.append(
            NotificationRequest(
                user_id=job.user_id,
                category="accrual_threshold",
                title="Stations have unclaimed yield",
                body=(
                    f"Your stations have {threshold_user_total} pending credits"
                    " — `/claim` to collect."
                ),
                correlation_id=str(job.id),
                dedupe_key=f"accrual_threshold:{job.user_id}:{now.date().isoformat()}",
            )
        )

    # Mark this tick complete.
    job.state = JobState.COMPLETED
    job.completed_at = func.now()

    # Schedule the next tick.
    next_for = now + timedelta(minutes=settings.ACCRUAL_TICK_INTERVAL_MINUTES)
    await enqueue_accrual_tick(session, user_id=job.user_id, scheduled_for=next_for)

    return HandlerResult(notifications=notifications)


# Self-register.
register(JobType.ACCRUAL_TICK, handle_accrual_tick)
