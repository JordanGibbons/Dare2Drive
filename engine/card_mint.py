"""Card minting — serial numbers and stat variance rolls."""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import Card, UserCard

log = get_logger(__name__)

# Each stat gets an independent roll within this range (±5%)
STAT_VARIANCE_RANGE = 0.05


def roll_stat_modifiers(base_stats: dict[str, Any]) -> dict[str, dict[str, float]]:
    """
    Roll per-stat percentage modifiers for a new card copy.

    Returns a dict mirroring the base_stats structure but with float modifiers
    in the range [-STAT_VARIANCE_RANGE, +STAT_VARIANCE_RANGE].
    e.g. {"primary": {"power": 0.03, "torque": -0.02}, "secondary": {"durability": 0.01}}
    """
    modifiers: dict[str, dict[str, float]] = {}
    for section in ("primary", "secondary"):
        section_stats = base_stats.get(section, {})
        if not section_stats:
            continue
        mods: dict[str, float] = {}
        for stat_name, value in section_stats.items():
            if not isinstance(value, (int, float)):
                continue
            mods[stat_name] = round(random.uniform(-STAT_VARIANCE_RANGE, STAT_VARIANCE_RANGE), 4)
        if mods:
            modifiers[section] = mods
    return modifiers


async def mint_card(
    session: AsyncSession, user_id: str, card: Card, is_foil: bool = False
) -> UserCard:
    """
    Mint a new individual copy of a card for a user.

    - Increments card.total_minted
    - Assigns the next serial number
    - Rolls random stat modifiers (±5% per stat)
    - Creates and returns the new UserCard row
    """
    card.total_minted += 1
    serial = card.total_minted

    modifiers = roll_stat_modifiers(card.stats)

    uc = UserCard(
        user_id=user_id,
        card_id=card.id,
        serial_number=serial,
        stat_modifiers=modifiers,
        is_foil=is_foil,
    )
    session.add(uc)
    await session.flush()

    log.debug(
        "Minted %s #%d for user %s (foil=%s)",
        card.name,
        serial,
        user_id,
        is_foil,
    )
    return uc


async def mint_tutorial_card(session: AsyncSession, user_id: str, card: Card) -> UserCard:
    """
    Mint a temporary tutorial card copy.

    - serial_number = 0 (marks it as a dummy/tutorial card)
    - Does NOT increment card.total_minted
    - No stat variance — uses base stats as-is
    """
    uc = UserCard(
        user_id=user_id,
        card_id=card.id,
        serial_number=0,
        stat_modifiers={},
        is_foil=False,
    )
    session.add(uc)
    await session.flush()

    log.debug("Minted TUTORIAL copy of %s for user %s", card.name, user_id)
    return uc


async def delete_tutorial_cards(session: AsyncSession, user_id: str) -> int:
    """
    Delete all tutorial cards (serial_number=0) for a user and clear them from builds.

    Returns the number of cards deleted.
    """
    from db.models import Build

    # Find all tutorial copies
    result = await session.execute(
        select(UserCard).where(
            UserCard.user_id == user_id,
            UserCard.serial_number == 0,
        )
    )
    tutorial_cards = list(result.scalars().all())
    if not tutorial_cards:
        return 0

    tutorial_ids = {str(uc.id) for uc in tutorial_cards}

    # Clear from active build slots
    build_result = await session.execute(
        select(Build).where(Build.user_id == user_id, Build.is_active)
    )
    build = build_result.scalar_one_or_none()
    if build:
        new_slots = dict(build.slots)
        changed = False
        for slot_name, uc_id in new_slots.items():
            if uc_id in tutorial_ids:
                new_slots[slot_name] = None
                changed = True
        if changed:
            build.slots = new_slots

    # Delete the tutorial cards
    for uc in tutorial_cards:
        await session.delete(uc)

    log.debug("Deleted %d tutorial cards for user %s", len(tutorial_cards), user_id)
    return len(tutorial_cards)


def degrade_stat_modifiers(
    modifiers: dict[str, dict[str, float]],
    severity: float = 0.005,
) -> dict[str, dict[str, float]]:
    """
    Degrade per-copy stat modifiers by a small amount after a race.

    severity: how much to subtract from each modifier per race.
    A card that starts at +0.05 will slowly drift toward 0 and then negative.
    Returns a new modifiers dict.
    """
    degraded: dict[str, dict[str, float]] = {}
    for section, mods in modifiers.items():
        new_mods: dict[str, float] = {}
        for stat_name, value in mods.items():
            new_mods[stat_name] = round(value - severity, 4)
        degraded[section] = new_mods
    return degraded


def apply_stat_modifiers(
    base_stats: dict[str, Any], modifiers: dict[str, dict[str, float]]
) -> dict[str, Any]:
    """
    Apply per-copy stat modifiers to base card stats.

    Returns a new stats dict with adjusted values.
    """
    result: dict[str, Any] = {}
    for section in ("primary", "secondary"):
        base_section = base_stats.get(section, {})
        mod_section = modifiers.get(section, {})
        adjusted: dict[str, Any] = {}
        for stat_name, value in base_section.items():
            if isinstance(value, (int, float)) and stat_name in mod_section:
                modifier = mod_section[stat_name]
                adjusted[stat_name] = round(value * (1 + modifier), 2)
            else:
                adjusted[stat_name] = value
        result[section] = adjusted
    return result
