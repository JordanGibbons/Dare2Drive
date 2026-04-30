# Authoring Expedition Templates

> **If you are a Claude/LLM session helping a human author an expedition:** follow this loop:
>
> 1. Read this entire guide — including the **Narrative tokens** section at the bottom. Tokens like `{pilot.callsign}` and `{ship}` are what make the prose feel personal; use them.
> 2. Read 1–2 example templates from `data/expeditions/`.
> 3. Write the new YAML.
> 4. Run the CLI validator (see "Testing your template" below).
> 5. Fix any errors. Repeat until validator says `OK`.
>
> Templates that fail the validator do not merge — CI gates on `pytest tests/test_expedition_template_files.py`.

---

## What an expedition is

An expedition is a multi-hour, scheduled mission that runs in the background while the player does other things. Mid-flight, the bot DMs the player with an embed and 2–3 choice buttons; the player has a response window (default 30 minutes) to commit a choice. If they don't, the engine resolves with the scene's `default` choice. When the expedition ends, the bot DMs a closing narrative.

Loadout matters. The player picks a build (one ship) and 0–4 crew members (one per archetype slot: PILOT, GUNNER, ENGINEER, NAVIGATOR). Choices in your scenes can be **gated** by archetype (only show up if a PILOT is on board) and rolls can be **modified** by the assigned crew's stats. Hidden = harder to access; modified = roll outcomes shift in the player's favor with stronger crew.

Narration is **personal**. Any player-visible string can reference the aboard crew and ship by name with closed-vocabulary tokens — `{pilot.callsign}`, `{ship}`, `{gunner.first_name}`, `{ship.hull}`, etc. The bot substitutes them at render time. Empty slots fall back to a generic noun ("the pilot") so the prose stays coherent. Full token list and examples are in the **Narrative tokens** section at the bottom of this guide.

Stakes are real but bounded: in v1 there is no permadeath. Crew can be temporarily injured (a timestamp blocks them from other activities for a duration). Parts can take durability damage. Credits can be lost. Crew never permanently die; ships never blow up.

## Two template kinds

Pick one. Each YAML file declares its `kind`.

- **`scripted`** — fixed arc. You write opening → ordered scenes → closing. Every playthrough plays identically. Use this for cinematic, narrative-rich content.
- **`rolled`** — fixed opening + closing, middle pulled from a pool. You write 6–10 candidate events; the engine samples `event_count` of them per playthrough (deterministic given `expedition.id`, so retries are stable). Use this for utility / replayable runs.

**Discipline for rolled templates:** middle-pool events MUST be self-contained. Don't reference a specific predecessor event — your event might fire first, last, or alone. It's safe to set/check flags via `set_flag` / `has_flag`, but don't write events that only make sense after another specific event has fired.

## File location and naming

- One file per template at `data/expeditions/<id>.yaml`
- ID convention: `^[a-z][a-z0-9_]*$`
- Filename (without `.yaml`) MUST equal the `id` field in the file (validator enforces).

## Annotated example: scripted

