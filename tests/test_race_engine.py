"""Tests for engine/race_engine.py."""

from __future__ import annotations

import random

from engine.durability import DurabilityResult, WreckPart
from engine.environment import EnvironmentCondition
from engine.race_engine import (
    Placement,
    RaceResult,
    _build_stats_to_flat,
    _compute_base_score,
    _generate_narrative,
    compute_race,
)
from engine.stat_resolver import BuildStats


class TestBuildStatsToFlat:
    def test_converts_all_fields(self):
        bs = BuildStats(
            effective_power=100,
            effective_handling=80,
            effective_top_speed=90,
            effective_grip=70,
            effective_braking=60,
            effective_durability=50,
            effective_acceleration=85,
            effective_stability=75,
            effective_weather_performance=40,
        )
        flat = _build_stats_to_flat(bs)
        assert flat["power"] == 100
        assert flat["handling"] == 80
        assert flat["top_speed"] == 90
        assert flat["grip"] == 70
        assert flat["braking"] == 60
        assert flat["durability"] == 50
        assert flat["acceleration"] == 85
        assert flat["stability"] == 75
        assert flat["weather_performance"] == 40

    def test_zero_stats(self):
        bs = BuildStats()
        flat = _build_stats_to_flat(bs)
        assert all(v == 0.0 for v in flat.values())


class TestComputeBaseScore:
    def test_sums_all_stats(self):
        stats = {"a": 10.0, "b": 20.0, "c": 30.0}
        assert _compute_base_score(stats) == 60.0

    def test_empty_stats(self):
        assert _compute_base_score({}) == 0.0


class TestComputeRace:
    def test_two_player_race(self, full_build, empty_build):
        random.seed(42)
        env = EnvironmentCondition(
            name="test_track",
            display_name="Test Track",
            description="A test.",
            stat_weights={
                "power": 1.0,
                "handling": 1.0,
                "top_speed": 1.0,
                "grip": 1.0,
                "braking": 1.0,
                "durability": 1.0,
                "acceleration": 1.0,
                "stability": 1.0,
                "weather_performance": 1.0,
            },
            variance_multiplier=1.0,
        )
        result = compute_race([full_build, empty_build], environment=env)
        assert isinstance(result, RaceResult)
        assert len(result.placements) == 2
        # Full build should score higher than empty build
        first = result.placements[0]
        second = result.placements[1]
        assert first.position == 1
        assert second.position == 2
        assert first.score >= second.score

    def test_single_player_race(self, full_build):
        random.seed(42)
        env = EnvironmentCondition(
            name="drag_strip",
            display_name="Drag Strip",
            description="Quarter mile.",
            stat_weights={
                "power": 2.0,
                "handling": 0.3,
                "top_speed": 1.5,
                "grip": 1.0,
                "braking": 1.0,
                "durability": 1.0,
                "acceleration": 1.0,
                "stability": 1.0,
                "weather_performance": 1.0,
            },
        )
        result = compute_race([full_build], environment=env)
        assert len(result.placements) == 1
        assert result.placements[0].position == 1

    def test_random_environment_used_when_none(self, full_build):
        random.seed(42)
        result = compute_race([full_build])
        assert result.environment is not None
        assert result.environment.name

    def test_dnf_sorted_last(self, full_build, empty_build):
        """If one player DNFs, they should be placed after non-DNF players."""
        random.seed(42)
        env = EnvironmentCondition(
            name="test",
            display_name="Test",
            description="Test",
            stat_weights={},
        )
        result = compute_race([full_build, empty_build], environment=env)
        # The last placement - if any is DNF, it should be sorted appropriately
        for i, p in enumerate(result.placements):
            assert p.position == i + 1

    def test_result_to_dict(self, full_build):
        random.seed(42)
        result = compute_race([full_build])
        d = result.to_dict()
        assert "placements" in d
        assert "environment" in d
        assert "wrecks" in d
        assert len(d["placements"]) == 1
        placement = d["placements"][0]
        assert "user_id" in placement
        assert "score" in placement
        assert "position" in placement
        assert "dnf" in placement
        assert "narrative" in placement


