"""Tests for engine/timer_recipes.py — JSON loader and lookup."""

from __future__ import annotations

import pytest

from db.models import TimerType


def test_get_recipe_returns_known_routine():
    from engine.timer_recipes import get_recipe

    r = get_recipe(TimerType.TRAINING, "combat_drills")
    assert r["id"] == "combat_drills"
    assert r["duration_minutes"] == 30
    assert r["cost_credits"] == 50
    assert r["rewards"]["xp"] == 200


def test_get_recipe_unknown_id_raises():
    from engine.timer_recipes import RecipeNotFound, get_recipe

    with pytest.raises(RecipeNotFound):
        get_recipe(TimerType.TRAINING, "no_such_routine")


def test_list_recipes_returns_all_for_type():
    from engine.timer_recipes import list_recipes

    training = list_recipes(TimerType.TRAINING)
    assert {r["id"] for r in training} == {
        "combat_drills",
        "specialty_course",
        "field_exercise",
    }
    research = list_recipes(TimerType.RESEARCH)
    assert {r["id"] for r in research} == {
        "drive_tuning",
        "shield_calibration",
        "nav_charting",
    }
    ship_build = list_recipes(TimerType.SHIP_BUILD)
    assert {r["id"] for r in ship_build} == {"salvage_reconstruction"}


def test_recipe_id_uniqueness_enforced_at_load():
    """If two recipes share an id within a type, loader raises."""
    from engine.timer_recipes import _build_registry

    bad_data = {
        TimerType.TRAINING: [
            {"id": "x", "name": "X", "duration_minutes": 1, "cost_credits": 1, "rewards": {}},
            {"id": "x", "name": "X2", "duration_minutes": 1, "cost_credits": 1, "rewards": {}},
        ]
    }
    with pytest.raises(ValueError, match="duplicate recipe id"):
        _build_registry(bad_data)
