"""Stat namespace registry for expedition templates.

Single source of truth for what `roll.stat` and `requires.stat` may reference.
Consumed by:
  - engine/expedition_engine.py — at resolution time, to read the value
  - engine/expedition_template.py — at validation time, to reject unknown keys
  - scripts/build_authoring_docs.py — to regenerate the docs reference table
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Build,
    Card,
    CrewArchetype,
    CrewMember,
    ExpeditionCrewAssignment,
    UserCard,
)

if TYPE_CHECKING:
    from db.models import Expedition

# Per-archetype stat namespaces. Each archetype's stat list is the union
# of stats meaningful to that archetype's events. Adding a new stat here
# is a one-line change; the doc generator picks it up automatically.
_CREW_STATS: dict[str, tuple[str, ...]] = {
    "pilot": ("acceleration", "handling", "luck"),
    "gunner": ("combat", "luck"),
    "engineer": ("repair", "luck"),
    "navigator": ("luck", "perception"),
}

# Ship-resolved stats. These flow through engine/stat_resolver.py.
_SHIP_STATS: tuple[str, ...] = (
    "acceleration",
    "durability",
    "power",
    "weather_performance",
)

# Aggregate / derived crew keys.
_CREW_AGGREGATE: tuple[str, ...] = ("avg_level", "count")


def _build_known_stat_keys() -> frozenset[str]:
    keys: set[str] = set()
    for archetype, stats in _CREW_STATS.items():
        for stat in stats:
            keys.add(f"{archetype}.{stat}")
    for stat in _SHIP_STATS:
        keys.add(f"ship.{stat}")
    for stat in _CREW_AGGREGATE:
        keys.add(f"crew.{stat}")
    return frozenset(keys)


KNOWN_STAT_KEYS: frozenset[str] = _build_known_stat_keys()


_ARCHETYPE_BY_PREFIX: dict[str, str] = {
    "pilot": "PILOT",
    "gunner": "GUNNER",
    "engineer": "ENGINEER",
    "navigator": "NAVIGATOR",
}


def is_known_stat(key: str) -> bool:
    """True iff `key` is a published stat namespace entry."""
    return key in KNOWN_STAT_KEYS


def archetype_for_stat(key: str) -> str | None:
    """Return the implicit archetype gate for a crew-specific stat key.

    e.g. 'pilot.acceleration' → 'PILOT'.
    Non-crew keys (ship.*, crew.*) return None.
    """
    if "." not in key:
        return None
    prefix, _ = key.split(".", 1)
    return _ARCHETYPE_BY_PREFIX.get(prefix)


async def read_stat(
    session: AsyncSession,
    expedition: "Expedition",
    key: str,
) -> float | int | None:
    """Read the live value of a stat namespace key for an expedition.

    Returns None if the key is unassigned (e.g., 'gunner.combat' when no
    GUNNER is on this expedition). Callers should treat None as
    'this choice is hidden / not applicable.'
    """
    if not is_known_stat(key):
        raise ValueError(f"unknown stat key: {key}")

    if "." not in key:
        return None
    prefix, stat = key.split(".", 1)

    if prefix == "ship":
        # Resolve ship stats via the existing stat_resolver, loading card data
        # from the DB for the expedition's locked build.
        resolved = await _resolve_ship_stats(session, expedition.build_id)
        return resolved.get(stat)

    if prefix == "crew":
        if stat == "count":
            return await _crew_count(session, expedition.id)
        if stat == "avg_level":
            return await _crew_avg_level(session, expedition.id)
        return None

    # Per-archetype crew stat: load the assigned crew of that archetype.
    archetype = _ARCHETYPE_BY_PREFIX[prefix]
    crew = await _assigned_crew(session, expedition.id, archetype)
    if crew is None:
        return None
    return _crew_stat_value(crew, stat)


async def _resolve_ship_stats(
    session: AsyncSession,
    build_id: uuid.UUID,
) -> dict[str, float]:
    """Load a build's equipped cards from DB and return a flat stat dict.

    Keys match the _SHIP_STATS tuple (e.g. 'durability', 'acceleration').
    Uses engine.stat_resolver.aggregate_build under the hood; maps the
    resulting BuildStats.effective_* fields to unadorned stat names.
    """
    from engine.card_mint import apply_stat_modifiers
    from engine.stat_resolver import aggregate_build

    build = await session.get(Build, build_id)
    if build is None:
        return {}

    hull_class = build.hull_class
    slots: dict[str, str | None] = build.slots or {}

    # Load card data for each equipped slot
    cards: dict[str, dict] = {}
    for slot_name, uc_id_str in slots.items():
        if not uc_id_str:
            continue
        try:
            uc_id = uuid.UUID(uc_id_str)
        except (ValueError, AttributeError):
            continue
        uc = await session.get(UserCard, uc_id)
        if not uc:
            continue
        card = await session.get(Card, uc.card_id)
        if not card:
            continue
        effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})
        cards[uc_id_str] = {"slot": card.slot.value, "stats": effective_stats}

    bs = aggregate_build(
        slots,
        cards,
        hull_class=hull_class.value if hull_class else None,
    )

    # Map effective_* fields → plain stat names for the namespace
    return {
        "acceleration": bs.effective_acceleration,
        "durability": bs.effective_durability,
        "power": bs.effective_power,
        "weather_performance": bs.effective_weather_performance,
    }


async def _assigned_crew(
    session: AsyncSession, expedition_id: uuid.UUID, archetype_str: str
) -> CrewMember | None:
    """Return the assigned crew of the given archetype, or None."""
    archetype = CrewArchetype(archetype_str.lower())
    result = await session.execute(
        select(CrewMember)
        .join(ExpeditionCrewAssignment, ExpeditionCrewAssignment.crew_id == CrewMember.id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
        .where(ExpeditionCrewAssignment.archetype == archetype)
    )
    return result.scalar_one_or_none()


def _crew_stat_value(crew: CrewMember, stat: str) -> float | int | None:
    """Read a stat off a crew row.

    CrewMember stores stats as a JSON dict in the `stats` JSONB column.
    Shape: {"acceleration": 70, "luck": 40, ...}
    """
    stats = getattr(crew, "stats", None) or {}
    return stats.get(stat)


async def _crew_count(session: AsyncSession, expedition_id: uuid.UUID) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.count())
        .select_from(ExpeditionCrewAssignment)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
    )
    return int(result.scalar_one() or 0)


async def _crew_avg_level(session: AsyncSession, expedition_id: uuid.UUID) -> float:
    from sqlalchemy import func

    result = await session.execute(
        select(func.avg(CrewMember.level))
        .select_from(ExpeditionCrewAssignment)
        .join(CrewMember, CrewMember.id == ExpeditionCrewAssignment.crew_id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
    )
    val = result.scalar_one()
    return float(val) if val is not None else 0.0
