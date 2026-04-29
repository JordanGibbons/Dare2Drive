# Phase 2c — Ship-Crew Binding + Narrative Substitution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move crew assignment from per-expedition slash params (Phase 2b) to persistent on-ship binding, with hull-class-specific crew slots. Players assign crew once via an interactive `/hangar` view; `/expedition start` simplifies to `(template, build)` and derives the aboard set from the ship. Same phase ships closed-vocabulary narrative substitution (`{pilot.callsign}`, `{ship}`) rendered at scene-fire time.

**Architecture:** Reuses the existing `crew_assignments` table and `CrewAssignment` ORM model from Phase 1, which already enforce one-archetype-slot-per-build (via `UniqueConstraint("build_id", "archetype")`) and one-build-per-crew (via `unique=True` on `crew_id`). No schema work is required — Phase 2c's contribution at the data layer is purely additive on top of this. Hull-class crew slot composition lives as a Python constant `HULL_CREW_SLOTS` in `engine/class_engine.py`. New `engine/narrative_render.py` module exposes `render(text, context) -> str` using `str.format_map` with a custom mapping subclass — token allow-list enforced at template-load time by an extension to the existing template validator. `/expedition start` drops its four crew params and reads from `crew_assignments`; the engine runtime is unchanged because `ExpeditionCrewAssignment` (Phase 2b) is kept as the in-flight snapshot, populated from the persistent table at launch. Hangar UX is a new `HangarView` (persistent `discord.ui.View`, registered globally at bot startup like `ExpeditionResponseView`) attached to the existing `/hangar <build>` command, with one `Select` per crew slot.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, discord.py 2.x (Select menus + persistent View), pytest + pytest-asyncio. No new top-level dependencies.

**Spec:** [docs/superpowers/specs/2026-04-27-phase-2c-ship-crew-binding-design.md](../specs/2026-04-27-phase-2c-ship-crew-binding-design.md)

**Dev loop:** All tests run via `pytest` from the repo root. The `db_session` fixture in `tests/conftest.py` opens a per-test savepoint against the Docker Postgres (localhost:5432). `docker compose up db redis` must be running for DB-backed tests. Apply migrations with `DATABASE_URL=postgresql://dare2drive:dare2drive@localhost:5432/dare2drive python -m alembic upgrade head` after pulling new migrations.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `engine/narrative_render.py` | `render(text, context)` + custom mapping subclass + allow-list constant |
| `bot/views/hangar_view.py` | `HangarView` persistent View class + `render_hangar_view(session, build, user)` factory + custom_id helpers |
| `tests/test_engine_class_engine_crew_slots.py` | `HULL_CREW_SLOTS` + `slots_for_hull()` tests |
| `tests/test_engine_narrative_render.py` | `render()` tests covering substitution, property access, fallbacks, brace escape |
| `tests/test_expedition_template_narrative_validation.py` | Validator extension — token allow-list enforcement |
| `tests/test_view_hangar.py` | Embed render + select option building + interaction_check tests |
| `tests/test_scenarios/test_ship_crew_binding_flow.py` | End-to-end: assign crew → launch expedition → mid-flight event with rendered tokens → button click → completion |

### Modified files

| Path | Change |
|---|---|
| `engine/class_engine.py` | Add `HULL_CREW_SLOTS` constant + `slots_for_hull(hull) -> list[CrewArchetype]` helper |
| `engine/expedition_template.py` | Validator extends to scan renderable strings for unknown `{...}` tokens at load time |
| `scheduler/jobs/expedition_event.py` | Calls `narrative_render.render()` on scene narration + visible choice text |
| `scheduler/jobs/expedition_resolve.py` | Calls `render()` on outcome narrative |
| `scheduler/jobs/expedition_complete.py` | Calls `render()` on closing body |
| `bot/cogs/expeditions.py` | Drop `pilot/gunner/engineer/navigator` slash params + their autocompletes; launch handler reads `crew_assignments`; slot-walking error message |
| `bot/cogs/hangar.py` | `/hangar` command renders via `render_hangar_view()` and attaches the View |
| `bot/cogs/hiring.py` (or wherever `/crew_inspect` lives — see Task 19) | Add "Aboard `<ship name>`" line when crew member appears in `crew_assignments` |
| `bot/main.py` | `setup_hook` registers persistent `HangarView` |
| `tests/test_cog_expedition_start.py` | Tests rewritten — set up crew via `crew_assignments`, drop slash crew params from launch calls |
| `tests/test_cog_expedition_autocomplete.py` | Drop the four crew-archetype autocomplete tests (those handlers are removed) |
| `docs/authoring/expeditions.md` | New "Narrative tokens" section with allow-list and an example template |

---

## Task 1: Hull-class crew slot config

**Files:**
- Modify: `engine/class_engine.py`
- Create: `tests/test_engine_class_engine_crew_slots.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_engine_class_engine_crew_slots.py`:

