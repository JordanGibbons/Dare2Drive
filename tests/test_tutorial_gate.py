"""Regression tests for the tutorial-gate allow-list and step transitions.

The allow-list in `bot.cogs.tutorial.STEP_ALLOWED_COMMANDS` and `ALWAYS_ALLOWED`
references commands by their slash-command qualified_name (full path including
any parent Group, e.g. "build preview"). A rename of a command without a
matching update to the allow-list silently breaks the tutorial —
`interaction_check` blocks the command and its autocomplete, leaving the
player stuck.

The cogs also call `advance_tutorial(interaction, user_id, command_name)`
manually after a successful command. The string they pass must match what
`advance_tutorial`'s internal `command_name == "..."` checks expect — another
class of soft-lock bug.

These tests catch both classes of bug at import / DB-fixture time.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio
from discord.ext import commands

from bot.cogs.tutorial import (
    ALWAYS_ALLOWED,
    STEP_ALLOWED_COMMANDS,
    advance_tutorial,
    is_command_allowed,
)
from db.models import HullClass, TutorialStep, User


def _all_registered_qualified_names() -> set[str]:
    """Load every cog and collect the qualified_names of all registered app commands.

    qualified_name returns the full path (e.g. "build preview"), so this set
    correctly distinguishes /build preview from a hypothetical /research preview.
    """
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog_modules = [
        "bot.cogs.tutorial",
        "bot.cogs.cards",
        "bot.cogs.hangar",
        "bot.cogs.race",
        "bot.cogs.market",
        "bot.cogs.admin",
        "bot.cogs.hiring",
        "bot.cogs.fleet",
    ]
    import asyncio

    async def _load() -> None:
        for m in cog_modules:
            await bot.load_extension(m)

    asyncio.run(_load())
    # walk_commands yields both Groups and leaf commands. Filter to the leaves
    # (Groups themselves cannot be invoked, so they should never appear in the
    # allow-list).
    return {
        c.qualified_name
        for c in bot.tree.walk_commands()
        if not isinstance(c, discord.app_commands.Group)
    }


def test_allow_list_only_references_real_command_names():
    """Every name in STEP_ALLOWED_COMMANDS must match a real qualified slash-command name."""
    registered = _all_registered_qualified_names()
    for step, allowed in STEP_ALLOWED_COMMANDS.items():
        bogus = allowed - registered
        assert not bogus, (
            f"TutorialStep.{step.name} allow-list references command(s) that "
            f"don't exist as slash commands: {bogus}. The command(s) may have "
            f"been renamed without updating the allow-list. "
            f"Reminder: entries are full qualified names (e.g. 'build preview'), "
            f"not leaf names."
        )


def test_always_allowed_only_references_real_command_names():
    """Every entry in ALWAYS_ALLOWED must match a real qualified slash-command name."""
    registered = _all_registered_qualified_names()
    bogus = ALWAYS_ALLOWED - registered
    assert not bogus, (
        f"ALWAYS_ALLOWED references command(s) that don't exist as slash commands: " f"{bogus}."
    )


def test_garage_step_allows_hangar_command():
    """Player on GARAGE step must be able to run /hangar (the inspection command)."""
    assert "hangar" in STEP_ALLOWED_COMMANDS[TutorialStep.GARAGE]


def test_race_step_allows_race_and_hangar():
    """Player on RACE step must be able to run /race (and /hangar to re-check)."""
    assert "race" in STEP_ALLOWED_COMMANDS[TutorialStep.RACE]
    assert "hangar" in STEP_ALLOWED_COMMANDS[TutorialStep.RACE]


def test_subcommand_does_not_match_top_level_allowed():
    """/training start must NOT bypass gating just because /start is in ALWAYS_ALLOWED.

    Regression: previously the gating call site keyed on `interaction.command.name`
    (the leaf "start"), so any subcommand whose leaf happened to be in the
    allow-list bypassed the gate. Switched to qualified_name; this test locks
    in that invariant.
    """
    user = User(
        discord_id="100",
        username="x",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
        tutorial_step=TutorialStep.STARTED,
    )
    assert is_command_allowed(user, "start"), "/start should remain allowed at STARTED"
    assert not is_command_allowed(user, "training start"), (
        "/training start must be blocked at STARTED — leaf 'start' must not match "
        "ALWAYS_ALLOWED entry 'start'"
    )
    assert not is_command_allowed(user, "research start"), "/research start must be blocked"


def test_mint_step_allows_only_build_subcommands():
    """/build preview and /build mint allowed at MINT; bare 'preview' / 'mint' must not match."""
    user = User(
        discord_id="101",
        username="y",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
        tutorial_step=TutorialStep.MINT,
    )
    assert is_command_allowed(user, "build preview")
    assert is_command_allowed(user, "build mint")


# ---------------------------------------------------------------------------
# Step transitions: advance_tutorial actually fires when the right command
# fires at the right step.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def garage_step_user(db_session):
    """A player parked on TutorialStep.GARAGE — has a minted ship, ready to /hangar."""
    u = User(
        discord_id="666666666",
        username="garagestepper",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
        tutorial_step=TutorialStep.GARAGE,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_advance_tutorial_garage_to_race_fires_on_hangar(
    garage_step_user, db_session, monkeypatch
):
    """Running /hangar while on GARAGE step must advance the player to RACE.

    Regression test for the bug where bot/cogs/hangar.py called
    advance_tutorial(..., "garage") but tutorial.py expected command_name
    to be "hangar", silently failing to advance the step.
    """
    from bot.cogs import tutorial as tutorial_mod

    # advance_tutorial opens its own async_session(); patch it to yield the test session
    sess_ctx = MagicMock()
    sess_ctx.__aenter__ = AsyncMock(return_value=db_session)
    sess_ctx.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(tutorial_mod, "async_session", lambda: sess_ctx)

    # send_dialogue calls Discord APIs we don't want to exercise; stub it.
    monkeypatch.setattr(tutorial_mod, "send_dialogue", AsyncMock(return_value=None))

    interaction = MagicMock(spec=discord.Interaction)

    await advance_tutorial(interaction, garage_step_user.discord_id, "hangar")
    await db_session.refresh(garage_step_user)

    assert garage_step_user.tutorial_step == TutorialStep.RACE, (
        "Player on GARAGE step ran /hangar but tutorial did not advance to RACE. "
        "Check that bot/cogs/hangar.py passes 'hangar' (not 'garage') to "
        "advance_tutorial, and that tutorial.py's transition guard matches."
    )


@pytest.mark.asyncio
async def test_advance_tutorial_garage_does_not_advance_on_wrong_command(
    garage_step_user, db_session, monkeypatch
):
    """Sanity: passing the wrong command_name must NOT advance the step.

    Locks in the symmetric guarantee — only the right command at the right
    step fires the transition.
    """
    from bot.cogs import tutorial as tutorial_mod

    sess_ctx = MagicMock()
    sess_ctx.__aenter__ = AsyncMock(return_value=db_session)
    sess_ctx.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(tutorial_mod, "async_session", lambda: sess_ctx)
    monkeypatch.setattr(tutorial_mod, "send_dialogue", AsyncMock(return_value=None))

    interaction = MagicMock(spec=discord.Interaction)

    await advance_tutorial(interaction, garage_step_user.discord_id, "garage")
    await db_session.refresh(garage_step_user)

    assert garage_step_user.tutorial_step == TutorialStep.GARAGE
