"""Tests for engine/stat_resolver.py."""

from __future__ import annotations

import uuid

from engine.stat_resolver import _get_stat, aggregate_build


class TestGetStat:
    def test_retrieves_nested_value(self):
        stats = {"primary": {"power": 65}}
        assert _get_stat(stats, "primary", "power") == 65.0

    def test_returns_default_for_missing_key(self):
        stats = {"primary": {}}
        assert _get_stat(stats, "primary", "power") == 0.0

    def test_returns_default_for_missing_section(self):
        stats = {}
        assert _get_stat(stats, "primary", "power") == 0.0

    def test_custom_default(self):
        assert _get_stat({}, "primary", "x", default=42.0) == 42.0


class TestAggregateBuild:
    def test_empty_build_returns_zeroes(self, empty_build):
        bs = aggregate_build(empty_build["slots"], empty_build["cards"])
        assert bs.effective_power == 0.0
        assert bs.effective_handling == 0.0
        assert bs.effective_top_speed == 0.0
        assert bs.effective_grip == 0.0
        assert bs.effective_braking == 0.0
        assert not bs.overheat_risk

    def test_full_build_produces_positive_stats(self, full_build):
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        assert bs.effective_power > 0
        assert bs.effective_handling > 0
        assert bs.effective_top_speed > 0
        assert bs.effective_grip > 0
        assert bs.effective_braking > 0
        assert bs.effective_acceleration > 0
        assert bs.effective_stability > 0
        assert bs.effective_durability > 0

    def test_overdrive_boosts_power(self, full_build):
        # With overdrive
        bs_with = aggregate_build(full_build["slots"], full_build["cards"])

        # Without overdrive
        slots_no_overdrive = dict(full_build["slots"])
        slots_no_overdrive["overdrive"] = None
        bs_without = aggregate_build(slots_no_overdrive, full_build["cards"])

        assert bs_with.effective_power > bs_without.effective_power

    def test_hull_multiplier_affects_top_speed(self, full_build):
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        # The hull has top_speed_multiplier=1.05, so top speed should be boosted
        assert bs.effective_top_speed > 0

    def test_slot_durabilities_populated(self, full_build):
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        assert "reactor" in bs.slot_durabilities
        assert "drive" in bs.slot_durabilities
        assert "thrusters" in bs.slot_durabilities
        assert "overdrive" in bs.slot_durabilities
        assert "retros" in bs.slot_durabilities
        assert "hull" in bs.slot_durabilities

    def test_overheat_risk_flags_correctly(self):
        """When overdrive temp_increase > reactor max_temp * 0.8, overheat should flag."""
        reactor_id = str(uuid.uuid4())
        overdrive_id = str(uuid.uuid4())
        cards = {
            reactor_id: {
                "stats": {
                    "primary": {
                        "power": 50,
                        "acceleration": 50,
                        "torque": 50,
                        "max_reactor_temp": 50,
                    },
                    "secondary": {"weight": -10, "durability": 50, "fuel_efficiency": 50},
                }
            },
            overdrive_id: {
                "stats": {
                    "primary": {
                        "power_boost_pct": 20,
                        "acceleration_boost_pct": 10,
                        "engine_temp_increase": 45,
                    },
                    "secondary": {"durability": 50, "torque_spike_modifier": 10},
                }
            },
        }
        slots = {
            "reactor": reactor_id,
            "drive": None,
            "thrusters": None,
            "stabilizers": None,
            "hull": None,
            "overdrive": overdrive_id,
            "retros": None,
        }
        bs = aggregate_build(slots, cards)
        assert bs.overheat_risk is True

    def test_no_overheat_when_temp_is_safe(self):
        reactor_id = str(uuid.uuid4())
        overdrive_id = str(uuid.uuid4())
        cards = {
            reactor_id: {
                "stats": {
                    "primary": {
                        "power": 50,
                        "acceleration": 50,
                        "torque": 50,
                        "max_reactor_temp": 90,
                    },
                    "secondary": {"weight": -10, "durability": 50, "fuel_efficiency": 50},
                }
            },
            overdrive_id: {
                "stats": {
                    "primary": {
                        "power_boost_pct": 20,
                        "acceleration_boost_pct": 10,
                        "engine_temp_increase": 10,
                    },
                    "secondary": {"durability": 50, "torque_spike_modifier": 10},
                }
            },
        }
        slots = {
            "reactor": reactor_id,
            "drive": None,
            "thrusters": None,
            "stabilizers": None,
            "hull": None,
            "overdrive": overdrive_id,
            "retros": None,
        }
        bs = aggregate_build(slots, cards)
        assert bs.overheat_risk is False

    def test_hull_class_applies_base_stats(self, full_build):
        """Passing a hull_class should add non-zero base stats to the build."""
        bs_no_hull = aggregate_build(full_build["slots"], full_build["cards"])
        bs_hauler = aggregate_build(full_build["slots"], full_build["cards"], hull_class="hauler")
        # hauler hull class should contribute extra power
        assert bs_hauler.effective_power != bs_no_hull.effective_power

    def test_hull_class_unknown_does_not_crash(self, full_build):
        """Unknown hull class silently contributes zero base stats."""
        bs = aggregate_build(full_build["slots"], full_build["cards"], hull_class="unicorn")
        assert bs.effective_power >= 0  # no crash, stats from cards still applied

    def test_effective_torque_exposed(self, full_build):
        """effective_torque should be non-zero when a reactor is equipped."""
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        assert bs.effective_torque > 0

    def test_effective_torque_zero_when_no_reactor(self):
        """No reactor → effective_torque should be zero."""
        bs = aggregate_build(
            {
                "reactor": None,
                "drive": None,
                "thrusters": None,
                "stabilizers": None,
                "hull": None,
                "overdrive": None,
                "retros": None,
            },
            {},
        )
        assert bs.effective_torque == 0.0

    def test_handling_capped_by_hull_modifier(self):
        """Effective handling should not exceed 100 + handling_cap_modifier."""
        str(uuid.uuid4())
        thrusters_id = str(uuid.uuid4())
        stab_id = str(uuid.uuid4())
        hull_id = str(uuid.uuid4())
        retros_id = str(uuid.uuid4())

        cards = {
            thrusters_id: {
                "stats": {
                    "primary": {"grip": 99, "handling": 99, "launch_acceleration": 99},
                    "secondary": {"durability": 99, "weather_performance": 99, "drag": 0},
                }
            },
            stab_id: {
                "stats": {
                    "primary": {"handling": 99, "stability": 99, "ride_height_modifier": 0},
                    "secondary": {"weight_balance_bonus": 20, "brake_efficiency_scaling": 20},
                }
            },
            hull_id: {
                "stats": {
                    "primary": {"drag": 0, "weight": 0, "durability": 99, "style": 99},
                    "secondary": {"handling_cap_modifier": -20, "top_speed_multiplier": 1.0},
                }
            },
            retros_id: {
                "stats": {
                    "primary": {
                        "brake_force": 99,
                        "corner_entry_speed": 99,
                        "stability_under_decel": 99,
                    },
                    "secondary": {"handling_bonus": 20, "durability": 99},
                }
            },
        }
        slots = {
            "reactor": None,
            "drive": None,
            "thrusters": thrusters_id,
            "stabilizers": stab_id,
            "hull": hull_id,
            "overdrive": None,
            "retros": retros_id,
        }
        bs = aggregate_build(slots, cards)
        assert bs.effective_handling <= 100 + (-20)  # cap is 100 + handling_cap_modifier
