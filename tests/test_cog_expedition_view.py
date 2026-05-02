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


def test_expedition_choice_button_template_matches_built_custom_ids():
    """The DynamicItem template regex must match the same custom_ids that
    build_custom_id produces — otherwise clicks won't dispatch."""
    from bot.cogs.expeditions import ExpeditionChoiceButton, build_custom_id

    eid = uuid.uuid4()
    cid = build_custom_id(eid, "scene_a", "outrun")
    match = ExpeditionChoiceButton.__discord_ui_compiled_template__.fullmatch(cid)
    assert match is not None, f"DynamicItem template does not match {cid!r}"
    assert match["expedition_id"] == str(eid)
    assert match["scene_id"] == "scene_a"
    assert match["choice_id"] == "outrun"


def test_expedition_choice_button_template_rejects_other_prefixes():
    from bot.cogs.expeditions import ExpeditionChoiceButton

    assert (
        ExpeditionChoiceButton.__discord_ui_compiled_template__.fullmatch(
            "hangar:slot:12345678-1234-5678-1234-567812345678:PILOT"
        )
        is None
    )


@pytest.mark.asyncio
async def test_expedition_choice_button_from_custom_id_round_trip():
    """from_custom_id must reconstruct an ExpeditionChoiceButton with the
    parsed expedition_id/scene_id/choice_id — this is the path discord.py
    uses to deliver clicks after a bot restart."""
    from unittest.mock import MagicMock

    from bot.cogs.expeditions import ExpeditionChoiceButton, build_custom_id

    eid = uuid.uuid4()
    cid = build_custom_id(eid, "scene_a", "outrun")
    match = ExpeditionChoiceButton.__discord_ui_compiled_template__.fullmatch(cid)
    assert match is not None

    # Stub the inbound item so from_custom_id can pull its label.
    fake_item = MagicMock()
    fake_item.label = "A"
    instance = await ExpeditionChoiceButton.from_custom_id(MagicMock(), fake_item, match)
    assert instance.expedition_id == eid
    assert instance.scene_id == "scene_a"
    assert instance.choice_id == "outrun"


def test_expedition_cog_registers_dynamic_item_at_setup():
    """Regression for the silent-click bug: setup() must call add_dynamic_items,
    not add_view — a persistent View with no children doesn't route
    parameterized custom_ids through discord.py's dispatch."""
    import inspect

    from bot.cogs import expeditions as cog_mod

    source = inspect.getsource(cog_mod.setup)
    assert (
        "add_dynamic_items" in source
    ), "expeditions setup must call bot.add_dynamic_items(ExpeditionChoiceButton)"
    assert "ExpeditionChoiceButton" in source
    assert (
        "add_view(ExpeditionResponseView" not in source
    ), "old persistent-view registration must be gone — it doesn't route clicks"


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
