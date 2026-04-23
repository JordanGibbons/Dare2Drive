"""Tests for the sector gating helper."""

from __future__ import annotations

from unittest.mock import MagicMock

from bot.sector_gating import (
    SECTOR_GATED_COMMANDS,
    UNIVERSE_WIDE_COMMANDS,
    get_active_sector,
    requires_sector,
)


async def test_get_active_sector_returns_sector_when_enabled(db_session, sample_sector):
    """When the channel is an enabled sector, the helper returns the Sector row."""
    interaction = MagicMock()
    interaction.channel_id = int(sample_sector.channel_id)
    interaction.guild_id = int(sample_sector.system_id)

    result = await get_active_sector(interaction, db_session)
    assert result is not None
    assert result.channel_id == sample_sector.channel_id


async def test_get_active_sector_returns_none_for_unregistered_channel(db_session, sample_system):
    """An unregistered channel returns None."""
    interaction = MagicMock()
    interaction.channel_id = 999999
    interaction.guild_id = int(sample_system.guild_id)

    result = await get_active_sector(interaction, db_session)
    assert result is None


async def test_get_active_sector_returns_none_in_dm(db_session):
    """A DM (no guild) returns None."""
    interaction = MagicMock()
    interaction.channel_id = 12345
    interaction.guild_id = None

    result = await get_active_sector(interaction, db_session)
    assert result is None


def test_command_registries_are_disjoint():
    """A command can't be both universe-wide and sector-gated."""
    assert UNIVERSE_WIDE_COMMANDS.isdisjoint(SECTOR_GATED_COMMANDS)


def test_known_universe_wide_commands_listed():
    """Profile, inventory, help, etc. are universe-wide."""
    for cmd in {"profile", "inventory", "help", "start", "skip_tutorial"}:
        assert cmd in UNIVERSE_WIDE_COMMANDS


def test_known_sector_gated_commands_listed():
    """Race, pack, equip, etc. require an enabled sector."""
    for cmd in {"race", "pack", "equip", "autoequip", "preview", "mint"}:
        assert cmd in SECTOR_GATED_COMMANDS


def test_requires_sector_helper():
    """requires_sector('race') returns True; requires_sector('profile') returns False."""
    assert requires_sector("race") is True
    assert requires_sector("profile") is False
