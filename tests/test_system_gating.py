"""Tests for the system gating helper."""

from __future__ import annotations

from unittest.mock import MagicMock, create_autospec

import pytest

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
    """Profile, inventory, build management, etc. are universe-wide —
    a player can manage their builds from any channel the bot is in."""
    for cmd in {
        "profile",
        "inventory",
        "help",
        "start",
        "skip_tutorial",
        "hangar",
        "equip",
        "autoequip",
        "preview",
        "mint",
    }:
        assert cmd in UNIVERSE_WIDE_COMMANDS


def test_known_system_gated_commands_listed():
    """Competition and economy commands require an enabled system."""
    for cmd in {
        "race",
        "multirace",
        "leaderboard",
        "wrecks",
        "pack",
        "daily",
        "market",
        "list",
        "buy",
        "trade",
        "shop",
        "shop_buy",
        "salvage",
    }:
        assert cmd in SYSTEM_GATED_COMMANDS


def test_requires_system_helper():
    """requires_system('race') returns True; requires_system('profile') returns False."""
    assert requires_system("race") is True
    assert requires_system("profile") is False


async def test_create_autospec_get_active_system_enforces_signature():
    """Document the mock idiom that catches signature drift on get_active_system.

    Cog tests mock get_active_system. If the signature changes (as it did when
    the `session` parameter was added — see PR #18), an AsyncMock(return_value=...)
    accepts ANY call shape, so the cog tests pass while production crashes with
    TypeError. create_autospec(func) is the right tool: it inspects the real
    function and rejects calls that don't match its signature.

    This test fails if the idiom regresses (e.g. if a refactor switches to a
    looser mock helper that no longer enforces signature).
    """
    mock = create_autospec(get_active_system, return_value="ok")

    # Correct call shape: succeeds.
    assert await mock(MagicMock(), MagicMock()) == "ok"

    # Wrong call shape: must TypeError, not silently return "ok".
    with pytest.raises(TypeError):
        await mock(MagicMock())  # missing session
    with pytest.raises(TypeError):
        await mock(MagicMock(), MagicMock(), MagicMock())  # too many args
