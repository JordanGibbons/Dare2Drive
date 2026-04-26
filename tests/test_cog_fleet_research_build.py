"""Tests for /research and /build commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import HullClass, TimerType, User
from tests.conftest import SessionWrapper


def _make_interaction(user_id: str) -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id)
    inter.channel_id = 222222222
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_research_start_inserts_active_research_timer(db_session, sample_system, monkeypatch):
    from sqlalchemy import select

    from bot.cogs import fleet as fleet_mod
    from db.models import Timer

    user = User(discord_id="600401", username="r_a", hull_class=HullClass.HAULER, currency=500)
    db_session.add(user)
    await db_session.flush()

    monkeypatch.setattr(fleet_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    inter = _make_interaction(user.discord_id)
    cog = fleet_mod.FleetCog(MagicMock())
    await cog.research_start.callback(cog, inter, project="drive_tuning")

    timer = (
        await db_session.execute(
            select(Timer).where(
                Timer.user_id == user.discord_id, Timer.timer_type == TimerType.RESEARCH
            )
        )
    ).scalar_one_or_none()
    assert timer is not None
    assert timer.recipe_id == "drive_tuning"


@pytest.mark.asyncio
async def test_research_start_blocked_by_partial_unique_index(
    db_session, sample_system, monkeypatch
):
    """A second concurrent research timer must be rejected by the DB."""
    from bot.cogs import fleet as fleet_mod

    user = User(discord_id="600402", username="r_b", hull_class=HullClass.HAULER, currency=2000)
    db_session.add(user)
    await db_session.flush()

    monkeypatch.setattr(fleet_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    cog = fleet_mod.FleetCog(MagicMock())
    inter1 = _make_interaction(user.discord_id)
    await cog.research_start.callback(cog, inter1, project="drive_tuning")

    inter2 = _make_interaction(user.discord_id)
    with pytest.raises(IntegrityError):
        await cog.research_start.callback(cog, inter2, project="shield_calibration")


@pytest.mark.asyncio
async def test_build_construct_inserts_active_ship_build_timer(
    db_session, sample_system, monkeypatch
):
    from sqlalchemy import select

    from bot.cogs import fleet as fleet_mod
    from db.models import Timer

    user = User(discord_id="600403", username="r_c", hull_class=HullClass.HAULER, currency=1000)
    db_session.add(user)
    await db_session.flush()

    monkeypatch.setattr(fleet_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.build_construct.callback(cog, inter, recipe="salvage_reconstruction")

    timer = (
        await db_session.execute(
            select(Timer).where(
                Timer.user_id == user.discord_id, Timer.timer_type == TimerType.SHIP_BUILD
            )
        )
    ).scalar_one_or_none()
    assert timer is not None
    assert timer.recipe_id == "salvage_reconstruction"
