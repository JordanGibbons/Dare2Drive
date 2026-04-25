"""Smoke test: tutorial pack-reveal flow uses PartRevealEntry correctly."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_card(name: str = "Test Part", rarity: str = "common", slot: str = "engine") -> MagicMock:
    card = MagicMock()
    card.name = name
    card.slot = MagicMock()
    card.slot.value = slot
    card.rarity = MagicMock()
    card.rarity.value = rarity
    card.stats = {"primary": {"power": 10}, "secondary": {"durability": 10}}
    card.print_max = None
    return card


def _make_uc(serial: int = 1) -> MagicMock:
    uc = MagicMock()
    uc.serial_number = serial
    return uc


@pytest.mark.asyncio
async def test_tutorial_can_construct_pack_reveal_for_starter_cards():
    """Locks in fix for the Phase 1 _PackRevealView refactor break in tutorial.py."""
    from bot.cogs.cards import _PackRevealView
    from bot.reveal import PartRevealEntry

    # Mimic tutorial.py's starter-card adapter logic
    starter_cards = [_make_card(name=f"Card {i}") for i in range(3)]
    starter_entries = [
        PartRevealEntry(
            name=card.name,
            rarity=card.rarity.value,
            slot=card.slot.value,
            serial_number=0,
            print_max=card.print_max,
            primary_stats=card.stats.get("primary", {}),
            secondary_stats=card.stats.get("secondary", {}),
        )
        for card in starter_cards
    ]
    view = _PackRevealView(entries=starter_entries, display_name="Starter Parts", owner_id=42)
    embed = view.build_embed()
    assert embed.title is not None  # didn't crash building


@pytest.mark.asyncio
async def test_tutorial_can_construct_pack_reveal_for_pack_cards():
    """Locks in fix for the Phase 1 _PackRevealView refactor break in tutorial.py."""
    from bot.cogs.cards import _PackRevealView
    from bot.reveal import PartRevealEntry

    # Mimic tutorial.py's pack-card adapter logic
    pack_cards = [(_make_card(name=f"Pack Card {i}"), _make_uc(serial=i)) for i in range(3)]
    pack_entries = [
        PartRevealEntry(
            name=card.name,
            rarity=card.rarity.value,
            slot=card.slot.value,
            serial_number=uc.serial_number,
            print_max=card.print_max,
            primary_stats=card.stats.get("primary", {}),
            secondary_stats=card.stats.get("secondary", {}),
        )
        for card, uc in pack_cards
    ]
    view = _PackRevealView(entries=pack_entries, display_name="Salvage Crate", owner_id=42)
    embed = view.build_embed()
    assert embed.title is not None
