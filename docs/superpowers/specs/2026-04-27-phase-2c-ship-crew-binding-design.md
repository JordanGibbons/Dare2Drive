# Phase 2c — Ship-Crew Binding + Narrative Substitution

**Status:** Approved 2026-04-27
**Phase:** 2c of 6+ (see [salvage-pulp revamp roadmap](../../roadmap/2026-04-22-salvage-pulp-revamp.md))
**Owner:** Jordan
**Depends on:** [Phase 2b expeditions](2026-04-26-phase-2b-expeditions-design.md) (shipped)

---

## Context

Phase 2b shipped expeditions, but with a UX seam: crew assignment happens at expedition launch (`/expedition start build:... pilot:... gunner:...`) rather than persistently on the ship. That's awkward in two ways. First, it implies crew are stateless drifters who attach to a ship for one run, which doesn't match the "crew sector" framing from Phase 1 — these are named characters with histories, not vendor-machine outputs. Second, it forces the player to re-pick the same crew every single launch, even though they almost always pick the same loadout for the same ship.

Phase 2c moves crew binding to the ship. Each ship has a fixed crew composition determined by its hull class (e.g., a SKIRMISHER has a pilot slot and a gunner slot, period). Players assign crew once via `/hangar`, and `/expedition start` reads from the ship — no crew picker at launch time.

This phase also lands a long-asked-for narrative win: **expedition templates can reference the crew and ship in their narration**. Authors can write `{pilot.callsign} pulls the {ship} alongside the wreck...` and the engine renders 'Sixgun pulls the Flagstaff alongside the wreck...' at scene-fire time. It's a small change with outsized story impact, made cheap by the fact that 2c is already plumbing crew context through the engine for the binding work.

The two halves ship together because they're cheap together. The data model change (crew on ship) needs a one-time migration; doing the narrative-rendering work in the same sprint avoids touching the same files twice.

---

## Locked decisions

These were settled during brainstorming. Re-litigation belongs in a follow-on spec.

### Crew capacity is hull-class-specific

Each hull class has a fixed crew composition expressed as a list of archetypes:

```python
HULL_CREW_SLOTS = {
    HullClass.SKIRMISHER: [PILOT, GUNNER],
    HullClass.HAULER:     [PILOT, ENGINEER, NAVIGATOR],
    HullClass.SCOUT:      [PILOT, NAVIGATOR],
}
```

This is a Python constant in `engine/class_engine.py` (or a sibling module), not a DB table — adding a new hull means editing the dict and adding the enum value. The choice of slot composition makes hull selection meaningful: a SKIRMISHER can never satisfy a template that requires an ENGINEER, because there's literally no engineer slot. Hull = role, not just stat profile.

A future `HullClass` addition (e.g., `CRUISER` with all four slots) is a one-line dict entry plus a migration to extend the enum.

### Crew is bound persistently to ships, not to expeditions

A new `build_crew_assignments` table holds the persistent (build, archetype) → crew mapping. A crew member is on at most one ship at a time, enforced by a `UNIQUE(crew_id)` constraint. Reassignment is allowed when both the ship and the crew are IDLE.

`/expedition start` no longer accepts crew parameters. It takes only `template:` and `build:` and derives the aboard crew from the ship.

`ExpeditionCrewAssignment` (Phase 2b) **stays as the in-flight snapshot.** It's populated from `build_crew_assignments` at `/expedition start`, and it's what the engine reads during the expedition. Keeping it means: (a) reassigning crew on the ship while another ship is on expedition doesn't disturb the active expedition's view of who's aboard; (b) the historical "who was on this run" record survives crew swaps later.

### Assignment surface is an interactive view, not atomic slash commands

Following the project preference for combinatory views over single-purpose slash commands, the assignment UX extends the existing `/hangar <build>` command. The view's embed shows ship stats and parts (existing) plus crew slots; the components are Discord Select menus, one per crew slot, listing eligible crew of that archetype. Selecting a crew member commits the assignment; selecting the special `Unassign` option clears the slot. The view is a persistent View (registered globally at bot startup, like `ExpeditionResponseView`).

