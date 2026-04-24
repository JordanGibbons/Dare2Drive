# Phase 1 — Crew Sector

**Status:** Approved 2026-04-24
**Phase:** 1 of 6 (see [salvage-pulp revamp roadmap](../../roadmap/2026-04-22-salvage-pulp-revamp.md))
**Owner:** Jordan
**Depends on:** [Phase 0 foundation](2026-04-22-phase-0-foundation-design.md) (shipped)

---

## Context

Phase 0 pivoted the universe to salvage-pulp ships and introduced multi-tenant Sector/System tables. The game loop (pack → build → race) works mechanically unchanged.

Phase 1 adds **persistent crew members** as the first real new sector of gameplay on top of the pivot. Players hire named characters with archetypes (Pilot / Engineer / Gunner / Navigator / Medic), rarities, and levels. Crew are assigned to a Build and boost that build's composite stats during encounters. Crew gain XP per encounter and level up over time.

Crew are acquired from a separate surface — **dossiers** — with a 3-tier pricing structure that parallels the parts-crate economy. Every player also gets a **daily free lead** rolled alongside `/daily`, which they can accept via `/hire`.

This phase ships the first real dopamine loop beyond parts collection, and lays the scaffolding that Phase 2 (training timers) and Phase 3 (crew rewards from jobs, unique named crew, crew trading) build on.

No scheduler, no job board, no crew trading, no unique named crew, no crew wounding. Those are later phases.

---

## Locked decisions

These were settled during brainstorming. Re-litigation belongs in a follow-on spec.

### Power budget — "B" (meaningful lever, not decisive)

A fully crewed mid-tier ship moves stats ~8–15% vs. an uncrewed one. Parts still dominate the collection loop. Crew is tunable to a "C" budget later (where an uncrewed ship is narratively AI-autopiloted and noticeably weaker) via data-file edits only — no schema changes.

### Archetype mapping (Option 1 — pure composite-stat boosts)

All five archetypes boost composite stats from `BuildStats`. Two stats each: a **primary** (full boost) and a **secondary** (half the primary).

| Archetype | Primary | Secondary |
|---|---|---|
| Pilot | `effective_handling` | `effective_stability` |
| Engineer | `effective_power` | `effective_acceleration` |
| Gunner | `effective_top_speed` | `effective_braking` |
| Navigator | `effective_weather_performance` | `effective_grip` |
| Medic | `effective_durability` | `effective_stability` |

`effective_stability` appears twice (Pilot secondary + Medic secondary) — intentional, creates a natural defensive double-stack combo.

### Rarity base boosts (primary %, L1)

| Rarity | Primary |
|---|---|
| common | 2.0% |
| uncommon | 3.0% |
| rare | 5.0% |
| epic | 7.0% |
| legendary | 10.0% |
| ghost | 14.0% |

Secondary = primary / 2. Stored in `data/crew/rarity_boosts.json` as floats.

### Level scaling

- **Max level:** 10
- **Scaling shape:** linear — `boost × (1 + (level − 1) × 0.1)`, so L1 = 1.0×, L10 = 1.9×
- **XP curve:** `xp_for_next(level) = 50 × level²`. L1→L2 = 50 XP. Cumulative to L10 = 14,250 XP (sum of 50×n² for n=1..9).
- **XP per encounter:** 20 participation + 10 bonus for 1st place. Awarded to every assigned crew on the build.

### Dossier economy (single-pull per dossier)

| Tier | Price | Rarity weights (common / uncommon / rare / epic / legendary / ghost) |
|---|---|---|
| Recruit Lead | 150 creds | 65 / 25 / 8 / 1.8 / 0.19 / 0.01 |
| Dossier | 500 creds | 10 / 35 / 35 / 15 / 4.8 / 0.2 |
| Elite Dossier | 1500 creds | 0 / 0 / 40 / 40 / 17 / 3 |

Daily free lead uses `recruit_lead` weights but costs nothing.

Archetype roll is uniform (20% each) across all tiers. Rarity is the only thing dossier tier influences.