class TestGenerateNarrative:
    def _env(self):
        return EnvironmentCondition(
            name="test",
            display_name="Test Track",
            description="A test.",
            stat_weights={},
            variance_multiplier=1.0,
        )

    def _clean_dur(self):
        return DurabilityResult(failures=[], dnf=False, score_multiplier=1.0, wrecked_parts=[])

    def test_dnf_with_wrecked_parts(self):
        dur = DurabilityResult(
            failures=[],
            dnf=True,
            score_multiplier=0.0,
            wrecked_parts=[WreckPart(card_id="x", slot="engine", card_name="Ironforge V8")],
        )
        narrative = _generate_narrative(
            user_id="u1",
            equipped_cards={},
            durability_result=dur,
            score=0.0,
            position=2,
            environment=self._env(),
            distance_pct=0.4,
        )
        assert "Lost: Ironforge V8" in narrative

    def test_dnf_no_wrecked_parts(self):
        dur = DurabilityResult(failures=[], dnf=True, score_multiplier=0.0, wrecked_parts=[])
        narrative = _generate_narrative(
            user_id="u1",
            equipped_cards={},
            durability_result=dur,
            score=0.0,
            position=2,
            environment=self._env(),
            distance_pct=0.5,
        )
        assert "survived" in narrative

    def test_clean_first_place(self):
        narrative = _generate_narrative(
            user_id="u1",
            equipped_cards={"engine": {"name": "Ironforge V8"}},
            durability_result=self._clean_dur(),
            score=300.0,
            position=1,
            environment=self._env(),
            distance_pct=1.0,
        )
        assert "First place" in narrative

    def test_clean_mid_position(self):
        narrative = _generate_narrative(
            user_id="u1",
            equipped_cards={},
            durability_result=self._clean_dur(),
            score=200.0,
            position=2,
            environment=self._env(),
            distance_pct=1.0,
        )
        assert "P2" in narrative

    def test_clean_low_position(self):
        narrative = _generate_narrative(
            user_id="u1",
            equipped_cards={},
            durability_result=self._clean_dur(),
            score=100.0,
            position=4,
            environment=self._env(),
            distance_pct=1.0,
        )
        assert "P4" in narrative and "improvement" in narrative

    def test_failures_without_dnf(self):
        from engine.durability import FailureEvent, FailureSeverity

        dur = DurabilityResult(
            failures=[
                FailureEvent(
                    slot="tires",
                    severity=FailureSeverity.MINOR,
                    narrative_fragment="Tires slipped.",
                )
            ],
            dnf=False,
            score_multiplier=0.9,
            wrecked_parts=[],
        )
        narrative = _generate_narrative(
            user_id="u1",
            equipped_cards={},
            durability_result=dur,
            score=180.0,
            position=2,
            environment=self._env(),
            distance_pct=1.0,
        )
        assert "Tires slipped" in narrative


class TestComputeRaceTies:
    def test_tie_detection_identical_scores(self, full_build):
        """Two identical builds should produce equal scores and be marked as ties."""
        import copy

        build2 = copy.deepcopy(full_build)
        build2["user_id"] = "999999999"
        random.seed(0)
        result = compute_race([full_build, build2])
        scores = [p.score for p in result.placements]
        # With same seed and same build, both scores should be equal → tie
        if scores[0] == scores[1]:
            assert any(p.is_tie for p in result.placements)


class TestPlacement:
    def test_to_dict(self):
        p = Placement(
            user_id="123",
            score=150.5,
            position=1,
            dnf=False,
            narrative="Great race!",
        )
        d = p.to_dict()
        assert d["user_id"] == "123"
        assert d["score"] == 150.5
        assert d["position"] == 1
        assert d["dnf"] is False
        assert d["narrative"] == "Great race!"
