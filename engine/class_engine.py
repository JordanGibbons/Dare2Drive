"""Class engine — derives a rig's CarClass from its combined BuildStats."""

from __future__ import annotations

import json
from pathlib import Path

from db.models import BodyType, CarClass
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


# Evaluation order: most specific/exclusive first
_CLASS_ORDER: list[CarClass] = [
    CarClass.ELITE,
    CarClass.DRAG,
    CarClass.CIRCUIT,
    CarClass.DRIFT,
    CarClass.RALLY,
    CarClass.STREET,
]


def calculate_class(
    stats: BuildStats,
    body_type: BodyType | None = None,
    pedigree_bonus: float = 0.0,
) -> CarClass:
    """
    Derive a CarClass from the rig's aggregate stats.

    Evaluation proceeds in order: ELITE → DRAG → CIRCUIT → DRIFT → RALLY → STREET.
    STREET is the fallback and always matches.
    """
    thresholds = _get_thresholds()

    for car_class in _CLASS_ORDER:
        if car_class == CarClass.STREET:
            return CarClass.STREET

        class_key = car_class.value
        class_thresholds = thresholds.get(class_key, {})

        if car_class == CarClass.ELITE:
            elite_t = class_thresholds.get("min_pedigree_bonus", 0)
            if pedigree_bonus >= elite_t and elite_t > 0:
                return CarClass.ELITE
            continue

        if _class_met(class_thresholds, stats):
            return car_class

    return CarClass.STREET


def trending_toward(
    stats: BuildStats,
    body_type: BodyType | None = None,
    pedigree_bonus: float = 0.0,
) -> list[tuple[CarClass, float]]:
    """
    Return each class with a completion percentage [0.0–1.0] of its requirements.

    Used for the /build preview command to show which class the build is trending toward.
    Results are sorted by completion descending.
    """
    thresholds = _get_thresholds()
    results: list[tuple[CarClass, float]] = []

    for car_class in _CLASS_ORDER:
        if car_class == CarClass.STREET:
            results.append((CarClass.STREET, 1.0))
            continue

        class_key = car_class.value
        class_thresholds = thresholds.get(class_key, {})
        pct = _class_pct(class_thresholds, stats, pedigree_bonus)
        results.append((car_class, pct))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
