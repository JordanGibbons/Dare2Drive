"""Scenario: a new player walks /inventory → /equip ×7 → /build mint.

Catches the class of integration bugs that unit tests miss — missing
seed data, misaligned slot enum values, missing bootstrap rows. The
real handlers are driven via .callback() against the live test
Postgres. Fixtures and Discord interaction mocks live in conftest.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from bot.cogs.cards import CardsCog
from bot.cogs.hangar import HangarCog
from db.models import Card, CardSlot, ShipTitle
from db.session import async_session

from .conftest import make_interaction


@pytest.mark.asyncio
async def test_new_player_can_reach_a_minted_ship_title(fresh_player) -> None:
    """/inventory → /equip ×7 → /build mint on a fresh account."""
    user_id, starters = fresh_player
    uid_int = int(user_id)

    hangar = HangarCog(bot=None)  # type: ignore[arg-type]
    cards = CardsCog(bot=None)  # type: ignore[arg-type]

    # 1. /inventory must show the starter cards, not "empty"
    inv = make_interaction(uid_int)
    await cards.inventory.callback(cards, inv)
    assert "inventory is empty" not in inv.all_content(), (
        "Inventory is empty — seed_cards or starter grant broken. " f"Calls: {inv.calls}"
    )

    # 2. /equip each slot with the matching starter card
    async with async_session() as session:
        for slot in CardSlot:
            uc = starters[slot.value]
            card = await session.get(Card, uc.card_id)
            eq = make_interaction(uid_int)
            await hangar.equip.callback(hangar, eq, slot=slot.value, card_name=card.name)
            assert eq.calls, f"/equip {slot.value}: no response recorded"

    # 3. /build mint must succeed now that all slots are filled + release exists
    mint = make_interaction(uid_int)
    await hangar.build_mint.callback(hangar, mint, build=None)

    content = mint.all_content()
    assert (
        "No active release found" not in content
    ), "seed_initial_release did not run or did not persist a Genesis ShipRelease"
    assert "Fill all 7 slots" not in content, "equip step did not complete all slots"

    # 4. Assert a ShipTitle row now exists for this user
    async with async_session() as session:
        result = await session.execute(select(ShipTitle).where(ShipTitle.owner_id == user_id))
        title = result.scalar_one_or_none()
        assert title is not None, f"No ShipTitle was created. responses: {mint.calls}"
        assert title.release_serial > 0