### Assignment mechanics

- **One crew ↔ one build.** Unique constraint on `crew_assignments.crew_id`. Assigning Jax to Build B auto-unassigns them from Build A.
- **Max one archetype per build.** Unique constraint on `(build_id, archetype)`. Assigning a new Pilot auto-unassigns the prior Pilot.
- **Free swap.** No cred cost, no cooldown.
- **"Crew quarters"** is not a separate view — unassigned crew are accessed via `/crew filter:unassigned`.

### Naming (template pools only in Phase 1)

- `data/crew/name_pool.json` with three lists: `first_names`, `last_names`, `callsigns`. 60–100 entries each.
- Format: `Jax "Blackjack" Krell`
- Collision handling: reroll up to 5 times against this user's existing crew; fall back to numeric suffix on callsign.
- No cross-player uniqueness — two players may independently roll the same name.
- Unique named crew are explicitly a Phase 3 concern (alongside crew trading).

### Portrait art — emoji-only Phase 1

- Pilot 🧑‍✈️ / Engineer 🔧 / Gunner 🔫 / Navigator 🧭 / Medic 🩹
- `crew_members.portrait_key: String(60) | None` column exists as scaffolding for Phase 5 real-art swap-in. Unused in Phase 1.

### Non-tradable in Phase 1

No `MarketListing`-analogue for crew. Phase 3 unlocks crew trading alongside unique named crew.

---

## Schema

All tables layered on top of Phase 0's `0001_initial.py`. Single new migration.

### New enum

```python
class CrewArchetype(str, enum.Enum):
    PILOT = "pilot"
    ENGINEER = "engineer"
    GUNNER = "gunner"
    NAVIGATOR = "navigator"
    MEDIC = "medic"
```

### `crew_members`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `user_id` | `String(20)` FK → `users.discord_id` not null | |
| `first_name` | `String(60)` not null | From name pool |
| `last_name` | `String(60)` not null | From name pool |
| `callsign` | `String(60)` not null | From name pool |
| `archetype` | `Enum(CrewArchetype)` not null | |
| `rarity` | `Enum(Rarity)` not null | Reuses existing enum |
| `level` | `Integer` not null default `1` | Clamped 1–10 |
| `xp` | `Integer` not null default `0` | Cumulative lifetime XP |
| `portrait_key` | `String(60)` nullable | Reserved for Phase 5 |
| `acquired_at` | `DateTime(timezone=True)` not null default `now()` | |
| `retired_at` | `DateTime(timezone=True)` nullable | Scaffolding only; not used in Phase 1 |

**Indexes:**
- `ix_crew_members_user_id` on `user_id`
- `ix_crew_members_user_archetype` on `(user_id, archetype)` — supports `/crew filter:pilot`
- Unique constraint `uq_crew_members_user_name` on `(user_id, first_name, last_name, callsign)`

### `crew_assignments`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `crew_id` | `UUID` FK → `crew_members.id` not null | Unique — enforces one-crew-one-build |
| `build_id` | `UUID` FK → `builds.id` not null | |
| `archetype` | `Enum(CrewArchetype)` not null | Denormalized from crew_member for the partial-unique below |
| `assigned_at` | `DateTime(timezone=True)` not null default `now()` | |

**Constraints:**
- Unique on `crew_id` — one crew can only be assigned to one build at a time
- Unique on `(build_id, archetype)` — one archetype slot per build
- On `crew_members` delete: cascade
- On `builds` delete: cascade

**Indexes:**
- `ix_crew_assignments_build_id` on `build_id` — for stat-resolver lookup

### `crew_daily_leads`

| Column | Type | Notes |
|---|---|---|
| `user_id` | `String(20)` FK → `users.discord_id` PK | |
| `rolled_for_date` | `Date` PK | UTC date of the `/daily` that rolled this lead |
| `archetype` | `Enum(CrewArchetype)` not null | Pre-rolled; stable across repeat `/daily` calls same day |
| `rarity` | `Enum(Rarity)` not null | |
| `first_name` | `String(60)` not null | |
| `last_name` | `String(60)` not null | |
| `callsign` | `String(60)` not null | |
| `claimed_at` | `DateTime(timezone=True)` nullable | Stamped by `/hire`. Nullable = still available today |
| `created_at` | `DateTime(timezone=True)` not null default `now()` | |

