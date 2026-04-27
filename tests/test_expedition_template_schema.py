"""JSON-Schema-level validator tests for expedition templates."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "expeditions" / "schema.json"


@pytest.fixture(scope="module")
def schema():
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _scripted_min():
    """Minimal valid scripted template body."""
    return {
        "id": "scripted_min",
        "kind": "scripted",
        "duration_minutes": 360,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "opening",
                "narration": "You depart.",
            },
            {
                "id": "closing",
                "is_closing": True,
                "closings": [
                    {"when": {"default": True}, "body": "You return.", "effects": []},
                ],
            },
        ],
    }


def _rolled_min():
    return {
        "id": "rolled_min",
        "kind": "rolled",
        "duration_minutes": 360,
        "response_window_minutes": 30,
        "event_count": 1,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "opening": {"id": "opening", "narration": "You depart."},
        "events": [
            {
                "id": "evt_a",
                "narration": "Something happens.",
                "choices": [
                    {
                        "id": "safe",
                        "text": "Play it safe.",
                        "default": True,
                        "outcomes": {"result": {"narrative": "ok", "effects": []}},
                    },
                ],
            },
        ],
        "closings": [
            {"when": {"default": True}, "body": "You return.", "effects": []},
        ],
    }


def test_scripted_minimum_validates(schema):
    jsonschema.validate(_scripted_min(), schema)


def test_rolled_minimum_validates(schema):
    jsonschema.validate(_rolled_min(), schema)


def test_kind_enum_enforced(schema):
    bad = _scripted_min()
    bad["kind"] = "novel"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_id_pattern_enforced(schema):
    bad = _scripted_min()
    bad["id"] = "BadID-WithDash"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_rolled_requires_event_count(schema):
    bad = _rolled_min()
    del bad["event_count"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_scripted_requires_scenes(schema):
    bad = _scripted_min()
    del bad["scenes"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_choice_with_roll_requires_success_and_failure(schema):
    bad = _rolled_min()
    bad["events"][0]["choices"][0] = {
        "id": "rolled_choice",
        "text": "Try it.",
        "default": True,
        "roll": {"stat": "pilot.acceleration", "base_p": 0.5, "base_stat": 50, "per_point": 0.005},
        "outcomes": {"result": {"narrative": "ok", "effects": []}},  # missing success/failure
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