```python
"""Hull-class crew slot composition + lookup helper."""

from __future__ import annotations

import pytest


def test_hull_crew_slots_skirmisher():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert HULL_CREW_SLOTS[HullClass.SKIRMISHER] == [
        CrewArchetype.PILOT,
        CrewArchetype.GUNNER,
    ]


def test_hull_crew_slots_hauler():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert HULL_CREW_SLOTS[HullClass.HAULER] == [
        CrewArchetype.PILOT,
        CrewArchetype.ENGINEER,
        CrewArchetype.NAVIGATOR,
    ]


def test_hull_crew_slots_scout():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert HULL_CREW_SLOTS[HullClass.SCOUT] == [
        CrewArchetype.PILOT,
        CrewArchetype.NAVIGATOR,
    ]


def test_hull_crew_slots_covers_every_hull_class():
    """If a new HullClass is added without a slot config, this test must fail."""
    from db.models import HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert set(HULL_CREW_SLOTS.keys()) == set(HullClass)


def test_slots_for_hull_returns_list():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import slots_for_hull

    slots = slots_for_hull(HullClass.SKIRMISHER)
    assert slots == [CrewArchetype.PILOT, CrewArchetype.GUNNER]


def test_slots_for_hull_unknown_hull_raises():
    """Defense in depth: if someone passes an invalid hull, fail loudly."""
    from engine.class_engine import slots_for_hull

    with pytest.raises((KeyError, TypeError)):
        slots_for_hull("not_a_hull_class")  # type: ignore[arg-type]
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_class_engine_crew_slots.py -v --no-cov`
Expected: 6 FAIL with `ImportError` (the constant + helper don't exist yet).

- [ ] **Step 3: Add the config and helper**

Append to `engine/class_engine.py`:

```python
# ──────────── Phase 2c: hull-class crew slot composition ────────────

from db.models import CrewArchetype, HullClass  # noqa: E402  (top-of-file import may not exist)

HULL_CREW_SLOTS: dict[HullClass, list[CrewArchetype]] = {
    HullClass.SKIRMISHER: [CrewArchetype.PILOT, CrewArchetype.GUNNER],
    HullClass.HAULER: [
        CrewArchetype.PILOT,
        CrewArchetype.ENGINEER,
        CrewArchetype.NAVIGATOR,
    ],
    HullClass.SCOUT: [CrewArchetype.PILOT, CrewArchetype.NAVIGATOR],
}


def slots_for_hull(hull: HullClass) -> list[CrewArchetype]:
    """Return the canonical archetype slot list for a hull class.

    The returned list's order is the canonical display order for embed/UI rendering.
    """
    return HULL_CREW_SLOTS[hull]
```

If the imports `from db.models import CrewArchetype, HullClass` are already present at the top of `engine/class_engine.py`, drop the redundant import inside the new block.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_class_engine_crew_slots.py -v --no-cov`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/class_engine.py tests/test_engine_class_engine_crew_slots.py
git commit -m "feat(phase2c): add HULL_CREW_SLOTS config + slots_for_hull helper"
```

---

## Task 2: Reuse existing `crew_assignments` table — no migration needed

**Files:** none.

The `crew_assignments` table already exists from Phase 1 (`db/migrations/versions/0002_phase1_crew.py`) and enforces the invariants Phase 2c needs:

- `UniqueConstraint("build_id", "archetype", name="uq_crew_assignments_build_archetype")` — one slot per archetype per ship.
- `unique=True` on `crew_id` — a crew member is on at most one ship at a time.
- `crew_id` and `build_id` FKs both `ondelete="CASCADE"`.
- `archetype` reuses the Phase 1 `crewarchetype` enum.

The original Phase 2c plan called for a new `build_crew_assignments` table; this was caught during code review of an earlier draft as a duplicate of existing infrastructure. We retired the new table in favour of the existing one. Skip this task — there is no schema change to make.

---

## Task 3: Reuse existing `CrewAssignment` ORM model — no new model needed

**Files:** none.

`db/models.CrewAssignment` (`db/models.py:495-520`) is the persistent on-ship crew binding for Phase 2c. Existing call sites already use it:

- `bot/cogs/hiring.py` (assign / unassign / view crew on ship).
- `bot/cogs/race.py` (joins to derive aboard set for race events).

Phase 2c will add new call sites (Task 12: expedition launch reads `CrewAssignment` for the active build; Tasks 14–15: `HangarView` writes and reads via `CrewAssignment`; Task 17: `/crew_inspect` shows the aboard ship via a join through `CrewAssignment`). No model changes required — skip this task.

> **Note for downstream tasks (12, 13, 14, 15, 17, 18):** wherever the prior plan-text references `BuildCrewAssignment` / `build_crew_assignments`, read it as `CrewAssignment` / `crew_assignments`. The existing model has an extra `id` UUID PK column (auto-default `uuid.uuid4`) that the new code does not need to set explicitly. The constraint name for the unique-on-`crew_id` invariant is auto-generated rather than `uq_crew_assignments_crew_id`; downstream tests that catch the IntegrityError should match on the substring `unique` rather than a specific constraint name.

---

## Task 4: Narrative render — top-level token substitution

**Files:**
- Create: `engine/narrative_render.py`
- Create: `tests/test_engine_narrative_render.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_engine_narrative_render.py`:

```python
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
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_narrative_render.py -v --no-cov`
Expected: 4 FAIL — module doesn't exist.

- [ ] **Step 3: Create the module with top-level token support**

Create `engine/narrative_render.py`:

```python
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
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_narrative_render.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/narrative_render.py tests/test_engine_narrative_render.py
git commit -m "feat(phase2c): add narrative_render with top-level token substitution"
```

---

## Task 5: Narrative render — property access

**Files:**
- Modify: `engine/narrative_render.py`
- Modify: `tests/test_engine_narrative_render.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_engine_narrative_render.py`:

```python
def test_render_property_access_callsign():
    from engine.narrative_render import render

    context = {
        "pilot": {"display": 'Mira "Sixgun" Voss', "callsign": "Sixgun",
                  "first_name": "Mira", "last_name": "Voss"},
    }
    out = render("{pilot.callsign} climbs in.", context)
    assert out == "Sixgun climbs in."


def test_render_property_access_first_name_and_last_name():
    from engine.narrative_render import render

    context = {
        "pilot": {"first_name": "Mira", "last_name": "Voss",
                  "callsign": "Sixgun", "display": "Mira 'Sixgun' Voss"},
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
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_narrative_render.py -v --no-cov -k "property_access or hull_property"`
Expected: 3 FAIL with `KeyError`.

- [ ] **Step 3: Implement property access**

In `engine/narrative_render.py`, replace the `_RenderMapping.__getitem__` method with:

```python
    def __getitem__(self, key: str) -> str:
        if "." not in key:
            slot = self._ctx.get(key)
            if slot is None:
                return _GENERIC_NOUN_FALLBACK.get(key, "{" + key + "}")
            default_key = _TOP_LEVEL_DEFAULT_KEY.get(key, "")
            return str(slot.get(default_key, _GENERIC_NOUN_FALLBACK.get(key, "")))
        # Property access: {pilot.callsign}, {ship.hull}, etc.
        slot_name, _, attr = key.partition(".")
        slot = self._ctx.get(slot_name)
        if slot is None:
            return _GENERIC_NOUN_FALLBACK.get(slot_name, "{" + key + "}")
        value = slot.get(attr)
        if value is None:
            return _GENERIC_NOUN_FALLBACK.get(slot_name, "{" + key + "}")
        return str(value)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_narrative_render.py -v --no-cov`
Expected: 7 PASS (4 from Task 4 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add engine/narrative_render.py tests/test_engine_narrative_render.py
git commit -m "feat(phase2c): narrative_render supports {slot.attr} property access"
```

---

## Task 6: Narrative render — generic-noun fallbacks for missing slots

**Files:**
- Modify: `tests/test_engine_narrative_render.py`

(Implementation already covers fallbacks; this task adds explicit regression tests so the contract is encoded.)

- [ ] **Step 1: Append failing tests** (these may pass already, depending on Task 4/5 implementation completeness)

Append to `tests/test_engine_narrative_render.py`:

```python
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

```

The last test assertion (`"The the ship drops out of warp."`) is intentional — `{ship}` is a noun, not an article-aware token. Authors should write `"The {ship}"` knowing the fallback may produce `"The the ship"`. We document this in the authoring guide (Task 22) and accept it because (a) the empty-`ship` case essentially never happens — every expedition has a build, and (b) it's a clear visual signal to the author/player that something went wrong.

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_engine_narrative_render.py -v --no-cov`
Expected: 10 PASS (3 new fallback tests pass with the existing implementation from Tasks 4-5).

If any FAIL, revisit `_RenderMapping.__getitem__` to confirm the fallback paths are correct.

- [ ] **Step 3: Commit**

```bash
git add tests/test_engine_narrative_render.py
git commit -m "test(phase2c): regression tests for narrative_render generic-noun fallbacks"
```

---

## Task 7: Narrative render — escape literal braces

**Files:**
- Modify: `engine/narrative_render.py`
- Modify: `tests/test_engine_narrative_render.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_engine_narrative_render.py`:

```python
def test_render_escapes_double_braces_to_literal_braces():
    """Authors can write `{{` for a literal `{` and `}}` for a literal `}`."""
    from engine.narrative_render import render

    out = render("Use {{pilot}} as the slot name.", {})
    assert out == "Use {pilot} as the slot name."


def test_render_unmatched_left_brace_raises_or_passes_through():
    """Unmatched braces are treated as a format error — surface clearly."""
    from engine.narrative_render import render

    # str.format_map raises ValueError on unmatched braces — that's acceptable
    # as long as the validator catches these at template load time (Task 8).
    import pytest
    with pytest.raises((ValueError, IndexError)):
        render("Unmatched {", {})
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_engine_narrative_render.py -v --no-cov -k "escape or unmatched"`
Expected: 2 PASS — Python's `str.format_map` already handles double-brace escape and raises on unmatched braces, so no implementation change is needed.

If FAILs occur, the implementation diverges from `str.format_map` semantics; revisit `_RenderMapping`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_engine_narrative_render.py
git commit -m "test(phase2c): narrative_render brace-escape + unmatched-brace contract"
```

---

## Task 8: Template validator — token allow-list enforcement

**Files:**
- Modify: `engine/expedition_template.py`
- Create: `tests/test_expedition_template_narrative_validation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expedition_template_narrative_validation.py`:

```python
"""Phase 2c — narrative-token allow-list validator extension."""

from __future__ import annotations

import pytest


# Minimal valid template fragments used to exercise narrative validation.
# We only fill the fields the validator inspects for tokens.

def _scripted_template_with_narration(narration: str) -> dict:
    return {
        "id": "test_template",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "opening": {"id": "opening", "narration": narration},
        "scenes": [],
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
    ]
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template_dict(tmpl)
    assert "villain" in str(exc_info.value)
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_expedition_template_narrative_validation.py -v --no-cov`
Expected: 6 FAIL. Some may pass (the allow-list isn't enforced yet, so unknown tokens are accepted; "rejects unknown" cases will fail).

- [ ] **Step 3: Add the allow-list constant + walker to `engine/expedition_template.py`**

Near the top of `engine/expedition_template.py`, add the allow-list:

```python
# Phase 2c: narrative-token allow-list. Closed vocabulary; extensions go here.
_VALID_TOP_LEVEL_TOKENS: set[str] = {"pilot", "gunner", "engineer", "navigator", "ship"}
_VALID_CREW_ATTRS: set[str] = {"callsign", "first_name", "last_name", "display"}
_VALID_SHIP_ATTRS: set[str] = {"name", "hull"}

import re as _re
_TOKEN_RE = _re.compile(r"(?<!\{)\{([a-z_]+(?:\.[a-z_]+)?)\}(?!\})")
```

The negative lookbehind/lookahead in `_TOKEN_RE` excludes escaped `{{...}}` from validation.

Add a helper function:

```python
def _validate_narrative_tokens_in_text(text: str, where: str) -> None:
    """Raise TemplateValidationError for any unknown {token} in `text`.

    `where` is a human-readable location for error messages (e.g. "scene 'drifting_wreck' narration").
    """
    for match in _TOKEN_RE.finditer(text):
        token = match.group(1)
        slot, _, attr = token.partition(".")
        if slot not in _VALID_TOP_LEVEL_TOKENS:
            raise TemplateValidationError(
                f"unknown narrative token {{{token}}} in {where} "
                f"(valid slots: {sorted(_VALID_TOP_LEVEL_TOKENS)})"
            )
        if attr:
            allowed = (
                _VALID_SHIP_ATTRS if slot == "ship" else _VALID_CREW_ATTRS
            )
            if attr not in allowed:
                raise TemplateValidationError(
                    f"unknown attribute '.{attr}' on {{{slot}}} in {where} "
                    f"(valid attrs: {sorted(allowed)})"
                )
```

Inside the existing `validate_template_dict` function, after the JSON-Schema and existing semantic checks, walk all renderable strings:

```python
    # ─────── Phase 2c: narrative-token allow-list ───────
    _walk_narrative_strings_and_validate(template)
```

And add the walker:

```python
def _walk_narrative_strings_and_validate(template: dict) -> None:
    """Walk every player-visible string in `template` and validate {tokens}."""
    # Top-level opening (rolled templates)
    opening = template.get("opening", {})
    if isinstance(opening, dict) and "narration" in opening:
        _validate_narrative_tokens_in_text(
            opening["narration"], where=f"opening narration of {template.get('id')}"
        )

    # Scripted scenes
    for scene in template.get("scenes", []) or []:
        _validate_scene_strings(scene, template.get("id", "?"))

    # Rolled events pool
    for event in template.get("events", []) or []:
        _validate_scene_strings(event, template.get("id", "?"))

    # Closings (both kinds)
    for closing in template.get("closings", []) or []:
        if "body" in closing:
            _validate_narrative_tokens_in_text(
                closing["body"], where=f"closing of {template.get('id')}"
            )


def _validate_scene_strings(scene: dict, template_id: str) -> None:
    sid = scene.get("id", "?")
    if "narration" in scene:
        _validate_narrative_tokens_in_text(
            scene["narration"], where=f"scene '{sid}' narration in {template_id}"
        )
    for choice in scene.get("choices", []) or []:
        cid = choice.get("id", "?")
        if "text" in choice:
            _validate_narrative_tokens_in_text(
                choice["text"], where=f"scene '{sid}' choice '{cid}' text in {template_id}"
            )
        outcomes = choice.get("outcomes", {})
        for branch_name, branch in outcomes.items():
            if isinstance(branch, dict) and "narrative" in branch:
                _validate_narrative_tokens_in_text(
                    branch["narrative"],
                    where=f"scene '{sid}' choice '{cid}' {branch_name} narrative in {template_id}",
                )
    if "outcome" in scene and isinstance(scene["outcome"], dict):
        outcome = scene["outcome"]
        if "narrative" in outcome:
            _validate_narrative_tokens_in_text(
                outcome["narrative"], where=f"scene '{sid}' outcome narrative in {template_id}"
            )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_expedition_template_narrative_validation.py -v --no-cov`
Expected: 6 PASS.

Also re-run the existing template-file CI gate to confirm the v1 templates still load:

Run: `pytest tests/test_expedition_template_files.py -v --no-cov`
Expected: PASS (v1 templates have no `{...}` tokens).

- [ ] **Step 5: Commit**

```bash
git add engine/expedition_template.py tests/test_expedition_template_narrative_validation.py
git commit -m "feat(phase2c): template validator enforces narrative-token allow-list"
```

---

## Task 9: Wire `render()` into EXPEDITION_EVENT handler

**Files:**
- Create: `scheduler/jobs/_render_context.py`
- Modify: `scheduler/jobs/expedition_event.py`
- Modify: `tests/test_handler_expedition_event.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_handler_expedition_event.py`:

```python
@pytest.mark.asyncio
async def test_event_handler_renders_narrative_tokens_in_body(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    """Narration with {pilot.callsign} and {ship} renders in the DM body."""
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, pilot = sample_expedition_with_pilot

    # Monkey-patch the template loader so this test owns its scene narration
    from engine import expedition_template as tmpl_mod

    fake_template = {
        "id": "marquee_run",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "pirate_skiff",
                "narration": "{pilot.callsign} aboard the {ship} sights pirates.",
                "choices": [
                    {
                        "id": "outrun",
                        "text": "{pilot.callsign} burns hard.",
                        "default": True,
                        "outcomes": {"result": {"narrative": "ok", "effects": []}},
                    },
                ],
            }
        ],
    }
    monkeypatch.setattr(tmpl_mod, "load_template", lambda _id: fake_template)

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    body = result.notifications[0].body

    # The literal `{pilot.callsign}` token must be replaced; the actual pilot's
    # callsign comes from the `sample_expedition_with_pilot` fixture.
    assert pilot.callsign in body
    assert "{pilot" not in body
    assert "{ship" not in body
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_event.py::test_event_handler_renders_narrative_tokens_in_body -v --no-cov`
Expected: FAIL — narration is sent through verbatim, so the `{pilot.callsign}` literal is in the body.

- [ ] **Step 3: Create the shared render-context module**

Create `scheduler/jobs/_render_context.py`:

```python
"""Shared render-context builder for expedition handlers (event/resolve/complete).

Lives here (not in `engine/`) because it pulls together expedition-side ORM rows
(`ExpeditionCrewAssignment`) — the engine only knows about scenes and outcomes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Build, CrewMember, Expedition, ExpeditionCrewAssignment


async def build_render_context(session: AsyncSession, expedition: Expedition) -> dict:
    """Assemble the narrative-render context dict from the expedition's build + aboard crew.

    Returns a dict shaped like:
        {
            "ship": {"name": "Flagstaff", "hull": "Skirmisher"},
            "pilot": {"display": '...', "callsign": "Sixgun", "first_name": "Mira", "last_name": "Voss"},
            ...
        }
    Archetypes that aren't aboard simply aren't in the dict; the renderer's
    fallback handles them.
    """
    build = await session.get(Build, expedition.build_id)
    ctx: dict = {
        "ship": {
            "name": build.name if build else "the ship",
            "hull": build.hull_class.name.title() if build and build.hull_class else "",
        }
    }
    rows = (
        await session.execute(
            select(ExpeditionCrewAssignment, CrewMember)
            .join(CrewMember, ExpeditionCrewAssignment.crew_id == CrewMember.id)
            .where(ExpeditionCrewAssignment.expedition_id == expedition.id)
        )
    ).all()
    for assignment, crew in rows:
        archetype_key = assignment.archetype.value  # "pilot", "gunner", etc.
        ctx[archetype_key] = {
            "display": f'{crew.first_name} "{crew.callsign}" {crew.last_name}',
            "callsign": crew.callsign,
            "first_name": crew.first_name,
            "last_name": crew.last_name,
        }
    return ctx
```

- [ ] **Step 4: Wire render() into the EXPEDITION_EVENT handler**

In `scheduler/jobs/expedition_event.py`, add the imports:

```python
from engine.narrative_render import render
from scheduler.jobs._render_context import build_render_context
```

In `handle_expedition_event`, after computing `visible` and BEFORE calling `_format_event_body`, build the context and render the strings:

```python
    # ─────── Phase 2c: render narrative tokens ───────
    ctx = await build_render_context(session, expedition)
    rendered_narration = render(scene.get("narration", ""), ctx)
    rendered_visible = [
        {**c, "text": render(c["text"], ctx)} for c in visible
    ]

    body = _format_event_body(
        narration=rendered_narration,
        choices=rendered_visible,
        scene_id=scene_id,
        response_window_minutes=int(response_window),
    )
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_event.py -v --no-cov`
Expected: ALL PASS (existing 7 + new 1 = 8).

- [ ] **Step 6: Commit**

```bash
git add scheduler/jobs/_render_context.py scheduler/jobs/expedition_event.py tests/test_handler_expedition_event.py
git commit -m "feat(phase2c): render narrative tokens in EXPEDITION_EVENT body"
```

---

## Task 10: Wire `render()` into EXPEDITION_RESOLVE handler

**Files:**
- Modify: `scheduler/jobs/expedition_resolve.py`
- Modify: `tests/test_handler_expedition_resolve.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_handler_expedition_resolve.py`:

```python
@pytest.mark.asyncio
async def test_resolve_handler_renders_narrative_tokens_in_body(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    """Outcome narrative with {ship} renders before being formatted."""
    from db.models import Expedition
    from engine import expedition_template as tmpl_mod
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve

    expedition, pilot = sample_expedition_with_pilot
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "pending",
            "fired_at": "2026-04-26T12:00:00Z",
            "visible_choice_ids": ["comply"],
        },
    ]
    await db_session.flush()

    fake_template = {
        "id": "marquee_run",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "pirate_skiff",
                "narration": "ok",
                "choices": [
                    {
                        "id": "comply",
                        "text": "Comply.",
                        "default": True,
                        "outcomes": {
                            "result": {
                                "narrative": "{pilot.callsign} surrenders the {ship}.",
                                "effects": [],
                            }
                        },
                    },
                ],
            }
        ],
    }
    monkeypatch.setattr(tmpl_mod, "load_template", lambda _id: fake_template)

    job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_resolve(db_session, job)
    body = result.notifications[0].body
    assert pilot.callsign in body
    assert "{pilot" not in body
    assert "{ship" not in body
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_resolve.py::test_resolve_handler_renders_narrative_tokens_in_body -v --no-cov`
Expected: FAIL — narrative passes through verbatim.

- [ ] **Step 3: Wire render() into the resolve handler**

`scheduler/jobs/_render_context.py` already exists from Task 9 — just import its `build_render_context` and use it.

In `scheduler/jobs/expedition_resolve.py`, add at the top:

```python
from engine.narrative_render import render
from scheduler.jobs._render_context import build_render_context
```

And in `handle_expedition_resolve`, change the section that builds `body`:

```python
    ctx = await build_render_context(session, expedition)
    rendered_narrative = render(resolution["outcome"].get("narrative", ""), ctx)
    body = _format_resolution_body(
        narrative=rendered_narrative,
        auto_resolved=auto_resolved,
    )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_event.py tests/test_handler_expedition_resolve.py -v --no-cov`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_resolve.py tests/test_handler_expedition_resolve.py
git commit -m "feat(phase2c): render narrative tokens in EXPEDITION_RESOLVE body"
```

---

## Task 11: Wire `render()` into EXPEDITION_COMPLETE handler

**Files:**
- Modify: `scheduler/jobs/expedition_complete.py`
- Modify: `tests/test_handler_expedition_complete.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_handler_expedition_complete.py`:

```python
@pytest.mark.asyncio
async def test_complete_handler_renders_narrative_tokens_in_closing(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from engine import expedition_template as tmpl_mod
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, pilot = sample_expedition_with_pilot
    expedition.scene_log = []
    await db_session.flush()

    fake_template = {
        "id": "marquee_run",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "closing",
                "is_closing": True,
                "narration": "ok",
                "closings": [
                    {
                        "when": {"default": True},
                        "body": "{pilot.callsign} brings the {ship} home.",
                        "effects": [],
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(tmpl_mod, "load_template", lambda _id: fake_template)

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_complete(db_session, job)
    body = result.notifications[0].body
    assert pilot.callsign in body
    assert "{pilot" not in body
    assert "{ship" not in body
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_complete.py::test_complete_handler_renders_narrative_tokens_in_closing -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Wire render() into complete handler**

In `scheduler/jobs/expedition_complete.py`, add at the top:

```python
from engine.narrative_render import render
from scheduler.jobs._render_context import build_render_context
```

In `handle_expedition_complete`, before building `body`, render the closing body:

```python
    ctx = await build_render_context(session, expedition)
    rendered_closing = render(closing.get("body", ""), ctx)
    body = _format_complete_body(
        narrative=rendered_closing,
        summary=expedition.outcome_summary,
    )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_complete.py -v --no-cov`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_complete.py tests/test_handler_expedition_complete.py
git commit -m "feat(phase2c): render narrative tokens in EXPEDITION_COMPLETE closing"
```

---

## Task 12: `/expedition start` — drop crew slash params, derive aboard from ship

**Files:**
- Modify: `bot/cogs/expeditions.py`
- Modify: `tests/test_cog_expedition_start.py`
- Modify: `tests/test_cog_expedition_autocomplete.py`

This is the largest single task. It's bundled because the slash signature change cascades through the launch handler and its tests; doing it in pieces would leave the codebase non-compiling between commits.

- [ ] **Step 1: Update the slash command signature + remove crew autocompletes**

In `bot/cogs/expeditions.py`, find the `expedition_start` slash command and:

1. Remove the four crew params and their `app_commands.describe`/`app_commands.autocomplete` decorators.
2. Remove the four module-level autocomplete handlers `_pilot_autocomplete`, `_gunner_autocomplete`, `_engineer_autocomplete`, `_navigator_autocomplete` AND the `_make_crew_autocomplete` factory above them.

The new method signature is:

```python
    @expedition.command(name="start", description="Launch a new expedition.")
    @app_commands.describe(
        template="Pick from the autocomplete list",
        build="Pick a ship from your fleet",
    )
    @app_commands.autocomplete(
        template=_template_autocomplete,
        build=_build_autocomplete,
    )
    async def expedition_start(
        self,
        interaction: discord.Interaction,
        template: str,
        build: str,
    ) -> None:
        ...
```

- [ ] **Step 2: Update the launch handler body to derive aboard from `crew_assignments`**

Inside the new `expedition_start` body, replace the section that processed crew slash params with:

```python
        async with async_session() as session, session.begin():
            sys = await get_active_system(interaction, session)
            if sys is None:
                await interaction.response.send_message(
                    system_required_message(), ephemeral=True
                )
                return

            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None:
                await interaction.response.send_message(
                    "You don't have a profile yet — run `/start` first.",
                    ephemeral=True,
                )
                return

            # Concurrency cap (existing logic)
            max_active = await get_max_expeditions(session, user)
            current_active = await count_active_expeditions_for_user(session, user.discord_id)
            if current_active >= max_active:
                await interaction.response.send_message(
                    f"You're at the max active expedition limit ({current_active}/{max_active}). "
                    "Wait for one to complete.",
                    ephemeral=True,
                )
                return

            # Resolve build
            try:
                build_uuid = uuid.UUID(build)
            except ValueError:
                await interaction.response.send_message(
                    "Pick a ship from the autocomplete list.", ephemeral=True
                )
                return
            build_row = await session.get(Build, build_uuid, with_for_update=True)
            if build_row is None or build_row.user_id != user.discord_id:
                await interaction.response.send_message(
                    "Build not found.", ephemeral=True
                )
                return
            if build_row.current_activity != BuildActivity.IDLE:
                await interaction.response.send_message(
                    f"`{build_row.name}` is currently busy and can't launch.",
                    ephemeral=True,
                )
                return

            # ─────── Phase 2c: derive aboard set from crew_assignments ───────
            aboard_rows = (
                await session.execute(
                    select(CrewAssignment, CrewMember)
                    .join(CrewMember, CrewAssignment.crew_id == CrewMember.id)
                    .where(CrewAssignment.build_id == build_row.id)
                )
            ).all()

            now = datetime.now(timezone.utc)
            idle_aboard: list[tuple[CrewAssignment, CrewMember]] = []
            for assignment, crew in aboard_rows:
                is_busy = crew.current_activity != CrewActivity.IDLE
                is_injured = crew.injured_until is not None and crew.injured_until > now
                if not is_busy and not is_injured:
                    idle_aboard.append((assignment, crew))

            # Validate against template's crew_required
            archetypes_aboard = {a.archetype.name for a, _ in idle_aboard}  # uppercase like "PILOT"
            crew_req = tmpl.get("crew_required", {})
            min_required = int(crew_req.get("min", 1))
            archetypes_any = set(crew_req.get("archetypes_any", []))

            satisfies_min = len(idle_aboard) >= min_required
            satisfies_any = (not archetypes_any) or bool(archetypes_aboard & archetypes_any)
            if not satisfies_min or not satisfies_any:
                error_lines = _format_crew_required_error(
                    template_id=template,
                    template_label=tmpl.get("id", template),
                    archetypes_any=archetypes_any,
                    min_required=min_required,
                    build_row=build_row,
                    aboard_rows=aboard_rows,
                    now=now,
                )
                await interaction.response.send_message(
                    "\n".join(error_lines), ephemeral=True
                )
                return

            # Cost check (existing logic)
            cost = int(tmpl.get("cost_credits", 0))
            if user.currency < cost:
                await interaction.response.send_message(
                    f"You need {cost} credits to launch — you have {user.currency}.",
                    ephemeral=True,
                )
                return

            # Create expedition + snapshot crew
            now_utc = datetime.now(timezone.utc)
            duration = int(tmpl["duration_minutes"])
            completes_at = now_utc + timedelta(minutes=duration)
            expedition = Expedition(
                id=uuid.uuid4(),
                user_id=user.discord_id,
                build_id=build_row.id,
                template_id=template,
                state=ExpeditionState.ACTIVE,
                started_at=now_utc,
                completes_at=completes_at,
                correlation_id=uuid.uuid4(),
                scene_log=[],
            )
            session.add(expedition)

            # Snapshot idle aboard members into ExpeditionCrewAssignment
            for assignment, crew in idle_aboard:
                session.add(
                    ExpeditionCrewAssignment(
                        expedition_id=expedition.id,
                        crew_id=crew.id,
                        archetype=assignment.archetype,
                    )
                )
                crew.current_activity = CrewActivity.ON_EXPEDITION
                crew.current_activity_id = expedition.id

            build_row.current_activity = BuildActivity.ON_EXPEDITION
            build_row.current_activity_id = expedition.id
            user.currency -= cost
            await session.flush()

            # Schedule events + completion (existing logic — see git history for the
            # _select_scheduled_scenes loop; copy unchanged from previous version)
            scheduled_scenes = _select_scheduled_scenes(tmpl, expedition.id)
            spacing = duration / max(len(scheduled_scenes) + 1, 2)
            jitter_pct = settings.EXPEDITION_EVENT_JITTER_PCT / 100.0
            rng = Random(str(expedition.id))
            for i, scene_id in enumerate(scheduled_scenes, start=1):
                offset_min = spacing * i
                jitter_min = offset_min * jitter_pct * (rng.random() * 2 - 1)
                fire_at = now_utc + timedelta(minutes=offset_min + jitter_min)
                session.add(
                    ScheduledJob(
                        id=uuid.uuid4(),
                        user_id=user.discord_id,
                        job_type=JobType.EXPEDITION_EVENT,
                        payload={
                            "expedition_id": str(expedition.id),
                            "scene_id": scene_id,
                            "template_id": template,
                        },
                        scheduled_for=fire_at,
                        state=JobState.PENDING,
                    )
                )
            session.add(
                ScheduledJob(
                    id=uuid.uuid4(),
                    user_id=user.discord_id,
                    job_type=JobType.EXPEDITION_COMPLETE,
                    payload={
                        "expedition_id": str(expedition.id),
                        "template_id": template,
                    },
                    scheduled_for=completes_at,
                    state=JobState.PENDING,
                )
            )
            await session.flush()

        expeditions_started_total.labels(template_id=template, kind=tmpl["kind"]).inc()
        expedition_active.inc()

        await interaction.response.send_message(
            f"**{tmpl.get('id', template)}** launched. ETA "
            f"{discord.utils.format_dt(completes_at, 'R')}.",
            ephemeral=True,
        )
```

Add the slot-walking error helper at module scope (near `_lookup_crew_by_display`):

```python
def _format_crew_required_error(
    *,
    template_id: str,
    template_label: str,
    archetypes_any: set[str],
    min_required: int,
    build_row: Build,
    aboard_rows: list,
    now: datetime,
) -> list[str]:
    """Return the multi-line `/expedition start` error message walking every slot."""
    from engine.class_engine import slots_for_hull

    lines: list[str] = []
    if archetypes_any:
        sorted_any = sorted(archetypes_any)
        lines.append(
            f"**{template_label}** needs at least {min_required} of "
            f"{{{', '.join(sorted_any)}}}."
        )
    else:
        lines.append(
            f"**{template_label}** needs at least {min_required} idle aboard crew."
        )
    lines.append(f"`{build_row.name}` ({build_row.hull_class.value.title()}):")

    aboard_by_archetype = {a.archetype: c for a, c in aboard_rows}
    for slot_archetype in slots_for_hull(build_row.hull_class):
        crew = aboard_by_archetype.get(slot_archetype)
        if crew is None:
            lines.append(f"  • **{slot_archetype.name}** — empty")
        else:
            display = f'{crew.first_name} "{crew.callsign}" {crew.last_name}'
            if crew.injured_until is not None and crew.injured_until > now:
                returns_at = discord.utils.format_dt(crew.injured_until, "R")
                lines.append(
                    f"  • **{slot_archetype.name}** — {display} "
                    f"(injured, recovers {returns_at})"
                )
            elif crew.current_activity != CrewActivity.IDLE:
                lines.append(
                    f"  • **{slot_archetype.name}** — {display} "
                    f"({crew.current_activity.value})"
                )
            else:
                lines.append(f"  • **{slot_archetype.name}** — {display} (idle)")
    lines.append("Assign crew via `/hangar` or wait for busy crew to free up.")
    return lines
```

Make sure the import block at the top of `bot/cogs/expeditions.py` includes:

```python
from db.models import (
    # ...existing...
    CrewAssignment,
    CrewActivity,
)
```

- [ ] **Step 3: Update `tests/test_cog_expedition_start.py`**

Existing tests pass crew params via slash. Rewrite them to set up `crew_assignments` first, then call `/expedition start` with only `template:` and `build:`. Below is a representative rewrite for one test — apply the same pattern to all tests in the file.

Replace the existing setup pattern:

```python
# OLD
result = await cog.expedition_start.callback(
    cog,
    interaction=mock_interaction,
    template="marquee_run",
    build=str(build.id),
    pilot='Mira "Sixgun" Voss',
    gunner=None,
    engineer=None,
    navigator=None,
)
```

With:

```python
# NEW — set up assignment via the table, call /expedition start without crew params
from db.models import CrewAssignment

db_session.add(
    CrewAssignment(
        build_id=build.id,
        crew_id=pilot.id,
        archetype=CrewArchetype.PILOT,
    )
)
await db_session.flush()

result = await cog.expedition_start.callback(
    cog,
    interaction=mock_interaction,
    template="marquee_run",
    build=str(build.id),
)
```

Update each test in the file accordingly. Add one new test that exercises the slot-walking error:

```python
@pytest.mark.asyncio
async def test_expedition_start_blocks_when_crew_required_unsatisfied(
    db_session, sample_user, mock_interaction, monkeypatch
):
    """Slot-walking error: SKIRMISHER with empty pilot slot can't run a template needing PILOT."""
    from db.models import Build, BuildActivity, HullClass
    from bot.cogs.expeditions import ExpeditionsCog
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)
    await db_session.flush()

    monkeypatch.setattr(
        "bot.cogs.expeditions.async_session", lambda: SessionWrapper(db_session)
    )

    cog = ExpeditionsCog(MagicMock())
    await cog.expedition_start.callback(
        cog,
        interaction=mock_interaction,
        template="marquee_run",
        build=str(build.id),
    )
    sent = mock_interaction.response.send_message.call_args
    body = sent[0][0]
    assert "marquee_run" in body or "Marquee Run" in body
    assert "**PILOT**" in body and "empty" in body
    assert "/hangar" in body
