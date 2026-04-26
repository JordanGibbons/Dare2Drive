# Phase 2b — Expeditions

**Status:** Approved 2026-04-26
**Phase:** 2b of 6+ (see [salvage-pulp revamp roadmap](../../roadmap/2026-04-22-salvage-pulp-revamp.md))
**Owner:** Jordan
**Depends on:** [Phase 2a scheduler foundation](2026-04-25-phase-2a-scheduler-foundation-design.md) (shipped)

---

## Context

Phase 2a shipped the durable scheduler-worker, three timer types (Training, Research, ShipBuild), Station accrual, and the worker→bot Redis-stream notification pipeline. Players now have fire-and-resolve background activities — the bot does work while they're away, then DMs them when it's done.

Phase 2b is **the first time the bot tells a story while you're away from the keyboard**. It builds on the Phase 2a scheduler to deliver multi-hour *expeditions*: scheduled missions with mid-flight events that interrupt the player for a choice, with auto-resolution if they don't respond in time. Loadout (which crew, which ship) materially influences what choices appear and how rolls land. Outcomes can carry real consequences — credit losses, part-durability damage, temporary crew injury — within an "asymmetric risk, no permadeath" envelope.

A second goal of this phase is **content-authorability by external developers and LLM sessions**. Expeditions are the first system in this codebase whose value scales with the volume of authored content (more templates = more replayability), not with engineering hours. The authoring format, schema, and validator are first-class deliverables, sized for someone (human or Claude) to read the authoring guide and produce a valid template without reading engine code.

A small **adjacent UX update** lands in this phase: `/crew` and `/crew_inspect` are refreshed to surface the new crew states (`ON_EXPEDITION`, `INJURED`) and the broader "what is this crew member good for?" question that the expanded activity surface raises. Full tutorial overhaul (covering crew + Phase 2a + Phase 2b for new players) is **out of scope** and tracked as Phase 2c, blocking Phase 3.

---

## Locked decisions

These were settled during brainstorming. Re-litigation belongs in a follow-on spec.

### Player-facing vision: hybrid engine, two template kinds

The engine supports two distinct template formats, sharing the same Scene/Choice/Outcome primitives. Authors pick the kind that fits the content:

- **`scripted`** — fixed, hand-authored arc (opening → ordered events → closing). Every playthrough plays identically. For marquee/cinematic content where the author wants tight narrative control. Replayability comes from authoring more templates.
- **`rolled`** — fixed opening + closing, middle pulled from a pool. Engine samples N events from the pool per playthrough (deterministic given `expedition.id`, so retries are stable). Each playthrough varies. For utility/replayable runs.

Authoring discipline for `rolled` templates: middle-pool events MUST be self-contained — coherent in any combination/order. The authoring guide enforces this convention; the validator does not (impractical to check statically), so it lives in the human review.

**v1 ships with two templates as authoring exemplars:** one scripted (the marquee narrative) and one rolled (a generic patrol run with an 8-event middle pool).

### Delivery and response: DM with buttons + slash command fallback

When a mid-flight event triggers, the bot **DMs** the player with an embed and 2–3 choice buttons. Symmetric with Phase 2a's DM pattern. Click commits.

A **slash command fallback** `/expedition respond` is mandatory because (a) Discord buttons can go stale (default 15-min view inactivity timeout) and (b) DMs may be muted, closed, or buried under others. Both paths reach the same cog method and trigger the same `EXPEDITION_RESOLVE` job. Buttons are ergonomic sugar; the slash command is the durable contract.

Public outcome posts to the `/system` channel (the "Cmdr X just got back from the Vega Run with 3 wrecks and one fewer crew member than they left with" multiplayer-spectacle UX) are **out of v1**. Phase 3's channel-events feature is the right place for that pattern.

### Stakes: asymmetric risk, no permadeath in v1

Most outcomes are positive, but bad rolls or wrong choices can produce real losses:

- Crew **injury** (temporary `injured_until` block; cog assignment refuses while `injured_until > now()`; default duration ~24h, set per-outcome by the author).
- Part **durability damage** (e.g., 15% durability hit on a slot).
- Credit **fines** or **lost rewards** (an outcome can apply a negative `reward_credits`).

Crew **never permanently die in v1**. Ships **never blow up** in v1 (no hull loss). Permadeath is a Phase 3+ design decision once the supporting UX (memorial system, insurance/recovery) and Phase 3 villain-event pacing exist.

### Resolution model: archetype gates + stat-modified rolls

Each `choice` in a scene can declare:

- `requires:` — optional gate on archetype, min crew level, ship hull_class, or other constraints. **Choices that fail their requires are hidden** from the DM (and from the slash-command picker). Loadout shapes which choices exist.
- `roll:` — optional `{stat, base_p, base_stat, per_point}`. Engine reads the stat (via the published namespace), computes `p = base_p + (stat - base_stat) * per_point`, clamps to `[0.05, 0.95]`, rolls a uniform `random()`. Authors can override the clamp range per choice.
- `outcomes:` — `{success: ..., failure: ...}` for rolled choices, or `{result: ...}` for deterministic ones.

