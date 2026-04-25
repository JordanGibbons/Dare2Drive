"""Regression tests for the tutorial-gate allow-list.

The allow-list in `bot.cogs.tutorial.STEP_ALLOWED_COMMANDS` references commands
by their slash-command name (the name registered on `@app_commands.command`).
A rename of a command without a matching update to the allow-list silently
breaks the tutorial — `interaction_check` blocks the command and its
autocomplete, leaving the player stuck.

These tests catch that class of bug at import time.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.cogs.tutorial import STEP_ALLOWED_COMMANDS
from db.models import TutorialStep


def _all_registered_slash_command_names() -> set[str]:
    """Load every cog and collect the names of all registered app commands."""
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog_modules = [
        "bot.cogs.tutorial",
        "bot.cogs.cards",
        "bot.cogs.hangar",
        "bot.cogs.race",
        "bot.cogs.market",
        "bot.cogs.admin",
        "bot.cogs.hiring",
    ]
    import asyncio

    async def _load() -> None:
        for m in cog_modules:
            await bot.load_extension(m)

    asyncio.run(_load())
    return {c.name for c in bot.tree.walk_commands()}


def test_allow_list_only_references_real_command_names():
    """Every name in the allow-list must match a real registered slash command."""
    registered = _all_registered_slash_command_names()
    for step, allowed in STEP_ALLOWED_COMMANDS.items():
        bogus = allowed - registered
        assert not bogus, (
            f"TutorialStep.{step.name} allow-list references command(s) that "
            f"don't exist as slash commands: {bogus}. The command(s) may have "
            f"been renamed without updating the allow-list."
        )


def test_garage_step_allows_hangar_command():
    """Player on GARAGE step must be able to run /hangar (the inspection command)."""
    assert "hangar" in STEP_ALLOWED_COMMANDS[TutorialStep.GARAGE]


def test_race_step_allows_race_and_hangar():
    """Player on RACE step must be able to run /race (and /hangar to re-check)."""
    assert "race" in STEP_ALLOWED_COMMANDS[TutorialStep.RACE]
    assert "hangar" in STEP_ALLOWED_COMMANDS[TutorialStep.RACE]
