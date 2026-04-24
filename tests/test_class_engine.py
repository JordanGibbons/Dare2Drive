"""Tests for engine/class_engine.py."""

from __future__ import annotations

import pytest

from db.models import HullClass, RaceFormat
from engine.class_engine import calculate_race_format, trending_toward
from engine.stat_resolver import BuildStats


def _stats(**kwargs: float) -> BuildStats:
    """Construct a BuildStats with only the specified fields, rest zero."""
    return BuildStats(**{k: float(v) for k, v in kwargs.items()})


# ── calculate_race_format ──────────────────────────────────────────────────────


class TestCalculateRaceFormat:
    def test_sprint_is_default_for_empty_stats(self):
        """Empty stats don't meet any specific threshold, falls back to SPRINT."""
        bs = BuildStats()
        assert calculate_race_format(bs) == RaceFormat.SPRINT

    def test_sprint_when_high_power_accel_low_handling(self):
        # sprint: min_power=80, min_acceleration=70, max_handling=55
        bs = _stats(effective_power=85, effective_acceleration=75, effective_handling=40)
        assert calculate_race_format(bs) == RaceFormat.SPRINT

    def test_sprint_criteria_not_met_when_handling_too_high(self):
        # max_handling=55; handling=65 means SPRINT threshold not qualified by criteria.
        # With high handling + braking + stability ENDURANCE may qualify instead.
        bs = _stats(
            effective_power=85,
            effective_acceleration=75,
            effective_handling=70,
            effective_braking=65,
            effective_stability=60,
        )
        # This build qualifies for ENDURANCE (which is checked before fallback)
        result = calculate_race_format(bs)
        assert result == RaceFormat.ENDURANCE

    def test_mid_power_falls_back_to_sprint(self):
        # Power=70 doesn't meet sprint min_power=80, no other format qualifies → fallback SPRINT
        bs = _stats(effective_power=70, effective_acceleration=75, effective_handling=40)
        result = calculate_race_format(bs)
        assert result == RaceFormat.SPRINT  # fallback

    def test_low_accel_falls_back_to_sprint(self):
        # accel=60 doesn't meet sprint min_acceleration=70, fallback → SPRINT
        bs = _stats(effective_power=85, effective_acceleration=60, effective_handling=40)
        result = calculate_race_format(bs)
        assert result == RaceFormat.SPRINT  # fallback

    def test_endurance_when_balanced_handling_braking_stability(self):
        # endurance: min_handling=65, min_braking=60, min_stability=55
        bs = _stats(effective_handling=70, effective_braking=65, effective_stability=60)
        assert calculate_race_format(bs) == RaceFormat.ENDURANCE

    def test_endurance_fails_when_handling_insufficient(self):
        bs = _stats(effective_handling=60, effective_braking=65, effective_stability=60)
        result = calculate_race_format(bs)
        assert result != RaceFormat.ENDURANCE

    def test_endurance_fails_when_braking_insufficient(self):
        bs = _stats(effective_handling=70, effective_braking=50, effective_stability=60)
        result = calculate_race_format(bs)
        assert result != RaceFormat.ENDURANCE

    def test_gauntlet_when_all_criteria_met(self):
        # gauntlet: max_grip=45, min_torque=70, min_stability=45, min_durability=70, min_weather=55
        bs = _stats(
            effective_grip=30,
            effective_torque=75,
            effective_stability=50,
            effective_durability=75,
            effective_weather_performance=60,
        )
        assert calculate_race_format(bs) == RaceFormat.GAUNTLET

    def test_gauntlet_fails_when_grip_too_high(self):
        bs = _stats(
            effective_grip=60,
            effective_torque=75,
            effective_stability=50,
            effective_durability=75,
            effective_weather_performance=60,
        )
        result = calculate_race_format(bs)
        assert result != RaceFormat.GAUNTLET

    def test_gauntlet_fails_when_torque_too_low(self):
        bs = _stats(
            effective_grip=30,
            effective_torque=60,
            effective_stability=50,
            effective_durability=75,
            effective_weather_performance=60,
        )
        result = calculate_race_format(bs)
        assert result != RaceFormat.GAUNTLET

    def test_gauntlet_fails_when_durability_low(self):
        bs = _stats(
            effective_grip=30,
            effective_torque=75,
            effective_stability=50,
            effective_durability=60,
            effective_weather_performance=60,
        )
        result = calculate_race_format(bs)
        assert result != RaceFormat.GAUNTLET

    def test_hull_class_accepted_without_error(self):
        """hull_class is accepted as a parameter — shouldn't crash."""
        bs = BuildStats()
        result = calculate_race_format(bs, hull_class=HullClass.SCOUT)
        assert result == RaceFormat.SPRINT

    def test_returns_sprint_for_mid_range_stats(self):
        """Stats that don't meet any specific threshold should fall back to SPRINT."""
        bs = _stats(effective_power=50, effective_handling=50, effective_stability=40)
        assert calculate_race_format(bs) == RaceFormat.SPRINT


# ── trending_toward ────────────────────────────────────────────────────────────


class TestTrendingToward:
    def test_returns_all_formats(self):
        bs = BuildStats()
        results = trending_toward(bs)
        formats = {f for f, _ in results}
        assert RaceFormat.SPRINT in formats
        assert RaceFormat.ENDURANCE in formats
        assert RaceFormat.GAUNTLET in formats

    def test_sorted_descending(self):
        bs = BuildStats()
        results = trending_toward(bs)
        pcts = [pct for _, pct in results]
        assert pcts == sorted(pcts, reverse=True)

    def test_pct_between_zero_and_one(self):
        bs = _stats(effective_power=40, effective_acceleration=30)
        results = trending_toward(bs)
        for _, pct in results:
            assert 0.0 <= pct <= 1.0

    def test_endurance_trending_increases_with_handling(self):
        bs_low = _stats(effective_handling=50)
        bs_high = _stats(effective_handling=80)
        low_end = next(p for f, p in trending_toward(bs_low) if f == RaceFormat.ENDURANCE)
        high_end = next(p for f, p in trending_toward(bs_high) if f == RaceFormat.ENDURANCE)
        assert high_end > low_end

    def test_fully_met_endurance_shows_100_pct(self):
        # Build that fully meets ENDURANCE requirements
        bs = _stats(effective_handling=70, effective_braking=65, effective_stability=60)
        results = trending_toward(bs)
        end_pct = next(p for f, p in results if f == RaceFormat.ENDURANCE)
        assert end_pct == pytest.approx(1.0, abs=0.01)

    def test_fully_met_sprint_shows_100_pct(self):
        # Build that fully meets SPRINT requirements
        bs = _stats(effective_power=85, effective_acceleration=75, effective_handling=40)
        results = trending_toward(bs)
        sprint_pct = next(p for f, p in results if f == RaceFormat.SPRINT)
        assert sprint_pct == pytest.approx(1.0, abs=0.01)

    def test_sprint_trending_increases_with_power(self):
        bs_low = _stats(effective_power=50, effective_handling=40)
        bs_high = _stats(effective_power=80, effective_handling=40)
        low_sprint = next(p for f, p in trending_toward(bs_low) if f == RaceFormat.SPRINT)
        high_sprint = next(p for f, p in trending_toward(bs_high) if f == RaceFormat.SPRINT)
        assert high_sprint > low_sprint
