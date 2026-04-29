"""Narrative substitution for expedition templates.

Renders `{token}` placeholders in player-visible strings using a closed
allow-list of tokens. Top-level tokens (`{pilot}`, `{ship}`) resolve to the
'display' or 'name' of the slot. Property access (`{pilot.callsign}`) is
added in a follow-on. Missing slots fall back to a generic noun.
"""

from __future__ import annotations

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
    """Custom mapping for str.format_map that resolves slot.property tokens."""

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


def render(text: str, context: dict) -> str:
    """Render a string with {token}/{token.attr} placeholders.

    `context` is a dict like:
        {"pilot": {"display": "...", "callsign": "..."},
         "ship":  {"name": "...", "hull": "..."}}
    """
    return text.format_map(_RenderMapping(context))
