"""Engine tests for resolve_scene, select_closing, _filter_visible_choices."""

from __future__ import annotations

import pytest


def test_filter_visible_choices_hides_archetype_gated(monkeypatch):
    from engine.expedition_engine import _filter_visible_choices

    scene = {
        "id": "test",
        "choices": [
            {
                "id": "always",
                "text": "ok",
                "default": True,
                "outcomes": {"result": {"narrative": "x", "effects": []}},
            },
            {
                "id": "engineer_only",
                "text": "ok",
                "requires": {"archetype": "ENGINEER"},
                "outcomes": {"result": {"narrative": "x", "effects": []}},
            },
        ],
    }
    visible = _filter_visible_choices(
        scene, assigned_archetypes={"PILOT"}, ship_hull_class="SKIRMISHER"
    )
    assert {c["id"] for c in visible} == {"always"}


def test_filter_visible_choices_hides_implicit_archetype_gate(monkeypatch):
    """A choice with `roll.stat: pilot.X` is hidden when no PILOT is assigned."""
    from engine.expedition_engine import _filter_visible_choices

    scene = {
        "id": "test",
        "choices": [
            {
                "id": "always",
                "text": "ok",
                "default": True,
                "outcomes": {"result": {"narrative": "x", "effects": []}},
            },
            {
                "id": "pilot_roll",
                "text": "ok",
                "roll": {
                    "stat": "pilot.acceleration",
                    "base_p": 0.5,
                    "base_stat": 50,
                    "per_point": 0.005,
                },
                "outcomes": {
                    "success": {"narrative": "yes", "effects": []},
                    "failure": {"narrative": "no", "effects": []},
                },
            },
        ],
    }
    visible = _filter_visible_choices(
        scene, assigned_archetypes={"GUNNER"}, ship_hull_class="HAULER"
    )
    assert {c["id"] for c in visible} == {"always"}


def test_filter_visible_choices_keeps_default_always():
    """Default choice is always visible (validator enforces no requires)."""
    from engine.expedition_engine import _filter_visible_choices

    scene = {
        "id": "test",
        "choices": [
            {
                "id": "default_choice",
                "text": "ok",
                "default": True,
                "outcomes": {"result": {"narrative": "x", "effects": []}},
            },
        ],
    }
    visible = _filter_visible_choices(
        scene, assigned_archetypes=set(), ship_hull_class="SKIRMISHER"
    )
    assert {c["id"] for c in visible} == {"default_choice"}


def test_select_closing_first_match_wins():
    from engine.expedition_engine import select_closing

    closings = [
        {"when": {"min_successes": 99}, "body": "unreachable", "effects": []},
        {"when": {"min_successes": 1}, "body": "matched", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    state = {"successes": 2, "failures": 0, "flags": set()}
    selected = select_closing(closings, state)
    assert selected["body"] == "matched"


def test_select_closing_default_when_no_match():
    from engine.expedition_engine import select_closing

    closings = [
        {"when": {"min_successes": 99}, "body": "unreachable", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    state = {"successes": 0, "failures": 0, "flags": set()}
    selected = select_closing(closings, state)
    assert selected["body"] == "fallback"


def test_select_closing_has_flag_match():
    from engine.expedition_engine import select_closing

    closings = [
        {"when": {"has_flag": "rescued"}, "body": "good", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    selected = select_closing(
        closings,
        {
            "successes": 0,
            "failures": 0,
            "flags": {"rescued"},
        },
    )
    assert selected["body"] == "good"


def test_select_closing_not_flag_match():
    from engine.expedition_engine import select_closing

    closings = [
        {"when": {"not_flag": "rescued"}, "body": "alone", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    selected = select_closing(
        closings,
        {
            "successes": 0,
            "failures": 0,
            "flags": set(),
        },
    )
    assert selected["body"] == "alone"


@pytest.mark.asyncio
async def test_resolve_scene_with_roll_records_outcome(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    """Successful roll should produce success branch + correct ledger write."""
    from engine import expedition_engine
    from engine.expedition_engine import resolve_scene

    # Pin the RNG to a value that always falls under base_p; the test asserts
    # the success branch is wired correctly, not that 0.99 wins by luck.
    monkeypatch.setattr(expedition_engine, "_seeded_random", lambda *_: 0.0)

    expedition, _ = sample_expedition_with_pilot
    scene = {
        "id": "roll_test",
        "narration": "test",
        "choices": [
            {
                "id": "go",
                "text": "Go.",
                "default": True,
                "roll": {
                    "stat": "pilot.acceleration",
                    "base_p": 0.99,
                    "base_stat": 50,
                    "per_point": 0.005,
                },
                "outcomes": {
                    "success": {
                        "narrative": "yay",
                        "effects": [{"reward_credits": 100}],
                    },
                    "failure": {
                        "narrative": "boo",
                        "effects": [{"reward_credits": -50}],
                    },
                },
            },
        ],
    }
    resolution = await resolve_scene(
        db_session,
        expedition,
        scene,
        picked_choice_id="go",
    )
    assert resolution["choice_id"] == "go"
    assert resolution["outcome"]["narrative"] == "yay"
    assert resolution["roll"] is not None


@pytest.mark.asyncio
async def test_resolve_scene_seeded_rng_is_stable(db_session, sample_expedition_with_pilot):
    """Re-resolving the same (expedition_id, scene_id) must produce the same rolled value."""
    from engine.expedition_engine import _seeded_random

    expedition, _ = sample_expedition_with_pilot
    a = _seeded_random(expedition.id, "scene_a")
    b = _seeded_random(expedition.id, "scene_a")
    assert a == b
    c = _seeded_random(expedition.id, "scene_b")
    assert a != c


@pytest.mark.asyncio
async def test_resolve_scene_default_when_no_pick(db_session, sample_expedition_with_pilot):
    """auto_resolved=True when picked_choice_id is None."""
    from engine.expedition_engine import resolve_scene

    expedition, _ = sample_expedition_with_pilot
    scene = {
        "id": "auto_test",
        "narration": "test",
        "choices": [
            {
                "id": "comply",
                "text": "ok",
                "default": True,
                "outcomes": {
                    "result": {
                        "narrative": "default",
                        "effects": [{"reward_credits": -10}],
                    }
                },
            },
        ],
    }
    resolution = await resolve_scene(
        db_session,
        expedition,
        scene,
        picked_choice_id=None,
    )
    assert resolution["auto_resolved"] is True
    assert resolution["choice_id"] == "comply"
