"""Ship namer — generates evocative names for Ship Titles based on race format and hull class."""

from __future__ import annotations

import json
import random
from pathlib import Path

from db.models import HullClass, RaceFormat
from engine.stat_resolver import BuildStats

_NAMES_PATH = Path(__file__).resolve().parent.parent / "data" / "ship_names.json"

_names_cache: dict | None = None


def _get_pools() -> dict:
    global _names_cache
    if _names_cache is None:
        with open(_NAMES_PATH, "r", encoding="utf-8") as f:
            _names_cache = json.load(f)
    return _names_cache


def generate_ship_name(
    race_format: RaceFormat,
    hull_class: HullClass | None,
    stats: BuildStats | None = None,
) -> str:
    """
    Generate an evocative two-word name for a ship title.

    Looks up a word pool keyed by "{race_format}_{hull_class}". Falls back to a
    generic pool if no specific match exists, then falls back to a plain
    descriptive name as a last resort.
    """
    pools = _get_pools()
    hull_key = hull_class.value if hull_class else "skirmisher"
    format_key = race_format.value
    pool_key = f"{format_key}_{hull_key}"

    pool = pools.get(pool_key)
    if pool is None:
        # Try format-only fallback (first matching key with same format prefix)
        fallback_key = next(
            (k for k in pools if k.startswith(f"{format_key}_") and not k.startswith("_")), None
        )
        pool = pools.get(fallback_key) if fallback_key else None

    if pool and len(pool) == 2:
        adjectives, nouns = pool[0], pool[1]
        return f"{random.choice(adjectives)} {random.choice(nouns)}"

    # Last resort fallback
    return f"{race_format.value.title()} Rig"