Composite PK `(user_id, rolled_for_date)` guarantees one lead per player per day. Old rows persist as history.

### No changes to existing tables

`Build`, `User`, `UserCard`, etc. unchanged. Crew are queried via `CrewAssignment.build_id` when resolving stats.

---

## Stat-resolver integration

### New function — `engine/stat_resolver.py::apply_crew_boosts`

```python
def apply_crew_boosts(bs: BuildStats, crew: list[CrewMember]) -> BuildStats:
    """Fold assigned crew boosts into the BuildStats in place.

    Called AFTER aggregate_build and BEFORE apply_environment_weights in
    engine/race_engine.py. Pure function; no DB access.
    """
    mapping = _get_archetype_mapping()       # archetypes.json
    base_boosts = _get_rarity_base_boosts()  # rarity_boosts.json
    for member in crew:
        arch = member.archetype.value
        primary_stat = mapping[arch]["primary"]
        secondary_stat = mapping[arch]["secondary"]
        level_mult = 1.0 + (member.level - 1) * 0.1
        base = base_boosts[member.rarity.value]
        primary_boost = base * level_mult
        secondary_boost = (base / 2) * level_mult
        _bump(bs, primary_stat, primary_boost)
        _bump(bs, secondary_stat, secondary_boost)
    return bs
```

`_bump(bs, stat_name, pct)` does `setattr(bs, stat_name, getattr(bs, stat_name) * (1 + pct))`. All boosts are multiplicative on the post-aggregation composite stat. Multiple crew boosting the same stat stack additively (two +5% crew → total +10%, not compound).

### Integration point — `engine/race_engine.py`

```python
# Before (today)
bs = aggregate_build(build.slots, cards, hull_class=build.hull_class.value)
bs = apply_environment_weights(bs, environment)

# After (Phase 1)
bs = aggregate_build(build.slots, cards, hull_class=build.hull_class.value)
crew = await _load_assigned_crew(session, build.id)  # new helper
bs = apply_crew_boosts(bs, crew)
bs = apply_environment_weights(bs, environment)
```

`_load_assigned_crew(session, build_id)` returns all `CrewMember` rows joined through `CrewAssignment` for that build. One indexed query per participant per race. Pre-warmed via `selectinload` where the surrounding code already does it.

### Data file — `data/crew/archetypes.json`

```json
{
  "pilot":     { "primary": "effective_handling",            "secondary": "effective_stability" },
  "engineer":  { "primary": "effective_power",               "secondary": "effective_acceleration" },
  "gunner":    { "primary": "effective_top_speed",           "secondary": "effective_braking" },
  "navigator": { "primary": "effective_weather_performance", "secondary": "effective_grip" },
  "medic":     { "primary": "effective_durability",          "secondary": "effective_stability" }
}
```

### Data file — `data/crew/rarity_boosts.json`

```json
{
  "common":    0.02,
  "uncommon":  0.03,
  "rare":      0.05,
  "epic":      0.07,
  "legendary": 0.10,
  "ghost":     0.14
}
```

### Worst-case stacking check

Five legendary crew at L10, each with different primary stats:
- Per primary: `0.10 × 1.9 = +19%`
- Per secondary: `0.05 × 1.9 = +9.5%`
- Stability stacks (Pilot secondary + Medic secondary) = +19% stability alone
- Average favored stat sees roughly one primary + one secondary = ~28%

That edges above the nominal "B" 8–15% ceiling at the absolute max-rarity / max-level / max-stack case, which is rare in practice. Tuning levers if playtest flags it:
- Drop `legendary` base from `0.10 → 0.08` (one-line data edit)
- Flatten scaling from `+10%/level` to `+6%/level`

Both are data-file changes, no schema impact.

