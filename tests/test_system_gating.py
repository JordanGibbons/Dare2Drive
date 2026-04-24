"""Tests for the system gating helper."""

from __future__ import annotations

from unittest.mock import MagicMock

from bot.system_gating import (
    SYSTEM_GATED_COMMANDS,
    UNIVERSE_WIDE_COMMANDS,
    get_active_system,
    requires_system,
)


async def test_get_active_system_returns_system_when_enabled(db_session, sample_system):
    """When the channel is an enabled system, the helper returns the System row."""
    interaction = MagicMock()
    interaction.channel_id = int(sample_system.channel_id)
    interaction.guild_id = int(sample_system.sector_id)

    result = await get_active_system(interaction, db_session)
    assert result is not None
    assert result.channel_id == sample_system.channel_id


async def test_get_active_system_returns_none_for_unregistered_channel(db_session, sample_sector):
    """An unregistered channel returns None."""
    interaction = MagicMock()
    interaction.channel_id = 999999
    interaction.guild_id = int(sample_sector.guild_id)

    result = await get_active_system(interaction, db_session)
    assert result is None


async def test_get_active_system_returns_none_in_dm(db_session):
    """A DM (no guild) returns None."""
    interaction = MagicMock()
    interaction.channel_id = 12345
    interaction.guild_id = None

    result = await get_active_system(interaction, db_session)
    assert result is None


def test_command_registries_are_disjoint():
    """A command can't be both universe-wide and system-gated."""
    assert UNIVERSE_WIDE_COMMANDS.isdisjoint(SYSTEM_GATED_COMMANDS)


def test_known_universe_wide_commands_listed():
    """Profile, inventory, help, etc. are universe-wide."""
    for cmd in {"profile", "inventory", "help", "start", "skip_tutorial"}:
        assert cmd in UNIVERSE_WIDE_COMMANDS


def test_known_system_gated_commands_listed():
    """Race, pack, equip, etc. require an enabled system."""
    for cmd in {"race", "pack", "equip", "autoequip", "preview", "mint"}:
        assert cmd in SYSTEM_GATED_COMMANDS


def test_requires_system_helper():
    """requires_system('race') returns True; requires_system('profile') returns False."""
    assert requires_system("race") is True
    assert requires_system("profile") is False
