"""Scenario: gameplay commands refuse to run outside an enabled System.

The post-phase-0 multi-tenant model says that gameplay-flavored
commands (/pack, /race, /daily, etc.) should only work in channels a
server admin has explicitly enabled via /system_enable. Universe-wide
commands (/inventory, /profile, /start) work anywhere.

This test exercises both halves of the gate in one run.
"""

from __future__ import annotations

import pytest

from bot.cogs.cards import CardsCog
from bot.cogs.market import MarketCog
from bot.cogs.race import RaceCog
from bot.system_gating import SYSTEM_GATED_COMMANDS, system_required_message

from .conftest import make_interaction


@pytest.mark.asyncio
async def test_gated_command_refused_without_active_system(fresh_player) -> None:
    """Without an `active_system` fixture, /pack must refuse with the gating message."""
    user_id, _ = fresh_player
    cards = CardsCog(bot=None)  # type: ignore[arg-type]

    pack_call = make_interaction(int(user_id))
    await cards.pack.callback(cards, pack_call, pack_type="salvage_crate")

    assert (
        system_required_message() in pack_call.all_content()
    ), f"Expected gating message, got: {pack_call.calls}"


@pytest.mark.asyncio
async def test_universe_wide_command_works_without_active_system(fresh_player) -> None:
    """/inventory is universe-wide and must work in an unregistered channel."""
    user_id, _ = fresh_player
    cards = CardsCog(bot=None)  # type: ignore[arg-type]

    inv = make_interaction(int(user_id))
    await cards.inventory.callback(cards, inv)

    # Should NOT get the system-gate refusal message
    assert (
        system_required_message() not in inv.all_content()
    ), "Universe-wide command got the system-gating refusal incorrectly"
    # AND inventory should have content (starter cards)
    assert inv.calls, "inventory handler produced no response at all"


@pytest.mark.asyncio
async def test_gated_command_works_inside_active_system(fresh_player, active_system) -> None:
    """With an active_system matching the interaction's channel, /pack proceeds
    past the gate check. It may still fail for insufficient Creds (fresh_player
    starts with 0) — we only assert the system-gate was not the reason."""
    user_id, _ = fresh_player
    cards = CardsCog(bot=None)  # type: ignore[arg-type]

    pack = make_interaction(int(user_id))
    await cards.pack.callback(cards, pack, pack_type="salvage_crate")

    assert (
        system_required_message() not in pack.all_content()
    ), f"Gate rejected a command inside an active system: {pack.calls}"


# ──────────────────────────────────────────────────────────────────────
# Regression matrix: every command in SYSTEM_GATED_COMMANDS actually enforces
# ──────────────────────────────────────────────────────────────────────
#
# SYSTEM_GATED_COMMANDS is the declaration of which slash commands require an
# active System. This test ensures each entry's handler actually enforces it.
# If a new gated command is added to the set, add a case here or the coverage
# meta-test below will fail.
#
# (command_name, cog_class, handler_attr, kwargs_for_handler). "challenge" is
# declared in SYSTEM_GATED_COMMANDS but no slash command by that name exists
# in the cogs — it's a dead entry, handled in the coverage assertion below.


class _FakeMember:
    """Minimal stand-in for discord.Member used as /trade target."""

    def __init__(self, user_id: int = 777777777) -> None:
        self.id = user_id
        self.bot = False
        self.display_name = "TradePartner"


GATED_CASES = [
    ("pack", CardsCog, "pack", {"pack_type": "salvage_crate"}),
    ("daily", CardsCog, "daily", {}),
    (
        "race",
        RaceCog,
        "race",
        {
            "opponent": None,
            "wager": 0,
            "race_format": "sprint",
            "race_hull": None,
            "build": None,
        },
    ),
    ("multirace", RaceCog, "multirace", {"wager": 0}),
    ("leaderboard", RaceCog, "leaderboard", {}),
    ("wrecks", RaceCog, "wrecks", {}),
    ("market", MarketCog, "market", {}),
    ("list", MarketCog, "list_card", {"card_name": "Rustbucket Reactor", "price": 100}),
    ("buy", MarketCog, "buy", {"card_name": "Rustbucket Reactor"}),
    (
        "trade",
        MarketCog,
        "trade",
        {
            "target": _FakeMember(),
            "your_card": "Rustbucket Reactor",
            "their_card": "Clunker Drive",
        },
    ),
    ("shop", MarketCog, "shop", {}),
    ("shop_buy", MarketCog, "shop_buy", {"slot": "reactor"}),
    ("salvage", MarketCog, "salvage", {"card_name": "Rustbucket Reactor"}),
]

# Entries declared in SYSTEM_GATED_COMMANDS but without a live slash command.
# Empty for now — all current entries have corresponding handlers.
_DEAD_ENTRIES: set[str] = set()


def test_every_gated_command_has_a_regression_case() -> None:
    """If a new entry is added to SYSTEM_GATED_COMMANDS, this test forces the
    developer to add a regression case (or mark it dead) so drift is caught."""
    covered = {name for name, *_ in GATED_CASES}
    expected = set(SYSTEM_GATED_COMMANDS) - _DEAD_ENTRIES
    missing = expected - covered
    assert not missing, (
        f"SYSTEM_GATED_COMMANDS entries without a regression case: {sorted(missing)}. "
        "Add a case to GATED_CASES in tests/test_scenarios/test_system_gating.py."
    )


@pytest.mark.parametrize(
    "name,cog_cls,handler_attr,kwargs", GATED_CASES, ids=lambda v: v if isinstance(v, str) else ""
)
@pytest.mark.asyncio
async def test_every_gated_command_enforces_the_gate(
    fresh_player, name, cog_cls, handler_attr, kwargs
) -> None:
    """Every declared-gated command must refuse outside an active_system.
    Catches the phase-0 drift where some hangar handlers were in the
    SYSTEM_GATED_COMMANDS set but didn't actually call get_active_system."""
    user_id, _ = fresh_player
    cog = cog_cls(bot=None)  # type: ignore[arg-type]

    handler = getattr(cog, handler_attr)
    interaction = make_interaction(int(user_id))
    await handler.callback(cog, interaction, **kwargs)

    assert (
        system_required_message() in interaction.all_content()
    ), f"/{name} did not enforce the system gate. responses: {interaction.calls}"
