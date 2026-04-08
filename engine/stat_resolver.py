"""Stat resolver — aggregates build stats across all 7 card slots."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.logging import get_logger

log = get_logger(__name__)

_TUTORIAL_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tutorial.json"

_body_type_stats_cache: dict[str, dict[str, float]] | None = None


def _get_body_type_stats() -> dict[str, dict[str, float]]:
    """Load body type base stats from tutorial data (cached)."""
    global _body_type_stats_cache
    if _body_type_stats_cache is None:
        with open(_TUTORIAL_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _body_type_stats_cache = data["body_type_base_stats"]
    return _body_type_stats_cache


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
    body_type: str | None = None,
) -> BuildStats:
    """
    Combine all 7 equipped card stats into composite BuildStats.

    Parameters
    ----------
    slots : dict mapping slot name → card_id (or None if empty)
    cards : dict mapping card_id → full card data dict (must include 'stats' key)
    body_type : optional body type string ("muscle", "sport", "compact")
                adds base stats from the chassis before card contributions
    """
    bs = BuildStats()

    # Apply body type base stats
    if body_type:
        base = _get_body_type_stats().get(body_type, {})
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

    # Engine
    engine_data = cards.get(slots.get("engine") or "", {})
    engine_stats = engine_data.get("stats", {})
    raw_power = _get_stat(engine_stats, "primary", "power")
    raw_accel = _get_stat(engine_stats, "primary", "acceleration")
    raw_torque = _get_stat(engine_stats, "primary", "torque")
    bs.engine_max_temp = _get_stat(engine_stats, "primary", "max_engine_temp")
    engine_weight = _get_stat(engine_stats, "secondary", "weight")
    engine_durability = _get_stat(engine_stats, "secondary", "durability")
    _get_stat(engine_stats, "secondary", "fuel_efficiency")
    bs.slot_durabilities["engine"] = engine_durability

    # Transmission
    trans_data = cards.get(slots.get("transmission") or "", {})
    trans_stats = trans_data.get("stats", {})
    accel_scaling = _get_stat(trans_stats, "primary", "acceleration_scaling")
    top_speed_ceiling = _get_stat(trans_stats, "primary", "top_speed_ceiling")
    shift_efficiency = _get_stat(trans_stats, "primary", "shift_efficiency")
    trans_durability = _get_stat(trans_stats, "secondary", "durability")
    torque_transfer = _get_stat(trans_stats, "secondary", "torque_transfer_pct")
    bs.slot_durabilities["transmission"] = trans_durability

    # Tires
    tires_data = cards.get(slots.get("tires") or "", {})
    tires_stats = tires_data.get("stats", {})
    tire_grip = _get_stat(tires_stats, "primary", "grip")
    tire_handling = _get_stat(tires_stats, "primary", "handling")
    tire_launch = _get_stat(tires_stats, "primary", "launch_acceleration")
    tire_durability = _get_stat(tires_stats, "secondary", "durability")
    tire_weather = _get_stat(tires_stats, "secondary", "weather_performance")
    tire_drag = _get_stat(tires_stats, "secondary", "drag")
    bs.slot_durabilities["tires"] = tire_durability

    # Suspension
    susp_data = cards.get(slots.get("suspension") or "", {})
    susp_stats = susp_data.get("stats", {})
    susp_handling = _get_stat(susp_stats, "primary", "handling")
    susp_stability = _get_stat(susp_stats, "primary", "stability")
    _get_stat(susp_stats, "primary", "ride_height_modifier")
    weight_balance = _get_stat(susp_stats, "secondary", "weight_balance_bonus")
    brake_eff_scaling = _get_stat(susp_stats, "secondary", "brake_efficiency_scaling")
    bs.slot_durabilities["suspension"] = susp_stability  # suspension uses stability as proxy

    # Chassis
    chassis_data = cards.get(slots.get("chassis") or "", {})
    chassis_stats = chassis_data.get("stats", {})
    chassis_drag = _get_stat(chassis_stats, "primary", "drag")
    chassis_weight = _get_stat(chassis_stats, "primary", "weight")
    chassis_durability = _get_stat(chassis_stats, "primary", "durability")
    _get_stat(chassis_stats, "primary", "style")
    handling_cap_mod = _get_stat(chassis_stats, "secondary", "handling_cap_modifier")
    top_speed_mult = _get_stat(chassis_stats, "secondary", "top_speed_multiplier", default=1.0)
    bs.slot_durabilities["chassis"] = chassis_durability

    # Turbo
    turbo_data = cards.get(slots.get("turbo") or "", {})
    turbo_stats = turbo_data.get("stats", {})
    power_boost_pct = _get_stat(turbo_stats, "primary", "power_boost_pct")
    accel_boost_pct = _get_stat(turbo_stats, "primary", "acceleration_boost_pct")
    engine_temp_inc = _get_stat(turbo_stats, "primary", "engine_temp_increase")
    turbo_durability = _get_stat(turbo_stats, "secondary", "durability")
    torque_spike = _get_stat(turbo_stats, "secondary", "torque_spike_modifier")
    bs.slot_durabilities["turbo"] = turbo_durability
    bs.turbo_engine_temp_increase = engine_temp_inc

    # Brakes
    brakes_data = cards.get(slots.get("brakes") or "", {})
    brakes_stats = brakes_data.get("stats", {})
    brake_force = _get_stat(brakes_stats, "primary", "brake_force")
    corner_entry = _get_stat(brakes_stats, "primary", "corner_entry_speed")
    stability_decel = _get_stat(brakes_stats, "primary", "stability_under_decel")
    brakes_handling = _get_stat(brakes_stats, "secondary", "handling_bonus")
    brakes_durability = _get_stat(brakes_stats, "secondary", "durability")
    bs.slot_durabilities["brakes"] = brakes_durability

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

    # Top speed: ceiling from transmission × chassis multiplier - drag penalties
    base_top_speed = top_speed_ceiling + raw_power * 0.3
    total_drag = max(chassis_drag + tire_drag + engine_weight + chassis_weight, -50)
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