```

- [ ] **Step 4: Update `tests/test_cog_expedition_autocomplete.py`**

Remove the four crew-archetype autocomplete tests:

```python
# REMOVE these test functions:
# - test_pilot_autocomplete_filters_by_archetype_and_idle
# - any test referencing _pilot_autocomplete / _gunner_autocomplete / etc.
```

Update the regression test that asserts autocompletes are wired:

```python
def test_expedition_start_has_autocompletes_wired():
    """Regression test: every player-facing string parameter must have an autocomplete."""
    from bot.cogs.expeditions import ExpeditionsCog

    cog = ExpeditionsCog(MagicMock())
    autocompletes = cog.expedition_start._params
    for param_name in ("template", "build"):  # crew params dropped in Phase 2c
        param = autocompletes.get(param_name)
        assert param is not None, f"missing param descriptor for {param_name}"
        assert param.autocomplete is not None, f"{param_name} has no autocomplete handler"
```

- [ ] **Step 5: Run all expedition cog tests, confirm pass**

```bash
pytest tests/test_cog_expedition_start.py tests/test_cog_expedition_autocomplete.py tests/test_cog_expedition_status.py tests/test_cog_expedition_respond.py -v --no-cov
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/expeditions.py tests/test_cog_expedition_start.py tests/test_cog_expedition_autocomplete.py
git commit -m "feat(phase2c): /expedition start derives aboard crew from ship; drop crew slash params"
```

---

## Task 13: `HangarView` module skeleton + custom_id helpers

**Files:**
- Create: `bot/views/__init__.py` (empty)
- Create: `bot/views/hangar_view.py`
- Create: `tests/test_view_hangar.py`

- [ ] **Step 1: Write failing tests**

Create `bot/views/__init__.py` with an empty file.

Create `tests/test_view_hangar.py`:

```python
"""HangarView — custom_id encoding/decoding tests."""

