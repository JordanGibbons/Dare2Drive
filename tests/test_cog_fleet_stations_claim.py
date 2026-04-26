"""Tests for /stations assign/list/recall and /claim."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from sqlalchemy import select

from bot.system_gating import get_active_system
from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    Rarity,
    StationAssignment,
    StationType,
    User,
)
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
async def test_stations_assign_creates_row_and_marks_crew_busy(
    db_session, sample_system, monkeypatch
):
    from bot.cogs import fleet as fleet_mod

    user = User(discord_id="600501", username="s_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()
    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Cee",
        last_name="Are",
        callsign="Crow",
        archetype=CrewArchetype.NAVIGATOR,
        rarity=Rarity.COMMON,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(fleet_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(
        fleet_mod,
        "get_active_system",
        create_autospec(get_active_system, return_value=sample_system),
    )

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.stations_assign.callback(
        cog,
        inter,
        crew='Cee "Crow" Are',
        station="cargo_run",
    )

    sa = (
        await db_session.execute(
            select(StationAssignment).where(StationAssignment.user_id == user.discord_id)
        )
    ).scalar_one_or_none()
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert sa is not None
    assert sa.station_type == StationType.CARGO_RUN
    assert refreshed_crew.current_activity == CrewActivity.ON_STATION


@pytest.mark.asyncio
async def test_claim_zeroes_pending_and_credits_user(db_session, sample_system, monkeypatch):
    from bot.cogs import fleet as fleet_mod

    user = User(discord_id="600502", username="s_b", hull_class=HullClass.HAULER, currency=10)
    db_session.add(user)
    await db_session.flush()
    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="X",
        last_name="Y",
        callsign="Z",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    await db_session.flush()
    sa = StationAssignment(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        station_type=StationType.WATCH_TOWER,
        crew_id=crew.id,
        pending_credits=300,
        pending_xp=80,
    )
    db_session.add(sa)
    await db_session.flush()

    monkeypatch.setattr(fleet_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(
        fleet_mod,
        "get_active_system",
        create_autospec(get_active_system, return_value=sample_system),
    )

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.claim.callback(cog, inter)

    refreshed_user = await db_session.get(User, user.discord_id)
    refreshed_sa = await db_session.get(StationAssignment, sa.id)
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert refreshed_user.currency == 310  # 10 + 300.
    assert refreshed_sa.pending_credits == 0
    assert refreshed_sa.pending_xp == 0
    assert refreshed_crew.xp == 80
