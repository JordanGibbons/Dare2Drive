"""Smoke test: HiringCog loads and registers its commands."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from discord.ext import commands

from bot.cogs.hiring import HiringCog
from db.models import CrewMember, HullClass, User


def test_hiring_cog_imports():
    from bot.cogs import hiring  # noqa: F401

    assert hasattr(hiring, "HiringCog")


def test_hiring_cog_registers_commands():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)
    command_names = {c.name for c in cog.walk_app_commands()}
    assert {"dossier", "hire", "crew", "assign", "unassign"} <= command_names


@pytest_asyncio.fixture
async def hiring_user(db_session):
    unique_id = str(uuid.uuid4())[:8]
    u = User(
        discord_id=unique_id,
        username=f"hiringtest_{unique_id}",
        hull_class=HullClass.SKIRMISHER,
        currency=3000,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_dossier_command_deducts_creds_and_creates_crew(hiring_user, db_session):
    from sqlalchemy import select

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)

    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = hiring_user.discord_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        sess_ctx.return_value.__aexit__.return_value = None
        with patch(
            "bot.cogs.hiring.get_active_system",
            new=AsyncMock(return_value=MagicMock()),
        ):
            await cog.dossier.callback(cog, interaction, tier="dossier")

    await db_session.refresh(hiring_user)
    assert hiring_user.currency == 2500  # 3000 - 500

    res = await db_session.execute(
        select(CrewMember).where(CrewMember.user_id == hiring_user.discord_id)
    )
    members = list(res.scalars().all())
    assert len(members) == 1


@pytest.mark.asyncio
async def test_crew_command_lists_user_crew(hiring_user, db_session):

    from bot.cogs.hiring import HiringCog
    from db.models import CrewArchetype, CrewMember, Rarity

    # Pre-seed two crew
    c1 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Jax",
        last_name="Krell",
        callsign="Blackjack",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
    )
    c2 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.ENGINEER,
        rarity=Rarity.EPIC,
    )
    db_session.add_all([c1, c2])
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)

    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = hiring_user.discord_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        sess_ctx.return_value.__aexit__.return_value = None
        await cog.crew.callback(cog, interaction, filter=None)

    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    embed = kwargs.get("embed")
    assert embed is not None
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "Jax" in flat
    assert "Mira" in flat


@pytest.mark.asyncio
async def test_crew_inspect_command_shows_detail(hiring_user, db_session):
    import discord
    from discord.ext import commands

    from bot.cogs.hiring import HiringCog
    from db.models import CrewArchetype, CrewMember, Rarity

    c = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Cas",
        last_name="Harrow",
        callsign="Crow",
        archetype=CrewArchetype.NAVIGATOR,
        rarity=Rarity.EPIC,
        level=3,
        xp=120,
    )
    db_session.add(c)
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)

    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = hiring_user.discord_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        sess_ctx.return_value.__aexit__.return_value = None
        await cog.crew_inspect.callback(cog, interaction, name='Cas "Crow" Harrow')

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "Navigator" in flat
    assert "Epic" in flat
    assert "L3" in flat or "Level 3" in flat
    assert "120" in flat  # xp


@pytest.mark.asyncio
async def test_assign_auto_unassigns_prior_same_archetype(hiring_user, db_session):
    """Assigning a new pilot auto-replaces the old one."""
    import discord
    from discord.ext import commands

    from bot.cogs.hiring import HiringCog
    from db.models import Build, CrewArchetype, CrewAssignment, CrewMember, Rarity

    build = Build(
        user_id=hiring_user.discord_id,
        name="Flagship",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()

    pilot1 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Jax",
        last_name="Krell",
        callsign="Blackjack",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    pilot2 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
    )
    db_session.add_all([pilot1, pilot2])
    await db_session.flush()

    db_session.add(
        CrewAssignment(crew_id=pilot1.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = hiring_user.discord_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        sess_ctx.return_value.__aexit__.return_value = None
        with patch(
            "bot.cogs.hiring.get_active_system",
            new=AsyncMock(return_value=MagicMock()),
        ):
            await cog.assign.callback(cog, interaction, crew='Mira "Sixgun" Voss')

    # Only pilot2 should be assigned now
    from sqlalchemy import select

    res = await db_session.execute(select(CrewAssignment))
    rows = list(res.scalars().all())
    assert len(rows) == 1
    assert rows[0].crew_id == pilot2.id


@pytest.mark.asyncio
async def test_unassign_removes_crew_from_build(hiring_user, db_session):
    import discord
    from discord.ext import commands

    from bot.cogs.hiring import HiringCog
    from db.models import Build, CrewArchetype, CrewAssignment, CrewMember, Rarity

    build = Build(
        user_id=hiring_user.discord_id,
        name="Flagship",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()

    pilot = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Jax",
        last_name="Krell",
        callsign="Blackjack",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    db_session.add(pilot)
    await db_session.flush()

    db_session.add(
        CrewAssignment(crew_id=pilot.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = hiring_user.discord_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        sess_ctx.return_value.__aexit__.return_value = None
        with patch(
            "bot.cogs.hiring.get_active_system",
            new=AsyncMock(return_value=MagicMock()),
        ):
            await cog.unassign.callback(cog, interaction, crew='Jax "Blackjack" Krell')

    from sqlalchemy import select

    res = await db_session.execute(select(CrewAssignment))
    rows = list(res.scalars().all())
    assert len(rows) == 0
