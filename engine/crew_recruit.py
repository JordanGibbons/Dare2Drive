"""Crew recruitment engine — archetype / rarity / name rolls + DB persist."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import CrewArchetype, CrewDailyLead, CrewMember, Rarity, User

log = get_logger(__name__)

_NAME_POOL_PATH = Path(__file__).resolve().parent.parent / "data" / "crew" / "name_pool.json"
_DOSSIER_TABLES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "crew" / "dossier_tables.json"
)

_name_pool_cache: dict[str, list[str]] | None = None
_dossier_tables_cache: dict[str, dict[str, Any]] | None = None


class InsufficientCreditsError(Exception):
    """Raised when a user lacks creds to buy a dossier."""


class NoDailyLeadError(Exception):
    """Raised when a user runs /hire without a rolled-and-unclaimed lead."""


class LeadAlreadyClaimedError(Exception):
    """Raised when /hire is run twice on the same day."""


@dataclass
class CrewRollResult:
    archetype: str
    rarity: str
    first_name: str
    last_name: str
    callsign: str


def _get_name_pool() -> dict[str, list[str]]:
    global _name_pool_cache
    if _name_pool_cache is None:
        with open(_NAME_POOL_PATH, "r", encoding="utf-8") as f:
            _name_pool_cache = json.load(f)
    return _name_pool_cache


def _get_dossier_tables() -> dict[str, dict[str, Any]]:
    global _dossier_tables_cache
    if _dossier_tables_cache is None:
        with open(_DOSSIER_TABLES_PATH, "r", encoding="utf-8") as f:
            _dossier_tables_cache = json.load(f)
    return _dossier_tables_cache


def _roll_name(
    existing_names: set[tuple[str, str, str]], max_attempts: int = 5
) -> tuple[str, str, str]:
    """Roll (first, last, callsign) avoiding collisions with `existing_names`.

    After `max_attempts` full rerolls, appends a numeric suffix to callsign
    until unique.
    """
    pool = _get_name_pool()
    for _ in range(max_attempts):
        triple = (
            random.choice(pool["first_names"]),
            random.choice(pool["last_names"]),
            random.choice(pool["callsigns"]),
        )
        if triple not in existing_names:
            return triple
    # Fallback: suffix the callsign
    base = (
        random.choice(pool["first_names"]),
        random.choice(pool["last_names"]),
        random.choice(pool["callsigns"]),
    )
    suffix = 2
    while (base[0], base[1], f"{base[2]}-{suffix}") in existing_names:
        suffix += 1
    return (base[0], base[1], f"{base[2]}-{suffix}")


def roll_crew(
    weights: dict[str, float],
    existing_names: set[tuple[str, str, str]],
) -> CrewRollResult:
    """Pure: roll archetype (uniform), rarity (weighted), name (unique-ish)."""
    archetype = random.choice([a.value for a in CrewArchetype])
    rarities = [r for r, w in weights.items() if w > 0]
    rarity_weights = [weights[r] for r in rarities]
    rarity = random.choices(rarities, weights=rarity_weights, k=1)[0]
    first, last, callsign = _roll_name(existing_names)
    return CrewRollResult(
        archetype=archetype,
        rarity=rarity,
        first_name=first,
        last_name=last,
        callsign=callsign,
    )


async def _load_existing_names(session: AsyncSession, user_id: str) -> set[tuple[str, str, str]]:
    result = await session.execute(
        select(CrewMember.first_name, CrewMember.last_name, CrewMember.callsign).where(
            CrewMember.user_id == user_id
        )
    )
    return {(r[0], r[1], r[2]) for r in result.all()}


async def recruit_crew_from_dossier(session: AsyncSession, user: User, tier: str) -> CrewMember:
    """Deduct creds, roll, persist a CrewMember.

    Raises `InsufficientCreditsError` if user can't afford the tier.
    Raises `KeyError` if tier is unknown.
    """
    tables = _get_dossier_tables()
    cfg = tables[tier]
    price = cfg["price"]
    if user.currency < price:
        raise InsufficientCreditsError(
            f"User {user.discord_id} has {user.currency} creds; needs {price}."
        )

    existing = await _load_existing_names(session, user.discord_id)
    roll = roll_crew(cfg["weights"], existing)
    user.currency -= price

    member = CrewMember(
        user_id=user.discord_id,
        first_name=roll.first_name,
        last_name=roll.last_name,
        callsign=roll.callsign,
        archetype=CrewArchetype(roll.archetype),
        rarity=Rarity(roll.rarity),
    )
    session.add(member)
    await session.flush()
    log.info(
        "crew recruited",
        extra={
            "event": "crew_recruited",
            "user_id": user.discord_id,
            "crew_id": str(member.id),
            "archetype": member.archetype.value,
            "rarity": member.rarity.value,
            "source": "dossier",
            "tier": tier,
        },
    )
    return member


async def recruit_crew_from_daily_lead(
    session: AsyncSession, user: User, lead: CrewDailyLead
) -> CrewMember:
    """Consume today's unclaimed lead, persist as CrewMember, stamp claimed_at.

    Raises `LeadAlreadyClaimedError` if already claimed.
    """
    if lead.claimed_at is not None:
        raise LeadAlreadyClaimedError(f"User {user.discord_id} already claimed today's lead.")

    member = CrewMember(
        user_id=user.discord_id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        callsign=lead.callsign,
        archetype=lead.archetype,
        rarity=lead.rarity,
    )
    session.add(member)
    lead.claimed_at = datetime.now(timezone.utc)
    await session.flush()
    log.info(
        "crew recruited",
        extra={
            "event": "crew_recruited",
            "user_id": user.discord_id,
            "crew_id": str(member.id),
            "archetype": member.archetype.value,
            "rarity": member.rarity.value,
            "source": "daily_lead",
        },
    )
    return member


async def get_or_roll_today_lead(
    session: AsyncSession, user: User, today: date | None = None
) -> CrewDailyLead:
    """Return today's lead, rolling one if not already present. Idempotent."""
    today = today or datetime.now(timezone.utc).date()
    existing = await session.get(CrewDailyLead, (user.discord_id, today))
    if existing is not None:
        return existing

    tables = _get_dossier_tables()
    weights = tables["recruit_lead"]["weights"]
    existing_names = await _load_existing_names(session, user.discord_id)
    roll = roll_crew(weights, existing_names)

    lead = CrewDailyLead(
        user_id=user.discord_id,
        rolled_for_date=today,
        archetype=CrewArchetype(roll.archetype),
        rarity=Rarity(roll.rarity),
        first_name=roll.first_name,
        last_name=roll.last_name,
        callsign=roll.callsign,
    )
    session.add(lead)
    await session.flush()
    return lead