Choices without `roll` resolve deterministically — useful for "safe" or always-succeeds branches.

### Concurrency, lockup, and the move away from "active build"

- **Per-user cap:** at most `get_max_expeditions(user)` concurrent active expeditions. Default returns 2 (from a config setting). The function form means a future raise (player level, premium tier, etc.) is a one-line change with no schema migration.
- **Per-build cap:** at most one active expedition per build. Enforced by checking for an `ACTIVE` expedition with the same `build_id` at `/expedition start`, plus the `Build.current_activity = ON_EXPEDITION` lock.
- **Build is locked while on expedition.** `/equip`, future `/build delete`, and any other build-mutating cog refuses with a clear "this ship is on expedition, returns at `<eta>`" message. Crew is locked too (`current_activity = ON_EXPEDITION`).
- **No stat snapshotting.** Live stat reads at event resolution are equivalent to launch-time snapshots because the build/crew can't change while locked. One less column.
- **`/expedition start` takes an explicit `build` arg.** It does not read or rely on any "active build" / default-build concept. This is part of the broader move away from the active-ship pattern; the existing `/build set-default` is left in place for now (its full deprecation is tracked as a separate cleanup, not part of this phase).

### Forward-compat: fleets

V1 expeditions are single-ship. The `Expedition.build_id` column is the future fleet hook. A future `Fleet` table with a `BuildFleet` join table extends by adding a nullable `fleet_id` to `Expedition`; existing single-ship rows stay valid (`fleet_id = NULL`). No data migration needed.

### Cancellation: not in v1

