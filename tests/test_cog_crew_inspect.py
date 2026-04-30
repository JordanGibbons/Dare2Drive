"""Phase 2c — /crew_inspect shows aboard ship when crew is assigned."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id: str) -> MagicMock:
    inter = MagicMock()
    inter.user.id = user_id  # cog calls str(interaction.user.id), so any str works
    inter.channel_id = 222222222
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_crew_inspect_shows_aboard_line_when_assigned(db_session, sample_user, monkeypatch):
    """When the crew member is in crew_assignments, show the ship name."""
    from db.models import (
        Build,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
    )

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    from bot.cogs.hiring import HiringCog
    from tests.conftest import SessionWrapper

    monkeypatch.setattr("bot.cogs.hiring.async_session", lambda: SessionWrapper(db_session))
    cog = HiringCog(MagicMock())
    mock_interaction = _make_interaction(sample_user.discord_id)
    await cog.crew_inspect.callback(cog, interaction=mock_interaction, crew='Mira "Sixgun" Voss')

    sent_kwargs = mock_interaction.response.send_message.call_args.kwargs
    embed = sent_kwargs.get("embed")
    assert embed is not None
    # Check field names and values together: "Aboard" appears as a field name,
    # "Flagstaff" appears in the field value.
    field_names = [f.name for f in embed.fields]
    field_values = " ".join(f.value for f in embed.fields)
    assert "Aboard" in field_names
    assert "Flagstaff" in field_values


@pytest.mark.asyncio
async def test_crew_inspect_no_aboard_line_when_unassigned(db_session, sample_user, monkeypatch):
    """When the crew member has no assignment, the Aboard field should not appear."""
    from db.models import (
        CrewArchetype,
        CrewMember,
        Rarity,
    )

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    db_session.add(crew)
    await db_session.flush()

    from bot.cogs.hiring import HiringCog
    from tests.conftest import SessionWrapper

    monkeypatch.setattr("bot.cogs.hiring.async_session", lambda: SessionWrapper(db_session))
    cog = HiringCog(MagicMock())
    mock_interaction = _make_interaction(sample_user.discord_id)
    await cog.crew_inspect.callback(cog, interaction=mock_interaction, crew='Mira "Sixgun" Voss')

    sent_kwargs = mock_interaction.response.send_message.call_args.kwargs
    embed = sent_kwargs.get("embed")
    assert embed is not None
    field_names = [f.name for f in embed.fields]
    assert "Aboard" not in field_names