---

## Crew recruitment engine

### `engine/crew_recruit.py`

Three public functions, all async where they touch the DB:

```python
def roll_crew(
    rarity_weights: dict[str, float],
    existing_names: set[tuple[str, str, str]],
) -> CrewRollResult:
    """Pure: roll archetype, rarity, and a unique-per-user name."""

async def recruit_crew_from_dossier(
    session: AsyncSession,
    user: User,
    tier: str,
) -> CrewMember:
    """Deduct creds, roll, persist a CrewMember. Raises on insufficient creds."""

async def recruit_crew_from_daily_lead(
    session: AsyncSession,
    user: User,
    lead: CrewDailyLead,
) -> CrewMember:
    """Consume today's unclaimed lead, persist as CrewMember, stamp claimed_at."""
```

`CrewRollResult` is a plain dataclass carrying archetype / rarity / first_name / last_name / callsign — the pure-roll output before it becomes a row.

**Rarity roll:** `random.choices(rarities, weights=..., k=1)` against the dossier tier's weights dict.

**Archetype roll:** uniform `random.choice(list(CrewArchetype))`. Dossier tier does **not** influence archetype; it only gates rarity. This keeps the economy symmetric and prevents accidental meta-locks (e.g., "always buy Elite for Pilots").

**Name collision handling:** attempt up to 5 full rerolls of the triple; on the 6th attempt, append a numeric suffix to callsign (`"Blackjack-2"`). With a 60×60×60 pool and realistic crew counts, 5 retries is overkill.

### `engine/crew_recruit.py` — why "recruit" not "mint"

Parts come off a press (`card_mint.py` — serial numbers, foils, copies). Crew are characters being recruited from the outer-rim rogues' gallery. Different domain verb for different domain noun. `card_mint.py` keeps its name.

### Daily lead lifecycle

1. `/daily` is invoked. After the existing parts/creds grant, check `crew_daily_leads` for `(user_id, today_utc_date)`.
   - If a row exists: show that lead in the embed (idempotent replay).
   - If not: `roll_crew(recruit_lead_weights, existing_names)`, insert the row, show it.
2. `/hire` is invoked. Load today's unclaimed lead (if any). Show preview + Accept button via `_PackRevealView` with one `CrewRevealEntry`. On Accept: `recruit_crew_from_daily_lead`, stamp `claimed_at`, acknowledge.
3. Expiry: running `/daily` tomorrow rolls fresh. Yesterday's unclaimed row just sits — trivial row count, no cleanup job.
4. Retry safety: `/hire` on an already-claimed lead responds "You've already hired today's lead." `/hire` with no rolled lead (player skipped `/daily`) responds "Run `/daily` to see today's lead."

### XP award hook

In `engine/race_engine.py::run_race`, after result computation, for each placement we load the crew assigned to that participant's build and award XP:

```python
for placement in result.placements:
    crew = await _load_assigned_crew_for_user(session, placement.user_id)
    xp_gain = 20 + (10 if placement.position == 1 else 0)
    for member in crew:
        leveled_up = _award_xp(member, xp_gain)
        if leveled_up:
            _record_level_up_for_embed(member)
```

`_load_assigned_crew_for_user(session, user_id)` resolves the user's active build via `Build.is_active` and joins through `CrewAssignment`. (Exact threading — e.g., whether to add `build_id` to `Placement` or look it up from `user_id` — is an implementation-plan call.)

`_award_xp(member, amount)` adds to `xp`, then while `xp >= xp_for_next(level) and level < 10`: deducts threshold, increments `level`. Returns `True` if at least one level was gained. `xp_for_next(n) = 50 * n * n`.

Level-ups are appended to the existing race result embed as a footer line per crew: `"⭐ Mira 'Sixgun' Voss reached Level 4."` No separate DMs, no rate limiting.

---

## Reveal UX — extending `_PackRevealView`

`bot/cogs/cards.py::_PackRevealView` is tested and reusable. Refactor to accept a polymorphic list of reveal entries:

