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
    """Happy path: build IDLE, crew IDLE, no existing expedition → starts."""
    from sqlalchemy import select

    from bot.cogs import expeditions as exp_mod
    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewArchetype,
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
        pilot=f'{pilot.first_name} "{pilot.callsign}" {pilot.last_name}',
        gunner=None,
        engineer=None,
        navigator=None,
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
        pilot=None,
        gunner=None,
        engineer=None,
        navigator=None,
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
        pilot=None,
        gunner=None,
        engineer=None,
        navigator=None,
    )
    msg = inter.response.send_message.call_args.args[0]
    assert "expedition" in msg.lower()


@pytest.mark.asyncio
async def test_start_blocked_when_insufficient_credits(db_session, sample_user, monkeypatch):
    from bot.cogs import expeditions as exp_mod
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="X",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)
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
        pilot=None,
        gunner=None,
        engineer=None,
        navigator=None,
    )
    msg = inter.response.send_message.call_args.args[0]
    assert "credit" in msg.lower()
