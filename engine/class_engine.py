"""Race format engine — derives a ship's RaceFormat from its combined BuildStats."""

from __future__ import annotations

import json
from pathlib import Path

from db.models import HullClass, RaceFormat
from engine.stat_resolver import BuildStats

_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "data" / "class_thresholds.json"

_thresholds_cache: dict | None = None


def _get_thresholds() -> dict:
    global _thresholds_cache
    if _thresholds_cache is None:
        with open(_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
            _thresholds_cache = json.load(f)
    return _thresholds_cache


def _stat(stats: BuildStats, key: str) -> float:
    """Map threshold config keys to BuildStats fields."""
    mapping = {
        "min_power": stats.effective_power,
        "max_power": stats.effective_power,
        "min_acceleration": stats.effective_acceleration,
        "max_acceleration": stats.effective_acceleration,
        "min_handling": stats.effective_handling,
        "max_handling": stats.effective_handling,
        "min_braking": stats.effective_braking,
        "max_braking": stats.effective_braking,
        "min_stability": stats.effective_stability,
        "max_stability": stats.effective_stability,
        "min_grip": stats.effective_grip,
        "max_grip": stats.effective_grip,
        "min_torque": stats.effective_torque,
        "max_torque": stats.effective_torque,
        "min_durability": stats.effective_durability,
        "max_durability": stats.effective_durability,
        "min_weather": stats.effective_weather_performance,
        "max_weather": stats.effective_weather_performance,
    }
    return mapping.get(key, 0.0)


def _class_met(thresholds: dict, stats: BuildStats) -> bool:
    """Return True if all thresholds for a class are satisfied."""
    for key, value in thresholds.items():
        if key == "min_pedigree_bonus":
            continue  # handled separately via pedigree_bonus arg
        stat_val = _stat(stats, key)
        if key.startswith("min_") and stat_val < value:
            return False
        if key.startswith("max_") and stat_val > value:
            return False
    return True


def _class_pct(thresholds: dict, stats: BuildStats, pedigree_bonus: float = 0.0) -> float:
    """Return fraction [0.0–1.0] of threshold requirements met for a class."""
    if not thresholds:
        return 1.0
    met = 0
    for key, value in thresholds.items():
        if key == "min_pedigree_bonus":
            if pedigree_bonus >= value:
                met += 1
            continue
        stat_val = _stat(stats, key)
        if key.startswith("min_"):
            met += min(stat_val / value, 1.0)
        elif key.startswith("max_") and value > 0:
            # For max requirements (e.g. max_handling for drag): full credit when at or below cap
            met += min(value / max(stat_val, 0.01), 1.0)
    return met / len(thresholds)


# Evaluation order: sprint, endurance, gauntlet (most specific/exclusive first)
_RACE_FORMAT_ORDER: list[RaceFormat] = [
    RaceFormat.SPRINT,
    RaceFormat.ENDURANCE,
    RaceFormat.GAUNTLET,
]


def calculate_race_format(
    stats: BuildStats,
    hull_class: HullClass | None = None,
    pedigree_bonus: float = 0.0,
) -> RaceFormat:
    """
    Derive a RaceFormat from the ship's aggregate stats.

    Evaluation proceeds in order: SPRINT → ENDURANCE → GAUNTLET.
    SPRINT is the fallback and always matches.

    Mapping from old 6-class system:
    - drag (high acceleration + top speed) → SPRINT
    - circuit (balanced, long-haul, durability) → ENDURANCE
    - drift/rally (precision, handling) → GAUNTLET
    - street (default) → SPRINT (most accessible)
    - elite (prestige) → removed; not a format
    """
    thresholds = _get_thresholds()

    # Try to read new 3-format keys from thresholds; fall back to old keys for compatibility
    sprint_thresholds = thresholds.get("sprint", {})
    endurance_thresholds = thresholds.get("endurance", {})
    gauntlet_thresholds = thresholds.get("gauntlet", {})

    # If no new-format keys found, derive from old schema if available
    if not sprint_thresholds and "drag" in thresholds:
        # Fallback: use old drag thresholds for sprint
        sprint_thresholds = thresholds.get("drag", {})
    if not endurance_thresholds and "circuit" in thresholds:
        # Fallback: use old circuit thresholds for endurance
        endurance_thresholds = thresholds.get("circuit", {})
    if not gauntlet_thresholds:
        # Fallback: merge drift and rally constraints with permissive thresholds
        drift_t = thresholds.get("drift", {})
        rally_t = thresholds.get("rally", {})
        # For gauntlet, we accept if either drift OR rally criteria are met
        # For now, just use drift as the primary gauntlet threshold
        gauntlet_thresholds = drift_t if drift_t else rally_t

    # Evaluate in order: if SPRINT criteria met, return SPRINT; else try ENDURANCE; else GAUNTLET
    if _class_met(sprint_thresholds, stats):
        return RaceFormat.SPRINT
    if _class_met(endurance_thresholds, stats):
        return RaceFormat.ENDURANCE
    if _class_met(gauntlet_thresholds, stats):
        return RaceFormat.GAUNTLET

    # Default fallback to SPRINT (the most accessible format)
    return RaceFormat.SPRINT


def trending_toward(
    stats: BuildStats,
    hull_class: HullClass | None = None,
    pedigree_bonus: float = 0.0,
) -> list[tuple[RaceFormat, float]]:
    """
    Return each format with a completion percentage [0.0–1.0] of its requirements.

    Used for the /build preview command to show which format the build is trending toward.
    Results are sorted by completion descending.
    """
    thresholds = _get_thresholds()
    results: list[tuple[RaceFormat, float]] = []

    # Try to read new 3-format keys from thresholds; fall back to old keys for compatibility
    sprint_thresholds = thresholds.get("sprint", {})
    endurance_thresholds = thresholds.get("endurance", {})
    gauntlet_thresholds = thresholds.get("gauntlet", {})

    # If no new-format keys found, derive from old schema if available
    if not sprint_thresholds and "drag" in thresholds:
        sprint_thresholds = thresholds.get("drag", {})
    if not endurance_thresholds and "circuit" in thresholds:
        endurance_thresholds = thresholds.get("circuit", {})
    if not gauntlet_thresholds:
        drift_t = thresholds.get("drift", {})
        rally_t = thresholds.get("rally", {})
        gauntlet_thresholds = drift_t if drift_t else rally_t

    for race_format in _RACE_FORMAT_ORDER:
        if race_format == RaceFormat.SPRINT:
            pct = _class_pct(sprint_thresholds, stats, pedigree_bonus)
        elif race_format == RaceFormat.ENDURANCE:
            pct = _class_pct(endurance_thresholds, stats, pedigree_bonus)
        else:  # GAUNTLET
            pct = _class_pct(gauntlet_thresholds, stats, pedigree_bonus)
        results.append((race_format, pct))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ──────────── Phase 2c: hull-class crew slot composition ────────────

from db.models import CrewArchetype  # noqa: E402

HULL_CREW_SLOTS: dict[HullClass, list[CrewArchetype]] = {
    HullClass.SKIRMISHER: [CrewArchetype.PILOT, CrewArchetype.GUNNER],
    HullClass.HAULER: [
        CrewArchetype.PILOT,
        CrewArchetype.ENGINEER,
        CrewArchetype.NAVIGATOR,
    ],
    HullClass.SCOUT: [CrewArchetype.PILOT, CrewArchetype.NAVIGATOR],
}


def slots_for_hull(hull: HullClass) -> list[CrewArchetype]:
    """Return the canonical archetype slot list for a hull class.

    The returned list's order is the canonical display order for embed/UI rendering.
    """
    return HULL_CREW_SLOTS[hull]