```python
class RevealEntry(Protocol):
    name: str
    rarity: str
    def build_embed_fields(self) -> list[tuple[str, str, bool]]: ...

class PartRevealEntry:   # wraps (Card, UserCard) — today's behavior
class CrewRevealEntry:   # wraps CrewMember — new for Phase 1
```

`_PackRevealView` stays in `bot/cogs/cards.py` but moves the protocol + entry classes to a small shared helper module (`bot/reveal.py` or similar; final location chosen in plan). Single-pull dossiers render identically to a 3-card pack with `len == 1` (no arrows, single Accept).

Existing `test_pack_reveal_view.py` test stays green after the refactor; new `test_pack_reveal_view.py::test_crew_reveal` covers the crew path.

---

## Command surface — `bot/cogs/hiring.py`

New cog.

| Command | Params | System-gated? | Behavior |
|---|---|---|---|
| `/dossier` | `tier: recruit_lead \| dossier \| elite_dossier` | ✅ | Validate creds, recruit, reveal |
| `/hire` | — | ✅ | Claim today's daily lead |
| `/crew` | `filter: all \| unassigned \| assigned \| pilot \| engineer \| gunner \| navigator \| medic` (default `all`) | ❌ universe-wide | Paginated roster |
| `/crew inspect` | `name: autocomplete` | ❌ universe-wide | Full-detail embed |
| `/assign` | `crew: autocomplete` | ✅ | Assign to active build; auto-unassign prior same-archetype |
| `/unassign` | `crew: autocomplete` | ✅ | Remove from build |

System-gating follows existing patterns: `get_active_system` → `system_required_message` on None. `/crew` and `/crew inspect` skip gating like `/inventory` already does (universe-wide state view).

### `/daily` extension

`bot/cogs/cards.py::daily` gets three additions:

1. After parts grant, check/roll today's `crew_daily_leads` row
2. Append a "Today's Lead" field to the response embed with name + archetype + rarity
3. Hint line: `"Run /hire to recruit them."`

No new command created — the lead is surfaced in the existing daily flow. `/hire` claims it.

### Autocomplete helpers

`/crew inspect`, `/assign`, `/unassign` all accept a crew name with autocomplete. Matches against display format `"First 'Callsign' Last"` case-insensitive substring, capped at 25 results (Discord limit). Lives in `bot/cogs/hiring.py::_crew_name_autocomplete`.

---

## Observability

### Prometheus metrics (`dare2drive_` prefix)

| Metric | Labels | Where |
|---|---|---|
| `crew_recruited_total` | `source`, `archetype`, `rarity` | `crew_recruit.py` on persist. `source ∈ {dossier, daily_lead}` |
| `crew_boost_apply_total` | `archetype`, `rarity` | `stat_resolver.apply_crew_boosts` per crew per race |
| `crew_level_up_total` | `archetype`, `from_level`, `to_level` | `race_engine._award_xp` on level change |
| `dossier_purchased_total` | `tier` | `/dossier` cog command |
| `crew_assignment_total` | `action` (`assign`, `unassign`, `auto_unassign`) | `/assign` and `/unassign` cog commands |

### OpenTelemetry spans

- `crew.recruit` wrapping `recruit_crew_from_*`, tagged with `source`, `archetype`, `rarity`, `user_id`
- `crew.boost_apply` wrapping `apply_crew_boosts`, tagged with `crew_count`
- Command-level spans via the existing `@traced_command` decorator — no new work

### Structured logs (INFO level)

- `"crew recruited"` — user_id, crew_id, archetype, rarity, source
- `"crew level up"` — crew_id, from_level, to_level, xp_total
- `"crew assigned"` — crew_id, build_id, previous_assignee_id (or null)

### Grafana dashboard — `dare2drive-crew`

New dashboard in `monitoring/grafana-stack/provisioning/dashboards/`. Panels:

