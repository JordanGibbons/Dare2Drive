"""Tests for engine/card_mint.py."""

from __future__ import annotations

import pytest

from engine.card_mint import (
    STAT_VARIANCE_RANGE,
    apply_stat_modifiers,
    degrade_stat_modifiers,
    roll_stat_modifiers,
)

# ---------------------------------------------------------------------------
# roll_stat_modifiers
# ---------------------------------------------------------------------------


class TestRollStatModifiers:
    def test_returns_modifiers_for_each_stat(self):
        stats = {"primary": {"power": 60, "torque": 50}, "secondary": {"durability": 70}}
        mods = roll_stat_modifiers(stats)
        assert set(mods["primary"]) == {"power", "torque"}
        assert set(mods["secondary"]) == {"durability"}

    def test_modifiers_within_variance_range(self):
        stats = {"primary": {"power": 60, "torque": 50, "acceleration": 55}}
        for _ in range(50):
            mods = roll_stat_modifiers(stats)
            for val in mods["primary"].values():
                assert -STAT_VARIANCE_RANGE <= val <= STAT_VARIANCE_RANGE

    def test_non_numeric_stats_skipped(self):
        stats = {"primary": {"power": 60, "label": "fast"}, "secondary": {}}
        mods = roll_stat_modifiers(stats)
        assert "label" not in mods.get("primary", {})

    def test_empty_section_omitted(self):
        stats = {"primary": {"power": 60}, "secondary": {}}
        mods = roll_stat_modifiers(stats)
        assert "secondary" not in mods

    def test_entirely_empty_stats(self):
        mods = roll_stat_modifiers({})
        assert mods == {}

    def test_modifiers_are_rounded_to_4_places(self):
        stats = {"primary": {"power": 60}}
        for _ in range(20):
            mods = roll_stat_modifiers(stats)
            val = mods["primary"]["power"]
            assert val == round(val, 4)


# ---------------------------------------------------------------------------
# apply_stat_modifiers
# ---------------------------------------------------------------------------


class TestApplyStatModifiers:
    def test_applies_positive_modifier(self):
        base = {"primary": {"power": 100}, "secondary": {}}
        mods = {"primary": {"power": 0.05}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["power"] == pytest.approx(105.0, rel=1e-3)

    def test_applies_negative_modifier(self):
        base = {"primary": {"power": 100}, "secondary": {}}
        mods = {"primary": {"power": -0.05}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["power"] == pytest.approx(95.0, rel=1e-3)

    def test_stat_without_modifier_unchanged(self):
        base = {"primary": {"power": 80, "torque": 60}, "secondary": {}}
        mods = {"primary": {"power": 0.1}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["torque"] == 60

    def test_non_numeric_stat_passed_through(self):
        base = {"primary": {"label": "fast"}, "secondary": {}}
        mods = {}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["label"] == "fast"

    def test_empty_modifiers_returns_base_values(self):
        base = {"primary": {"power": 75}, "secondary": {"durability": 55}}
        result = apply_stat_modifiers(base, {})
        assert result["primary"]["power"] == 75
        assert result["secondary"]["durability"] == 55

    def test_both_sections_processed(self):
        base = {"primary": {"power": 50}, "secondary": {"durability": 60}}
        mods = {"primary": {"power": 0.1}, "secondary": {"durability": -0.1}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["power"] == pytest.approx(55.0, rel=1e-3)
        assert result["secondary"]["durability"] == pytest.approx(54.0, rel=1e-3)


# ---------------------------------------------------------------------------
# degrade_stat_modifiers
# ---------------------------------------------------------------------------


class TestDegradeStatModifiers:
    def test_reduces_each_modifier_by_severity(self):
        mods = {"primary": {"power": 0.05, "torque": 0.02}}
        result = degrade_stat_modifiers(mods, severity=0.005)
        assert result["primary"]["power"] == pytest.approx(0.045, rel=1e-3)
        assert result["primary"]["torque"] == pytest.approx(0.015, rel=1e-3)

    def test_can_go_negative(self):
        mods = {"primary": {"power": 0.001}}
        result = degrade_stat_modifiers(mods, severity=0.005)
        assert result["primary"]["power"] < 0

    def test_does_not_mutate_input(self):
        mods = {"primary": {"power": 0.05}}
        original = mods["primary"]["power"]
        degrade_stat_modifiers(mods)
        assert mods["primary"]["power"] == original

    def test_default_severity(self):
        mods = {"primary": {"power": 0.05}}
        result = degrade_stat_modifiers(mods)
        assert result["primary"]["power"] == pytest.approx(0.045, rel=1e-3)

    def test_empty_modifiers(self):
        assert degrade_stat_modifiers({}) == {}