from __future__ import annotations

import uuid


def test_make_select_custom_id_format():
    from bot.views.hangar_view import make_select_custom_id

    build_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    out = make_select_custom_id(build_id, "PILOT")
    assert out == "hangar:slot:12345678-1234-5678-1234-567812345678:PILOT"


def test_parse_select_custom_id_round_trip():
    from bot.views.hangar_view import make_select_custom_id, parse_select_custom_id

    build_id = uuid.uuid4()
    cid = make_select_custom_id(build_id, "GUNNER")
    parsed = parse_select_custom_id(cid)
    assert parsed == (build_id, "GUNNER")


def test_parse_select_custom_id_rejects_unknown_prefix():
    from bot.views.hangar_view import parse_select_custom_id

    assert parse_select_custom_id("expedition:button:foo:bar") is None
    assert parse_select_custom_id("totally bogus") is None
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_view_hangar.py -v --no-cov`
Expected: 3 FAIL — module doesn't exist.

- [ ] **Step 3: Create the view module skeleton**

Create `bot/views/hangar_view.py`:

```python
"""Persistent HangarView for the /hangar <build> command.

The View has one Select per crew slot. Selecting a crew option assigns that
crew to the slot; selecting the special 'Unassign' option clears the slot.
The View is registered globally at bot startup via `bot.add_view(HangarView())`
so button/select interactions survive restarts.

custom_id format:
    hangar:slot:<build_id>:<archetype_name>
    e.g. hangar:slot:12345678-1234-5678-1234-567812345678:PILOT

Select option values:
    A real crew_id UUID, OR the literal string "unassign".
"""

