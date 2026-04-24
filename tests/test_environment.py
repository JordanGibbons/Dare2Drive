"""Tests for engine/environment.py."""

from __future__ import annotations

import json
from pathlib import Path

from engine.environment import (
    EnvironmentCondition,
    apply_environment_weights,
    get_environment_by_name,
    roll_environment,
)


class TestRollEnvironment:
    def test_returns_environment_condition(self):
        env = roll_environment()
        assert isinstance(env, EnvironmentCondition)
        assert env.name
        assert env.display_name
        assert env.description
        assert isinstance(env.stat_weights, dict)
        assert env.variance_multiplier > 0

    def test_all_environments_loadable(self):
        """Every environment in JSON should be loadable by name."""
        env_file = Path(__file__).resolve().parent.parent / "data" / "environments.json"
        with open(env_file) as f:
            envs = json.load(f)
        for env_data in envs:
            env = get_environment_by_name(env_data["name"])
            assert env.name == env_data["name"]


class TestGetEnvironmentByName:
    def test_known_environment(self):
        env = get_environment_by_name("nebula")
        assert env.name == "nebula"
        assert env.stat_weights["grip"] == 2.0

    def test_unknown_environment_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown environment"):
            get_environment_by_name("nonexistent_track")


class TestApplyEnvironmentWeights:
    def test_weights_applied_correctly(self):
        stats = {"power": 100, "grip": 50, "handling": 80}
        env = EnvironmentCondition(
            name="test",
            display_name="Test",
            description="Test",
            stat_weights={"power": 2.0, "grip": 0.5},
        )
        weighted = apply_environment_weights(stats, env)
        assert weighted["power"] == 200.0
        assert weighted["grip"] == 25.0
        assert weighted["handling"] == 80.0  # default weight 1.0

    def test_empty_stats(self):
        env = EnvironmentCondition(
            name="test",
            display_name="Test",
            description="Test",
            stat_weights={"power": 2.0},
        )
        assert apply_environment_weights({}, env) == {}

    def test_to_dict(self):
        env = EnvironmentCondition(
            name="test",
            display_name="Test",
            description="Desc",
            stat_weights={"a": 1.5},
            variance_multiplier=2.0,
        )
        d = env.to_dict()
        assert d["name"] == "test"
        assert d["variance_multiplier"] == 2.0
        assert d["stat_weights"]["a"] == 1.5


class TestEnvironmentStatWeights:
    """Validate specific environment configs match the design spec."""

    def test_nebula_weights(self):
        env = get_environment_by_name("nebula")
        assert env.stat_weights["grip"] == 2.0
        assert env.stat_weights["weather_performance"] == 1.8
        assert env.stat_weights["handling"] == 1.3
        assert env.stat_weights["power"] == 0.8

    def test_solar_flare_weights(self):
        env = get_environment_by_name("solar_flare")
        assert env.stat_weights["power"] == 2.0
        assert env.stat_weights["top_speed"] == 1.5
        assert env.stat_weights["handling"] == 0.3

    def test_clear_space_variance(self):
        env = get_environment_by_name("clear_space")
        assert env.variance_multiplier == 1.5

    def test_debris_field_weights(self):
        env = get_environment_by_name("debris_field")
        assert env.stat_weights["stability"] == 2.0
        assert env.stat_weights["top_speed"] == 0.5
