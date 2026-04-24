"""Tests for engine/ship_namer.py."""

from __future__ import annotations

import pytest

from db.models import HullClass, RaceFormat
from engine.ship_namer import generate_ship_name
from engine.stat_resolver import BuildStats


class TestGenerateShipName:
    def test_returns_non_empty_string(self):
        result = generate_ship_name(RaceFormat.SPRINT, HullClass.HAULER)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_two_words(self):
        result = generate_ship_name(RaceFormat.ENDURANCE, HullClass.SKIRMISHER)
        parts = result.split()
        assert len(parts) == 2

    @pytest.mark.parametrize(
        "race_format,hull_class",
        [
            (RaceFormat.SPRINT, HullClass.HAULER),
            (RaceFormat.SPRINT, HullClass.SKIRMISHER),
            (RaceFormat.SPRINT, HullClass.SCOUT),
            (RaceFormat.ENDURANCE, HullClass.HAULER),
            (RaceFormat.ENDURANCE, HullClass.SKIRMISHER),
            (RaceFormat.ENDURANCE, HullClass.SCOUT),
            (RaceFormat.GAUNTLET, HullClass.HAULER),
            (RaceFormat.GAUNTLET, HullClass.SKIRMISHER),
            (RaceFormat.GAUNTLET, HullClass.SCOUT),
        ],
    )
    def test_all_format_hull_combos_return_string(self, race_format, hull_class):
        result = generate_ship_name(race_format, hull_class)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_none_hull_class_does_not_crash(self):
        result = generate_ship_name(RaceFormat.SPRINT, None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_stats_param_accepted_without_error(self):
        bs = BuildStats()
        result = generate_ship_name(RaceFormat.ENDURANCE, HullClass.SKIRMISHER, stats=bs)
        assert isinstance(result, str)

    def test_names_are_not_always_identical(self):
        """Multiple calls should not always return the same name (randomness test)."""
        results = {generate_ship_name(RaceFormat.SPRINT, HullClass.HAULER) for _ in range(20)}
        # With pools of 8×8 combinations the chance of all 20 being the same is ~1 in 64
        assert len(results) > 1

    def test_gauntlet_skirmisher_uses_thematic_words(self):
        """GAUNTLET+SKIRMISHER pool contains ghost/phantom/wraith themed words."""
        pool_words = {
            "Ghost",
            "Phantom",
            "Wraith",
            "Specter",
            "Blackstar",
            "Smoke",
            "Silk",
            "Runner",
            "Stalker",
            "Drifter",
            "Shade",
            "Trace",
            "Whisper",
            "Haunt",
            "Glide",
        }
        found = False
        for _ in range(30):
            name = generate_ship_name(RaceFormat.GAUNTLET, HullClass.SKIRMISHER)
            if any(word in name for word in pool_words):
                found = True
                break
        assert found, "GAUNTLET+SKIRMISHER names should use ghost/phantom themed words"

    def test_sprint_hauler_uses_thematic_words(self):
        """SPRINT+HAULER pool contains iron/thunder/hammer themed words."""
        pool_words = {
            "Iron",
            "Thunder",
            "Hammer",
            "Steel",
            "Titan",
            "Gravjaw",
            "Fury",
            "Wrath",
            "Fist",
            "Brute",
            "Cannon",
            "Crusher",
            "Hauler",
            "Slab",
            "Beast",
            "Barge",
        }
        found = False
        for _ in range(30):
            name = generate_ship_name(RaceFormat.SPRINT, HullClass.HAULER)
            if any(word in name for word in pool_words):
                found = True
                break
        assert found, "SPRINT+HAULER names should use iron/thunder themed words"