```yaml
id: marquee_run                            # must match filename
kind: scripted
duration_minutes: 360                      # 60..1440 — total wall time of the expedition
response_window_minutes: 30                # how long the player has to click a choice button
cost_credits: 250                          # what /expedition start charges. 0 is fine.
crew_required:
  min: 2                                   # at least N crew assigned overall
  archetypes_any: [PILOT, GUNNER]          # at least one of these archetypes must be present
scenes:
  - id: opening                            # narration-only, no choices, just sets the scene
    narration: |
      Multi-line prose works with the `|` block scalar. Use second-person
      present tense, gritty noir voice. 60–150 words for opening/closing,
      30–80 for choice text and outcome narratives. Reference the crew by
      callsign — `{pilot.callsign}` settles into the helm of `{ship}` —
      and the prose feels written for this player, not a stranger.

  - id: distress_beacon                    # a scene with choices
    narration: |
      A civilian beacon flares two hours into the run. {navigator.callsign}
      flags it on the nav console; the merchant's hull is cracked.
    choices:
      - id: investigate
        text: "{pilot.callsign}, decelerate and bring them aboard."
        roll:                              # optional: gives this choice a stat-modified probability roll
          stat: navigator.luck             # one of the published stat namespace keys (see table below)
          base_p: 0.55                     # base probability of success (0..1)
          base_stat: 50                    # stat value at which p == base_p
          per_point: 0.005                 # +0.5pp for each stat point above base_stat
        outcomes:
          success:
            narrative: "{pilot.callsign} matches velocities clean. The merchant captain promises a favor in lieu of payment."
            effects:
              - reward_credits: 150
              - reward_xp: { archetype: NAVIGATOR, amount: 40 }
              - set_flag: { name: rescued_merchant }   # readable later by `has_flag` in closings
          failure:
            narrative: "The maneuver costs {ship} fuel and momentum. You get them aboard, but the gratitude doesn't pay rent."
            effects:
              - damage_part: { slot: drive, amount: 0.10 }
      - id: ignore
        text: "Mark the beacon and keep moving."
        default: true                      # exactly one choice per scene must be marked default
                                           # — the default fires on auto-resolve and must be ungated
        outcomes:                          # no `roll` → outcomes uses `result` (deterministic)
          result:
            narrative: "{pilot.callsign} logs the position for someone else's conscience and slides past."
            effects:
              - reward_xp: { archetype: PILOT, amount: 20 }

  - id: closing                            # mark the closing scene
    is_closing: true
    closings:                              # closing variants — first match wins
      - when: { has_flag: rescued_merchant, min_successes: 2 }
        body: "{pilot.callsign} brings the {ship} home with the merchant's signature on a future favor."
        effects:
          - reward_credits: 500
      - when: { default: true }            # exactly one closing must be `default: true`
        body: "{ship} makes port. Just barely. Tomorrow's another contract."
        effects:
          - reward_credits: 100
```

## Annotated example: rolled

```yaml
id: outer_marker_patrol
kind: rolled
duration_minutes: 240
response_window_minutes: 30
cost_credits: 100
event_count: 2                             # engine samples this many events from the pool
crew_required: { min: 1, archetypes_any: [PILOT, GUNNER] }
opening:
  id: opening
  narration: "..."

events:                                    # pool — len(events) MUST be >= event_count
  - id: drifting_wreck
    narration: "..."
    choices:
      - id: salvage
        text: "Match velocities and crack it open."
        roll: { stat: engineer.repair, base_p: 0.50, base_stat: 50, per_point: 0.005 }
        outcomes:
          success: { narrative: "...", effects: [...] }
          failure: { narrative: "...", effects: [...] }
      - id: leave_it
        text: "Mark the position and move on."
        default: true
        outcomes:
          result: { narrative: "...", effects: [...] }

  - id: distress_call
    # ...another self-contained event...

closings:
  - when: { min_successes: 2 }
    body: "..."
    effects: [...]
  - when: { default: true }                # mandatory
    body: "..."
    effects: [...]
```

## Stat namespace reference

Use these keys in `roll.stat` and `requires.stat`. The validator rejects unknown keys at CI time.

A choice whose `roll.stat` references a per-archetype key (e.g., `pilot.acceleration`) is **automatically hidden** when the player hasn't assigned that archetype — no separate `requires` clause needed. Crew/ship namespaces are always available.

