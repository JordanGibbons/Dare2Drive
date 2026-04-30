"""Phase 2c — narrative-token allow-list validator extension."""

from __future__ import annotations

import pytest

# Minimal valid template fragments used to exercise narrative validation.
# We only fill the fields the validator inspects for tokens.


def _scripted_template_with_narration(narration: str) -> dict:
    """Build a minimal scripted template that passes JSON Schema.

    Schema requires:
    - Top-level: id, kind, duration_minutes, response_window_minutes,
      cost_credits, crew_required
    - scripted kind: scenes (minItems: 2)
    - scenes need at least 2 items; the closing scene must have is_closing+closings
      so the semantic "exactly one default closing" check passes.

    The narration parameter is placed in the first scene narration field.
    """
    return {
        "id": "test_template",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "opening",
                "narration": narration,
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


def test_validator_accepts_known_token_pilot_callsign():
    from engine.expedition_template import validate_template_dict

    tmpl = _scripted_template_with_narration("{pilot.callsign} climbs in.")
    # Should not raise
    validate_template_dict(tmpl)


def test_validator_accepts_known_token_ship():
    from engine.expedition_template import validate_template_dict

    tmpl = _scripted_template_with_narration("The {ship} drops out of warp.")
    validate_template_dict(tmpl)


def test_validator_accepts_double_brace_escape():
    from engine.expedition_template import validate_template_dict

    tmpl = _scripted_template_with_narration("Use {{pilot}} as a slot name.")
    validate_template_dict(tmpl)


def test_validator_rejects_unknown_top_level_token():
    from engine.expedition_template import (
        TemplateValidationError,
        validate_template_dict,
    )

    tmpl = _scripted_template_with_narration("{villain} appears.")
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template_dict(tmpl)
    assert "villain" in str(exc_info.value)


def test_validator_rejects_unknown_attr_on_known_slot():
    from engine.expedition_template import (
        TemplateValidationError,
        validate_template_dict,
    )

    tmpl = _scripted_template_with_narration("{pilot.combat_score} is sharp tonight.")
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template_dict(tmpl)
    assert "combat_score" in str(exc_info.value)


def test_validator_walks_choice_text_and_outcome_narrative():
    """Tokens in nested fields (choices, outcomes) are also checked."""
    from engine.expedition_template import (
        TemplateValidationError,
        validate_template_dict,
    )

    tmpl = _scripted_template_with_narration("plain narration")
    tmpl["scenes"] = [
        {
            "id": "s1",
            "narration": "ok",
            "choices": [
                {
                    "id": "c1",
                    "text": "{villain} attacks!",  # bad token in choice text
                    "default": True,
                    "outcomes": {"result": {"narrative": "ok", "effects": []}},
                },
            ],
        },
        {
            "id": "closing",
            "is_closing": True,
            "closings": [
                {"when": {"default": True}, "body": "You return.", "effects": []},
            ],
        },
    ]
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template_dict(tmpl)
    assert "villain" in str(exc_info.value)
