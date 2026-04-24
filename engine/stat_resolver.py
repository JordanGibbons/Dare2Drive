"""Stat resolver — aggregates build stats across all 7 card slots."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.logging import get_logger

log = get_logger(__name__)

_TUTORIAL_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tutorial.json"

_hull_class_stats_cache: dict[str, dict[str, float]] | None = None


def _get_hull_class_stats() -> dict[str, dict[str, float]]:
    """Load hull class base stats from tutorial data (cached)."""
    global _hull_class_stats_cache
    if _hull_class_stats_cache is None:
        with open(_TUTORIAL_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _hull_class_stats_cache = data["hull_class_base_stats"]
    return _hull_class_stats_cache


@dataclass
class BuildStats:
    """Composite race-ready stats derived from all 7 slots."""

    effective_power: float = 0.0
    effective_handling: float = 0.0
    effective_top_speed: float = 0.0
    effective_grip: float = 0.0
    effective_braking: float = 0.0
    effective_durability: float = 0.0
    effective_acceleration: float = 0.0
    effective_stability: float = 0.0
    effective_weather_performance: float = 0.0

    # Torque exposed separately (used by drift class calculation)
    effective_torque: float = 0.0

    # Flags set by cross-slot interactions
    overheat_risk: bool = False

    # Per-slot durability values for failure checks
    slot_durabilities: dict[str, float] = field(default_factory=dict)

    # Metadata
    turbo_engine_temp_increase: float = 0.0
    engine_max_temp: float = 0.0


def _get_stat(stats: dict[str, Any], section: str, key: str, default: float = 0.0) -> float:
    """Safely extract a stat value from nested card stats dict."""
    return float(stats.get(section, {}).get(key, default))


def aggregate_build(
    slots: dict[str, str | None],
    cards: dict[str, dict[str, Any]],
    hull_class: str | None = None,
) -> BuildStats:
    """
    Combine all 7 equipped card stats into composite BuildStats.

    Parameters
    ----------
    slots : dict mapping slot name → card_id (or None if empty)
    cards : dict mapping card_id → full card data dict (must include 'stats' key)
    hull_class : optional hull class string ("hauler", "skirmisher", "scout")
                adds base stats from the hull before card contributions
    """
    bs = BuildStats()

    # Apply hull class base stats
    if hull_class:
        base = _get_hull_class_stats().get(hull_class, {})
        bs.effective_power = base.get("power", 0.0)
        bs.effective_acceleration = base.get("acceleration", 0.0)
        bs.effective_top_speed = base.get("top_speed", 0.0)
        bs.effective_handling = base.get("handling", 0.0)
        bs.effective_grip = base.get("grip", 0.0)
        bs.effective_braking = base.get("braking", 0.0)
        bs.effective_stability = base.get("stability", 0.0)
        bs.effective_durability = base.get("durability", 0.0)
        bs.effective_weather_performance = base.get("weather_performance", 0.0)

    # ── Extract raw stats from each slot ──

    # Reactor
    reactor_data = cards.get(slots.get("reactor") or "", {})
    reactor_stats = reactor_data.get("stats", {})
    raw_power = _get_stat(reactor_stats, "primary", "power")
    raw_accel = _get_stat(reactor_stats, "primary", "acceleration")
    raw_torque = _get_stat(reactor_stats, "primary", "torque")
    bs.engine_max_temp = _get_stat(reactor_stats, "primary", "max_reactor_temp")
    reactor_weight = _get_stat(reactor_stats, "secondary", "weight")
    reactor_durability = _get_stat(reactor_stats, "secondary", "durability")
    _get_stat(reactor_stats, "secondary", "fuel_efficiency")
    bs.slot_durabilities["reactor"] = reactor_durability

    # Drive
    drive_data = cards.get(slots.get("drive") or "", {})
    drive_stats = drive_data.get("stats", {})
    accel_scaling = _get_stat(drive_stats, "primary", "acceleration_scaling")
    top_speed_ceiling = _get_stat(drive_stats, "primary", "top_speed_ceiling")
    shift_efficiency = _get_stat(drive_stats, "primary", "shift_efficiency")
    drive_durability = _get_stat(drive_stats, "secondary", "durability")
    torque_transfer = _get_stat(drive_stats, "secondary", "torque_transfer_pct")
    bs.slot_durabilities["drive"] = drive_durability

    # Thrusters
    thrusters_data = cards.get(slots.get("thrusters") or "", {})
    thrusters_stats = thrusters_data.get("stats", {})
    tire_grip = _get_stat(thrusters_stats, "primary", "grip")
    tire_handling = _get_stat(thrusters_stats, "primary", "handling")
    tire_launch = _get_stat(thrusters_stats, "primary", "launch_acceleration")
    thruster_durability = _get_stat(thrusters_stats, "secondary", "durability")
    tire_weather = _get_stat(thrusters_stats, "secondary", "weather_performance")
    tire_drag = _get_stat(thrusters_stats, "secondary", "drag")
    bs.slot_durabilities["thrusters"] = thruster_durability

    # Stabilizers
    stab_data = cards.get(slots.get("stabilizers") or "", {})
    stab_stats = stab_data.get("stats", {})
    susp_handling = _get_stat(stab_stats, "primary", "handling")
    susp_stability = _get_stat(stab_stats, "primary", "stability")
    _get_stat(stab_stats, "primary", "ride_height_modifier")
    weight_balance = _get_stat(stab_stats, "secondary", "weight_balance_bonus")
    brake_eff_scaling = _get_stat(stab_stats, "secondary", "brake_efficiency_scaling")
    bs.slot_durabilities["stabilizers"] = susp_stability  # stabilizers uses stability as proxy

    # Hull
    hull_data = cards.get(slots.get("hull") or "", {})
    hull_stats = hull_data.get("stats", {})
    chassis_drag = _get_stat(hull_stats, "primary", "drag")
    chassis_weight = _get_stat(hull_stats, "primary", "weight")
    chassis_durability = _get_stat(hull_stats, "primary", "durability")
    _get_stat(hull_stats, "primary", "style")
    handling_cap_mod = _get_stat(hull_stats, "secondary", "handling_cap_modifier")
    top_speed_mult = _get_stat(hull_stats, "secondary", "top_speed_multiplier", default=1.0)
    bs.slot_durabilities["hull"] = chassis_durability

    # Overdrive
    overdrive_data = cards.get(slots.get("overdrive") or "", {})
    overdrive_stats = overdrive_data.get("stats", {})
    power_boost_pct = _get_stat(overdrive_stats, "primary", "power_boost_pct")
    accel_boost_pct = _get_stat(overdrive_stats, "primary", "acceleration_boost_pct")
    engine_temp_inc = _get_stat(overdrive_stats, "primary", "engine_temp_increase")
    overdrive_durability = _get_stat(overdrive_stats, "secondary", "durability")
    torque_spike = _get_stat(overdrive_stats, "secondary", "torque_spike_modifier")
    bs.slot_durabilities["overdrive"] = overdrive_durability
    bs.turbo_engine_temp_increase = engine_temp_inc

    # Retros
    retros_data = cards.get(slots.get("retros") or "", {})
    retros_stats = retros_data.get("stats", {})
    brake_force = _get_stat(retros_stats, "primary", "brake_force")
    corner_entry = _get_stat(retros_stats, "primary", "corner_entry_speed")
    stability_decel = _get_stat(retros_stats, "primary", "stability_under_decel")
    brakes_handling = _get_stat(retros_stats, "secondary", "handling_bonus")
    retros_durability = _get_stat(retros_stats, "secondary", "durability")
    bs.slot_durabilities["retros"] = retros_durability

    # ── Composite stat computations (added to body type base) ──

    # Power: engine base + turbo boost + torque contribution
    boosted_power = raw_power * (1 + power_boost_pct / 100)
    bs.effective_torque = raw_torque * (torque_transfer / 100 if torque_transfer else 1.0)
    bs.effective_power += boosted_power + bs.effective_torque * 0.3 + torque_spike * 0.2

    # Acceleration: engine accel + turbo boost + transmission scaling + tire launch
    boosted_accel = raw_accel * (1 + accel_boost_pct / 100)
    bs.effective_acceleration += (
        boosted_accel * (accel_scaling / 100 if accel_scaling else 1.0)
        + tire_launch * 0.4
        + shift_efficiency * 0.2
    )

    # Top speed: ceiling from drive × hull multiplier - drag penalties
    base_top_speed = top_speed_ceiling + raw_power * 0.3
    total_drag = max(chassis_drag + tire_drag + reactor_weight + chassis_weight, -50)
    bs.effective_top_speed += base_top_speed * top_speed_mult - total_drag * 0.3

    # Handling: tires + suspension + brakes bonus + chassis cap modifier
    raw_handling = tire_handling * 0.4 + susp_handling * 0.4 + brakes_handling + corner_entry * 0.1
    handling_cap = 100 + handling_cap_mod
    bs.effective_handling = min(
        bs.effective_handling + raw_handling + weight_balance * 0.5, handling_cap
    )

    # Grip
    bs.effective_grip += tire_grip + susp_stability * 0.2

    # Braking: brake force amplified by suspension scaling
    brake_eff_mult = 1 + brake_eff_scaling / 100
    bs.effective_braking += (
        brake_force * brake_eff_mult + stability_decel * 0.3 + corner_entry * 0.2
    )

    # Stability
    bs.effective_stability += susp_stability + stability_decel * 0.2 + weight_balance * 0.3

    # Weather performance
    bs.effective_weather_performance += tire_weather

    # Durability: average of all slot durabilities + body type base
    durabilities = [v for v in bs.slot_durabilities.values() if v > 0]
    card_durability = sum(durabilities) / len(durabilities) if durabilities else 0
    bs.effective_durability += card_durability

    # ── Cross-slot interactions ──

    # Overheat risk: turbo temp increase vs engine max temp
    if bs.engine_max_temp > 0 and engine_temp_inc > bs.engine_max_temp * 0.8:
        bs.overheat_risk = True
        log.debug(
            "Overheat risk flagged: temp_inc=%.1f > %.1f", engine_temp_inc, bs.engine_max_temp * 0.8
        )

    return bs


_ARCHETYPE_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "crew" / "archetypes.json"
)
_RARITY_BOOSTS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "crew" / "rarity_boosts.json"
)

_archetype_mapping_cache: dict[str, dict[str, str]] | None = None
_rarity_boosts_cache: dict[str, float] | None = None


def _get_archetype_mapping() -> dict[str, dict[str, str]]:
    global _archetype_mapping_cache
    if _archetype_mapping_cache is None:
        with open(_ARCHETYPE_MAPPING_PATH, "r", encoding="utf-8") as f:
            _archetype_mapping_cache = json.load(f)
    return _archetype_mapping_cache


def _get_rarity_boosts() -> dict[str, float]:
    global _rarity_boosts_cache
    if _rarity_boosts_cache is None:
        with open(_RARITY_BOOSTS_PATH, "r", encoding="utf-8") as f:
            _rarity_boosts_cache = json.load(f)
    return _rarity_boosts_cache


def _bump(bs: BuildStats, stat_name: str, pct: float) -> None:
    """Multiplicatively bump a BuildStats attribute by `pct` (e.g. 0.05 = +5%)."""
    current = getattr(bs, stat_name)
    setattr(bs, stat_name, current * (1.0 + pct))


def apply_crew_boosts(bs: BuildStats, crew: list[Any]) -> BuildStats:
    """Fold assigned crew boosts into the BuildStats in place.

    Called AFTER aggregate_build and BEFORE environment weighting. Pure — no DB access.

    Each crew member's archetype determines primary/secondary stats. Rarity and
    level determine magnitude. Multiple crew on the same stat compound multiplicatively.
    """
    mapping = _get_archetype_mapping()
    base_boosts = _get_rarity_boosts()
    for member in crew:
        arch = member.archetype.value
        primary_stat = mapping[arch]["primary"]
        secondary_stat = mapping[arch]["secondary"]
        level_mult = 1.0 + (member.level - 1) * 0.1
        base = base_boosts[member.rarity.value]
        primary_boost = base * level_mult
        secondary_boost = (base / 2) * level_mult
        _bump(bs, primary_stat, primary_boost)
        _bump(bs, secondary_stat, secondary_boost)
    return bs
