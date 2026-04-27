"""/expedition respond — slash-command path through handle_expedition_response."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_respond_routes_through_handle_expedition_response(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from sqlalchemy import select

    from bot.cogs import expeditions as exp_mod
    from db.models import JobState, JobType, ScheduledJob
    from tests.conftest import SessionWrapper

    expedition, _ = sample_expedition_with_pilot
    auto = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc) + timedelta(minutes=30),
        state=JobState.PENDING,
    )
    db_session.add(auto)
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "pending",
            "fired_at": "2026-04-26T12:00:00Z",
            "visible_choice_ids": ["outrun", "comply"],
            "auto_resolve_job_id": str(auto.id),
        },
    ]
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.expedition_respond.callback(
        cog,
        inter,
        expedition=str(expedition.id),
        scene="pirate_skiff",
        choice="outrun",
    )

    refreshed_auto = await db_session.get(ScheduledJob, auto.id)
    assert refreshed_auto.state == JobState.CANCELLED
    resolves = (
        (
            await db_session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
                .where(ScheduledJob.user_id == expedition.user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(resolves) == 1
