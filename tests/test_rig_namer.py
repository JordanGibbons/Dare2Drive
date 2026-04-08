"""Tests for engine/rig_namer.py."""

from __future__ import annotations

import pytest

from db.models import BodyType, CarClass
from engine.rig_namer import generate_rig_name
from engine.stat_resolver import BuildStats


class TestGenerateRigName:
    def test_returns_non_empty_string(self):
        result = generate_rig_name(CarClass.DRAG, BodyType.MUSCLE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_two_words(self):
        result = generate_rig_name(CarClass.CIRCUIT, BodyType.SPORT)
        parts = result.split()
        assert len(parts) == 2

    @pytest.mark.parametrize(
        "car_class,body_type",
        [
            (CarClass.DRAG, BodyType.MUSCLE),
            (CarClass.DRAG, BodyType.SPORT),
            (CarClass.DRAG, BodyType.COMPACT),
            (CarClass.CIRCUIT, BodyType.MUSCLE),
            (CarClass.CIRCUIT, BodyType.SPORT),
            (CarClass.CIRCUIT, BodyType.COMPACT),
            (CarClass.DRIFT, BodyType.MUSCLE),
            (CarClass.DRIFT, BodyType.SPORT),
            (CarClass.DRIFT, BodyType.COMPACT),
            (CarClass.RALLY, BodyType.MUSCLE),
            (CarClass.RALLY, BodyType.SPORT),
            (CarClass.RALLY, BodyType.COMPACT),
            (CarClass.ELITE, BodyType.MUSCLE),
            (CarClass.ELITE, BodyType.SPORT),
            (CarClass.ELITE, BodyType.COMPACT),
            (CarClass.STREET, BodyType.MUSCLE),
            (CarClass.STREET, BodyType.SPORT),
            (CarClass.STREET, BodyType.COMPACT),
        ],
    )
    def test_all_class_body_combos_return_string(self, car_class, body_type):
        result = generate_rig_name(car_class, body_type)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_none_body_type_does_not_crash(self):
        result = generate_rig_name(CarClass.DRAG, None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_stats_param_accepted_without_error(self):
        bs = BuildStats()
        result = generate_rig_name(CarClass.CIRCUIT, BodyType.SPORT, stats=bs)
        assert isinstance(result, str)

    def test_names_are_not_always_identical(self):
        """Multiple calls should not always return the same name (randomness test)."""
        results = {generate_rig_name(CarClass.DRAG, BodyType.MUSCLE) for _ in range(20)}
        # With pools of 8×8 combinations the chance of all 20 being the same is ~1 in 64
        assert len(results) > 1

    def test_drift_compact_uses_thematic_words(self):
        """DRIFT+COMPACT pool contains ghost/phantom/wraith themed words."""
        pool_words = {
            "Ghost",
            "Phantom",
            "Wraith",
            "Specter",
            "Mist",
            "Wisp",
            "Vapor",
            "Runner",
            "Stalker",
            "Drifter",
            "Shade",
            "Drift",
            "Trace",
            "Whisper",
            "Haunt",
        }
        found = False
        for _ in range(30):
            name = generate_rig_name(CarClass.DRIFT, BodyType.COMPACT)
            if any(word in name for word in pool_words):
                found = True
                break
        assert found, "DRIFT+COMPACT names should use ghost/drift themed words"

    def test_drag_muscle_uses_thematic_words(self):
        """DRAG+MUSCLE pool contains iron/thunder/hammer themed words."""
        pool_words = {
            "Iron",
            "Thunder",
            "Hammer",
            "Steel",
            "Titan",
            "Boulder",
            "Fury",
            "Wrath",
            "Fist",
            "Brute",
            "Cannon",
            "Crusher",
            "Bull",
            "Hauler",
            "Slab",
            "Beast",
        }
        found = False
        for _ in range(30):
            name = generate_rig_name(CarClass.DRAG, BodyType.MUSCLE)
            if any(word in name for word in pool_words):
                found = True
                break
        assert found, "DRAG+MUSCLE names should use iron/thunder themed words"