`/crew inspect <crew>` adds a passive read-only line ("Aboard *Flagstaff* (Skirmisher), idle"). No assignment power from the crew side — the ship is the canonical mutation surface.

### Launch validation is template-required only

At `/expedition start`, the launch handler computes the *idle aboard set* — crew assigned to that ship whose `current_activity == IDLE` and not currently injured. The launch is allowed iff the template's `crew_required.min` and `archetypes_any` are satisfied by the idle aboard set. Empty slots and busy/injured crew don't block launch on their own — only when they prevent the template's requirements from being met.

This carries Phase 2b's `crew_required` semantics forward unchanged: same field, same meaning, just applied to ship-bound crew instead of slash-param crew. No template changes needed for the existing two templates.

The error message enumerates **every** crew slot on the ship — assigned crew with their current activity, and empty slots — so the player sees both the gap and the path to fix it (assign someone, finish the training a crew member is in, etc.). Example shape:

```text
Outer Marker Patrol needs at least 1 of {PILOT, GUNNER}.
Flagstaff (Skirmisher):
  • PILOT — Mira "Sixgun" Voss (in training, returns in 2h 14m)
  • GUNNER — empty
Try assigning a gunner via /hangar Flagstaff, or wait for Mira.
```

### Crew assignments persist across expeditions

After an expedition completes, crew return to `current_activity = IDLE` but stay assigned to the ship. There is no "re-equip after every run" loop — the player only manages crew assignments when they actually want to change them.

### Narrative substitution: closed allow-list, render at scene-fire time

Templates can reference the aboard crew and the ship in player-visible strings using `{token}` syntax. The token allow-list is closed for v1:

| Token | Resolves to |
| --- | --- |
| `{pilot}` / `{gunner}` / `{engineer}` / `{navigator}` | Display name 'First "Callsign" Last' |
| `{<archetype>.callsign}` | Just the callsign |
| `{<archetype>.first_name}` / `{<archetype>.last_name}` | Name parts |
| `{ship}` | Ship name |
| `{ship.hull}` | Hull class display name |

Substitution happens at the point the player sees the text — the `EXPEDITION_EVENT` and `EXPEDITION_RESOLVE` notification handlers, just before formatting the body. A new `engine/narrative_render.py` module owns the rendering; handlers call it as the last step. Context (build + crew lookups) is assembled once per render call.

**Empty slot fallback:** missing crew → generic noun. `{pilot}` → "the pilot"; `{gunner.callsign}` → "the gunner"; `{ship}` → "the ship". This keeps grammar intact when a SKIRMISHER runs a template that references `{engineer}`.

**Validator-enforced allow-list:** the template loader extends to scan all renderable strings for `{...}` tokens and fail load if any token is unknown. CI's existing template-validation gate catches typos before they ship. There's no silent-fallback-to-literal — unknown token = template fails to load.

### Migration is a clean cutover, no auto-binding

`build_crew_assignments` migration creates the table; existing builds start with empty crew slots. Active expeditions during the cutover are unaffected — their `ExpeditionCrewAssignment` rows from Phase 2b stay valid and the in-flight engine continues to read from them. Players (in dev: just the developer) reassign crew via `/hangar` before launching the next expedition.

Auto-binding from active expeditions (e.g., "Mira is currently on a run aboard *Flagstaff*, so we'll persist her as *Flagstaff*'s pilot") was considered and rejected — it adds migration complexity for no gameplay benefit on a small dev game.

---

## Architecture

### Two parallel changes, one phase

```text
┌─────────────────────────────────────────────────────────────┐
│                    Phase 2c                                 │
├─────────────────────────────┬───────────────────────────────┤
│  Ship-crew binding          │  Narrative substitution       │
│  ─────────────────          │  ──────────────────           │
│  - new build_crew_assign... │  - new engine/narrative_      │
│    table + migration        │    render.py                  │
│  - HULL_CREW_SLOTS config   │  - validator extension        │
│  - /hangar view extension   │  - handler integration        │
│  - /expedition start sig    │  - opt-in template authoring  │
│    change                   │                               │
│  - launch handler refactor  │                               │
└─────────────────────────────┴───────────────────────────────┘
```

