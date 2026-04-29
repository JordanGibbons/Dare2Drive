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
