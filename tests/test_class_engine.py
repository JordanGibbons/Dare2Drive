"""Tests for engine/class_engine.py."""

from __future__ import annotations

import pytest

from db.models import BodyType, CarClass
from engine.class_engine import calculate_class, trending_toward
from engine.stat_resolver import BuildStats


def _stats(**kwargs: float) -> BuildStats:
    """Construct a BuildStats with only the specified fields, rest zero."""
    return BuildStats(**{k: float(v) for k, v in kwargs.items()})


# ── calculate_class ────────────────────────────────────────────────────────────


class TestCalculateClass:
    def test_street_is_default_for_empty_stats(self):
        bs = BuildStats()
        assert calculate_class(bs) == CarClass.STREET

    def test_drag_when_high_power_accel_low_handling(self):
        # min_power: 80, min_acceleration: 70, max_handling: 55
        bs = _stats(effective_power=85, effective_acceleration=75, effective_handling=40)
        assert calculate_class(bs) == CarClass.DRAG

    def test_drag_fails_when_handling_too_high(self):
        # Handling above 55 disqualifies DRAG
        bs = _stats(effective_power=85, effective_acceleration=75, effective_handling=65)
        result = calculate_class(bs)
        assert result != CarClass.DRAG

    def test_drag_fails_when_power_too_low(self):
        bs = _stats(effective_power=70, effective_acceleration=75, effective_handling=40)
        result = calculate_class(bs)
        assert result != CarClass.DRAG

    def test_drag_fails_when_accel_too_low(self):
        bs = _stats(effective_power=85, effective_acceleration=60, effective_handling=40)
        result = calculate_class(bs)
        assert result != CarClass.DRAG

    def test_circuit_when_balanced_handling_braking_stability(self):
        # min_handling: 65, min_braking: 60, min_stability: 55
        bs = _stats(effective_handling=70, effective_braking=65, effective_stability=60)
        assert calculate_class(bs) == CarClass.CIRCUIT

    def test_circuit_fails_when_handling_insufficient(self):
        bs = _stats(effective_handling=60, effective_braking=65, effective_stability=60)
        result = calculate_class(bs)
        assert result != CarClass.CIRCUIT

    def test_circuit_fails_when_braking_insufficient(self):
        bs = _stats(effective_handling=70, effective_braking=50, effective_stability=60)
        result = calculate_class(bs)
        assert result != CarClass.CIRCUIT

    def test_drift_when_low_grip_high_torque_stable(self):
        # max_grip: 45, min_torque: 70, min_stability: 45
        bs = _stats(effective_grip=30, effective_torque=75, effective_stability=50)
        assert calculate_class(bs) == CarClass.DRIFT

    def test_drift_fails_when_grip_too_high(self):
        bs = _stats(effective_grip=60, effective_torque=75, effective_stability=50)
        result = calculate_class(bs)
        assert result != CarClass.DRIFT

    def test_drift_fails_when_torque_too_low(self):
        bs = _stats(effective_grip=30, effective_torque=60, effective_stability=50)
        result = calculate_class(bs)
        assert result != CarClass.DRIFT

    def test_rally_when_durable_stable_weather(self):
        # min_durability: 70, min_stability: 60, min_weather: 55
        bs = _stats(
            effective_durability=75,
            effective_stability=65,
            effective_weather_performance=60,
        )
        assert calculate_class(bs) == CarClass.RALLY

    def test_rally_fails_when_durability_low(self):
        bs = _stats(
            effective_durability=60,
            effective_stability=65,
            effective_weather_performance=60,
        )
        result = calculate_class(bs)
        assert result != CarClass.RALLY

    def test_elite_when_pedigree_bonus_high(self):
        # min_pedigree_bonus: 2.0
        bs = BuildStats()
        assert calculate_class(bs, pedigree_bonus=2.5) == CarClass.ELITE

    def test_elite_not_triggered_when_pedigree_zero(self):
        # ELITE requires pedigree >= 2.0; 0.0 should not qualify
        bs = BuildStats()
        result = calculate_class(bs, pedigree_bonus=0.0)
        assert result != CarClass.ELITE

    def test_elite_not_triggered_when_pedigree_just_below(self):
        bs = BuildStats()
        result = calculate_class(bs, pedigree_bonus=1.99)
        assert result != CarClass.ELITE

    def test_elite_beats_drag_in_evaluation_order(self):
        # A build that qualifies for both DRAG and ELITE should get ELITE
        bs = _stats(effective_power=85, effective_acceleration=75, effective_handling=40)
        result = calculate_class(bs, pedigree_bonus=3.0)
        assert result == CarClass.ELITE

    def test_body_type_accepted_without_error(self):
        """body_type is accepted as a parameter — shouldn't crash."""
        bs = BuildStats()
        result = calculate_class(bs, body_type=BodyType.COMPACT)
        assert result == CarClass.STREET

    def test_returns_street_for_mid_range_stats(self):
        """Stats that don't meet any class threshold should be STREET."""
        bs = _stats(effective_power=50, effective_handling=50, effective_stability=40)
        assert calculate_class(bs) == CarClass.STREET


# ── trending_toward ────────────────────────────────────────────────────────────


class TestTrendingToward:
    def test_returns_all_classes(self):
        bs = BuildStats()
        results = trending_toward(bs)
        classes = {c for c, _ in results}
        assert CarClass.STREET in classes
        assert CarClass.DRAG in classes
        assert CarClass.CIRCUIT in classes
        assert CarClass.DRIFT in classes
        assert CarClass.RALLY in classes
        assert CarClass.ELITE in classes

    def test_sorted_descending(self):
        bs = BuildStats()
        results = trending_toward(bs)
        pcts = [pct for _, pct in results]
        assert pcts == sorted(pcts, reverse=True)

    def test_street_always_100_pct(self):
        bs = BuildStats()
        results = trending_toward(bs)
        street_pct = next(pct for c, pct in results if c == CarClass.STREET)
        assert street_pct == 1.0

    def test_pct_between_zero_and_one(self):
        bs = _stats(effective_power=40, effective_acceleration=30)
        results = trending_toward(bs)
        for _, pct in results:
            assert 0.0 <= pct <= 1.0

    def test_drag_trending_increases_with_power(self):
        bs_low = _stats(effective_power=50)
        bs_high = _stats(effective_power=80)
        low_drag = next(p for c, p in trending_toward(bs_low) if c == CarClass.DRAG)
        high_drag = next(p for c, p in trending_toward(bs_high) if c == CarClass.DRAG)
        assert high_drag > low_drag

    def test_fully_met_class_shows_100_pct(self):
        # Build that fully meets DRAG requirements
        bs = _stats(effective_power=85, effective_acceleration=75, effective_handling=40)
        results = trending_toward(bs)
        drag_pct = next(p for c, p in results if c == CarClass.DRAG)
        assert drag_pct == pytest.approx(1.0, abs=0.01)

    def test_pedigree_contributes_to_elite_trending(self):
        bs = BuildStats()
        low = next(p for c, p in trending_toward(bs, pedigree_bonus=0.0) if c == CarClass.ELITE)
        high = next(p for c, p in trending_toward(bs, pedigree_bonus=2.0) if c == CarClass.ELITE)
        assert high > low