1. **Recruit rate by source + rarity** — stacked area, 24h window
2. **Rarity distribution vs. expected weights** — bar chart per dossier tier, annotated with expected %; alerts when drift >2σ over 24h
3. **Active assignments heatmap** — `archetype × rarity` matrix; shows meta shape
4. **Level-up cadence** — histogram of level-ups per hour; helps tune XP curve
5. **Dossier-vs-parts-crate revenue split** — comparative time series; tracks whether crew economy is cannibalizing parts
6. **Assignment churn** — `/assign` + `/unassign` rate; high churn signals UX issues (maybe friction needed later)

### Alerts

- **Rarity drift** — if `recruit_rarity_pct{tier=elite_dossier, rarity=ghost}` deviates >2σ from expected 3% over 24h, page. Likely indicates RNG bug.
- **Assignment constraint violation** — any `IntegrityError` on `crew_assignments` unique indexes → error log + page. Should be impossible via the cog flow; if it happens, there's a concurrency bug to find.

---

## Migration

Single alembic migration: `db/migrations/versions/0002_phase1_crew.py`

**Up:**
1. Create `crew_archetype` enum type
2. Create `crew_members`, `crew_assignments`, `crew_daily_leads` tables with all indexes/constraints
3. No backfill — zero existing crew data

**Down:**
1. Drop tables (reverse dependency order)
2. Drop `crew_archetype` enum

Up/down round-trip must pass the same CI check Phase 0 uses.

---

## Testing

Following the [feature completion checklist](../../../../.claude/projects/c--Users-jorda-dev-dare2drive/memory/feedback_feature_checklist.md).

### Unit tests

- **`tests/test_crew_recruit.py`** — archetype uniform distribution (χ² against null hypothesis), rarity weighting matches config within 3% tolerance over 10k samples per tier, name-collision retry logic, dossier price deduction on insufficient creds raises, suffix fallback on name exhaustion
- **`tests/test_stat_resolver.py`** — extend existing file:
  - `apply_crew_boosts` with zero crew is identity
  - L1 common pilot yields exactly 1.02× handling
  - L10 legendary pilot yields exactly `1.0 × 1.9 × 0.10 = 1.19×` handling
  - Two rare pilots stack additively on handling
  - Secondary is exactly half of primary after rounding
- **`tests/test_crew_assignments.py`** — unique `crew_id` constraint, unique `(build_id, archetype)` constraint, `/assign` auto-swap pathway, cascade on `CrewMember` delete, cascade on `Build` delete
- **`tests/test_crew_xp.py`** — `_award_xp` edge cases: exact-threshold, multi-level-in-one-grant, level cap at 10 (no further gains)

### Integration scenarios (`tests/test_scenarios/`)

- **`test_crew_flow.py`** — full path: `/dossier` → crew in `/crew` → `/assign` → race → XP gained → level-up visible in next race
- **`test_daily_lead_flow.py`** — `/daily` creates lead → `/daily` same day idempotent → `/hire` claims → second `/hire` errors → next day rolls fresh
- **Extend `test_race_flow.py`** — assert that same build with crew vs. without crew produces different stat outputs (crew actually moves the needle)

### Load / perf

- **`tests/test_crew_perf.py`** — 100 crew per user × 10 concurrent races: `apply_crew_boosts` p99 < 50ms. Locked roadmap target (line 214).

### Manual smoke

- End-to-end in a test server: run `/daily` → `/hire` → `/dossier tier:dossier` → `/assign` → `/race start` → confirm XP increment on a crew member across runs → trigger a level-up by running enough races

---

## File inventory

New files:
- `db/migrations/versions/0002_phase1_crew.py`
- `engine/crew_recruit.py`
- `bot/cogs/hiring.py`
- `bot/reveal.py` (shared reveal-entry protocol + helpers extracted from `cards.py`)
- `data/crew/archetypes.json`
- `data/crew/rarity_boosts.json`
- `data/crew/dossier_tables.json`
- `data/crew/name_pool.json`
- `monitoring/grafana-stack/provisioning/dashboards/dare2drive-crew.json`
- `tests/test_crew_recruit.py`
- `tests/test_crew_assignments.py`
- `tests/test_crew_xp.py`
- `tests/test_scenarios/test_crew_flow.py`
- `tests/test_scenarios/test_daily_lead_flow.py`
- `tests/test_crew_perf.py`

