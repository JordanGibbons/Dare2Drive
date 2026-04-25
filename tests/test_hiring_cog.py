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