The two halves share one trans-system invariant — at scene-fire time the engine has the build and the aboard crew available — but otherwise touch different files. They can be implemented as two parallel task tracks within one PR, or split into two PRs if the ship-crew half lands first and narrative substitution follows. Recommendation: one PR, because the new module's tests benefit from end-to-end coverage that needs the binding work in place.

### Data flow at /expedition start (after 2c)

```text
Player → /expedition start template:X build:Y
                ↓
        Cog validates template + concurrency caps
                ↓
        SELECT FROM build_crew_assignments WHERE build_id=Y
        joined to crew_members
                ↓
        Partition into idle_aboard / busy_aboard
                ↓
        Validate: idle_aboard satisfies template.crew_required?
        ├── no  → return error walking ship slots ("show what's missing
        │         and what's available")
        └── yes → INSERT ExpeditionCrewAssignment rows for each idle
                  aboard member
                  UPDATE crew_members SET current_activity=ON_EXPEDITION,
                       current_activity_id=expedition.id
                  Schedule events (existing)
                  Return: "Expedition launched. ETA in 4h."
```

`build_crew_assignments` rows are unchanged by this flow — the persistent assignment doesn't move.

### Engine runtime: unchanged

The engine's existing `_assigned_archetypes(session, expedition_id)` already reads `ExpeditionCrewAssignment` rows for the expedition; `_filter_visible_choices` already filters scenes by archetype. Phase 2c doesn't touch either. The change is purely at the *boundary* — what fills `ExpeditionCrewAssignment` at launch time.

### Narrative render pipeline

```text
EXPEDITION_EVENT handler:
    1. Load expedition + scene (existing)
    2. Filter visible choices (existing)
    3. ───── new ─────
       Load build (for ship name + hull)
       Load aboard crew via ExpeditionCrewAssignment
       Build context dict: { pilot: <crew>, ship: <build>, ... }
       Pass scene's narration + each choice's text through render()
    4. Format notification body (with rendered text)
    5. Post to Redis stream
```

`engine/narrative_render.py` exposes one public function: `render(text: str, context: dict) -> str`. Internally it uses Python's `str.format_map` with a custom mapping subclass that:

