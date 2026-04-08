"""Rig namer — generates evocative names for Car Titles based on class, body type, and stats."""

from __future__ import annotations

import json
import random
from pathlib import Path

from db.models import BodyType, CarClass
from engine.stat_resolver import BuildStats

_NAMES_PATH = Path(__file__).resolve().parent.parent / "data" / "rig_names.json"

_names_cache: dict | None = None


def _get_pools() -> dict:
    global _names_cache
    if _names_cache is None:
        with open(_NAMES_PATH, "r", encoding="utf-8") as f:
            _names_cache = json.load(f)
    return _names_cache


def generate_rig_name(
    car_class: CarClass,
    body_type: BodyType | None,
    stats: BuildStats | None = None,
) -> str:
    """
    Generate an evocative two-word name for a rig title.

    Looks up a word pool keyed by "{class}_{body_type}". Falls back to a
    generic pool if no specific match exists, then falls back to a plain
    descriptive name as a last resort.
    """
    pools = _get_pools()
    body_key = body_type.value if body_type else "sport"
    class_key = car_class.value
    pool_key = f"{class_key}_{body_key}"

    pool = pools.get(pool_key)
    if pool is None:
        # Try class-only fallback (first matching key with same class prefix)
        fallback_key = next(
            (k for k in pools if k.startswith(f"{class_key}_") and not k.startswith("_")), None
        )
        pool = pools.get(fallback_key) if fallback_key else None

    if pool and len(pool) == 2:
        adjectives, nouns = pool[0], pool[1]
        return f"{random.choice(adjectives)} {random.choice(nouns)}"

    # Last resort fallback
    return f"{car_class.value.title()} Rig"
