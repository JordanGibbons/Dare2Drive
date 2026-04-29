"""Narrative substitution for expedition templates.

Renders `{token}` placeholders in player-visible strings using a closed
allow-list of tokens. Top-level tokens (`{pilot}`, `{ship}`) resolve to the
'display' or 'name' of the slot. Property access (`{pilot.callsign}`) is
added in a follow-on. Missing slots fall back to a generic noun.
"""

from __future__ import annotations

import string

# Top-level token → default sub-key the renderer reads from the slot dict
# when the bare `{<token>}` form is used. Property access (`{token.attr}`)
# overrides this and reads `attr` directly.
_TOP_LEVEL_DEFAULT_KEY: dict[str, str] = {
    "pilot": "display",
    "gunner": "display",
    "engineer": "display",
    "navigator": "display",
    "ship": "name",
}

# Generic-noun fallback when a slot is missing (e.g. SKIRMISHER running a
# template that references {engineer}). Returned for both bare tokens and
# property-access tokens against a missing slot.
_GENERIC_NOUN_FALLBACK: dict[str, str] = {
    "pilot": "the pilot",
    "gunner": "the gunner",
    "engineer": "the engineer",
    "navigator": "the navigator",
    "ship": "the ship",
}


class _RenderMapping:
    """Mapping for the formatter that resolves bare and dotted slot tokens."""

    def __init__(self, context: dict) -> None:
        self._ctx = context

    def __getitem__(self, key: str) -> str:
        # Bare token: {pilot}, {ship}
        if "." not in key:
            slot = self._ctx.get(key)
            if slot is None:
                return _GENERIC_NOUN_FALLBACK.get(key, "{" + key + "}")
            default_key = _TOP_LEVEL_DEFAULT_KEY.get(key, "")
            return str(slot.get(default_key, _GENERIC_NOUN_FALLBACK.get(key, "")))
        # Property access — implemented in Task 5
        raise KeyError(key)


class _NarrativeFormatter(string.Formatter):
    """Formatter that hands the entire dotted field name to the mapping.

    Default `string.Formatter` behaviour splits `pilot.callsign` into a base
    field (`pilot`) followed by attribute access (`.callsign`). For our
    closed-vocabulary tokens, we want `pilot.callsign` to reach the mapping
    as a single key so it can be resolved against the slot dict. Overriding
    `get_field` skips the attribute-walk path.
    """

    def get_field(self, field_name, args, kwargs):  # type: ignore[override]
        return self.get_value(field_name, args, kwargs), field_name


_FORMATTER = _NarrativeFormatter()


def render(text: str, context: dict) -> str:
    """Render a string with {token}/{token.attr} placeholders.

    `context` is a dict like:
        {"pilot": {"display": "...", "callsign": "..."},
         "ship":  {"name": "...", "hull": "..."}}
    """
    return _FORMATTER.vformat(text, (), _RenderMapping(context))