- Returns the fallback value on missing top-level keys.
- Splits on `.` for property access (`pilot.callsign` → walks the context's `pilot` dict for `callsign`).
- Returns the slot's generic noun on missing nested attributes.

The same `render()` is called by `EXPEDITION_RESOLVE` for outcome narratives and by `EXPEDITION_COMPLETE` for closing bodies.

---

## Data model

### New table

```sql
CREATE TABLE build_crew_assignments (
    build_id      UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    crew_id       UUID NOT NULL REFERENCES crew_members(id) ON DELETE CASCADE,
    archetype     crewarchetype NOT NULL,
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (build_id, archetype),
    UNIQUE (crew_id)
);

CREATE INDEX ix_build_crew_assignments_crew ON build_crew_assignments(crew_id);
```

The `UNIQUE(crew_id)` constraint is the load-bearing invariant: a crew member is on at most one ship at a time. Race-safe at the DB level.

The PK `(build_id, archetype)` enforces one slot per archetype per ship. Not all archetypes are valid for every hull (e.g., SKIRMISHER has no engineer slot); the cog validates against `HULL_CREW_SLOTS` before INSERT, so the DB never holds a row for a slot the hull doesn't support.

`assigned_at` is a small UX nicety — the `/crew inspect` view can display "Pilot of *Flagstaff* (since 3 days ago)".

### Hull-class slot config (data, not DB)

Lives next to `HullClass` in `engine/class_engine.py` (or a new `engine/hull_config.py` if the file would grow unwieldy):

```python
HULL_CREW_SLOTS: dict[HullClass, list[CrewArchetype]] = {
    HullClass.SKIRMISHER: [CrewArchetype.PILOT, CrewArchetype.GUNNER],
    HullClass.HAULER:     [CrewArchetype.PILOT, CrewArchetype.ENGINEER, CrewArchetype.NAVIGATOR],
    HullClass.SCOUT:      [CrewArchetype.PILOT, CrewArchetype.NAVIGATOR],
}
```

A helper `slots_for_hull(hull: HullClass) -> list[CrewArchetype]` is the canonical accessor. Anywhere code asks "what slots does this build have?" goes through this function, not the dict directly.

### Existing tables, unchanged

- `Build` — no schema change. A new computed property/method `crew_slots()` returns `HULL_CREW_SLOTS[self.hull_class]`.
- `CrewMember` — no schema change. The existing `current_activity` and `current_activity_id` continue to drive "is this crew on an expedition / training / idle?". A new `assigned_build_id` could be added for fast lookup, but `build_crew_assignments` already serves that need; no need to denormalize.
- `Expedition` — no schema change.
- `ExpeditionCrewAssignment` — no schema change. Populated from `build_crew_assignments` at `/expedition start` instead of from slash params.

---

## Surfaces affected

### New code

- `db/migrations/versions/0006_phase2c_build_crew_assignments.py` — table + indexes
- `engine/narrative_render.py` — render function + custom mapping class
- `bot/cogs/hangar.py` — `HangarView` persistent view + crew-slot select handlers
- `bot/views/hangar_view.py` (or kept inline if it stays small) — view class definition

### Modified code

- `db/models.py` — add `BuildCrewAssignment` ORM model
- `engine/class_engine.py` (or new `hull_config.py`) — `HULL_CREW_SLOTS` constant + `slots_for_hull()` helper
- `bot/cogs/hangar.py` — `/hangar <build>` command extended to render embed with crew slots and attach `HangarView`
- `bot/cogs/expeditions.py` — `/expedition start` signature drops `pilot/gunner/engineer/navigator`; launch handler reads `build_crew_assignments` instead of slash params; error messages updated
- `engine/expedition_template.py` — validator extends to scan renderable strings for unknown `{...}` tokens
- `scheduler/jobs/expedition_event.py` — calls `narrative_render.render()` on scene narration + choice text before formatting body
- `scheduler/jobs/expedition_resolve.py` — calls `render()` on outcome narrative
- `scheduler/jobs/expedition_complete.py` — calls `render()` on closing body
- `bot/cogs/hiring.py` (or wherever `/crew inspect` lives) — extend embed with an "Aboard `<ship name>`" line when the crew member appears in `build_crew_assignments`
- `bot/main.py` — `setup_hook` registers the persistent `HangarView`

### Templates

The two existing templates (`marquee_run`, `outer_marker_patrol`) **don't need changes** to ship 2c — the existing narration is valid (no `{...}` tokens). A follow-on content pass can sprinkle tokens into the existing narrations once the rendering ships.

### Removed code

- The `pilot/gunner/engineer/navigator` slash params and their autocompletes from `/expedition start` (and the corresponding tests in `tests/test_cog_expedition_autocomplete.py`).

---

## Testing strategy

### Unit / handler

- `engine/narrative_render.py`:
  - All token forms render correctly with full context.
  - Missing top-level slot → generic noun fallback.
  - Missing nested attribute (e.g., `{pilot.callsign}` with no pilot) → generic noun fallback.
  - Literal braces escape via `{{` `}}`.
  - Property access on a present slot (`{pilot.callsign}` with pilot present) works.
  - Multiple tokens in one string render together.
  - Unknown top-level key (validator should have caught it, defense in depth) → generic fallback rather than crash.

- `engine/class_engine.py` (or `hull_config.py`):
  - `slots_for_hull` returns expected lists for each HullClass.
  - Unknown hull class → raises (shouldn't happen, but caught explicitly).

- Template validator:
  - Templates with only allow-listed tokens load cleanly.
  - Templates with unknown tokens fail load with a specific error pointing at the bad token.
  - Templates with malformed brace syntax (unmatched `{`) fail load.

- `BuildCrewAssignment` model:
  - `UNIQUE(crew_id)` constraint trips when the same crew is inserted for two builds.
  - PK `(build_id, archetype)` constraint trips when the same slot is inserted twice.

### Cog (assignment view)

- `/hangar <build>` renders an embed with crew slots populated from `build_crew_assignments`.
- Selecting a crew option from a slot's select menu inserts/updates the row and re-renders the view.
- Selecting `Unassign` deletes the row and re-renders.
- Crew already aboard another ship is not in the eligible options (filtered by the existing `UNIQUE(crew_id)` invariant).
- Ship currently on expedition: select menus disabled, embed shows "Aboard expedition (ETA …)".
- Crew in training appears in the select with a status hint, can be assigned, but doesn't count toward idle aboard.
- View custom_ids parse correctly across bot restarts (regression for the persistent-view contract).

### Cog (`/expedition start`)

- Launch with all slots filled and idle: succeeds, ExpeditionCrewAssignment populated.
- Launch with empty pilot slot but a busy gunner slot, template requires PILOT: fails with the slot-walking error.
- Launch with template requiring ENGINEER on a SKIRMISHER (which has no engineer slot): fails with a hull-mismatch-flavored error ("your *Flagstaff* (Skirmisher) has no engineer slot…").
- Launch with all slots assigned but one in training: idle aboard set excludes the trainee, `crew_required.min/archetypes_any` checked against the reduced set.
- Concurrency: simultaneous launches against the same build serialize via `with_for_update` (existing pattern); no `UNIQUE` violations.

### Integration

- Full lifecycle with rendered narration:
  - Assign crew via `/hangar`.
  - `/expedition start` with the new flow.
  - Mid-flight event fires → DM body has rendered tokens (no literal `{pilot}` text leaks through).
  - Click button → outcome narrative also rendered.
  - Expedition completes → closing body rendered.
- `assigned_until` and `current_activity` lifecycle: assigned → on expedition → back to idle, persistent assignment unchanged.
- Cross-ship reassignment: assign Mira to *Flagstaff*, try to assign her to *Wanderer*, get a clear error pointing at the existing assignment.

### Migration

- Forward migration on a copy of dev DB: table created, indexes created, existing builds remain valid (empty slots), existing active expeditions remain valid.
- Rollback: table dropped cleanly, no orphaned rows.

---

## Open questions deferred to follow-ons

These came up during brainstorming and are explicitly **not** in scope for 2c:

- **Conditional Jinja-style narration** (`{% if has_engineer %}{{ engineer.callsign }} suggests rerouting power...{% endif %}`). Sometimes useful for variant narration based on loadout. Deferred until we have an external author writing templates and feel the constraint of the current closed allow-list.
- **Stat-derived tokens** (`{pilot.combat}`, `{ship.power}`). Useful for narrative variety ("Sixgun's combat reflexes (87) are sharp tonight..."). Same deferral reason — wait until an author wants them.
- **Rolled-value references** (`{roll.success}`, `{roll.value}`). Would let outcome narratives reference how close the roll was. Same deferral.
- **Templates declaring eligible hulls explicitly** (`hull_class_eligible: [HAULER, SCOUT]`). Today this falls out naturally from `crew_required` × `HULL_CREW_SLOTS` (a SKIRMISHER without an engineer slot can't satisfy a template needing one). Add explicit hull gating only if a template ever needs it for non-crew reasons (e.g., "stealth mission, scouts only, regardless of crew").
- **Crew swapping between ships mid-expedition.** Phase 2c locks this — ship must be IDLE to mutate crew. Lifting that requires designing what "swap during a 4h run" even means.
- **Captain / co-pilot hierarchy.** A captain crew member might give XP boosts to the rest of the ship's crew. Out of scope for 2c.

---

## Forward-compat hooks

- A future hull class adds a row to `HULL_CREW_SLOTS` and a value to the `HullClass` enum (one migration). No table changes required.
- A future archetype adds a value to `crewarchetype` enum (one migration) and gets used in `HULL_CREW_SLOTS`. The narrative-render allow-list extends by one row.
- A future `Fleet` (multi-ship) construct doesn't need 2c changes — `build_crew_assignments` is per-build, fleets are above the ship layer.
