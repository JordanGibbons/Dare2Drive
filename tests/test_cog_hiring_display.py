"""/crew + /crew_inspect display refresh tests."""

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
    return inter


@pytest.mark.asyncio
async def test_crew_roster_shows_on_expedition(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import hiring as hiring_mod
    from tests.conftest import SessionWrapper

    expedition, pilot = sample_expedition_with_pilot

    monkeypatch.setattr(hiring_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.crew.callback(cog, inter, filter=None)

    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    embed = kwargs.get("embed")
    assert embed is not None
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "ON_EXP" in flat or "expedition" in flat.lower()


@pytest.mark.asyncio
async def test_crew_roster_shows_injured(db_session, sample_user, monkeypatch):
    from bot.cogs import hiring as hiring_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Hurt",
        last_name="Body",
        callsign="Bandage",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.COMMON,
        level=2,
        current_activity=CrewActivity.IDLE,
        injured_until=datetime.now(timezone.utc) + timedelta(hours=14),
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(hiring_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.crew.callback(cog, inter, filter=None)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "INJURED" in flat or "🩹" in flat or "recover" in flat.lower()


@pytest.mark.asyncio
async def test_crew_roster_idle_recovered_when_past_injured_until(
    db_session, sample_user, monkeypatch
):
    """A crew member with `injured_until` in the past is shown as IDLE."""
    from bot.cogs import hiring as hiring_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Healed",
        last_name="Up",
        callsign="Up",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.COMMON,
        level=2,
        current_activity=CrewActivity.IDLE,
        injured_until=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(hiring_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.crew.callback(cog, inter, filter=None)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "IDLE" in flat or "🟢" in flat


@pytest.mark.asyncio
async def test_crew_inspect_shows_qualified_for(db_session, sample_user, monkeypatch):
    from bot.cogs import hiring as hiring_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Qual",
        last_name="Test",
        callsign="Q",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=3,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(hiring_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.crew_inspect.callback(cog, inter, crew='Qual "Q" Test')
    embed = inter.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "Qualified for" in flat
    assert "PILOT" in flat