Modified files:
- `db/models.py` — add `CrewArchetype` enum + three models + relationships
- `engine/stat_resolver.py` — add `apply_crew_boosts`
- `engine/race_engine.py` — load crew + call `apply_crew_boosts` + award XP per placement
- `bot/cogs/cards.py` — extract reveal-entry protocol; extend `/daily` with lead preview
- `tests/test_pack_reveal_view.py` — cover the new `CrewRevealEntry` path
- `tests/test_stat_resolver.py` — add crew-boost cases
- `tests/test_race_engine.py` — confirm crew XP + level-ups fire from race flow
- `api/metrics.py` — add new Prometheus counters
- `bot/main.py` — register the `HiringCog`
- Alerting rules under `monitoring/` — add the rarity-drift + assignment-violation alerts

---

## Scope boundary (OUT of Phase 1)

- **Crew trading** — Phase 3, alongside unique named crew
- **Unique named crew / villain drops** — Phase 3
- **Crew death / permanent retirement mechanics** — deferred; `retired_at` is scaffolding only
- **Crew training timers** — Phase 2 (requires scheduler)
- **Job / event crew rewards** — Phase 3 writes into `recruit_crew_from_*`-style entry points
- **Crew injury / wound state** — Phase 4 (combat)
- **Crew synergies or traits (e.g., "Veteran Pilot" buffs Engineers on same ship)** — not on any phase yet
- **Real portrait art** — Phase 5

---

## Carry-forward for future phase specs

1. **Gunner / Medic Phase 1 kits are translations, not their real identity.** `top_speed/braking` and `durability/stability` are approximations that fit the current race-style encounter. When Phase 4 combat lands, revisit whether their full Phase 4 kits (damage trades, crew injury mitigation) replace or extend the Phase 1 stat boosts. Entry point: Phase 4 spec brainstorm.
2. **Power budget is dialed to "B".** Phase 3/4 playtesting will likely push toward "C" where uncrewed ships feel narratively AI-autopiloted and noticeably weaker. Primary tuning levers are `data/crew/rarity_boosts.json` magnitudes and the `+10%/level` slope in `apply_crew_boosts`. Both are data edits; no schema change.
3. **Trading needs uniqueness.** Before Phase 3 opens `MarketListing` to crew, the Phase 3 spec must lock how unique crew differ structurally (catalog table? subclass? `is_unique: bool` flag?). Generic template crew are interchangeable and should not trade.
4. **No cross-player name uniqueness.** Two players may independently roll the same crew name today. If player-to-player interactions (trading, PvP, guilds) ever make this fiction-breaking, add a global unique constraint then — migration would be straightforward since the collision space is small.
5. **Scheduler dependency for Phase 2.** Crew training timers, passive accrual from crew assigned to stations, and long-running expeditions all sit in Phase 2. The `CrewMember` model is ready — Phase 2 just adds station/timer tables and references `crew_members.id`.

---

## Deliverable

Players can buy dossiers and claim daily leads. Hired crew appear in `/crew`, can be inspected and assigned to an active build. Running a race with crew assigned visibly changes encounter outcomes, and crew gain XP and level up over repeated runs. The dossier economy runs alongside the parts crate economy without replacing it. Observability is wired; Grafana dashboard + alerts exist on shipping.

---

## Verification

- All unit + integration tests pass
- Alembic up/down round-trips cleanly against a fresh DB
- Manual smoke: `/dossier` → `/assign` → `/race start` → confirm stat swing vs. uncrewed race on the same build
- Cross-server smoke: crew appear in `/crew` on both test servers (universe-wide state preserved)
- Load test: 100-crew users × 10 concurrent races meets p99 < 50ms on `apply_crew_boosts`
- Grep: no `mint_crew_*` references leak into `engine/crew_recruit.py` or tests
- Grafana dashboard renders on the local stack; alerts evaluate without error
