"""/expedition start cog tests — each validation path + happy path."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id: str, channel_id: int = 222222222) -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id) if user_id.isdigit() else user_id
    inter.channel_id = channel_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()
    return inter


def _mock_get_active_system():
    """Return an AsyncMock for get_active_system that returns a non-None System."""
    mock = AsyncMock(return_value=MagicMock())
    return mock


@pytest.mark.asyncio
async def test_start_happy_path(db_session, sample_user, monkeypatch):
    """Happy path: build IDLE, pilot assigned via CrewAssignment → starts."""
    from sqlalchemy import select

    from bot.cogs import expeditions as exp_mod
    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        Expedition,
        HullClass,
        Rarity,
    )
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)
    pilot = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
        stats={"acceleration": 70},
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(pilot)
    await db_session.flush()

    # Bind pilot to the build via CrewAssignment
    db_session.add(
        CrewAssignment(
            build_id=build.id,
            crew_id=pilot.id,
            archetype=CrewArchetype.PILOT,
        )
    )
    await db_session.flush()

    sample_user.currency = 1000
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(exp_mod, "get_active_system", _mock_get_active_system())

    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog,
        inter,
        template="outer_marker_patrol",
        build=str(build.id),
    )

    expeditions = (
        (
            await db_session.execute(
                select(Expedition).where(Expedition.user_id == sample_user.discord_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(expeditions) == 1


@pytest.mark.asyncio
async def test_start_blocked_when_max_concurrent_reached(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    """User already has max active expeditions → refuses."""
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper

    expedition_a, _ = sample_expedition_with_pilot
    from db.models import (
        Build,
        BuildActivity,
        Expedition,
        ExpeditionState,
        HullClass,
    )

    b2 = Build(
        id=uuid.uuid4(),
        user_id=expedition_a.user_id,
        name="B2",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(b2)
    await db_session.flush()
    e2 = Expedition(
        id=uuid.uuid4(),
        user_id=expedition_a.user_id,
        build_id=b2.id,
        template_id="outer_marker_patrol",
        state=ExpeditionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
        completes_at=datetime.now(timezone.utc) + timedelta(hours=4),
        correlation_id=uuid.uuid4(),
        scene_log=[],
    )
    db_session.add(e2)
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(exp_mod, "get_active_system", _mock_get_active_system())
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition_a.user_id)
    await cog.expedition_start.callback(
        cog,
        inter,
        template="outer_marker_patrol",
        build=str(uuid.uuid4()),
    )
    inter.response.send_message.assert_called_once()
    msg = inter.response.send_message.call_args.args[0]
    assert "limit" in msg.lower() or "max" in msg.lower() or "slot" in msg.lower()


@pytest.mark.asyncio
async def test_start_blocked_when_build_locked(db_session, sample_user, monkeypatch):
    from bot.cogs import expeditions as exp_mod
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Locked",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(exp_mod, "get_active_system", _mock_get_active_system())
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog,
        inter,
        template="marquee_run",
        build=str(build.id),
    )
    msg = inter.response.send_message.call_args.args[0]
    assert "busy" in msg.lower() or "can't launch" in msg.lower()


@pytest.mark.asyncio
async def test_start_blocked_when_insufficient_credits(db_session, sample_user, monkeypatch):
    """Insufficient credits — must have crew assigned to reach the cost check."""
    from bot.cogs import expeditions as exp_mod
    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
    )
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="X",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)

    # marquee_run requires min 2 crew with at least one PILOT or GUNNER
    pilot = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Ace",
        last_name="One",
        callsign="Alpha",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        current_activity=CrewActivity.IDLE,
    )
    gunner = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Ace",
        last_name="Two",
        callsign="Beta",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.COMMON,
        level=1,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add_all([pilot, gunner])
    await db_session.flush()

    db_session.add(
        CrewAssignment(
            build_id=build.id,
            crew_id=pilot.id,
            archetype=CrewArchetype.PILOT,
        )
    )
    db_session.add(
        CrewAssignment(
            build_id=build.id,
            crew_id=gunner.id,
            archetype=CrewArchetype.GUNNER,
        )
    )
    await db_session.flush()

    sample_user.currency = 50  # marquee_run costs 250
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(exp_mod, "get_active_system", _mock_get_active_system())
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog,
        inter,
        template="marquee_run",
        build=str(build.id),
    )
    msg = inter.response.send_message.call_args.args[0]
    assert "credit" in msg.lower()


@pytest.mark.asyncio
async def test_expedition_start_blocks_when_crew_required_unsatisfied(
    db_session, sample_user, monkeypatch
):
    """Slot-walking error: SKIRMISHER with empty pilot slot can't run a template needing PILOT."""
    from bot.cogs import expeditions as exp_mod
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(exp_mod, "get_active_system", _mock_get_active_system())

    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog,
        inter,
        template="marquee_run",
        build=str(build.id),
    )
    sent = inter.response.send_message.call_args
    body = sent[0][0]
    assert "marquee_run" in body or "Marquee Run" in body
    assert "**PILOT**" in body and "empty" in body
    assert "/hangar" in body
