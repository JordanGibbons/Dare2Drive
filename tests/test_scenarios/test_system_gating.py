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
from bot.system_gating import system_required_message

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
