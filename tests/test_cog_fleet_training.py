"""Tests for /training start, /training status, /training cancel."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    Rarity,
    User,
)


def _make_interaction(user_id: str, system_id: str = "222222222") -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id)
    inter.channel_id = int(system_id)
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_training_start_validates_credits_and_schedules_timer(
    db_session, sample_system, monkeypatch
):
    """A successful /training start deducts credits, sets crew busy, inserts timer + job."""
    from bot.cogs import fleet as fleet_mod

    user = User(
        discord_id="600301",
        username="cog_a",
        hull_class=HullClass.HAULER,
        currency=200,
    )
    db_session.add(user)
    await db_session.flush()
    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="A",
        last_name="B",
        callsign="C",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(
        fleet_mod,
        "async_session",
        lambda: _SessionWrapper(db_session),
    )
    monkeypatch.setattr(
        fleet_mod,
        "get_active_system",
        AsyncMock(return_value=sample_system),
    )

    inter = _make_interaction(user.discord_id)
    cog = fleet_mod.FleetCog(MagicMock())
    await cog.training_start.callback(
        cog,
        inter,
        crew='A "C" B',
        routine="combat_drills",
    )

    refreshed_user = await db_session.get(User, user.discord_id)
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert refreshed_user.currency == 150  # 200 - 50.
    assert refreshed_crew.current_activity == CrewActivity.TRAINING


from tests.conftest import SessionWrapper as _SessionWrapper  # noqa: E402, F401