<!-- BEGIN: STAT_NAMESPACE_TABLE -->
| Key | Implicit archetype gate | Source |
|---|---|---|
| `crew.avg_level` | — | aggregate across all assigned crew |
| `crew.count` | — | aggregate across all assigned crew |
| `engineer.luck` | ENGINEER | the assigned ENGINEER crew member's stats |
| `engineer.repair` | ENGINEER | the assigned ENGINEER crew member's stats |
| `gunner.combat` | GUNNER | the assigned GUNNER crew member's stats |
| `gunner.luck` | GUNNER | the assigned GUNNER crew member's stats |
| `navigator.luck` | NAVIGATOR | the assigned NAVIGATOR crew member's stats |
| `navigator.perception` | NAVIGATOR | the assigned NAVIGATOR crew member's stats |
| `pilot.acceleration` | PILOT | the assigned PILOT crew member's stats |
| `pilot.handling` | PILOT | the assigned PILOT crew member's stats |
| `pilot.luck` | PILOT | the assigned PILOT crew member's stats |
| `ship.acceleration` | — | resolved live from the locked build (engine/stat_resolver) |
| `ship.durability` | — | resolved live from the locked build (engine/stat_resolver) |
| `ship.power` | — | resolved live from the locked build (engine/stat_resolver) |
| `ship.weather_performance` | — | resolved live from the locked build (engine/stat_resolver) |
<!-- END: STAT_NAMESPACE_TABLE -->

## Outcome effect vocabulary

These are the closed-vocabulary operations an `outcome.effects` list may contain. Each effect is a dict with exactly one key (the op name).

<!-- BEGIN: EFFECT_VOCABULARY_TABLE -->
| Op | Required params | Summary |
|---|---|---|
| `damage_part` | `slot`, `amount` | Reduces durability on the equipped card in the given slot by `amount` (0..1, fractional). |
| `injure_crew` | `archetype`, `duration_hours` | Sets the assigned crew's `injured_until` to now + duration_hours. No-op if no crew of that archetype is assigned. |
| `reward_card` | `slot`, `rarity` | Mints a card of the given slot + rarity for the player. |
| `reward_credits` | (int value) | Adds (or subtracts, if negative) credits to the player. |
| `reward_wreck` | `hull_class`, `quality` | Generates a wreck row of the named hull_class + quality. |
| `reward_xp` | `archetype`, `amount` | Grants XP to the assigned crew of the named archetype. No-op if no crew of that archetype is assigned. |
| `set_flag` | `name` | Records a named flag in the expedition's accumulated state. Readable by `when` clauses on later scenes / closings. |
<!-- END: EFFECT_VOCABULARY_TABLE -->

## Authoring conventions

- **Voice:** Second-person present tense. Gritty noir. The player is the captain — the bot narrates what they see, the crew acts. e.g., "Mira pins the throttle. The skiff falls behind."
- **Length:** 60–150 words for opening + closing scenes. 30–80 words for choice text + outcome narrative. Discord DMs render embeds — long prose feels heavy on mobile.
- **Determinism:** the engine seeds RNG with `(expedition_id, scene_id)`, so a retry of a scene rolls the same value. Don't write outcomes that imply randomness beyond the engine roll.
- **Flag hygiene:** every `has_flag` / `not_flag` reference must match a `set_flag` somewhere in the same template. The validator catches typos.
- **Default choice rules:** every scene with choices must have exactly ONE choice marked `default: true`. The default must NOT have a `requires` clause (so it's always available as the auto-resolve fallback). Validator enforces.
- **Default closing rule:** every template must have exactly ONE closing with `when: { default: true }`. Validator enforces.

## Testing your template

```bash
python -m engine.expedition_template validate data/expeditions/<your_template>.yaml
```

Errors print with the file path and the specific invariant violated.

## Submitting

1. Run the validator locally — it must say `OK`.
2. Commit your YAML in a feature branch.
3. Open a PR. CI runs `pytest tests/test_expedition_template_files.py` — your template must pass.
4. The spec owner reviews the narrative content (tone, length, balance). Schema correctness is already CI-verified.

## Updating the engine registries

If you're adding a new stat to `engine/stat_namespace.py` or a new effect op to `engine/effect_registry.py`, you must regenerate this guide:

```bash
python -m scripts.build_authoring_docs
```

Then commit the regenerated `docs/authoring/expeditions.md` as part of the same PR. CI gate `tests/test_authoring_docs_drift.py` fails otherwise.

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
