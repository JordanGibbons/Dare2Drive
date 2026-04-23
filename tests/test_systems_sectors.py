"""Tests for System/Sector models and admin commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import select

from db.models import Sector, System

# ---------------------------------------------------------------------------
# Task 17 — register_system_for_guild + reconcile_systems_with_guilds
# ---------------------------------------------------------------------------


async def test_register_system_for_guild_creates_row(db_session):
    """register_system_for_guild inserts a System row with correct fields."""
    from bot.main import register_system_for_guild

    guild = MagicMock()
    guild.id = 111111111
    guild.name = "Test Guild"
    guild.owner_id = 999999999

    await register_system_for_guild(guild, db_session)

    result = await db_session.execute(select(System).where(System.guild_id == "111111111"))
    sys = result.scalar_one()
    assert sys.name == "Test Guild"
    assert sys.owner_discord_id == "999999999"
    assert sys.sector_cap == 1


async def test_register_system_idempotent(db_session, sample_system):
    """Calling register_system_for_guild twice does not duplicate."""
    from bot.main import register_system_for_guild

    guild = MagicMock()
    guild.id = int(sample_system.guild_id)
    guild.name = sample_system.name
    guild.owner_id = int(sample_system.owner_discord_id)

    await register_system_for_guild(guild, db_session)
    await register_system_for_guild(guild, db_session)

    result = await db_session.execute(
        select(System).where(System.guild_id == sample_system.guild_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


async def test_reconcile_creates_missing_systems(db_session):
    """reconcile_systems_with_guilds inserts rows for guilds the bot is in but DB has not seen."""
    from bot.main import reconcile_systems_with_guilds

    guild_a = MagicMock(id=111, owner_id=999)
    guild_a.name = "A"
    guild_b = MagicMock(id=222, owner_id=999)
    guild_b.name = "B"

    await reconcile_systems_with_guilds([guild_a, guild_b], db_session)

    result = await db_session.execute(select(System).where(System.guild_id.in_(["111", "222"])))
    systems = result.scalars().all()
    assert {s.guild_id for s in systems} == {"111", "222"}


# ---------------------------------------------------------------------------
# Task 18 — sector/system admin command logic functions
# ---------------------------------------------------------------------------


async def test_sector_enable_creates_sector_when_under_cap(db_session, sample_system):
    """Admin can enable a sector when under cap."""
    from bot.cogs.admin import _sector_enable_logic

    interaction = MagicMock()
    interaction.guild_id = int(sample_system.guild_id)
    interaction.channel_id = 333333
    interaction.channel.name = "test-channel"
    interaction.user.guild_permissions.manage_channels = True

    result = await _sector_enable_logic(interaction, db_session)
    assert result.success is True

    sec = (
        await db_session.execute(select(Sector).where(Sector.channel_id == "333333"))
    ).scalar_one()
    assert sec.system_id == sample_system.guild_id


async def test_sector_enable_rejects_at_cap(db_session, sample_system, sample_sector):
    """When at cap, sector enable rejects."""
    from bot.cogs.admin import _sector_enable_logic

    # sample_system starts with sector_cap=1; sample_sector is already 1 enabled.
    interaction = MagicMock()
    interaction.guild_id = int(sample_system.guild_id)
    interaction.channel_id = 444444
    interaction.user.guild_permissions.manage_channels = True

    result = await _sector_enable_logic(interaction, db_session)
    assert result.success is False
    assert "cap" in result.message.lower() or "sustain" in result.message.lower()


async def test_sector_enable_rejects_non_admin(db_session, sample_system):
    """Non-admin gets permission rejection."""
    from bot.cogs.admin import _sector_enable_logic

    interaction = MagicMock()
    interaction.guild_id = int(sample_system.guild_id)
    interaction.channel_id = 555555
    interaction.user.guild_permissions.manage_channels = False

    result = await _sector_enable_logic(interaction, db_session)
    assert result.success is False
    assert "admin" in result.message.lower() or "permission" in result.message.lower()


async def test_sector_disable_removes_row(db_session, sample_system, sample_sector):
    """Disable removes the Sector row."""
    from bot.cogs.admin import _sector_disable_logic

    interaction = MagicMock()
    interaction.guild_id = int(sample_system.guild_id)
    interaction.channel_id = int(sample_sector.channel_id)
    interaction.user.guild_permissions.manage_channels = True

    result = await _sector_disable_logic(interaction, db_session)
    assert result.success is True
    sec = (
        await db_session.execute(
            select(Sector).where(Sector.channel_id == sample_sector.channel_id)
        )
    ).scalar_one_or_none()
    assert sec is None


async def test_system_admin_set_sector_cap_bot_owner_only(db_session, sample_system, monkeypatch):
    """Only bot owner can set sector cap."""
    from bot.cogs.admin import _set_sector_cap_logic

    monkeypatch.setattr("config.settings.settings.BOT_OWNER_DISCORD_ID", "999999999")

    interaction_owner = MagicMock()
    interaction_owner.user.id = 999999999
    interaction_owner.guild_id = int(sample_system.guild_id)

    result_ok = await _set_sector_cap_logic(interaction_owner, 5, db_session)
    assert result_ok.success is True

    interaction_other = MagicMock()
    interaction_other.user.id = 111
    interaction_other.guild_id = int(sample_system.guild_id)

    result_deny = await _set_sector_cap_logic(interaction_other, 10, db_session)
    assert result_deny.success is False
