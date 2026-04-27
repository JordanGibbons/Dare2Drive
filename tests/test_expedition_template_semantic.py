"""Semantic validator tests — invariants the JSON Schema can't express."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

SCRIPTED_YAML = textwrap.dedent("""\
    id: scripted_test
    kind: scripted
    duration_minutes: 360
    response_window_minutes: 30
    cost_credits: 0
    crew_required: { min: 1, archetypes_any: [PILOT] }
    scenes:
      - id: opening
        narration: "You depart."
      - id: midscene
        narration: "Pirates!"
        choices:
          - id: comply
            text: "Pay them."
            default: true
            outcomes:
              result:
                narrative: "Paid."
                effects:
                  - reward_credits: -100
      - id: closing
        is_closing: true
        closings:
          - when: { default: true }
            body: "You return."
            effects: []
    """)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_valid_scripted_template(tmp_path):
    from engine.expedition_template import load_template_file

    p = _write(tmp_path, "scripted_test", SCRIPTED_YAML)
    tmpl = load_template_file(p)
    assert tmpl["id"] == "scripted_test"
    assert tmpl["kind"] == "scripted"


def test_filename_must_match_id(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace("id: scripted_test", "id: different_name")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="filename must match id"):
        load_template_file(p)


def test_default_choice_required_per_scene_with_choices(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace("        default: true\n        outcomes:", "        outcomes:")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="default"):
        load_template_file(p)


def test_default_choice_must_have_no_requires(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace(
        "        default: true",
        "        default: true\n        requires: { archetype: PILOT }",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="default.*requires"):
        load_template_file(p)


def test_default_closing_required(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace("when: { default: true }", "when: { min_successes: 99 }")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="default closing"):
        load_template_file(p)


def test_unknown_stat_in_roll_rejected(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace(
        "        outcomes:\n          result:",
        "        roll: { stat: pilot.bogus, base_p: 0.5, base_stat: 50, per_point: 0.005 }\n"
        "        outcomes:\n"
        "          success: { narrative: ok, effects: [] }\n"
        "          failure: { narrative: bad, effects: [] }\n"
        "          result:",
    )
    body = body.replace(
        '          result:\n            narrative: "Paid."\n'
        "            effects:\n              - reward_credits: -100\n",
        "",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="unknown stat"):
        load_template_file(p)


def test_unknown_archetype_in_outcome_rejected(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace(
        "- reward_credits: -100",
        "- reward_xp: { archetype: WIZARD, amount: 50 }",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="archetype"):
        load_template_file(p)


def test_unknown_effect_op_rejected(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace(
        "- reward_credits: -100",
        "- reward_telepathy: true",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="unknown effect op"):
        load_template_file(p)


def test_rolled_pool_must_be_at_least_event_count(tmp_path):
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = textwrap.dedent("""\
        id: rolled_test
        kind: rolled
        duration_minutes: 360
        response_window_minutes: 30
        cost_credits: 0
        event_count: 5
        crew_required: { min: 1, archetypes_any: [PILOT] }
        opening: { id: opening, narration: "Off you go." }
        events:
          - id: a
            narration: x
            choices:
              - id: ok
                text: ok
                default: true
                outcomes: { result: { narrative: ok, effects: [] } }
        closings:
          - when: { default: true }
            body: ok
            effects: []
        """)
    p = _write(tmp_path, "rolled_test", body)
    with pytest.raises(TemplateValidationError, match="event_count"):
        load_template_file(p)


def test_set_flag_referenced_by_when_clause_no_typo(tmp_path):
    """A `has_flag: foo` without any `set_flag: { name: foo }` is a typo."""
    from engine.expedition_template import TemplateValidationError, load_template_file

    body = SCRIPTED_YAML.replace(
        "      - when: { default: true }",
        '      - when: { has_flag: never_set_flag }\n        body: "closing a"\n'
        "        effects: []\n      - when: { default: true }",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="never_set_flag"):
        load_template_file(p)
