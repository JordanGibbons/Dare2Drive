"""Scenario: a player's inventory is visible from any guild.

Phase 0's multi-tenant model deliberately keeps user state (User,
UserCard, Build, ShipTitle, ...) universe-wide — there is no FK from
those tables to Sector or System. This asserts the claim by calling
/inventory from two different guild_ids and seeing the same cards.
"""

from __future__ import annotations

import pytest

from bot.cogs.cards import CardsCog

from .conftest import make_interaction


@pytest.mark.asyncio
async def test_inventory_visible_across_guilds(fresh_player) -> None:
    """/inventory called from guild A returns the same cards as from guild B."""
    user_id, _ = fresh_player
    cards = CardsCog(bot=None)  # type: ignore[arg-type]

    # Call from two different guild/channel pairs
    inv_a = make_interaction(int(user_id), guild_id=100001, channel_id=200001)
    inv_b = make_interaction(int(user_id), guild_id=100002, channel_id=200002)

    await cards.inventory.callback(cards, inv_a)
    await cards.inventory.callback(cards, inv_b)

    # Neither should say "empty" — seeds are universe-wide
    assert (
        "inventory is empty" not in inv_a.all_content()
    ), f"Inventory A reported empty: {inv_a.calls}"
    assert (
        "inventory is empty" not in inv_b.all_content()
    ), f"Inventory B reported empty: {inv_b.calls}"

    # Both calls produced a response (non-empty calls list)
    assert inv_a.calls and inv_b.calls
