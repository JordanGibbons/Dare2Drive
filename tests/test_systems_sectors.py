"""Tests for Sector/System models and admin commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import select

from db.models import Sector, System

# ---------------------------------------------------------------------------
# Task 17 — register_sector_for_guild + reconcile_sectors_with_guilds
# ---------------------------------------------------------------------------


async def test_register_sector_for_guild_creates_row(db_session):
    """register_sector_for_guild inserts a Sector row with correct fields."""
    from bot.main import register_sector_for_guild

    guild = MagicMock()
    guild.id = 111111111
    guild.name = "Test Guild"
    guild.owner_id = 999999999

    await register_sector_for_guild(guild, db_session)

    result = await db_session.execute(select(Sector).where(Sector.guild_id == "111111111"))
    sys = result.scalar_one()
    assert sys.name == "Test Guild"
    assert sys.owner_discord_id == "999999999"
    assert sys.system_cap == 1


async def test_register_sector_idempotent(db_session, sample_sector):
    """Calling register_sector_for_guild twice does not duplicate."""
    from bot.main import register_sector_for_guild

    guild = MagicMock()
    guild.id = int(sample_sector.guild_id)
    guild.name = sample_sector.name
    guild.owner_id = int(sample_sector.owner_discord_id)

    await register_sector_for_guild(guild, db_session)
    await register_sector_for_guild(guild, db_session)

    result = await db_session.execute(
        select(Sector).where(Sector.guild_id == sample_sector.guild_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


async def test_reconcile_creates_missing_sectors(db_session):
    """reconcile_sectors_with_guilds inserts rows for guilds the bot is in but DB has not seen."""
    from bot.main import reconcile_sectors_with_guilds

    guild_a = MagicMock(id=111, owner_id=999)
    guild_a.name = "A"
    guild_b = MagicMock(id=222, owner_id=999)
    guild_b.name = "B"

    await reconcile_sectors_with_guilds([guild_a, guild_b], db_session)

    result = await db_session.execute(select(Sector).where(Sector.guild_id.in_(["111", "222"])))
    sectors = result.scalars().all()
    assert {s.guild_id for s in sectors} == {"111", "222"}


# ---------------------------------------------------------------------------
# Task 18 — system/sector admin command logic functions
# ---------------------------------------------------------------------------


async def test_system_enable_creates_system_when_under_cap(db_session, sample_sector):
    """Admin can enable a system when under cap."""
    from bot.cogs.admin import _system_enable_logic

    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 333333
    interaction.channel.name = "test-channel"
    interaction.user.guild_permissions.manage_channels = True

    result = await _system_enable_logic(interaction, db_session)
    assert result.success is True

    sec = (
        await db_session.execute(select(System).where(System.channel_id == "333333"))
    ).scalar_one()
    assert sec.sector_id == sample_sector.guild_id


async def test_system_enable_rejects_at_cap(db_session, sample_sector, sample_system):
    """When at cap, system enable rejects."""
    from bot.cogs.admin import _system_enable_logic

    # sample_sector starts with system_cap=1; sample_system is already 1 enabled.
    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 444444
    interaction.user.guild_permissions.manage_channels = True

    result = await _system_enable_logic(interaction, db_session)
    assert result.success is False
    assert "cap" in result.message.lower() or "sustain" in result.message.lower()


async def test_system_enable_rejects_non_admin(db_session, sample_sector):
    """Non-admin gets permission rejection."""
    from bot.cogs.admin import _system_enable_logic

    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 555555
    interaction.user.guild_permissions.manage_channels = False

    result = await _system_enable_logic(interaction, db_session)
    assert result.success is False
    assert "admin" in result.message.lower() or "permission" in result.message.lower()


async def test_system_disable_removes_row(db_session, sample_sector, sample_system):
    """Disable removes the System row."""
    from bot.cogs.admin import _system_disable_logic

    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = int(sample_system.channel_id)
    interaction.user.guild_permissions.manage_channels = True

    result = await _system_disable_logic(interaction, db_session)
    assert result.success is True
    sec = (
        await db_session.execute(
            select(System).where(System.channel_id == sample_system.channel_id)
        )
    ).scalar_one_or_none()
    assert sec is None


async def test_sector_admin_set_system_cap_bot_owner_only(db_session, sample_sector, monkeypatch):
    """Only bot owner can set system cap."""
    from bot.cogs.admin import _set_system_cap_logic

    monkeypatch.setattr("config.settings.settings.BOT_OWNER_DISCORD_ID", "999999999")

    interaction_owner = MagicMock()
    interaction_owner.user.id = 999999999
    interaction_owner.guild_id = int(sample_sector.guild_id)

    result_ok = await _set_system_cap_logic(interaction_owner, 5, db_session)
    assert result_ok.success is True

    interaction_other = MagicMock()
    interaction_other.user.id = 111
    interaction_other.guild_id = int(sample_sector.guild_id)

    result_deny = await _set_system_cap_logic(interaction_other, 10, db_session)
    assert result_deny.success is False