There is no `/expedition cancel`. Once launched, expeditions run to completion. This matches the "real stakes" tone (you can't bail out of a tough run halfway through) and avoids the rules question of "what counts as a cancellation refund when half the events have resolved." `/admin force_complete_expedition` exists as the escape hatch for stuck expeditions; players can't invoke it.

---

## Architecture

The architecture mirrors Phase 2a's symmetric writer/reader split:

- **Cogs** (in the bot process) write `Expedition` rows + assignment rows + initial `ScheduledJob` rows in one atomic transaction at `/expedition start`. They never touch `ScheduledJob.state` after the initial insert (except the atomic `PENDING → CANCELLED` flip on response, which is the same primitive Phase 2a's `/training cancel` uses).
- **Scheduler-worker** runs handlers for `EXPEDITION_EVENT`, `EXPEDITION_AUTO_RESOLVE`, `EXPEDITION_RESOLVE`, `EXPEDITION_COMPLETE`. Each handler is its own transaction, idempotent on retry via `reward_ledger`'s `(source_type, source_id)` unique constraint.
- **Bot's notification consumer** (existing Phase 2a infrastructure) delivers DMs from the Redis stream. The button view registered at bot startup as a **persistent view** survives restarts.

Both processes share Postgres + Redis. Neither speaks to the other directly. The Phase 2a chaos-test guarantee (kill the worker mid-job, jobs resume on restart, no double-fire) carries forward unchanged because the JobType + handler + idempotency model is reused.

### Job lifecycle

```text
/expedition start (cog tx)
  ├── INSERT expeditions row (state = ACTIVE)
  ├── INSERT N expedition_crew_assignments
  ├── UPDATE builds.current_activity = ON_EXPEDITION
  ├── UPDATE crew_members.current_activity = ON_EXPEDITION (×N)
  └── INSERT ScheduledJob rows:
       - 1× EXPEDITION_EVENT per scheduled scene (scripted: per scene; rolled: event_count scenes from pool)
       - 1× EXPEDITION_COMPLETE at T + duration

EXPEDITION_EVENT fires (worker tx)
  ├── Build embed + buttons
  ├── INSERT ScheduledJob row: EXPEDITION_AUTO_RESOLVE at now + response_window
  ├── UPDATE expedition.scene_log (append "pending" entry)
  └── return NotificationRequest → Redis stream → bot DM

(player path)                         (timeout path)
button click / /expedition respond    EXPEDITION_AUTO_RESOLVE fires
  └── atomic UPDATE auto_resolve         └── if state = PENDING:
        WHERE state = PENDING                 enqueue EXPEDITION_RESOLVE
        SET state = CANCELLED                 (using scene.default_choice)
      if rowcount > 0:
        enqueue EXPEDITION_RESOLVE
        (using picked choice)

EXPEDITION_RESOLVE fires (worker tx)
  ├── Look up scene + choice
  ├── If choice.roll: read stat, compute p, roll
  ├── Apply outcome.effects (atomic, idempotent on reward_ledger)
  ├── UPDATE expedition.scene_log (resolve "pending" entry)
  └── return NotificationRequest → Redis stream → bot DM (resolution narrative)

EXPEDITION_COMPLETE fires (worker tx)
  ├── Resolve closing variant via when-clause matching
  ├── Apply closing outcome.effects
  ├── UPDATE expedition.state = COMPLETED, outcome_summary = {...}
  ├── UPDATE builds.current_activity = IDLE
  ├── UPDATE crew_members.current_activity = IDLE (×N) — but injury status preserved
  └── return NotificationRequest → Redis stream → bot DM (closing narrative + reward summary)
```

Atomic `PENDING → CANCELLED` UPDATE with `WHERE state = PENDING` is the concurrency primitive. Exactly one of (button-click cog, auto-resolve worker) wins. Reused verbatim from Phase 2a's `/training cancel`.

---

## Data model

### New table: `expeditions`

| col | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | varchar FK → `users.discord_id` | |
| `build_id` | UUID FK → `builds.id` | NOT NULL — single-ship in v1; future `fleet_id` column extends |
| `template_id` | varchar | matches `data/expeditions/<id>.yaml` filename, validator-enforced |
| `state` | enum `ExpeditionState` | `ACTIVE`, `COMPLETED`, `FAILED`. No `CANCELLED` in v1. |
| `started_at` | timestamptz | |
| `completes_at` | timestamptz | denormalized from `started_at + template.duration_minutes` for `/expedition status` queries |
| `correlation_id` | UUID | propagated through scheduler jobs + notifications + logs for tracing |
| `scene_log` | JSONB | append-only log: `[{scene_id, fired_at, status, resolved_at?, choice_id?, roll?, outcome?, narrative?}, ...]`. `/expedition status` reads this directly. |
| `outcome_summary` | JSONB nullable | populated at COMPLETE: `{narrative, rewards: {credits, xp, wrecks, cards}, losses: {durability, injuries}}` |
| `created_at` | timestamptz default now() | |

Indexes:
- `(user_id, state)` for "list my active expeditions"
- `(build_id)` partial unique `WHERE state = ACTIVE` — DB-level enforcement of one-active-per-build
- `(completes_at)` for due-job queries (defensive; the scheduler queries by `scheduled_jobs.scheduled_for` not this column)

### New table: `expedition_crew_assignments`

| col | type | notes |
|---|---|---|
| `expedition_id` | UUID FK → `expeditions.id` ON DELETE CASCADE | |
| `crew_id` | UUID FK → `crew_members.id` | |
| `archetype` | enum `CrewArchetype` | denormalized from crew, validated == `crew.archetype` at insert |

Constraints:
- Unique `(expedition_id, archetype)` — one crew per archetype slot per expedition

The "no crew on two active expeditions" invariant is enforced **two layers up**, not at the DB:

1. **Cog validation** at `/expedition start` checks `crew.current_activity == IDLE`.
2. **`crew_members.current_activity = ON_EXPEDITION`** is set inside the same transaction that inserts the assignment row. Since each crew has one `current_activity`, they can be on at most one expedition at a time.

(Postgres partial-unique indexes can't reference columns on other tables, so a `WHERE expedition.state = ACTIVE` clause on this join table is not actually enforceable without denormalizing `state` into `expedition_crew_assignments` and keeping it in sync. Not worth the synchronization complexity for the same guarantee the `current_activity` lock already provides.)

### Schema additions to existing tables

**`builds`:**
- `current_activity` new enum `BuildActivity` (`IDLE`, `ON_EXPEDITION`), default `IDLE`. Mirrors crew pattern. Future activity types just add enum values.
- `current_activity_id` UUID nullable. Set to `expedition.id` when `ON_EXPEDITION`. Not a DB foreign key (so future activity types don't pollute the schema).

**`crew_members`:**
- `injured_until` timestamptz nullable. Set by `injure_crew` outcome op. Cog assignment paths (`/training start`, `/stations assign`, `/expedition start`) refuse if `injured_until > now()`. Recovery is implicit — once `now() > injured_until`, the crew is assignable again. No background sweeper.

**`CrewActivity` enum:**
- New value: `ON_EXPEDITION`. Assigned at `/expedition start`, cleared at `EXPEDITION_COMPLETE`. (Injury does NOT use a `CrewActivity` value — `injured_until` is the truth; activity stays at the value set by whatever locked them last, typically `IDLE`.)

**`JobType` enum:**
- New values: `EXPEDITION_EVENT`, `EXPEDITION_AUTO_RESOLVE`, `EXPEDITION_RESOLVE`, `EXPEDITION_COMPLETE`.

**`RewardSourceType` enum:**
- New value: `EXPEDITION_OUTCOME`. `source_id` format: `"expedition:{expedition_id}:{scene_id}"` for events, `"expedition:{expedition_id}:closing"` for closings. The `(source_type, source_id)` unique constraint guarantees idempotency on retry.

### Migration

Single Alembic migration, all additive:

1. Create `expedition_state` and `build_activity` enums.
2. Create `expeditions` and `expedition_crew_assignments` tables with the indexes above.
3. Add `builds.current_activity` (default `IDLE`) and `builds.current_activity_id` (nullable).
4. Add `crew_members.injured_until` (nullable).
5. `ALTER TYPE crew_activity ADD VALUE 'ON_EXPEDITION'`.
6. `ALTER TYPE job_type ADD VALUE 'EXPEDITION_EVENT'`, etc. (×4).
7. `ALTER TYPE reward_source_type ADD VALUE 'EXPEDITION_OUTCOME'`.

No backfill. No data conversion. Rollout: dev → smoke test → demo → 24h dashboard watch.

---

## Engine

`engine/expedition_engine.py` is the core resolver. The interface is intentionally narrow:

```python
class Outcome(TypedDict):
    narrative: str
    effects: list[Effect]                # closed-vocabulary ops, see below

class SceneResolution(TypedDict):
    scene_id: str
    choice_id: str | None                # None if narration-only
    roll: dict | None                    # {stat, value, p, rolled} if rolled, None otherwise
    outcome: Outcome
    auto_resolved: bool                  # True if no player input

async def resolve_scene(
    session: AsyncSession,
    expedition: Expedition,
    scene: Scene,
    picked_choice_id: str | None,        # None → use scene.default_choice
) -> SceneResolution: ...
```

### Pseudocode

```python
async def resolve_scene(session, expedition, scene, picked_choice_id):
    if scene.is_narration_only:
        outcome = scene.outcome
        # No choice, no roll. Apply effects, return.

    choice = scene.find_choice(picked_choice_id) or scene.default_choice
    auto_resolved = picked_choice_id is None

    # Filter: hidden choices can't be picked even via /expedition respond
    # (validator already ensures default has no requires, so default is always available)
    if choice.requires and not _check_requires(expedition, choice.requires):
        choice = scene.default_choice  # fallback if player picked a now-hidden choice

    if choice.roll:
        stat_value = await _read_stat(session, expedition, choice.roll.stat)
        p = choice.roll.base_p + (stat_value - choice.roll.base_stat) * choice.roll.per_point
        p = clamp(p, choice.roll.clamp_min or 0.05, choice.roll.clamp_max or 0.95)
        rolled = _seeded_random(expedition.id, scene.id)  # PRNG seeded for retry stability
        success = rolled < p
        outcome = choice.outcomes['success' if success else 'failure']
        roll_info = {'stat': choice.roll.stat, 'value': stat_value, 'p': p, 'rolled': rolled}
    else:
        outcome = choice.outcomes['result']
        roll_info = None

    await _apply_outcome(session, expedition, scene.id, outcome)
    return SceneResolution(...)
```

The `_seeded_random(expedition_id, scene_id)` produces a deterministic float — a retried `EXPEDITION_RESOLVE` job (e.g., after a crash) computes the same roll, gets the same outcome, and the `reward_ledger` unique constraint short-circuits the duplicate write.

### Stat namespace

Authors reference stats via dotted keys. The full list is published in the authoring guide and auto-regenerated from this registry — see [§Authoring](#authoring-format--validator). Initial set:

| key | source |
|---|---|
| `pilot.<stat>` | the assigned PILOT crew member's stats |
| `gunner.<stat>` | the assigned GUNNER's stats |
| `engineer.<stat>` | the assigned ENGINEER's stats |
| `navigator.<stat>` | the assigned NAVIGATOR's stats |
| `ship.<stat>` | resolved live via `engine/stat_resolver.py` from the (locked) build |
| `crew.avg_level` | mean level across all assigned crew |
| `crew.count` | total assigned crew |

If a choice's `roll.stat` references a namespace the player doesn't have crew for (e.g., `pilot.acceleration` with no PILOT assigned), the choice is **hidden** — the same effect as a `requires` clause failing. This means authors don't need to write `requires: { archetype: PILOT }` on top of `roll: { stat: pilot.acceleration }`; the namespace dependency is implicit. Validator emits a warning (not error) on choices that have a redundant `requires` matching their `roll.stat`'s implicit gate.

### Outcome effect vocabulary

Closed list. Validator rejects unknown ops at CI time:

| op | shape | semantics |
|---|---|---|
| `reward_credits` | `int` (positive credits, negative fines) | applied via `apply_reward(RewardSourceType.EXPEDITION_OUTCOME, ...)` |
| `reward_wreck` | `{hull_class, quality}` | inserts a `Wreck` row; quality affects salvage value |
| `reward_card` | `{slot, rarity}` | mints a card (existing `engine/card_mint` path) |
| `reward_xp` | `{archetype, amount}` | XP to the assigned crew of that archetype; no-op if none assigned |
| `injure_crew` | `{archetype, duration_hours}` | sets `crew.injured_until = now() + duration_hours` |
| `damage_part` | `{slot, amount}` | reduces durability on the equipped card in that slot by `amount` (0..1) |
| `set_flag` | `{name}` | adds the flag name to the expedition's accumulated state, readable by `when` clauses in later scenes / closings |

All effects within an outcome apply atomically inside the resolver's transaction. Idempotency is via `reward_ledger`'s `(source_type, source_id)` unique constraint — a retried job hits the constraint and short-circuits with no double-write.

### Closing variants

Both kinds of templates have a closing scene with multiple variants selected by accumulated state:

```yaml
closings:
  - when: { min_successes: 2, has_flag: rescued_smuggler }
    body: "..."
    effects: [...]
  - when: { min_successes: 1 }
    body: "..."
    effects: [...]
  - when: { default: true }       # mandatory
    body: "..."
    effects: [...]
```

Supported `when` keys (closed grammar, validator-enforced):

- `min_successes: int`
- `max_failures: int`
- `has_flag: str`
- `not_flag: str`
- `default: true` — always matches; mandatory exactly one per template.

First match in declaration order wins. `default: true` is the fallback.

### Event scheduling — fixed at launch

When `/expedition start` fires:

1. The cog determines `event_count` from the template (scripted: `len(scenes_with_choices)`; rolled: `template.event_count`).
2. For rolled templates, samples `event_count` events from the pool deterministically (PRNG seeded with `expedition.id`).
3. Computes scheduled times — events evenly spaced within `template.duration_minutes` with small jitter (±10% of inter-event spacing) to avoid all expeditions on the same template firing at exactly synchronized times.
4. Queues all `ScheduledJob` rows in one transaction with the expedition row.

**Adaptive scheduling** (events fire faster if the player responds quickly) is **out of v1**. Fixed schedule preserves the "launch and forget" UX.

---

## Cog UX

`bot/cogs/expeditions.py` registers an `expedition` `app_commands.Group` with three sub-commands.

### `/expedition start`

```text
/expedition start
  template: <picker>           # autocomplete from data/expeditions/*.yaml
  build: <picker>              # autocomplete from user's IDLE builds
  pilot: <crew_picker?>        # optional; autocomplete filters PILOT, IDLE, not injured
  gunner: <crew_picker?>       # optional
  engineer: <crew_picker?>     # optional
  navigator: <crew_picker?>    # optional
```

**Validation order** (each step ephemerally tells the player what's wrong):

1. Template exists.
2. User has fewer than `get_max_expeditions(user)` active expeditions.
3. User has enough credits for `template.cost_credits` (per-template, free is allowed).
4. Build exists, owned by user, `current_activity == IDLE`.
5. Each picked crew owned by user, `current_activity == IDLE`, `injured_until` not in the future.
6. Crew satisfies template's `crew_required` minimums (e.g., `min: 1, archetypes_any: [PILOT, GUNNER]`).

Pass → atomic transaction creates the Expedition row, the crew assignment rows, queues the EVENT + COMPLETE jobs, locks build/crew. Player gets an ephemeral confirmation with ETA.

### `/expedition status`

No-arg form lists all active expeditions for the user with ETAs:

```text
**Active expeditions** (2 / 2 slots used)
• Outer Marker Patrol — Flagstaff — ETA 14:32 (~2h)
• Vega Run — Spinward — ETA 18:00 (~5h, 1 event pending response now)
```

Per-expedition form (when `expedition` arg is provided) renders the timeline from `expedition.scene_log`:

```text
**Outer Marker Patrol** — Flagstaff
ETA: 14:32 (in ~2h)
Crew: Mira (PILOT), Jax (GUNNER)

**Timeline**
✓ T+2h00m — Distress beacon → Investigate → success → +1 wreck, +30 PILOT XP
✓ T+4h00m — Pirate skiff → Outrun → success → +200cr, +50 PILOT XP
○ T+6h00m — Return to dock (closing scene)
```

### `/expedition respond`

```text
/expedition respond
  expedition: <picker>       # autocomplete: user's expeditions with a pending scene
  choice: <picker>           # autocomplete: visible choices for the current pending scene
```

Same handler as button clicks. Validation: expedition is active, has a pending scene, the picked choice is visible (passes `requires`).

### Persistent button view

Discord buttons go stale on bot restart unless registered as **persistent views** (`bot.add_view(view, message_id=X)`). The cog registers a single global `ExpeditionResponseView` in `setup_hook`. Buttons use stable `custom_id`s:

```python
custom_id = f"expedition:{expedition_id}:{scene_id}:{choice_id}"
```

The view's interaction handler parses the `custom_id` and routes to the same response method `/expedition respond` calls. One handler, two entry points.

The DM message ID is persisted in the `expedition.scene_log` pending entry so the consumer can re-attach the view if needed after restart.

### Tutorial gating

All three commands are gated behind `TutorialStep.COMPLETE` — they are NOT added to any step's `STEP_ALLOWED_COMMANDS`, so they're blocked until tutorial completion. Admin escape hatch (`/admin force_complete_expedition`) is added to `ALWAYS_ALLOWED`.

This phase does not introduce a new tutorial step. Players unlock expeditions when they complete the existing tutorial. A "your first expedition" tutorial beat is part of the Phase 2c tutorial overhaul.

### Edge cases

- **DMs closed:** the existing Phase 2a notification consumer XACKs and increments the `dm_closed` metric. The player sees their pending event on `/expedition status` and uses `/expedition respond`.
- **Player blocks the bot:** same path — slash commands still work.
- **Build deletion attempted while `ON_EXPEDITION`:** any future `/build delete` (and `/build set-default`, `/equip`) refuses with a clear "this ship is on expedition" message. Unit-tested.
- **Crew on two expeditions:** prevented at two layers within the same transaction — cog validation (`crew.current_activity == IDLE` precondition) and application-level lock (`crew.current_activity = ON_EXPEDITION` set in the same tx that inserts the assignment row). See data-model section for why DB-level enforcement isn't added.
- **Scheduled event fires for a COMPLETED/FAILED expedition** (e.g., admin-completed early): handler is idempotent, marks job COMPLETED, no-ops.

---

## Adjacent UX updates

### Crew display refresh

Existing commands updated to surface the new states.

`/crew` (roster) gains an activity column:

```text
**Your Crew**  (4 / 8)

 🟢 IDLE    Mira "Sixgun" Voss      PILOT     Lvl 4
 🚀 ON_EXP  Jax "Blackjack" Krell   GUNNER    Lvl 3   (Outer Marker Patrol — back ~2h)
 🩹 INJURED Cee "Crow" Are          NAVIGATOR Lvl 2   (recovers in ~14h)
 ⚙️  TRAIN   Rook "Tinker" Salim     ENGINEER  Lvl 1   (Combat Drills — done in ~18m)
```

`/crew_inspect` gains a status block and a "Qualified for" hint section:

```text
**Mira "Sixgun" Voss**  —  PILOT  —  Level 4
[stats block, unchanged]

**Status:** 🟢 Idle and available

**Qualified for** (derived from archetype + level):
  • Training: Specialty Course (level ≥ 3 ✓)
  • Expeditions: any with PILOT slot
  • Stations: cargo_run, watch_tower
```

The "Qualified for" derivation is a pure function of `(archetype, level, current_state)`. It reads from the existing recipe registries (`engine/timer_recipes`) and the new expedition template registry. No new persisted data.

### Roadmap update

The spec PR also updates `docs/roadmap/2026-04-22-salvage-pulp-revamp.md` to insert **Phase 2c — Tutorial v2** between Phase 2b and Phase 3, with a brief outline:

- 5+ new tutorial steps for crew, training, research, expeditions
- The time-gating design problem (training is 30+ min — onboarding wants engagement in the first 5 min)
- New `/skip_tutorial` UX considerations (multi-day tutorial vs instant flip)
- Tutorial-cohort metrics (funnel decay points across long-running steps)

Phase 3 is now blocked on Phase 2c.

---

## Authoring format + validator

### File format

**One YAML file per template** at `data/expeditions/<id>.yaml`. ID convention: `[a-z][a-z0-9_]*`, must equal the filename without extension (validator enforces both).

YAML over JSON because narrative text reads naturally with `|` block scalars; YAML over Markdown-with-frontmatter because the structure is deep enough that a single parser is cleaner than two.

### Schema

`data/expeditions/schema.json` is a JSON Schema with a discriminated `oneOf` on `kind`:

- **`kind: scripted`** — requires `scenes` array, ordered, including a closing scene as the last entry.
- **`kind: rolled`** — requires `opening` (single scene), `events` (pool, length ≥ `event_count`), `event_count` (int), `closings` (variant array).

Both kinds share the **Scene**, **Choice**, **Roll**, **Outcome**, **Effect**, and **WhenClause** sub-schemas.

### Validator

`engine/expedition_template.py` exposes:

```python
def load_template(template_id: str) -> Template       # parses + validates one
def validate_all() -> None                             # iterates data/expeditions/*.yaml
```

`tests/test_expedition_templates.py` is a CI gate that calls `validate_all()`. Failure breaks the build.

Beyond JSON-Schema conformance, the validator enforces semantic invariants:

1. Every scene with choices has **exactly one** `default: true` choice.
2. The default choice has **no `requires`** (always available as auto-resolve fallback).
3. Every template has **exactly one** closing with `when: { default: true }`.
4. Every `roll.stat` and `requires.stat` references a real entry in the published stat namespace.
5. Every effect op is from the closed outcome vocabulary; unknown ops fail.
6. Every archetype referenced (in `requires`, `outcomes[*].effects[*].archetype`, etc.) is a real `CrewArchetype` enum value.
7. Rolled templates: `len(events) >= event_count`.
8. Cross-reference: `set_flag` names match `has_flag` / `not_flag` references in the same template — typos surface as errors.
9. `template_id` matches filename.
10. Every `slot` reference (in `damage_part`, `reward_card`) is a real slot from the existing slot enum.

CLI form for use inside an LLM author's edit loop:

```bash
python -m engine.expedition_template validate path/to/file.yaml
```

Errors include file paths and line numbers.

### Authoring guide

Lives at `docs/authoring/expeditions.md`. **Self-contained** — a fresh Claude session reading just this file should produce a valid template.

Structure:

1. What an expedition is (player POV) + the two kinds.
2. File location, naming, ID conventions.
3. Annotated full example, scripted (every field explained inline).
4. Annotated full example, rolled (same treatment).
5. Stat namespace reference (auto-generated, see below).
6. Outcome vocabulary reference (auto-generated).
7. Authoring conventions: narrative voice (gritty noir, second-person present tense), scene length guidelines (60–150 words for openings/closings, 30–80 for choices), anti-patterns ("middle-pool events must be self-contained — don't reference a specific predecessor").
8. Testing your template (the CLI validator command).
9. Submitting (PR, CI runs validator).

A callout at the top of the guide:

> *If you are a Claude/LLM session helping a human author an expedition, follow this loop: read this entire guide → read 1–2 templates from `data/expeditions/` → write the new YAML → run the CLI validator → fix any errors → repeat.*

### Keeping docs in sync with code

Stat namespace and outcome vocabulary are single sources of truth in the engine, not in the guide. `scripts/build_authoring_docs.py` reads the engine's namespace registry + effect-op registry and regenerates the two reference tables in the guide. CI runs the script and fails if the diff is non-empty (i.e., the guide drifted). New stats / effect ops force the author to rebuild docs as part of their PR.

### v1 content

Two templates ship with v1, doubling as authoring exemplars:

- **1 scripted** — the marquee narrative, ~6hr, fixed scenes. Demonstrates the cinematic format. (Concrete title and content authored during implementation; the spec doesn't dictate.)
- **1 rolled** — a generic patrol run with an 8-event middle pool, ~4–8hr. Demonstrates the variance mechanism and gives players a replay loop.

Both are reviewed by the spec owner before merging. Both go through the same validator gate.

---

## Observability

### New metrics

```text
dare2drive_expeditions_started_total{template_id, kind}                    counter
dare2drive_expeditions_completed_total{template_id, outcome}               counter   # outcome ∈ {success, partial, failure}
dare2drive_expedition_events_fired_total{template_id, scene_id}            counter
dare2drive_expedition_events_resolved_total{template_id, scene_id, source} counter   # source ∈ {button, slash, auto}
dare2drive_expedition_active                                               gauge
dare2drive_expedition_event_response_seconds{template_id}                  histogram
```

Existing Phase 2a metrics (`scheduler_jobs_total{job_type, result}`) automatically pick up the four new `EXPEDITION_*` job types because the labels are dynamic.

### Tracing

Each scheduler job already emits a trace span (Phase 2a). Phase 2b adds expedition-level attributes: `expedition_id`, `template_id`, `scene_id`, `choice_id`, `outcome`. The `Expedition.correlation_id` propagates through the `NotificationRequest` payload into the bot's DM dispatch, so every log line involved in a single expedition is queryable in Loki by one ID.

### Dashboard

A new row on the existing `dare2drive-monitoring/dashboards/dare2drive-scheduler.json` (regenerated via the existing `generate_scheduler_dashboard.py` script):

- Active expeditions (gauge)
- Throughput by template (rate of `expeditions_started_total`)
- Event response time p50/p95/p99 (from the histogram)
- Auto-resolution rate per template (% of events that auto-resolved vs player-driven)
- Outcome distribution per template (success/partial/failure)

### Alerts

Two new alerts in `monitoring/grafana-stack/grafana/alerting/rules.yml`:

- **`ExpeditionAutoResolveRate`** — alert if any single template's auto-resolution rate exceeds 50% sustained 1h. Indicates content/UX issue (DMs not landing, response window too short, players ignoring).
- **`ExpeditionFailureRate`** — alert if any single template has > 95% failure outcomes sustained 1h. Indicates a broken template or grossly unbalanced choice math.

Both route to the existing Discord alerts channel via the existing notification policy.

---

## Files likely touched

### New

- `bot/cogs/expeditions.py` — slash commands + persistent button view
- `engine/expedition_engine.py` — `resolve_scene`, stat lookup, outcome application, closing variant selection
- `engine/expedition_template.py` — loader + validator + CLI entry point
- `scheduler/jobs/expedition_event.py` — `EXPEDITION_EVENT` handler
- `scheduler/jobs/expedition_auto_resolve.py` — `EXPEDITION_AUTO_RESOLVE` handler
- `scheduler/jobs/expedition_resolve.py` — `EXPEDITION_RESOLVE` handler
- `scheduler/jobs/expedition_complete.py` — `EXPEDITION_COMPLETE` handler
- `data/expeditions/schema.json` — JSON Schema
- `data/expeditions/<scripted_template_id>.yaml` — marquee template
- `data/expeditions/<rolled_template_id>.yaml` — patrol template
- `db/migrations/versions/<sha>_phase2b_expeditions.py` — Alembic migration
- `docs/authoring/expeditions.md` — authoring guide
- `scripts/build_authoring_docs.py` — namespace + vocab table regenerator
- `tests/test_expedition_engine.py`
- `tests/test_expedition_templates.py`
- `tests/test_cog_expedition_*.py`
- `tests/test_expedition_integration.py` — full-lifecycle test
- `tests/test_expedition_chaos.py` — kill-worker-mid-job recovery

### Modified

- `db/models.py` — new tables, enum extensions, `Build.current_activity`, `CrewMember.injured_until`
- `bot/cogs/hangar.py` — `/equip` and any build-mutation path checks `current_activity == IDLE`
- `bot/cogs/hiring.py` — `/crew` and `/crew_inspect` display refresh
- `bot/main.py` — `setup_hook` registers the persistent expedition view; load `bot.cogs.expeditions`
- `scheduler/dispatch.py` — register the four new handlers
- `engine/rewards.py` — `RewardSourceType.EXPEDITION_OUTCOME` accepted
- `api/metrics.py` — new metric definitions
- `monitoring/grafana-stack/generate_scheduler_dashboard.py` — new row
- `monitoring/grafana-stack/grafana/alerting/rules.yml` — two new alerts
- `docs/roadmap/2026-04-22-salvage-pulp-revamp.md` — insert Phase 2c

---

## Reuse pointers

- **Phase 2a scheduler-worker** — every expedition lifecycle event is a `ScheduledJob`, claimed via `SELECT FOR UPDATE SKIP LOCKED`, dispatched in its own transaction. No new scheduling primitives.
- **Phase 2a notification stream** — every player-facing DM goes through the existing Redis Streams + consumer-group + rate-limit + batching pipeline. No new delivery path.
- **Phase 2a `apply_reward` + `reward_ledger`** — every credit/XP/wreck/card delivery uses the existing idempotent reward pipeline. New `RewardSourceType.EXPEDITION_OUTCOME` value, no new reward path.
- **Phase 2a atomic-cancel idiom** — the `WHERE state = PENDING` UPDATE for race-resolution is reused verbatim from `/training cancel`.
- **Phase 1 crew assignment pattern** — `expedition_crew_assignments` mirrors the existing `crew_assignments` (build-crew) join table.
- **Phase 0 `engine/stat_resolver.py`** — `ship.<stat>` lookups go through the existing resolver.
- **Phase 0 `engine/card_mint`** — `reward_card` op delegates to the existing minting path.

---

## Scope boundary (OUT of Phase 2b)

- **Job board** (Phase 3) — expeditions here are user-initiated, not advertised on a board.
- **Channel events** (Phase 3) — public outcome posts to `/system` channels are deferred. v1 is DM-only.
- **Villain takeovers** (Phase 3).
- **Permadeath** — crew never permanently die in v1; ships never blow up. Phase 3+ feature with supporting UX.
- **PvP** (Phase 4).
- **Adaptive event scheduling** — events fire on a fixed schedule; player response speed doesn't change the timeline.
- **Cancellation** — no `/expedition cancel`. Admin escape hatch only.
- **Tutorial v2** (Phase 2c) — covering crew + Phase 2a + Phase 2b for new players is its own spec/phase.
- **Fleets** — single-ship in v1; schema is forward-compatible with future `Fleet` table.
- **Deprecation of `/build set-default`** — the broader move-away-from-active-build cleanup happens in a separate phase. Phase 2b just doesn't rely on the active-build concept.

---

## Verification

### Unit

- `resolve_scene` — every choice path (with roll, without roll, picked, default, hidden-choice fallback).
- `requires` filtering — choice hidden if missing crew/archetype/build constraint.
- Stat lookup for each namespace (`pilot.*`, `gunner.*`, `engineer.*`, `navigator.*`, `ship.*`, `crew.avg_level`, `crew.count`).
- Outcome effect application for each op in the closed vocabulary.
- Closing variant selection — `when` clauses match in declaration order; `default: true` is the fallback.
- Validator — positive cases (canonical templates) and negative cases for each invariant (missing default, unknown stat, archetype typo, pool-too-small, set/has flag mismatch, etc.).
- `get_max_expeditions(user)` — initial implementation returns 2 from config.
- Crew display refresh — each activity icon, injury rendering, "Qualified for" derivation.

### Integration

- Full expedition lifecycle with mocked clock: `/expedition start` → event 1 fires → DM delivered → button click → resolve → event 2 fires → no response → auto-resolve → expedition completes → closing applies → crew/build unlock.
- Crew injury flow: outcome sets `injured_until = now() + 24h`; `/training start` for that crew refuses; `injured_until - now() < 0` allows assignment.
- Idempotency: re-fire the same `EXPEDITION_RESOLVE` job; `reward_ledger` has exactly one row.
- Concurrency: simultaneous button click + auto-resolve fire — exactly one wins (the `WHERE state = PENDING` guard).

### Chaos

- Kill the scheduler-worker between `EXPEDITION_EVENT` firing and `EXPEDITION_RESOLVE`; restart; the resolution job re-claims and runs once.
- Kill the bot between DM send and player click; the persistent view re-binds on restart and the click still works.

### Cog

- Each `/expedition start` validation path produces the correct error message.
- Each `/expedition status` rendering case (no expeditions, one active, two active, one with pending event).
- Buttons + slash command both reach the same response handler.
- Build-mutation cogs (`/equip`, future `/build delete`) refuse on `current_activity != IDLE`.

### Rollout gate

`EXPEDITIONS_ENABLED` env var (default `false`) controls whether the expedition cog registers. Lets us merge the schema and engine, run on dev with the flag on, then flip prod once dev smoke-tests pass. Removed in a follow-up after a stable week.

---

## Deliverable

Players launch expeditions and get pinged for mid-flight decisions. Choices land within the response window via DM buttons or auto-resolve to the default branch. Crew and ship loadout materially shape which choices appear and how rolls land. Outcomes carry real consequences within the asymmetric-risk envelope (credit losses, durability damage, temporary crew injury — never permadeath in v1). Closing narrative is delivered on completion.

External developers (and Claude sessions) can author new expedition templates by reading `docs/authoring/expeditions.md` and 1–2 existing template files, with a CLI validator and CI gate that catches schema and semantic errors before merge.

`/crew` and `/crew_inspect` surface the new crew states and "what is this crew member good for?" hints.

The roadmap reflects Phase 2c — Tutorial v2 as the next blocking phase before Phase 3.