from __future__ import annotations

import uuid

import discord

CUSTOM_ID_PREFIX = "hangar:slot"
UNASSIGN_VALUE = "unassign"


def make_select_custom_id(build_id: uuid.UUID, archetype_name: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{build_id}:{archetype_name}"


def parse_select_custom_id(custom_id: str) -> tuple[uuid.UUID, str] | None:
    """Return (build_id, archetype_name) if `custom_id` matches the hangar slot format."""
    parts = custom_id.split(":")
    if len(parts) != 4 or parts[0] != "hangar" or parts[1] != "slot":
        return None
    try:
        build_uuid = uuid.UUID(parts[2])
    except ValueError:
        return None
    return build_uuid, parts[3]


class HangarView(discord.ui.View):
    """Persistent View that handles all /hangar crew-slot Select interactions."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    # interaction_check + _handle_assignment / _handle_unassignment land in Task 15.
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_view_hangar.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/views/__init__.py bot/views/hangar_view.py tests/test_view_hangar.py
git commit -m "feat(phase2c): HangarView module skeleton + custom_id helpers"
```

---

## Task 14: `render_hangar_view()` factory — embed + Select components

**Files:**
- Modify: `bot/views/hangar_view.py`
- Modify: `tests/test_view_hangar.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_view_hangar.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_render_hangar_view_returns_embed_and_view(
    db_session, sample_user
):
    from db.models import Build, HullClass
    from bot.views.hangar_view import render_hangar_view

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()

    embed, view = await render_hangar_view(db_session, build, sample_user)
    assert "Flagstaff" in embed.description or "Flagstaff" in embed.title
    # Skirmisher = 2 crew slots (PILOT, GUNNER) → 2 Select children
    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    assert len(selects) == 2


@pytest.mark.asyncio
async def test_render_hangar_view_filled_slot_shows_crew_name(
    db_session, sample_user
):
    from db.models import (
        Build,
        CrewAssignment,
        CrewArchetype,
        CrewMember,
        HullClass,
        Rarity,
    )
    from bot.views.hangar_view import render_hangar_view

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(
            build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT
        )
    )
    await db_session.flush()

    embed, view = await render_hangar_view(db_session, build, sample_user)
    description = embed.description or ""
    assert "Mira" in description and "Sixgun" in description


@pytest.mark.asyncio
async def test_render_hangar_view_disables_selects_when_on_expedition(
    db_session, sample_user
):
    from db.models import Build, BuildActivity, HullClass
    from bot.views.hangar_view import render_hangar_view

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()

    embed, view = await render_hangar_view(db_session, build, sample_user)
    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    assert all(s.disabled for s in selects)
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_view_hangar.py -v --no-cov`
Expected: 3 NEW FAIL — `render_hangar_view` doesn't exist.

- [ ] **Step 3: Implement `render_hangar_view()` in `bot/views/hangar_view.py`**

Add to `bot/views/hangar_view.py`:

```python
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Build,
    BuildActivity,
    CrewAssignment,
    CrewActivity,
    CrewArchetype,
    CrewMember,
    User,
)
from engine.class_engine import slots_for_hull


async def render_hangar_view(
    session: AsyncSession,
    build: Build,
    user: User,
) -> tuple[discord.Embed, "HangarView"]:
    """Render the /hangar embed + interactive View for `build`."""
    is_locked = build.current_activity != BuildActivity.IDLE

    # Load current assignments
    rows = (
        await session.execute(
            select(CrewAssignment, CrewMember)
            .join(CrewMember, CrewAssignment.crew_id == CrewMember.id)
            .where(CrewAssignment.build_id == build.id)
        )
    ).all()
    aboard_by_archetype: dict[CrewArchetype, CrewMember] = {
        assignment.archetype: crew for assignment, crew in rows
    }

    # Build embed
    crew_lines: list[str] = []
    for slot in slots_for_hull(build.hull_class):
        crew = aboard_by_archetype.get(slot)
        if crew is None:
            crew_lines.append(f"**{slot.name}** — empty")
        else:
            display = f'{crew.first_name} "{crew.callsign}" {crew.last_name} (Lvl {crew.level})'
            status = _crew_status_label(crew)
            crew_lines.append(f"**{slot.name}** — {display} — {status}")

    embed = discord.Embed(
        title=f"🚢 {build.name} ({build.hull_class.value.title()})",
        description="\n".join(["**Crew**", *crew_lines]),
    )
    if is_locked:
        embed.add_field(
            name="Status", value=f"Locked — {build.current_activity.value}", inline=False
        )

    # Build view: one Select per slot
    view = HangarView()
    if not is_locked:
        # Load eligible crew (idle, not aboard another ship, of the right archetype)
        eligible_by_archetype = await _load_eligible_crew_by_archetype(
            session, user.discord_id, build.id
        )
        for slot in slots_for_hull(build.hull_class):
            current_crew = aboard_by_archetype.get(slot)
            select_component = _build_slot_select(
                build.id, slot, current_crew, eligible_by_archetype.get(slot, [])
            )
            view.add_item(select_component)
    else:
        # Disabled placeholder selects so the View shape stays consistent
        for slot in slots_for_hull(build.hull_class):
            placeholder = discord.ui.Select(
                custom_id=make_select_custom_id(build.id, slot.name),
                placeholder=f"{slot.name}: ship locked",
                options=[
                    discord.SelectOption(label="(ship is busy)", value="locked", default=True)
                ],
                disabled=True,
                min_values=1,
                max_values=1,
            )
            view.add_item(placeholder)

    return embed, view


def _crew_status_label(crew: CrewMember) -> str:
    now = datetime.now(timezone.utc)
    if crew.injured_until is not None and crew.injured_until > now:
        return "injured"
    return crew.current_activity.value if crew.current_activity else "idle"


async def _load_eligible_crew_by_archetype(
    session: AsyncSession, user_id: str, this_build_id: uuid.UUID
) -> dict[CrewArchetype, list[CrewMember]]:
    """Return crew owned by `user_id` not currently assigned to a DIFFERENT build, grouped by archetype."""
    # Outer-join crew_assignments to find crew with no assignment OR assignment to THIS build
    rows = (
        await session.execute(
            select(CrewMember, CrewAssignment.build_id)
            .outerjoin(
                CrewAssignment, CrewMember.id == CrewAssignment.crew_id
            )
            .where(CrewMember.user_id == user_id)
        )
    ).all()
    out: dict[CrewArchetype, list[CrewMember]] = {}
    for crew, assigned_build_id in rows:
        if assigned_build_id is not None and assigned_build_id != this_build_id:
            continue  # aboard a different ship
        out.setdefault(crew.archetype, []).append(crew)
    return out


def _build_slot_select(
    build_id: uuid.UUID,
    archetype: CrewArchetype,
    current_crew: CrewMember | None,
    eligible: list[CrewMember],
) -> discord.ui.Select:
    options: list[discord.SelectOption] = []
    if not eligible:
        options.append(
            discord.SelectOption(
                label=f"(no eligible {archetype.name.lower()}s)",
                value="none",
                default=True,
            )
        )
        return discord.ui.Select(
            custom_id=make_select_custom_id(build_id, archetype.name),
            placeholder=archetype.name,
            options=options,
            disabled=True,
            min_values=1,
            max_values=1,
        )

    # Discord caps Select options at 25; with the Unassign option we leave room for 24 crew
    for crew in eligible[:24]:
        label = f'{crew.first_name} "{crew.callsign}" {crew.last_name} (Lvl {crew.level})'[:100]
        is_current = current_crew is not None and crew.id == current_crew.id
        status = _crew_status_label(crew)
        description = f"{archetype.name.title()} · {status}"[:100]
        options.append(
            discord.SelectOption(
                label=label,
                value=str(crew.id),
                description=description,
                default=is_current,
            )
        )
    if current_crew is not None:
        options.append(
            discord.SelectOption(
                label="Unassign",
                value=UNASSIGN_VALUE,
                description=f"Remove from {archetype.name.title()} slot",
            )
        )

    return discord.ui.Select(
        custom_id=make_select_custom_id(build_id, archetype.name),
        placeholder=archetype.name,
        options=options,
        min_values=1,
        max_values=1,
    )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_view_hangar.py -v --no-cov`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/views/hangar_view.py tests/test_view_hangar.py
git commit -m "feat(phase2c): render_hangar_view() returns embed + Select-per-slot View"
```

---

## Task 15: `HangarView.interaction_check` — assign + unassign handlers

**Files:**
- Modify: `bot/views/hangar_view.py`
- Modify: `tests/test_view_hangar.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_view_hangar.py`:

```python
@pytest.mark.asyncio
async def test_hangar_assign_inserts_build_crew_assignment(
    db_session, sample_user, monkeypatch
):
    from unittest.mock import AsyncMock, MagicMock
    from db.models import (
        Build,
        CrewAssignment,
        CrewArchetype,
        CrewMember,
        HullClass,
        Rarity,
    )
    from bot.views import hangar_view as hv
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add_all([crew, build])
    await db_session.flush()

    monkeypatch.setattr(hv, "async_session", lambda: SessionWrapper(db_session))

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)
    interaction.data = {
        "custom_id": hv.make_select_custom_id(build.id, "PILOT"),
        "values": [str(crew.id)],
    }
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()

    view = hv.HangarView()
    handled = await view.interaction_check(interaction)
    assert handled is False  # we handle the response, returning False short-circuits

    # Assignment row should exist
    from sqlalchemy import select

    rows = (
        await db_session.execute(
            select(CrewAssignment)
            .where(CrewAssignment.build_id == build.id)
            .where(CrewAssignment.archetype == CrewArchetype.PILOT)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].crew_id == crew.id


@pytest.mark.asyncio
async def test_hangar_unassign_removes_build_crew_assignment(
    db_session, sample_user, monkeypatch
):
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy import select
    from db.models import (
        Build,
        CrewAssignment,
        CrewArchetype,
        CrewMember,
        HullClass,
        Rarity,
    )
    from bot.views import hangar_view as hv
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(
            build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT
        )
    )
    await db_session.flush()

    monkeypatch.setattr(hv, "async_session", lambda: SessionWrapper(db_session))

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)
    interaction.data = {
        "custom_id": hv.make_select_custom_id(build.id, "PILOT"),
        "values": [hv.UNASSIGN_VALUE],
    }
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()

    view = hv.HangarView()
    await view.interaction_check(interaction)

    rows = (
        await db_session.execute(
            select(CrewAssignment).where(CrewAssignment.build_id == build.id)
        )
    ).scalars().all()
    assert rows == []
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_view_hangar.py -v --no-cov -k "assign or unassign"`
Expected: 2 FAIL — `interaction_check` is the default no-op.

- [ ] **Step 3: Implement `interaction_check`**

Add to `bot/views/hangar_view.py`:

```python
from db.session import async_session
from sqlalchemy import delete


class HangarView(discord.ui.View):
    """Persistent View that handles all /hangar crew-slot Select interactions."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:  # type: ignore[override]
        custom_id = (interaction.data or {}).get("custom_id", "") if interaction.data else ""
        parsed = parse_select_custom_id(custom_id)
        if parsed is None:
            return False  # not our component
        build_id, archetype_name = parsed
        try:
            archetype = CrewArchetype[archetype_name]
        except KeyError:
            await interaction.response.send_message(
                "Unknown crew slot.", ephemeral=True
            )
            return False

        values = (interaction.data or {}).get("values", [])
        if not values:
            return False
        chosen = values[0]

        async with async_session() as session, session.begin():
            build = await session.get(Build, build_id, with_for_update=True)
            if build is None or build.user_id != str(interaction.user.id):
                await interaction.response.send_message(
                    "Build not found.", ephemeral=True
                )
                return False
            if build.current_activity != BuildActivity.IDLE:
                await interaction.response.send_message(
                    f"`{build.name}` is currently busy and can't be modified.",
                    ephemeral=True,
                )
                return False

            if chosen == UNASSIGN_VALUE:
                await session.execute(
                    delete(CrewAssignment)
                    .where(CrewAssignment.build_id == build.id)
                    .where(CrewAssignment.archetype == archetype)
                )
                msg = f"Unassigned the {archetype.name.title()} slot of `{build.name}`."
            elif chosen in {"none", "locked"}:
                return False  # disabled placeholder; ignore
            else:
                try:
                    crew_uuid = uuid.UUID(chosen)
                except ValueError:
                    await interaction.response.send_message(
                        "Invalid selection.", ephemeral=True
                    )
                    return False
                crew = await session.get(CrewMember, crew_uuid)
                if crew is None or crew.user_id != str(interaction.user.id):
                    await interaction.response.send_message(
                        "Crew member not found.", ephemeral=True
                    )
                    return False
                if crew.archetype != archetype:
                    await interaction.response.send_message(
                        f"That crew member is a {crew.archetype.name.title()}, "
                        f"not a {archetype.name.title()}.",
                        ephemeral=True,
                    )
                    return False
                # Upsert: replace any existing assignment for this slot.
                await session.execute(
                    delete(CrewAssignment)
                    .where(CrewAssignment.build_id == build.id)
                    .where(CrewAssignment.archetype == archetype)
                )
                session.add(
                    CrewAssignment(
                        build_id=build.id, crew_id=crew.id, archetype=archetype
                    )
                )
                msg = (
                    f'Assigned {crew.first_name} "{crew.callsign}" {crew.last_name} '
                    f"as {archetype.name.title()} of `{build.name}`."
                )

        await interaction.response.send_message(msg, ephemeral=True)
        return False  # response handled; don't propagate to a child callback
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_view_hangar.py -v --no-cov`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/views/hangar_view.py tests/test_view_hangar.py
git commit -m "feat(phase2c): HangarView assign/unassign interaction_check"
```

---

## Task 16: Register `HangarView` persistent view + attach to `/hangar` command

**Files:**
- Modify: `bot/main.py`
- Modify: `bot/cogs/hangar.py`
- Modify: `tests/test_view_hangar.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_view_hangar.py`:

```python
def test_setup_hook_registers_hangar_view():
    """Persistent view contract: HangarView is added at bot startup."""
    import inspect
    from bot import main as main_mod

    source = inspect.getsource(main_mod)
    assert "HangarView" in source, "bot/main.py must reference HangarView"
    assert "add_view" in source, "bot/main.py must call add_view()"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_view_hangar.py::test_setup_hook_registers_hangar_view -v --no-cov`
Expected: FAIL — `bot/main.py` doesn't reference `HangarView`.

- [ ] **Step 3: Register the view in `bot/main.py`**

In `bot/main.py`, find the existing `bot.add_view(ExpeditionResponseView())` call inside `setup_hook` (or wherever Phase 2b registered persistent views). Add immediately after:

```python
        from bot.views.hangar_view import HangarView

        bot.add_view(HangarView())
```

- [ ] **Step 4: Attach view to `/hangar` command**

In `bot/cogs/hangar.py`, find the `hangar` slash command's `interaction.response.send_message(embed=embed)` line. Replace the entire embed-construction block with a call to `render_hangar_view`:

```python
    @app_commands.command(name="hangar", description="View your current build")
    @app_commands.describe(build="Which build to view (default: your default build)")
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def hangar(self, interaction: discord.Interaction, build: str | None = None) -> None:
        from bot.views.hangar_view import render_hangar_view

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return
            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b:
                await interaction.response.send_message(
                    "Build not found. Use `/build list` to see your builds.", ephemeral=True
                )
                return
            embed, view = await render_hangar_view(session, b, user)

        await interaction.response.send_message(embed=embed, view=view)

        # Tutorial progression (existing)
        from bot.cogs.tutorial import advance_tutorial
        await advance_tutorial(interaction, str(interaction.user.id), "hangar")
```

This drops the in-cog parts-rendering logic. Parts info now comes from `render_hangar_view`'s embed builder. **If you want to preserve the existing parts list in the embed** (recommended), extend `render_hangar_view` to add fields/lines for slots in `b.slots` — copy the iteration block from the old `hangar()` method into `render_hangar_view`'s embed builder. Keep this self-contained: do not split into a third helper. (If the existing `hangar` method is large enough that copying is awkward, refactor in a separate commit before this task.)

For the minimum viable Phase 2c, parts are a separate field. Extending `render_hangar_view` to include parts-list lines is straightforward — add to its embed `description`:

```python
    # In render_hangar_view, BEFORE returning:
    parts_lines: list[str] = []
    for slot in CardSlot:
        uc_id_str = build.slots.get(slot.value)
        # ... copy the existing parts-rendering logic from bot/cogs/hangar.py:355-377 ...
    if parts_lines:
        embed.description = (embed.description or "") + "\n\n**Parts**\n" + "\n".join(parts_lines)
```

(Don't add a runtime import of `CardSlot` etc. — bring them into the imports at the top of `bot/views/hangar_view.py`.)

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_view_hangar.py tests/test_cog_hangar.py -v --no-cov`
Expected: ALL PASS. (`test_cog_hangar.py` may not exist yet — if there's no existing hangar-cog test file, just run the view tests.)

- [ ] **Step 6: Commit**

```bash
git add bot/main.py bot/cogs/hangar.py bot/views/hangar_view.py tests/test_view_hangar.py
git commit -m "feat(phase2c): register persistent HangarView; /hangar attaches view"
```

---

## Task 17: `/crew_inspect` shows "Aboard `<ship name>`" line

**Files:**
- Modify: `bot/cogs/hiring.py` (or wherever `/crew_inspect` is defined — `grep -rn "crew_inspect" bot/cogs/`)
- Modify: appropriate test file

- [ ] **Step 1: Find the crew inspect command**

Run from repo root:

```bash
grep -rn "crew_inspect\|name=\"crew_inspect\"\|inspect.*description.*crew" bot/cogs/
```

Note the file and line number — you'll modify the embed-construction block where the crew member's status is rendered.

- [ ] **Step 2: Write failing test**

Locate or create `tests/test_cog_crew_inspect.py` (the existing test name may differ). Append:

```python
@pytest.mark.asyncio
async def test_crew_inspect_shows_aboard_line_when_assigned(
    db_session, sample_user, mock_interaction, monkeypatch
):
    """When the crew member is in crew_assignments, show the ship name."""
    from db.models import (
        Build,
        CrewAssignment,
        CrewArchetype,
        CrewMember,
        HullClass,
        Rarity,
    )

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(
            build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT
        )
    )
    await db_session.flush()

    # Invoke the cog command — adapt this section to the actual cog/command names
    from bot.cogs.hiring import HiringCog
    from tests.conftest import SessionWrapper

    monkeypatch.setattr(
        "bot.cogs.hiring.async_session", lambda: SessionWrapper(db_session)
    )
    cog = HiringCog(MagicMock())
    await cog.crew_inspect.callback(cog, interaction=mock_interaction, crew='Mira "Sixgun" Voss')

    sent_kwargs = mock_interaction.response.send_message.call_args.kwargs
    embed = sent_kwargs.get("embed")
    assert embed is not None
    description = (embed.description or "") + " ".join(
        f.value for f in embed.fields
    )
    assert "Aboard" in description and "Flagstaff" in description
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_cog_crew_inspect.py -v --no-cov`
Expected: FAIL — Aboard line missing.

- [ ] **Step 4: Add the Aboard line in the cog**

In the crew-inspect cog file, before sending the embed:

```python
        # Phase 2c: show "Aboard <ship>" if the crew member is assigned to a build
        from sqlalchemy import select as _select
        from db.models import Build, CrewAssignment

        assignment_row = (
            await session.execute(
                _select(CrewAssignment, Build)
                .join(Build, CrewAssignment.build_id == Build.id)
                .where(CrewAssignment.crew_id == crew.id)
            )
        ).first()
        if assignment_row is not None:
            _assignment, ship = assignment_row
            embed.add_field(
                name="Aboard",
                value=f"`{ship.name}` ({ship.hull_class.value.title()})",
                inline=False,
            )
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_cog_crew_inspect.py -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/hiring.py tests/test_cog_crew_inspect.py
git commit -m "feat(phase2c): /crew_inspect shows aboard ship when assigned"
```

---

## Task 18: End-to-end integration test

**Files:**
- Create: `tests/test_scenarios/test_ship_crew_binding_flow.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_scenarios/test_ship_crew_binding_flow.py`:

```python
"""End-to-end Phase 2c: ship-crew binding + narrative substitution lifecycle.

Builds the entire flow:
1. Player has a build + a crew member.
2. Crew is bound to ship via crew_assignments (direct DB write — the
   /hangar UX is exercised in test_view_hangar.py).
3. /expedition start launches with no crew params; the ship's crew is
   auto-derived.
4. EXPEDITION_EVENT fires; the DM body has rendered narrative tokens.
5. Player clicks the button (handle_expedition_response).
6. EXPEDITION_RESOLVE renders outcome narrative.
7. EXPEDITION_COMPLETE fires; closing body renders.
8. Build + crew return to IDLE; persistent assignment is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_full_lifecycle_with_persistent_assignment_and_rendered_tokens(
    db_session, sample_user, monkeypatch
):
    from db.models import (
        Build,
        BuildActivity,
        CrewAssignment,
        CrewActivity,
        CrewArchetype,
        CrewMember,
        Expedition,
        ExpeditionState,
        HullClass,
        JobState,
        JobType,
        Rarity,
        ScheduledJob,
    )
    from engine import expedition_template as tmpl_mod
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    from scheduler.jobs.expedition_event import handle_expedition_event

    # ─────── setup ───────
    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
        current_activity=CrewActivity.IDLE,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(
            build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT
        )
    )
    await db_session.flush()

    # Create the expedition row + crew snapshot directly (the cog test in Task 12
    # exercises the actual /expedition start path)
    expedition = Expedition(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        build_id=build.id,
        template_id="marquee_run",
        state=ExpeditionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
        completes_at=datetime.now(timezone.utc) + timedelta(hours=1),
        correlation_id=uuid.uuid4(),
        scene_log=[],
    )
    from db.models import ExpeditionCrewAssignment

    db_session.add(expedition)
    db_session.add(
        ExpeditionCrewAssignment(
            expedition_id=expedition.id, crew_id=crew.id, archetype=CrewArchetype.PILOT
        )
    )
    crew.current_activity = CrewActivity.ON_EXPEDITION
    crew.current_activity_id = expedition.id
    build.current_activity = BuildActivity.ON_EXPEDITION
    build.current_activity_id = expedition.id
    await db_session.flush()

    # Stub the template to use narrative tokens
    fake_template = {
        "id": "marquee_run",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "pirate_skiff",
                "narration": "{pilot.callsign} aboard the {ship} sights pirates.",
                "choices": [
                    {
                        "id": "outrun",
                        "text": "Burn hard.",
                        "default": True,
                        "outcomes": {
                            "result": {
                                "narrative": "{ship} pulls away clean.",
                                "effects": [],
                            }
                        },
                    }
                ],
            },
            {
                "id": "closing",
                "is_closing": True,
                "narration": "ok",
                "closings": [
                    {
                        "when": {"default": True},
                        "body": "{pilot.callsign} brings the {ship} home.",
                        "effects": [],
                    }
                ],
            },
        ],
    }
    monkeypatch.setattr(tmpl_mod, "load_template", lambda _id: fake_template)

    # ─────── EXPEDITION_EVENT renders tokens ───────
    event_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(event_job)
    await db_session.flush()
    event_result = await handle_expedition_event(db_session, event_job)
    event_body = event_result.notifications[0].body
    assert "Sixgun" in event_body
    assert "Flagstaff" in event_body
    assert "{pilot" not in event_body
    assert "{ship" not in event_body

    # ─────── EXPEDITION_COMPLETE renders closing ───────
    complete_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        job_type=JobType.EXPEDITION_COMPLETE,
        payload={
            "expedition_id": str(expedition.id),
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(complete_job)
    await db_session.flush()
    complete_result = await handle_expedition_complete(db_session, complete_job)
    closing_body = complete_result.notifications[0].body
    assert "Sixgun" in closing_body
    assert "Flagstaff" in closing_body

    # ─────── persistent assignment survived; crew/build unlocked ───────
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    refreshed_build = await db_session.get(Build, build.id)
    assert refreshed_crew.current_activity == CrewActivity.IDLE
    assert refreshed_build.current_activity == BuildActivity.IDLE

    from sqlalchemy import select

    binding = (
        await db_session.execute(
            select(CrewAssignment).where(CrewAssignment.build_id == build.id)
        )
    ).scalar_one_or_none()
    assert binding is not None
    assert binding.crew_id == crew.id
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_scenarios/test_ship_crew_binding_flow.py -v --no-cov`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scenarios/test_ship_crew_binding_flow.py
git commit -m "test(phase2c): end-to-end ship-crew binding lifecycle with rendered tokens"
```

---

## Task 19: Authoring docs — narrative tokens section

**Files:**
- Modify: `docs/authoring/expeditions.md`

- [ ] **Step 1: Append the new section**

At the bottom of `docs/authoring/expeditions.md`, append:

````markdown
---

## Narrative tokens (Phase 2c)

Templates can reference the aboard crew and ship by name in any player-visible string (`narration`, choice `text`, outcome `narrative`, closing `body`) using `{token}` syntax. The token vocabulary is **closed** — anything outside the allow-list will fail template validation at load time.

### Allow-list

| Token | Resolves to | Example |
| --- | --- | --- |
| `{pilot}` / `{gunner}` / `{engineer}` / `{navigator}` | display name `'First "Callsign" Last'` | `Mira "Sixgun" Voss` |
| `{<archetype>.callsign}` | callsign only | `Sixgun` |
| `{<archetype>.first_name}` / `{<archetype>.last_name}` | name parts | `Mira` / `Voss` |
| `{ship}` | ship name | `Flagstaff` |
| `{ship.hull}` | hull class display name | `Skirmisher` |

### Empty-slot fallback

When a slot is empty (the ship has no crew of that archetype assigned, OR the assigned crew is busy/injured), the token resolves to a generic noun:

- `{pilot}` → `the pilot`
- `{gunner.callsign}` → `the gunner`
- `{ship}` → `the ship` (rare — every expedition has a build)

This means narration like `{pilot.callsign} pulls the {ship} alongside the wreck` reads coherently even when the player launches without a pilot: `the pilot pulls the the ship alongside the wreck` — ugly, but a clear visual signal something is missing.

### Authoring tips

1. Lean on `.callsign` for terse, voice-driven narration (`"Sixgun, get on the guns."`).
2. Use full names sparingly — they're long and break the action verb of a sentence.
3. Don't prefix `{ship}` with `"the "` if you can avoid it — the fallback `the ship` will read awkwardly.
4. To use a literal `{` or `}` in narration, double the brace: `{{` and `}}`.

### Example

```yaml
- id: drifting_wreck
  narration: |
    {pilot.callsign} is checking the long-range scope when the contact pings —
    something cold and tumbling. {gunner.callsign} drifts over to the side
    guns, "just in case." Could be salvage. Could be bait.
  choices:
    - id: salvage
      text: "Match velocities and crack it open."
      ...
```

A SKIRMISHER (with both pilot and gunner slots filled) renders as: *"Sixgun is checking the long-range scope when the contact pings — Blackjack drifts over to the side guns…"*

The same template launched with an empty gunner slot renders as: *"Sixgun is checking the long-range scope when the contact pings — the gunner drifts over to the side guns…"* — the player sees they could have done better with a gunner aboard.
````

- [ ] **Step 2: Verify markdown renders**

If the project has a markdown CI gate (lint warnings on the existing roadmap suggest yes), run it locally. Otherwise eyeball the file in a renderer.

- [ ] **Step 3: Commit**

```bash
git add docs/authoring/expeditions.md
git commit -m "docs(phase2c): authoring guide section for narrative tokens"
```

---

## Final verification

After all tasks complete, run the full suite:

```bash
DATABASE_URL=postgresql://dare2drive:dare2drive@localhost:5432/dare2drive python -m alembic upgrade head
pytest --no-cov -x 2>&1 | tail -10
```

Expected: ALL PASS (modulo the pre-existing scenario-test failures that hit docker-network hostnames from a Windows host — those are environmental and not caused by this phase).

Then exercise the actual Discord flow on dev:

1. `/hangar <some build>` → confirm the new view renders, slots show empty/filled, selects work.
2. Assign a pilot to a SKIRMISHER → confirm "Aboard `<ship>`" appears on `/crew_inspect`.
3. `/expedition start template:outer_marker_patrol build:<that ship>` → confirm launch succeeds with no crew params.
4. Wait for an event DM → confirm the body is human-readable and (if you patched the template to use tokens) shows the actual crew callsign / ship name.
5. Click a choice button → confirm the outcome narrative renders.
6. Wait for completion → confirm the closing renders and the build/crew are back to IDLE with the persistent assignment intact.
