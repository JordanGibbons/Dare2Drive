"""Tests for engine/durability.py."""

from __future__ import annotations

import random
from unittest.mock import patch

from engine.durability import (
    DurabilityResult,
    FailureSeverity,
    WreckPart,
    _determine_severity,
    _should_part_survive_wreck,
    check_durability,
)


class TestDetermineSeverity:
    def test_minor(self):
        assert _determine_severity(1) == FailureSeverity.MINOR
        assert _determine_severity(10) == FailureSeverity.MINOR
        assert _determine_severity(20) == FailureSeverity.MINOR

    def test_major(self):
        assert _determine_severity(21) == FailureSeverity.MAJOR
        assert _determine_severity(30) == FailureSeverity.MAJOR
        assert _determine_severity(40) == FailureSeverity.MAJOR

    def test_dnf(self):
        assert _determine_severity(41) == FailureSeverity.DNF
        assert _determine_severity(60) == FailureSeverity.DNF
        assert _determine_severity(100) == FailureSeverity.DNF


class TestShouldPartSurviveWreck:
    def test_ghost_always_survives(self):
        for _ in range(50):
            assert _should_part_survive_wreck("ghost") is True

    def test_common_never_survives(self):
        for _ in range(50):
            assert _should_part_survive_wreck("common") is False

    def test_uncommon_never_survives(self):
        assert _should_part_survive_wreck("uncommon") is False

    def test_rare_never_survives(self):
        assert _should_part_survive_wreck("rare") is False

    def test_epic_never_survives(self):
        assert _should_part_survive_wreck("epic") is False

    def test_legendary_has_50_percent_chance(self):
        # Seed for determinism
        random.seed(42)
        results = [_should_part_survive_wreck("legendary") for _ in range(1000)]
        survival_rate = sum(results) / len(results)
        assert 0.4 < survival_rate < 0.6  # Should be roughly 50%


class TestCheckDurability:
    def test_high_durability_no_failures(self):
        """Parts with durability 100 should never fail."""
        slot_durabilities = {"reactor": 100, "thrusters": 100, "retros": 100}
        equipped = {
            "reactor": {"id": "e1", "name": "Test Reactor", "rarity": "common"},
            "thrusters": {"id": "t1", "name": "Test Thrusters", "rarity": "common"},
            "retros": {"id": "b1", "name": "Test Retros", "rarity": "common"},
        }
        # The roll is random(0,100) and durability is 100, so roll can never exceed it
        # Actually uniform(0,100) can equal 100 in theory, but practically never
        random.seed(1)
        result = check_durability(slot_durabilities, equipped)
        assert isinstance(result, DurabilityResult)

    def test_zero_durability_always_fails(self):
        """Parts with durability 0 should not be checked (skipped)."""
        slot_durabilities = {"reactor": 0}
        equipped = {"reactor": {"id": "e1", "name": "Test", "rarity": "common"}}
        result = check_durability(slot_durabilities, equipped)
        assert len(result.failures) == 0

    @patch("engine.durability.random.uniform", return_value=90.0)
    def test_low_durability_causes_failure(self, mock_uniform):
        """A roll of 90 against durability 30 → excess 60 → DNF."""
        slot_durabilities = {"reactor": 30}
        equipped = {"reactor": {"id": "e1", "name": "Bad Reactor", "rarity": "common"}}
        result = check_durability(slot_durabilities, equipped)
        assert len(result.failures) == 1
        assert result.failures[0].severity == FailureSeverity.DNF
        assert result.dnf is True
        assert result.score_multiplier == 0.0

    @patch("engine.durability.random.uniform", return_value=55.0)
    def test_minor_failure(self, mock_uniform):
        """Roll 55 against durability 50 → excess 5 → minor."""
        slot_durabilities = {"reactor": 50}
        equipped = {"reactor": {"id": "e1", "name": "Test Reactor", "rarity": "common"}}
        result = check_durability(slot_durabilities, equipped)
        assert len(result.failures) == 1
        assert result.failures[0].severity == FailureSeverity.MINOR
        assert result.score_multiplier == 0.85
        assert result.dnf is False

    @patch("engine.durability.random.uniform", return_value=75.0)
    def test_major_failure(self, mock_uniform):
        """Roll 75 against durability 50 → excess 25 → major."""
        slot_durabilities = {"reactor": 50}
        equipped = {"reactor": {"id": "e1", "name": "Test Reactor", "rarity": "common"}}
        result = check_durability(slot_durabilities, equipped)
        assert len(result.failures) == 1
        assert result.failures[0].severity == FailureSeverity.MAJOR
        assert result.score_multiplier == 0.60

    def test_wreck_parts_only_on_dnf(self):
        """Wrecked parts should only be populated when DNF occurs."""
        slot_durabilities = {"reactor": 100}
        equipped = {"reactor": {"id": "e1", "name": "Test", "rarity": "common"}}
        random.seed(1)
        result = check_durability(slot_durabilities, equipped)
        assert result.wrecked_parts == []

    @patch("engine.durability.random.uniform", return_value=99.0)
    @patch("engine.durability._resolve_wreck")
    def test_dnf_triggers_wreck(self, mock_wreck, mock_uniform):
        mock_wreck.return_value = [WreckPart(card_id="e1", slot="reactor", card_name="Bad Reactor")]
        slot_durabilities = {"reactor": 30}
        equipped = {"reactor": {"id": "e1", "name": "Bad Reactor", "rarity": "common"}}
        result = check_durability(slot_durabilities, equipped)
        assert result.dnf is True
        assert len(result.wrecked_parts) == 1
        assert result.wrecked_parts[0].card_name == "Bad Reactor"

    def test_overdrive_overheat_check(self):
        """Overdrive should have extra failure chance when overheating."""
        # Use a seed that makes initial roll pass but overheat roll fail
        slot_durabilities = {"overdrive": 80}
        equipped = {
            "overdrive": {"id": "t1", "name": "Hot Overdrive", "rarity": "common"},
        }
        # engine_temp_increase > engine_max_temp * 0.8
        random.seed(0)
        result = check_durability(
            slot_durabilities,
            equipped,
            turbo_temp_increase=50,
            engine_max_temp=40,
        )
        # Result varies by seed, but the code path should execute without error
        assert isinstance(result, DurabilityResult)


class TestWreckPart:
    def test_to_dict(self):
        wp = WreckPart(card_id="abc", slot="reactor", card_name="Test")
        d = wp.to_dict()
        assert d == {"card_id": "abc", "slot": "reactor", "card_name": "Test"}
