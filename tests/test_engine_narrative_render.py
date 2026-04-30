"""Narrative substitution — top-level slot tokens."""

from __future__ import annotations


def test_render_substitutes_pilot_display_name():
    from engine.narrative_render import render

    context = {
        "pilot": {"display": 'Mira "Sixgun" Voss', "callsign": "Sixgun"},
    }
    out = render("{pilot} pulls into the docking bay.", context)
    assert out == 'Mira "Sixgun" Voss pulls into the docking bay.'


def test_render_substitutes_ship_name():
    from engine.narrative_render import render

    context = {"ship": {"name": "Flagstaff", "hull": "Skirmisher"}}
    out = render("The {ship} drops out of warp.", context)
    assert out == "The Flagstaff drops out of warp."


def test_render_handles_multiple_tokens_in_one_string():
    from engine.narrative_render import render

    context = {
        "pilot": {"display": "Mira Voss", "callsign": "Sixgun"},
        "ship": {"name": "Flagstaff", "hull": "Skirmisher"},
    }
    out = render("{pilot} pilots the {ship}.", context)
    assert out == "Mira Voss pilots the Flagstaff."


def test_render_passes_through_text_with_no_tokens():
    from engine.narrative_render import render

    out = render("plain text with no tokens", {})
    assert out == "plain text with no tokens"


def test_render_property_access_callsign():
    from engine.narrative_render import render

    context = {
        "pilot": {
            "display": 'Mira "Sixgun" Voss',
            "callsign": "Sixgun",
            "first_name": "Mira",
            "last_name": "Voss",
        },
    }
    out = render("{pilot.callsign} climbs in.", context)
    assert out == "Sixgun climbs in."


def test_render_property_access_first_name_and_last_name():
    from engine.narrative_render import render

    context = {
        "pilot": {
            "first_name": "Mira",
            "last_name": "Voss",
            "callsign": "Sixgun",
            "display": "Mira 'Sixgun' Voss",
        },
    }
    out = render(
        "{pilot.first_name} climbs in. {pilot.last_name} salutes.",
        context,
    )
    assert out == "Mira climbs in. Voss salutes."


def test_render_ship_hull_property():
    from engine.narrative_render import render

    context = {"ship": {"name": "Flagstaff", "hull": "Skirmisher"}}
    out = render("A {ship.hull} stops at the airlock.", context)
    assert out == "A Skirmisher stops at the airlock."


def test_render_missing_top_level_slot_falls_back_to_generic_noun():
    from engine.narrative_render import render

    # Context has no `engineer` (e.g. SKIRMISHER running a template that mentions one)
    context = {"pilot": {"display": "Mira Voss", "callsign": "Sixgun"}}
    out = render("{engineer} reroutes power.", context)
    assert out == "the engineer reroutes power."


def test_render_missing_property_falls_back_to_generic_noun():
    from engine.narrative_render import render

    # Context has no `gunner` slot at all
    context = {"pilot": {"display": "Mira Voss", "callsign": "Sixgun"}}
    out = render("{gunner.callsign} swings the turret around.", context)
    assert out == "the gunner swings the turret around."


def test_render_missing_ship_falls_back():
    from engine.narrative_render import render

    out = render("The {ship} drops out of warp.", {})
    assert out == "The the ship drops out of warp."  # ugly but consistent


def test_render_escapes_double_braces_to_literal_braces():
    """Authors can write `{{` for a literal `{` and `}}` for a literal `}`."""
    from engine.narrative_render import render

    out = render("Use {{pilot}} as the slot name.", {})
    assert out == "Use {pilot} as the slot name."


def test_render_unmatched_left_brace_raises_or_passes_through():
    """Unmatched braces are treated as a format error — surface clearly."""
    import pytest

    from engine.narrative_render import render

    # str.format_map (and string.Formatter) raise ValueError on unmatched
    # braces — that's acceptable as long as the validator catches these at
    # template load time (Task 8).
    with pytest.raises((ValueError, IndexError)):
        render("Unmatched {", {})
