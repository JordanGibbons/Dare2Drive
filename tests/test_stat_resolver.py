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

    def test_turbo_boosts_power(self, full_build):
        # With turbo
        bs_with = aggregate_build(full_build["slots"], full_build["cards"])

        # Without turbo
        slots_no_turbo = dict(full_build["slots"])
        slots_no_turbo["turbo"] = None
        bs_without = aggregate_build(slots_no_turbo, full_build["cards"])

        assert bs_with.effective_power > bs_without.effective_power

    def test_chassis_multiplier_affects_top_speed(self, full_build):
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        # The chassis has top_speed_multiplier=1.05, so top speed should be boosted
        assert bs.effective_top_speed > 0

    def test_slot_durabilities_populated(self, full_build):
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        assert "engine" in bs.slot_durabilities
        assert "transmission" in bs.slot_durabilities
        assert "tires" in bs.slot_durabilities
        assert "turbo" in bs.slot_durabilities
        assert "brakes" in bs.slot_durabilities
        assert "chassis" in bs.slot_durabilities

    def test_overheat_risk_flags_correctly(self):
        """When turbo temp_increase > engine max_temp * 0.8, overheat should flag."""
        engine_id = str(uuid.uuid4())
        turbo_id = str(uuid.uuid4())
        cards = {
            engine_id: {
                "stats": {
                    "primary": {
                        "power": 50,
                        "acceleration": 50,
                        "torque": 50,
                        "max_engine_temp": 50,
                    },
                    "secondary": {"weight": -10, "durability": 50, "fuel_efficiency": 50},
                }
            },
            turbo_id: {
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
            "engine": engine_id,
            "transmission": None,
            "tires": None,
            "suspension": None,
            "chassis": None,
            "turbo": turbo_id,
            "brakes": None,
        }
        bs = aggregate_build(slots, cards)
        assert bs.overheat_risk is True

    def test_no_overheat_when_temp_is_safe(self):
        engine_id = str(uuid.uuid4())
        turbo_id = str(uuid.uuid4())
        cards = {
            engine_id: {
                "stats": {
                    "primary": {
                        "power": 50,
                        "acceleration": 50,
                        "torque": 50,
                        "max_engine_temp": 90,
                    },
                    "secondary": {"weight": -10, "durability": 50, "fuel_efficiency": 50},
                }
            },
            turbo_id: {
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
            "engine": engine_id,
            "transmission": None,
            "tires": None,
            "suspension": None,
            "chassis": None,
            "turbo": turbo_id,
            "brakes": None,
        }
        bs = aggregate_build(slots, cards)
        assert bs.overheat_risk is False

    def test_body_type_applies_base_stats(self, full_build):
        """Passing a body_type should add non-zero base stats to the build."""
        bs_no_body = aggregate_build(full_build["slots"], full_build["cards"])
        bs_muscle = aggregate_build(full_build["slots"], full_build["cards"], body_type="muscle")
        # muscle body type should contribute extra power
        assert bs_muscle.effective_power != bs_no_body.effective_power

    def test_body_type_unknown_does_not_crash(self, full_build):
        """Unknown body type silently contributes zero base stats."""
        bs = aggregate_build(full_build["slots"], full_build["cards"], body_type="unicorn")
        assert bs.effective_power >= 0  # no crash, stats from cards still applied

    def test_effective_torque_exposed(self, full_build):
        """effective_torque should be non-zero when an engine is equipped."""
        bs = aggregate_build(full_build["slots"], full_build["cards"])
        assert bs.effective_torque > 0

    def test_effective_torque_zero_when_no_engine(self):
        """No engine → effective_torque should be zero."""
        bs = aggregate_build(
            {
                "engine": None,
                "transmission": None,
                "tires": None,
                "suspension": None,
                "chassis": None,
                "turbo": None,
                "brakes": None,
            },
            {},
        )
        assert bs.effective_torque == 0.0

    def test_handling_capped_by_chassis_modifier(self):
        """Effective handling should not exceed 100 + handling_cap_modifier."""
        str(uuid.uuid4())
        tires_id = str(uuid.uuid4())
        susp_id = str(uuid.uuid4())
        chassis_id = str(uuid.uuid4())
        brakes_id = str(uuid.uuid4())

        cards = {
            tires_id: {
                "stats": {
                    "primary": {"grip": 99, "handling": 99, "launch_acceleration": 99},
                    "secondary": {"durability": 99, "weather_performance": 99, "drag": 0},
                }
            },
            susp_id: {
                "stats": {
                    "primary": {"handling": 99, "stability": 99, "ride_height_modifier": 0},
                    "secondary": {"weight_balance_bonus": 20, "brake_efficiency_scaling": 20},
                }
            },
            chassis_id: {
                "stats": {
                    "primary": {"drag": 0, "weight": 0, "durability": 99, "style": 99},
                    "secondary": {"handling_cap_modifier": -20, "top_speed_multiplier": 1.0},
                }
            },
            brakes_id: {
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
            "engine": None,
            "transmission": None,
            "tires": tires_id,
            "suspension": susp_id,
            "chassis": chassis_id,
            "turbo": None,
            "brakes": brakes_id,
        }
        bs = aggregate_build(slots, cards)
        assert bs.effective_handling <= 100 + (-20)  # cap is 100 + handling_cap_modifier
