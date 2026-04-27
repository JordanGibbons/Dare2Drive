"""Persistent expedition button view + atomic auto-resolve cancellation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


def test_custom_id_format_parses():
    from bot.cogs.expeditions import build_custom_id, parse_custom_id

    eid = uuid.uuid4()
    cid = build_custom_id(eid, "scene_a", "outrun")
    parsed = parse_custom_id(cid)
    assert parsed == (eid, "scene_a", "outrun")


def test_parse_custom_id_rejects_non_expedition_prefix():
    from bot.cogs.expeditions import parse_custom_id

    assert parse_custom_id("training:abc:run") is None


@pytest.mark.asyncio
async def test_handle_response_cancels_auto_resolve_and_enqueues_resolve(
    db_session, sample_expedition_with_pilot
):
    from sqlalchemy import select

    from bot.cogs.expeditions import handle_expedition_response
    from db.models import JobState, JobType, ScheduledJob

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

    outcome = await handle_expedition_response(
        db_session,
        expedition_id=expedition.id,
        scene_id="pirate_skiff",
        choice_id="outrun",
        invoking_user_id=expedition.user_id,
    )
    await db_session.flush()
    assert outcome["status"] == "accepted"

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
    assert resolves[0].payload["picked_choice_id"] == "outrun"


@pytest.mark.asyncio
async def test_handle_response_too_late_when_auto_already_fired(
    db_session, sample_expedition_with_pilot
):
    from bot.cogs.expeditions import handle_expedition_response
    from db.models import JobState, JobType, ScheduledJob

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
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.COMPLETED,  # already fired
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

    outcome = await handle_expedition_response(
        db_session,
        expedition_id=expedition.id,
        scene_id="pirate_skiff",
        choice_id="outrun",
        invoking_user_id=expedition.user_id,
    )
    assert outcome["status"] == "too_late"


@pytest.mark.asyncio
async def test_handle_response_rejects_other_user(db_session, sample_expedition_with_pilot):
    from bot.cogs.expeditions import handle_expedition_response

    expedition, _ = sample_expedition_with_pilot
    outcome = await handle_expedition_response(
        db_session,
        expedition_id=expedition.id,
        scene_id="pirate_skiff",
        choice_id="outrun",
        invoking_user_id="some_other_user",
    )
    assert outcome["status"] == "not_owner"


@pytest.mark.asyncio
async def test_handle_response_rejects_invalid_choice(db_session, sample_expedition_with_pilot):
    from bot.cogs.expeditions import handle_expedition_response

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "pending",
            "fired_at": "2026-04-26T12:00:00Z",
            "visible_choice_ids": ["outrun", "comply"],
            "auto_resolve_job_id": str(uuid.uuid4()),
        },
    ]
    await db_session.flush()
    outcome = await handle_expedition_response(
        db_session,
        expedition_id=expedition.id,
        scene_id="pirate_skiff",
        choice_id="board_them",  # not visible to this loadout
        invoking_user_id=expedition.user_id,
    )
    assert outcome["status"] == "invalid_choice"
