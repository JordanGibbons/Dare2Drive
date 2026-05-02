# Dare2Drive → Salvage-Pulp Space Revamp — Roadmap

**Status:** Approved 2026-04-22
**Owner:** Jordan
**Scope:** Multi-phase revamp of Dare2Drive from a car-racing game into a salvage-pulp spaceship game with multi-tenant support across Discord servers.

---

## Context

Dare2Drive today is a Discord bot + FastAPI game where players open packs of car parts, build a 7-slot car, and race. The sector is well-architected (async SQLAlchemy, 10 migrations, observability already wired up via Prometheus/Loki/Tempo/Grafana, no live users yet).

Two problems with the current premise:

1. **Art pipeline risk.** Getting artists to draw endless fully-fictional-but-not-infringing cars is a real creative constraint that will throttle content velocity.
2. **Weak bot heartbeat.** The bot only acts when players act. There's nothing ticking in the background that brings players back, and nothing that makes the server itself feel alive.

This plan pivots the game to a **salvage-pulp spaceship universe** (outer-rim scrappers meet 70s pulp sci-fi — rusted junker hulls alongside chrome psychic cruisers alongside bio-organic alien ships). The pivot unlocks maximum artist freedom, enables a fleshed-out fictional universe with crew characters and scheduled villain events, and reframes the Discord-server-installed-base as the in-fiction universe map.

The intended outcome is a multi-server Discord game where:

- Players collect cards (parts + crew), build ships, and field them in events
- The bot runs persistent background sectors (training timers, passive yield, multi-hour expeditions with choice points) that give players things to come back to
- A revolving job board and scheduled channel events drive server-wide engagement
- Scheduled villain takeovers create memorable moments with shared debuffs if the server loses
- Players can claim **control of systems**, earning tribute from other players' activity there; control can be contested by villains (PvE) or by other players (PvP), laying foundations for later guild/alliance play
- Every installed server is a sector in one shared universe — your fleet follows you anywhere
- Eventually: fleet-vs-fleet PvP (channel-native first, real-time Discord activity later) with artist-drawn tiered ships and crew portraits

The revamp is decomposed into six phases. Each phase is independently shippable and has its own spec + implementation plan written in a separate session when executed.

---

## Locked creative and architectural decisions

These apply to every phase and should not be re-litigated in phase specs.

### Creative

- **Universe tone:** salvage-pulp hybrid. Outer-rim scrappers in a weird 70s pulp sci-fi world. Rusted junkers, chrome psychic cruisers, bio-organic alien hulls all canonical.
- **Villain fiction range:** pirate warlords through cosmic cult overlords — all acceptable.
- **Crew archetypes:** Pilot, Engineer, Gunner, Navigator, Medic. Final list can adjust in Phase 1 spec.
- **Pack economy preserved:** the existing pack-opening dopamine loop is a strength and must survive the pivot intact (just reframed as salvage crates, dossiers, etc.).

### Architecture

- **Multi-tenant universe.** One D2D backend serves many Discord servers.
  - **Server (Discord guild) = "Sector"** (a collection of systems, e.g., a star sector or constellation).
  - **Channel = "System"** (specific game-enabled channels within a sector).
  - **Universe = federation** of all D2D-enabled sectors.
- **Player state is universe-wide.** Cards, crew, ship builds, and credits live on the player profile and follow them to any server. No per-server save file. Leaderboards and ongoing storylines can still be system/sector/universe scoped.
- **Travel is implicit.** Players are "active" in whichever system (channel) they're typing in. No `/travel` command in Phase 0–3. Explicit fleet deployment may be added in Phase 4+ as a PvP mechanic.
- **Admin opt-in.** Server owners explicitly register which channels are systems. The bot does not auto-enable itself in every channel it can see.
- **Scheduler is load-bearing.** A durable, restart-safe scheduler is the backbone of Phases 2+. Invest in it properly in Phase 2.
- **Observability from day one.** All new sectors emit traces (OpenTelemetry), metrics (`dare2drive_*` Prometheus), and structured logs. Existing infra handles the rest.

---

## How to execute a phase

For each phase, run a fresh Claude Code session and point it at this roadmap plus the phase section. The workflow per phase:

1. **Brainstorm the phase** (`superpowers:brainstorming` skill) — resolve spec-level open questions
2. **Write the spec** — saved to `docs/superpowers/specs/YYYY-MM-DD-<phase>-design.md`
3. **Write the implementation plan** (`superpowers:writing-plans` skill) — detailed, step-by-step
4. **Execute** (`superpowers:executing-plans` or `superpowers:subagent-driven-development`)
5. **Review** (`superpowers:requesting-code-review`) before merge

Entry criteria and scope boundary are specified per phase below. Do not violate scope boundary — if new work is discovered, add it to a later phase rather than bloating the current one.

---

## Phase 0 — Foundation: Theme Pivot + Multi-Tenant System Model

**Status:** Not started. No live users, so rename + restructure can land together.

### Goal

- Every model, enum, copy string, card JSON, and tutorial step reads as ships/salvage-pulp.
- The codebase supports multi-tenant operation: servers (sectors) register, channels (systems) are explicitly enabled, and player state is server-agnostic.
- Existing game loop (pack → build → race) works unchanged mechanically, just in the new vocabulary.

### Key renames (starting proposal — lock final list in Phase 0 spec)

| Current | New | Notes |
| --- | --- | --- |
| `Car` / "car" | `Ship` | Model, copy, everywhere |
| `Build` | keep as `Build` or rename `Loadout` | TBD in spec |
| `BodyType` (muscle/sport/compact) | `HullClass` (heavy/skirmisher/scout) | Enum rename |
| `CarClass` (street/drag/circuit/drift/rally/elite) | `EncounterType` (patrol/sprint/endurance/slalom/raid/elite) | Enum rename |
| `Race` | `Encounter` | Model + routes |
| `RigTitle` | `HullTitle` or `ShipTitle` | Model rename |
| `RigRelease` | `ShipRelease` | Model rename |
| `WreckLog` | keep (wrecks fit salvage-pulp fiction) | Copy update only |
| Slot: `engine` | `reactor` | |
| Slot: `transmission` | `drive` | |
| Slot: `tires` | `landing_gear` | TBD — could be `thrusters` |
| Slot: `suspension` | `stabilizers` | |
| Slot: `chassis` | `hull` | |
| Slot: `turbo` | `overdrive` | |
| Slot: `brakes` | `maneuvering` | |

### New entities

- **`Sector`** (one row per Discord guild using the bot). `guild_id`, `name`, `registered_at`, `owner_discord_id`, optional `flavor_text`.
- **`System`** (one row per enabled channel). `channel_id`, `sector_id`, `name`, `enabled_at`, config JSONB.
- **Player-active-system tracking** — no persistent column needed; derived from message context per command.

### Files likely touched

- `db/models.py` — rename models and enums
- `db/migrations/versions/` — new migration for renames + Sector/System tables
- `data/cards/*.json` — rewrite copy, keep stat structure
- `data/loot_tables.json` — rewrite pack display names/flavor
- `bot/cogs/*.py` — every cog needs copy updates; race cog becomes encounter cog
- `bot/cogs/tutorial.py` — rewrite tutorial script
- `bot/cogs/admin.py` — add `/system enable`, `/system disable`, `/sector info` commands
- `engine/race_engine.py` — rename to `encounter_engine.py`, internal rename only
- `engine/environment.py` — track conditions become space conditions (nebula, asteroid field, solar flare, etc.)
- `engine/stat_resolver.py` — no behavior change; slot name updates only
- `api/routes/*.py` — copy/route renames
- `config/settings.py` — server registration config

### Reuse pointers

- **Keep `engine/stat_resolver.py` structure intact.** The 7-slot composite stat aggregation is generic — slot names rename, math unchanged.
- **Keep pack-opening flow.** `engine/card_mint.py` and `data/loot_tables.json` structure are reused; only names/flavor change.
- **Keep observability.** Existing `config/tracing.py`, `config/metrics.py`, and FastAPI instrumentation continue working.

### Scope boundary (OUT of Phase 0)

- No crew sector (Phase 1)
- No timers/scheduler (Phase 2)
- No job board or events (Phase 3)
- No new art — existing card art stays as placeholder

### Deliverable

Existing game loop functional in the new ship vocabulary. Server owners can register systems. Player state is not tied to any single server.

### Verification

- Run existing test suite — all tests pass after renames
- Manual smoke test: open pack, build ship, run encounter, in two different test Discord servers with the same player account — cards should appear in both
- Grep for "car", "race", car-slot names to confirm no leaks in copy
- Alembic migration up/down round-trips cleanly
- Tutorial walkthrough end-to-end in new vocabulary

---

## Phase 1 — Crew Sector

**Status:** Blocked on Phase 0.

### Goal

Players hire persistent crew members with names, archetypes, rarity tiers, and levels. Crew boost ship stats. Crew are acquired from a separate surface (Hiring Hall) — not mixed with parts packs.

### Mechanics

- **Acquisition paths** (all feed one crew pool):
  - Daily free lead — one rotating candidate per day, low rarity weighted
  - Paid dossiers — buy at Hiring Hall with credits, tiered like existing parts packs
  - Job/event rewards — will be wired up in Phase 3 (design the hook in Phase 1)
- **Archetypes:** Pilot, Engineer, Gunner, Navigator, Medic. Each archetype boosts a subset of ship stats.
- **Persistence:** once recruited, crew are permanent characters with:
  - Unique name, portrait (placeholder art OK), backstory hook
  - Level (1 → N), XP gained from encounters
  - Rarity tier drives base boost magnitude; level scales it further
- **Assignment:** crew are assigned to a ship (Build). Max one crew per archetype per ship. Unassigned crew sit in a "crew quarters" pool.

### New entities

- **`CrewMember`** — persistent crew. `id`, `user_id`, `name`, `archetype`, `rarity`, `level`, `xp`, `portrait_key`, `created_at`, `retired_at` (nullable).
- **`CrewDossier`** — dossier pack type analog. Reuse loot table mechanics from parts packs.
- **`CrewAssignment`** — link `CrewMember` ↔ `Build`. Unique constraint on (build_id, archetype).

### Files likely touched

- `db/models.py` — new models
- `db/migrations/versions/` — new migration
- `data/crew/archetypes.json` — new data dir defining archetype → stat boost mapping
- `data/crew/name_pool.json` — name generator source (first + last + callsign)
- `data/dossiers.json` — dossier pack definitions (tiers, weights, prices)
- `bot/cogs/hiring.py` — new cog: `/hire`, `/crew`, `/dossier`, `/assign`
- `engine/crew_mint.py` — new: roll archetype, rarity, name, stat multipliers
- `engine/stat_resolver.py` — extend to fold crew boosts into composite stats after parts aggregation, before environment weighting
- `engine/encounter_engine.py` — read crew from active build, pass to stat resolver
- `api/routes/crew.py` — new routes for crew CRUD

### Reuse pointers

- **Pack opening UI** (`tests/test_pack_reveal_view.py` pattern) — reuse for dossier reveals
- **Rarity enum + weights** — same `Rarity` enum used for parts cards
- **Serial/mint pattern** — adapt from `engine/card_mint.py`
- **Card portrait rendering** (Pillow-based, used for ship parts) — extend for crew portraits

### Scope boundary (OUT of Phase 1)

- Crew death/retirement mechanics (defer; nullable `retired_at` column is enough scaffolding)
- Crew training timers (Phase 2 — Phase 1 ships crew that level via encounter XP only)
- Job/event crew rewards (Phase 3 wires rewards into jobs; Phase 1 builds the reward-entry hook)
- Unique named crew / villain drops (Phase 3)

### Deliverable

Players hire crew. Crew assignment meaningfully changes encounter outcomes. Dossier economy is live alongside parts packs.

### Verification

- Unit tests: crew minting, archetype boost application, assignment constraints
- Encounter test: same build, different crew → different outcome distributions
- Integration: hire → assign → run encounter → crew gains XP → level-up triggers higher boost
- Load test: crew pool of 100+ per user performs acceptably in stat resolver

---

## Phase 2 — Background Progression

Phase 2 was originally scoped as a single shipping unit covering the scheduler, short timers, overnight accrual, and multi-hour expeditions. During Phase 2 brainstorming the work was split into two independently shippable sub-phases (2026-04-25):

- **Phase 2a** ships the durable scheduler, short timers, and overnight accrual — all "fire-and-resolve" jobs that share the same infrastructure pattern.
- **Phase 2b** ships expeditions on top of the Phase 2a scheduler. Expeditions add a mid-job interaction model (response windows, choice resolution, narrative state) that warrants its own spec.

Splitting here lets the scheduler stress-test under simple, high-volume jobs before expedition complexity lands on top, and keeps each spec/plan to a sensible size. Phase 3 is blocked on Phase 2b.

---

## Phase 2a — Scheduler Foundation + Timers + Accrual

**Status:** Blocked on Phase 1.

### Goal

The bot heartbeat, simple-job edition. Two background engagement rhythms:

- **Timers** (15 min – 2 hr): crew training, research projects, ship builds
- **Accrual** (overnight): crew assigned to stations generate credits/XP/resources passively

The scheduler infrastructure built here is load-bearing for Phases 2b+.

### Mechanics

- **Scheduler:** durable, restart-safe. Must survive bot restarts without missing ticks or duplicating fires. Recommended approach: Redis-backed durable queue with DB-persisted job records as source of truth. (Redis is in `pyproject.toml` and `REDIS_URL` is configured, but no Python code touches it yet — Phase 2a introduces real Redis usage.)
- **Timers:** finite-duration tasks tied to a user. Completion DMs the user (rate-limited, opt-outable).
- **Accrual:** periodic yield computation (e.g., every N minutes) for crew assigned to stations. Collected on next login via `/claim`.

### New entities

- **`ScheduledJob`** — durable job record. `id`, `user_id`, `job_type` enum, `payload` JSONB, `scheduled_for`, `fired_at`, `resolved_at`, `state` enum.
- **`Training`**, **`Research`**, **`BuildJob`** (or one polymorphic `Timer` table) — concrete timer types.
- **`StationAssignment`** — `crew_id` → `station_type` for accrual.

### Files likely touched

- `scheduler/` — new top-level module
- `scheduler/engine.py` — durable scheduler loop
- `scheduler/jobs/` — per-job-type handlers
- `bot/cogs/fleet.py` — `/fleet`, `/training`, `/research`, `/stations`, `/claim`
- `db/migrations/versions/` — new migrations
- `bot/notifications.py` — DM rate limiter + opt-out

### Reuse pointers

- **OpenTelemetry spans** — wrap every scheduler fire with a span for trace correlation with Grafana
- **Prometheus counters** — add `dare2drive_scheduler_jobs_total{job_type, result}` for observability

### Scope boundary (OUT of Phase 2a)

- Expeditions (Phase 2b)
- Job board (Phase 3)
- Villain events (Phase 3)
- PvP mechanics (Phase 4)

### Deliverable

Players start timers, assign crew to stations, claim accrued yield. Bot pings them when work completes (respectfully). Scheduler survives deploys.

### Verification

- Chaos test: kill bot mid-job → jobs resume correctly on restart
- Load test: 1000 concurrent scheduled jobs
- Rate-limit test: notification throttling respects user opt-out + per-hour cap
- Idempotency test: simulated double-fire of the same job does not double-pay rewards

### Phase 2a follow-ons (deferred from initial implementation)

These were intentionally stubbed in the initial Phase 2a ship — or surfaced during the post-merge deploy. They are independent and can land separately. Items are grouped by category so they can be triaged. Completed items have been removed; this section reflects only what remains.

#### Gameplay completeness

- **Ship-build hull creation + input consumption + slash command surface.** `scheduler/jobs/timer_complete.py:_resolve_ship_build` writes a `RewardLedger` entry with `delta={"new_ship": {...}}` and emits a "Ship build complete" DM, but does not actually create a `Build` row, mint a Ship Title, or consume the recipe's `input_scrapped_ship_count` wrecks. The `/build construct/status/cancel` slash commands were also removed before launch (the chosen group name `build` collided with hangar's existing `/build` for parts management). Re-introduce as `/shipyard construct/status/cancel` once the hull-creation logic is built. Open questions: does "Reconstructed Hull" produce a fresh empty `Build`, or one pre-equipped with parts salvaged from the input wrecks? Which `hull_class` is selected — fixed (`hauler`) per recipe, or chosen by the player at start time?
- **Research fleet-buff application + expiry.** `scheduler/jobs/timer_complete.py:_resolve_research` writes a `RewardLedger` entry with `delta={"fleet_buff": {"stat": ..., "pct": ..., "duration_hours": 48}}` but `engine/stat_resolver.py` does not read active fleet buffs. Players see "Research complete" DMs but their `effective_acceleration` / `effective_durability` / `effective_weather_performance` never actually change. Needs (a) a `FleetBuff` table or derived view from `reward_ledger`, (b) `stat_resolver` integration to apply active buffs at resolve time, (c) expiry — buffs naturally drop off after `duration_hours` (could be a scheduler job, or just an `applied_at + duration > now()` filter at read time).
- **DM-closed user feedback loop.** `bot/notifications.py:_deliver_batch` silently XACKs entries when `discord.Forbidden` fires (player has DMs closed), incrementing the `dm_closed` notification metric. Players never learn their notifications are being dropped. Optional follow-on: track per-user `dm_closed` streaks and surface a one-time warning in a guild channel the player has used recently, prompting them to either re-open DMs or set the relevant `notification_prefs` category to `off`.

#### Operational / deploy hygiene

- **Re-connect `scheduler-worker` Railway service to GitHub for auto-deploy.** The service was created via `railway add` and the first deploy was via `railway up` from a local checkout. It currently has no GitHub source bound, so commits to `demo` will not auto-deploy the worker. In the Railway dashboard for the `scheduler-worker` service: Settings → Source → connect to `JordanGibbons/Dare2Drive`, Branch = `demo`. After connecting, the start command in dashboard ("Custom Start Command") must remain `python -m scheduler.worker` (currently set manually).
- **Clean up the no-op `RAILWAY_RUN_COMMAND` variable on `scheduler-worker`.** Set during deploy debugging hoping Railway honored it as a start-command override; it doesn't. Harmless but confusing in the variables list. Remove via dashboard.
- **Investigate Grafana 11.5 git-sync silently dropping a file when the previous version fails resource validation.** Documented in dare2drive-monitoring #6's PR description: a single file in legacy schema fails validation, never appears as a dashboard, and remains "stuck" — subsequent v2-format updates to the same file path fail to load because the diff requires parsing the broken predecessor. Workaround we used: delete + re-add as separate commits on the same merge. Worth filing upstream once we have time, both because it costs hours of investigation and because the failure mode is silent (sync_status reports `success`, but resource count is one short of the file count).

---

## Phase 2b — Expeditions

**Status:** Blocked on Phase 2a.

### Goal

Multi-hour expeditions with mid-flight decision points, built on the Phase 2a scheduler. The first time the bot tells a story while you're away from the keyboard.

### Mechanics

- **Expeditions:** scheduled jobs with interior "events" that fire partway through. If the user responds to an event in the response window, their choice applies. If they don't, it auto-resolves.
- Duration band: 4 – 12 hr per expedition.
- Crew assignment matters — the assigned crew's archetypes and stats influence event odds and outcomes.

### New entities

- **`Expedition`** — `id`, `user_id`, `ship_id`, `assigned_crew_ids`, `started_at`, `duration`, `scheduled_events` JSONB, `state`, `outcome_summary`.

### Files likely touched

- `bot/cogs/expeditions.py` — `/expedition start`, `/expedition status`, `/expedition respond`
- `engine/expedition_engine.py` — event rolling, resolution, narrative output
- `data/expeditions/` — expedition templates (routes, event tables, reward tables)
- `scheduler/jobs/expedition_event.py` — handler for mid-flight event fires
- `db/migrations/versions/` — new migrations

### Reuse pointers

- **Phase 2a scheduler** — expedition starts, mid-flight events, and resolutions are all scheduled jobs
- **Stat resolver** — expedition event outcome rolls reuse `engine/stat_resolver.py` for stat-dependent odds

### Scope boundary (OUT of Phase 2b)

- Job board (Phase 3) — expeditions here are user-initiated, not advertised on a board
- Villain events (Phase 3)
- PvP mechanics (Phase 4)

### Deliverable

Players launch expeditions and get pinged for mid-flight decisions. Choices land within window or auto-resolve. Outcome narrative delivered on completion.

### Verification

- Integration: full expedition with interior event choice → outcome narrative delivered
- Auto-resolution: unresponded events fall back to default branch deterministically
- Chaos test: kill bot during an expedition → resumes correctly on restart, no duplicate event fires

---

## Phase 2c — Ship-Crew Binding + Narrative Substitution

**Status:** Blocked on Phase 2b. **Phase 2d is blocked on Phase 2c.** (Inserted 2026-04-27 — was originally Tutorial v2; that has moved to Phase 2d.)

### Goal

Move crew assignment from per-expedition (Phase 2b) to persistent on-ship binding, with hull-class-specific crew slots. Players assign crew once via an interactive `/hangar` view; `/expedition start` drops its crew params and reads the aboard set from the ship. Ship the lightweight narrative-substitution layer in the same phase so templates can reference the crew and the ship name in their prose (`{pilot.callsign} pulls the {ship} alongside the wreck...`).

### What gets covered

- New `build_crew_assignments` table + hull-class slot config (SKIRMISHER → pilot+gunner; HAULER → pilot+engineer+navigator; SCOUT → pilot+navigator)
- Persistent `HangarView` extending `/hangar <build>` with select menus per crew slot
- `/expedition start` simplified to `(template, build)`; launch handler derives aboard crew from the ship and validates against the existing `crew_required` semantics
- Closed-vocabulary narrative tokens (`{pilot}`, `{pilot.callsign}`, `{ship}`, `{ship.hull}`) rendered at scene-fire time in `engine/narrative_render.py`, with generic-noun fallbacks for empty slots
- Template-loader validator extension to enforce the token allow-list at load time

### Design problems to solve

These were settled during brainstorming (2026-04-27); the spec captures the locked decisions. Re-litigation belongs in a follow-on spec:

- Hull-class slots vs flexible vs capacity-only → **hull-class slots** (justifies hull variety)
- Slash commands vs interactive view for assignment → **interactive view** (project preference)
- Strict full-crew launch vs permissive vs template-required → **template-required only** (carries Phase 2b semantics forward)
- Closed allow-list vs Jinja for narration → **closed allow-list for v1** (Jinja deferred)

### Files likely touched

- `db/migrations/versions/0006_phase2c_build_crew_assignments.py` (new)
- `engine/narrative_render.py` (new)
- `engine/class_engine.py` — `HULL_CREW_SLOTS` + `slots_for_hull()`
- `db/models.py` — `BuildCrewAssignment` ORM model
- `bot/cogs/hangar.py` — `HangarView` + crew-slot select handlers
- `bot/cogs/expeditions.py` — drop crew params, read from ship
- `engine/expedition_template.py` — token allow-list validator
- `scheduler/jobs/expedition_event.py` / `expedition_resolve.py` / `expedition_complete.py` — call `render()`
- `bot/main.py` — register persistent `HangarView`

### Scope boundary (OUT of Phase 2c)

- Conditional Jinja-style narration (`{% if has_engineer %}…`) — wait until external authors feel the constraint of the closed allow-list
- Stat-derived tokens (`{pilot.combat}`) and rolled-value references (`{roll.success}`) — same deferral
- Templates declaring eligible hulls explicitly (`hull_class_eligible`) — the existing `crew_required` × `HULL_CREW_SLOTS` covers this implicitly
- Crew swapping mid-expedition — ships are locked while on expedition (existing 2b invariant)
- Captain/co-pilot hierarchy — Phase 4+

### Deliverable

A player builds a ship, assigns crew via the `/hangar` view (one click per slot), and launches expeditions without re-picking crew every time. Mid-flight DMs reference the actual crew member by callsign and the ship by name where the template author has chosen to use the tokens. The two existing v1 templates work unchanged; new templates can opt in to substitution as the author sees fit.

### Spec

[docs/superpowers/specs/2026-04-27-phase-2c-ship-crew-binding-design.md](../superpowers/specs/2026-04-27-phase-2c-ship-crew-binding-design.md)

---

## Phase 2d — Tutorial v2

**Status:** Deferred until after Phase 3 (decision 2026-05-01). Originally blocked Phase 3, but the day-to-day gameplay loop is currently thin — most of what exists is "select and wait" — and tutorializing a game that isn't engaging yet bakes the wrong shape into onboarding. Phase 3 lands the actual gameplay layer (lighthouses, resources, home base, events). The tutorial gets rebuilt against that shape afterward, when there's a game worth introducing players to.

### Goal

Bring the new-player onboarding flow up to date with the post-Phase-2b game. Current tutorial walks players through ship-building only; it pre-dates crew, training/research/stations, and expeditions. New players see a misleading shape of the game.

### What gets covered

- Hire your first crew member (`/dossier` or `/hire`)
- Inspect a crew member (`/crew_inspect`)
- Run a training routine (`/training start`)
- Run a research project (`/research start`)
- Assign a crew member to a station (`/stations assign`)
- Launch your first expedition (`/expedition start`) on a marquee scripted template

### Design problems to solve

- **Time gating.** Training is 30+ min, research 60–90 min, expeditions 4–12 hr. Onboarding wants the first 5 min to feel rich. Three options worth weighing in the spec: (a) accelerated tutorial timers (30s instead of 30m), (b) "you've now seen all systems, here are pointers" — end the tutorial at the survey, don't force completion, (c) branching — hands-on for instant stuff, just-tell-them for time-gated stuff.
- **Multi-day onboarding.** A tutorial that spans real-time hours needs different mechanics from a 5-minute tutorial — funnel decay points multiply.
- **`/skip_tutorial` UX.** Currently an instant flip. With multi-day tutorial, "skip" is a more serious commitment.

### Tutorial-cohort metrics

Funnel decay points to instrument from day 1:

- Cohort defined by `tutorial_started_at` weekly bucket
- Decay at: hire-crew step, training-start step, training-completion step, expedition-launch step, expedition-completion step
- Day 1 / Day 7 retention by cohort

### Files likely touched

- `bot/cogs/tutorial.py` — extend `TutorialStep` enum, `STEP_ALLOWED_COMMANDS`, `advance_tutorial` transitions
- `data/tutorial.json` — new dialogue beats per step
- `bot/cogs/hiring.py`, `bot/cogs/fleet.py`, `bot/cogs/expeditions.py` — call `advance_tutorial(...)` after first-time successful invocations
- `db/migrations/versions/` — new tutorial_step enum values
- `api/metrics.py` — tutorial cohort funnel metrics

### Scope boundary (OUT of Phase 2c)

- New tutorial mechanics like guided-tour visuals (Phase 5+)
- A/B testing infrastructure for onboarding (post-launch)

### Deliverable

A new player who runs `/start` is guided through every Phase 0–2b system (ship building, crew, training/research/stations, expeditions) at a pace that respects the time-gating realities of the game. Funnel metrics are visible on the cohort dashboard.

---

## Phase 3 — Gameplay Layer (decomposed into 3a–e)

**Status:** Phase 3 was originally scoped as a single shipping unit covering jobs, channel events, villain takeovers, and system control. During Phase 3 brainstorming (2026-05-01) the work was split into five independently-shippable sub-phases. The originally-planned Phase 3 content survives as **Phase 3e**; the new sub-phases land foundations that the original Phase 3 had implicitly assumed.

The split reflects a shift in priority: the day-to-day game loop is currently thin (most of what exists is select-and-wait), and Phase 3 is now explicitly *the gameplay layer* — fleet operations players will actually engage with daily — not just background events.

Phase 3 sub-phases, in dependency order:

- **3a — Narrative Setting.** Canonical galaxy reference doc. (Done.)
- **3b — Lighthouses + System Character.** Replaces the abstract "system control" with the Lighthouse model from the setting. Star types and planets per system. Warden mechanic.
- **3c — Resource Loop.** Players exploit planets/system features for resources. Resources fuel home base, Lighthouse upgrades, and crew training. The day-to-day "what do I do today" loop.
- **3d — Home Base.** Unified DM-side hub for fleet ops; consolidates `/hangar`, `/fleet`, `/training`, `/research`, `/stations`, `/expedition` into a single navigation surface.
- **3e — Events: Weather + Channel + Villains.** Original Phase 3 content, reframed under the setting. Cosmic storms affect system yields; channel events spawn in enabled channels; villain takeovers attack Lighthouses.

Phase 4 (PvP) remains blocked on Phase 3 as a whole.

---

## Phase 3a — Narrative Setting

**Status:** **Done** (2026-05-01). Output: [`docs/lore/setting.md`](../lore/setting.md).

### Goal

Lock the cosmology, tone, factions, inhabitants, psychics, the Other Side, and the Lighthouse network in one canonical reference. Every Phase 3 sub-spec (and Phase 4+) leans on it instead of re-litigating world-building decisions.

### Deliverable

[`docs/lore/setting.md`](../lore/setting.md) — ten-section setting doc covering: one-line pitch; tone and creative pillars; the Cascade (the K3 → K4 attempt and its failure); today's galaxy (inner-systems nations + middle-band corps + outer-rim frontier); the Crossroads-Beacon (the official server's in-fiction home); inhabitants (humans + aliens + K3 echoes); psychics and the cults; the Other Side (named recurring antagonist minds + alien-physics terrain); the Lighthouse network; the player's place; deferred-to-spec list.

### Reuse pointers

- Setting doc names placeholder antagonists (the Sleeper, the Drowned Choir, the Conductor) and explicit categories (cults, corps, nations, weather-cults). Phase 3e specs can rename the placeholders without re-litigating the categories.

---

## Phase 3b — Lighthouses + System Character

**Status:** Spec drafted (2026-05-02). Full design: [`2026-05-02-phase-3b-lighthouses-design.md`](2026-05-02-phase-3b-lighthouses-design.md).

### Summary

Replaces the abstract "system control" concept with the canonical Lighthouse model from the setting. Phase 3b grew from a 4-mechanic plan into the gameplay-layer foundation that 3c, 3d, and 3e build on. See the dedicated spec for full mechanics, data model, commands, and verification criteria.

### Headline scope

- Per-system rich character (star + planets + features + LLM narrative seed).
- Self-elected `/dock` citizenship with switching cooldown.
- Lighthouse object per system with band-scaled slot count (rim 3 / middle 5 / inner 7).
- Wardenship claim via single Authority-vetted Phase-2b contract; tier-scaled difficulty, per-player cooldown.
- Donation flow (credits + parts, public goal embeds with patronage multiplier for citizens).
- Upgrade catalog stub: 5 categories × 2 tiers, dual Warden-side / citizen-side effects.
- Tribute ledger: passive base + activity cut, fuels Warden-flavor verbs.
- Beacon Flares Slice X: hourly-ish public events with click-to-claim, two archetypes (Salvage Drift, Signal Pulse), tiered audience delay within Sector, Warden-called variant.
- System Pride scoreboard with neighbor "stolen from / stolen by" surface.
- Inactivity lapse with dual-rate tribute defer (favorable vacation, penal panic-mode).

### Scope boundary (OUT of Phase 3b)

- Active resource gathering and sub-claims (Phase 3c).
- Home base UI consolidation (Phase 3d).
- Universe-wide flare tier, weather, channel events, named villains, contested-Lighthouse takeovers, additional flare archetypes (Phase 3e).
- PvP Warden challenges, contested claim windows, alliance Wardenship (Phase 4+).

---

## Phase 3c — Resource Loop

**Status:** Blocked on Phase 3b.

### Goal

Players exploit planets and system features for resources. Resources fuel home base, Lighthouse upgrades, and crew training. This is the day-to-day "what do I do today" loop currently missing from the game.

### Mechanics

- **Resource categories** — coarse-grained list (ore, salvage, biotech, exotic-physics samples — final list in spec).
- **Resource extraction** — a fleet/crew assignment to a planet in a system. Yields accumulate over time and are claimed at completion. Builds on the Phase 2a accrual model.
- **Resource expeditions** — a new expedition kind whose payload is resources rather than narrative outcomes.
- **Storage** — per-player resource stockpile. Soft caps to be tuned in spec.

### New entities

- **`Resource`** — definition table (category, name, base value).
- **`ResourceStock`** — per-player inventory.
- **`ResourceExtraction`** — active or scheduled extraction operations on planets.
- **`ResourceLedger`** — audit trail of grants and consumption.

### Files likely touched

- `db/models.py`, `db/migrations/versions/`
- `engine/resource_engine.py` — extraction yields, consumption, ledger writes
- `bot/cogs/resources.py` — `/resources stock`, `/resources extract`, `/resources claim`
- `scheduler/jobs/resource_extraction.py` — periodic yield computation

### Reuse pointers

- Phase 2a scheduler + accrual model — extractions are scheduled jobs with periodic yield ticks.
- Phase 2b expedition engine — resource expeditions are a new template kind.

### Scope boundary (OUT of Phase 3c)

- Specific upgrade-cost balancing (Phase 3b sets schema; Phase 3c provides feedstock; final balancing in 3e)
- Home base UI (Phase 3d)
- Player-to-player resource trading (Phase 4 or post-launch)

### Deliverable

Players assign fleets to extract resources from planets. Resources accumulate. Resources can be spent on Lighthouse upgrades and crew training.

### Verification

- Extraction yields scale with planet richness, crew assignment, ship build
- Two simultaneous extractions on different planets accrue independently
- Resource consumption (e.g., on a Lighthouse upgrade) writes a ledger row
- Cross-server: resources follow the player to any system

---

## Phase 3d — Home Base

**Status:** Blocked on Phase 3c (so resources, the most content-rich room, are populated when home base ships).

### Goal

Consolidate fleet operations into a unified DM-side surface — the player's home base. Today `/hangar`, `/fleet`, `/training`, `/research`, `/stations`, `/expedition`, and `/resources` (Phase 3c) are scattered slash commands. Home base reframes them as rooms inside one persistent navigation view.

### Mechanics

- `/base` opens a discord.py View with sub-views per room.
- **Rooms (starting list — refine in spec):** Hangar (ships), Crew Quarters, Training Grounds, Research Lab, Stations, Expedition Ops, Resource Stockpile, Lighthouse Console (visible only if Warden of at least one system).
- Each room is a thin adapter over the existing implementation cogs — no new gameplay verbs land here.
- Older slash commands remain functional; `/base` is the recommended interface.

### New entities

- Possibly none. If a `HomeBaseConfig` per player makes sense for room-order preferences, add it; otherwise everything is derived from existing state.

### Files likely touched

- `bot/views/home_base_view.py` — main View
- `bot/views/rooms/` — one View per room
- Existing fleet-side cogs — minor refactors so each room can reuse the underlying logic without going through the slash-command path

### Reuse pointers

- Phase 2c HangarView + DynamicItem pattern — same approach for every room.

### Scope boundary (OUT of Phase 3d)

- New gameplay verbs (those live in 3b/3c/3e)
- Combat depth (Phase 4)
- Mobile-optimized layout work (post-launch tuning)

### Deliverable

`/base` opens a unified view. Every existing fleet operation is reachable from a room. The Lighthouse Console room appears for Wardens.

### Verification

- Every existing slash command's primary action is reachable inside the home base view
- Switching rooms preserves View state (no message churn)
- Persistent dispatch (DynamicItem) routes clicks correctly across bot restarts

---

## Phase 3e — Events: Weather + Channel + Villains

**Status:** Blocked on Phase 3b (villain attacks target Lighthouses) and Phase 3c (weather modifies resource yields).

### Goal

Bot drives server-wide engagement under the canonical setting. Cosmic storms pass through systems and bend yields. The bot posts timed events to enabled system channels. Rare named villains target Lighthouses — a successful attack degrades the system, may strip its Warden, and is felt across multiple servers if the villain's scope is universe-wide. A rotating job board surfaces it all as actionable contracts.

### Mechanics

- **Weather events.** Storms passing through a system on schedules drawn from the system's character (3b). Weather affects resource extraction yields (3c), expedition odds, and visibility. Each weather kind is rooted in one of the over-there minds (setting §7). Weather-cult cosmetic flair can mark systems where their patron's storms are common.
- **Job board** (`/jobs`): rotating pool of contracts. Each job is a parameterized expedition or encounter template with rewards (credits, dossier leads, XP, rare parts, unique crew, resources, Lighthouse upgrade tokens). Jobs expire. Some are system-local, some sector-wide, some universe-wide. Authority-vetted contracts include the claim contracts that 3b uses for Wardenship; the job board UI is where they surface.
- **Channel events.** Bot posts a timed event to an enabled system channel (e.g., "Pirate convoy spotted — 2 hr window"). Multiple players participate; results aggregate for shared rewards.
- **Villain takeovers.** Rare scheduled events. A named villain (drawn from the over-there minds in setting §7, or their incursions) seizes one or more systems by attacking the Lighthouse. Resolution window 24–72 hours.
  - If players win: shared reward, possible unique crew drop, the villain returns to rotation for callbacks.
  - If the villain wins: the Lighthouse takes consequences. Exact failure mode (network sever, debuff settling in, upgrade reversal, Warden strip — combinations possible) tuned in this spec against 3b's state machine.
- **Cross-cutting:** debuffs and weather both layer into `engine/stat_resolver.py` as additional modifier sources.

### New entities

- **`Job`** — `id`, `title`, `scope` (system/sector/universe), `expedition_template_id` or `encounter_template_id`, `reward` JSONB, `expires_at`, `system_id` nullable, `sector_id` nullable.
- **`JobAcceptance`** — player takes a job; links to a scheduled expedition/encounter.
- **`ChannelEvent`** — timed event posted to a system. `system_id`, `spawned_at`, `expires_at`, `event_type`, `payload`, aggregated `participant_results`.
- **`WeatherEvent`** — active storm in a system. `system_id`, `kind`, `started_at`, `ends_at`, `intensity`, `over_there_mind` (which mind this kind is rooted in).
- **`VillainEvent`** — `id`, `villain_id`, `scope`, `target_lighthouse_ids`, `started_at`, `ends_at`, `resolution` enum, `collective_progress` (damage vs. villain HP).
- **`Villain`** — catalog of recurring villains. `id`, `name`, `tier`, `archetype`, `portrait_key`, `over_there_mind`, `debuff_template` JSONB.
- **`ActiveDebuff`** — `system_id` or `sector_id`, `debuff_template_id`, `applied_at`, `expires_at`.

(Note: `SectorControl` and `ControlHistory` from the original single-phase Phase 3 plan now live in 3b under the Lighthouse Warden model.)

### Files likely touched

- `bot/cogs/jobs.py` — `/jobs list`, `/jobs accept`, `/jobs status`
- `bot/cogs/events.py` — channel event command handlers
- `bot/cogs/villains.py` — villain status, participation
- `bot/cogs/weather.py` — `/weather` view per system
- `engine/weather_engine.py` — storm scheduling per system character, yield modifiers
- `engine/villain_engine.py` — aggregate player damage, determine resolution
- `scheduler/jobs/job_rotator.py` — rotates job board hourly/daily
- `scheduler/jobs/event_spawner.py` — spawns channel events per system config
- `scheduler/jobs/villain_scheduler.py` — triggers villain takeovers
- `scheduler/jobs/weather_scheduler.py` — spawns/expires weather events per system
- `engine/stat_resolver.py` — apply `ActiveDebuff` and active weather modifiers at resolve time
- `data/villains/` — villain catalog
- `data/jobs/templates.json` — job template pool
- `data/weather/` — weather catalog (kinds, durations, modifier ranges)
- `bot/cogs/admin.py` — extend `/system` config for event frequency, villain opt-out

### Reuse pointers

- Phase 2a scheduler — all spawning uses the durable scheduler.
- Phase 2b expedition engine — jobs are parameterized expeditions/encounters.
- Phase 3b Lighthouse model — villain takeovers target Lighthouses; defense outcomes write to the Lighthouse state machine.
- Stat resolver — weather and debuffs are additional modifier layers.

### Scope boundary (OUT of Phase 3e)

- PvP between players (Phase 4) — jobs and events here are PvE.
- PvP Warden challenges (Phase 4) — 3e contests Wardens via villains; 3b owns inactivity-lapse; player-vs-player Warden challenges land in Phase 4.
- Guild/alliance mechanics (future) — schema should not preclude group ownership; no group logic is built.
- Real-time battle experience (Phase 5).

### Deliverable

Players see a living job board including the claim contracts 3b uses for Wardenship. Systems feel alive — weather rolls through, channel events spawn, occasionally a villain attacks a Lighthouse and the affected servers rally. Wardens have something to defend.

### Verification

- Job board rotation: jobs expire on time, new ones appear, counts are correct
- Channel event lifecycle: spawn → participate → resolve → rewards paid
- Weather: a storm kind correctly modifies the yields/odds it's supposed to in its target system
- Villain takeover: simulate both win and loss, confirm Lighthouse state transitions and debuffs applied + expired correctly
- Villain strips a Warden when winning a Warden-held Lighthouse
- Cross-server: a universe-scale villain affects multiple test servers simultaneously

---

## Phase 4 — Fleet PvP (Channel-Native)

**Status:** Blocked on Phase 3.

### Goal

Player-vs-player fleet competition that lives entirely in Discord using channel-native turn-resolve. Everything before this has supported it.

### Mechanics

- Extend `encounter_engine.py` → multi-ship fleet battles (3–5 ships per side)
- Crew roles matter differently in PvP than PvE:
  - Gunners: damage trades during engagement rounds
  - Pilots: evasion + positioning
  - Navigators: engagement range / initiative
  - Engineers: damage control / durability regen
  - Medics: crew injury mitigation (crew can be wounded in PvP)
- Tournament/bracket support — the job board from Phase 3 surfaces tournaments as special jobs
- Ranked ladder with seasonal reset
- Spectator embed in Discord (updates round by round)
- Optional: explicit `/deploy` mechanic for fleet positioning if the team wants richer strategy
- **System control challenges (PvP):** a non-controller can formally challenge a controller for a system. Challenge has a response window (e.g., 48 hr) — if the controller accepts, a scheduled fleet match resolves control. If the controller declines or ignores past the window, control transfers by default (prevents turtling). Cooldowns prevent a controller from being challenge-spammed. This extends Phase 3's `SectorControl` — no new column, reuses `ControlHistory` with `reason = challenge`.

### New entities

- **`Fleet`** — a player's curated set of ships + assigned crew for PvP
- **`PvPMatch`** — match record with round-by-round log
- **`Tournament`** — bracket structure, rounds, prizes
- **`RankedSeason`** — season metadata, MMR tracking per player
- **`SectorChallenge`** — `system_id`, `challenger_user_id`, `defender_user_id`, `opened_at`, `responds_by`, `scheduled_match_id` nullable, `resolution` enum (pending / accepted / auto-forfeit / resolved)

### Files likely touched

- `engine/fleet_engine.py` — new multi-ship combat resolver
- `bot/cogs/pvp.py` — `/challenge`, `/fleet`, `/tournament`, `/ladder`
- `bot/cogs/control.py` — extend from Phase 3 with `/system challenge`, `/system defend`
- `scheduler/jobs/tournament_runner.py` — bracket progression
- `scheduler/jobs/challenge_expiry.py` — auto-forfeit unresponsive defenders
- Every existing cog touching ships gets a small extension for fleet concepts

### Reuse pointers

- **Stat resolver + encounter engine** — extend, don't replace
- **Scheduler** — tournaments and challenge windows are long-running jobs
- **Phase 3 `SectorControl` + `ControlHistory`** — challenge resolution writes to these
- **Spectator view** — reuse the race narrative renderer pattern

### Scope boundary (OUT of Phase 4)

- Real-time active-combat app (Phase 5)
- Artist-tier ship art (Phase 5)

### Deliverable

Ranked PvP ladder, seasonal rewards, tournaments with real stakes. Player-vs-player system challenges give controlled systems political life. Competitive endgame lives entirely inside Discord.

### Verification

- Match determinism: same inputs → same outputs (for replay / dispute resolution)
- MMR correctness across a simulated season
- Tournament bracket edge cases: odd player counts, dropouts, byes
- Spectator update rate doesn't spam channels
- System challenge flow: open → accept → match → winner takes control (recorded in `ControlHistory`)
- System challenge auto-forfeit: unresponsive defender loses control at window expiry
- Challenge cooldowns prevent spam; challenge-initiated control changes do not bypass villain strip rules

---

## Phase 5 — Artist Tiers + Discord Activity (External Work)

**Status:** Blocked on Phase 4. Partially gated on external artist capacity.

### Goal

Visual identity lands. Real-time fleet battle becomes an option alongside channel-native Phase 4.

### Two workstreams

**5a. Artist tiers (ongoing, can start during Phase 4):**

- Tiered ship art brief: common → legendary, within the salvage-pulp lane (rusted junkers, chrome psychic cruisers, bio-organic hulls — artist choice)
- Tiered crew portraits
- Event art (villains, job illustrations, expedition vignettes)
- Art swap-in happens incrementally — replace placeholder art card-by-card as tiers ship

**5b. Discord activity (engineering lift):**

- Discord activity SDK app hosted alongside API
- Loads a player's universe-wide fleet via existing API routes
- Real-time combat minigame (vs. Phase 4's turn-resolve)
- Launched from Discord with `/battle activity`

### Files likely touched

- `activity/` — new top-level module for Discord activity
- `activity/client/` — web client (framework TBD in spec)
- `api/routes/activity.py` — fleet loading, match auth
- `art/` — art asset pipeline: tier metadata, artist brief templates, swap scripts
- Card renderer — support tiered art fallback (use tier N if available, else lower tier, else placeholder)

### Reuse pointers

- **Existing API** for fleet/crew/ship data — activity is a new client against the same API
- **Auth** — extend existing Discord OAuth
- **Phase 4 fleet engine** — activity is a new presentation layer, combat resolution can share core math

### Scope boundary (OUT of Phase 5)

- Standalone web/desktop app (possible Phase 6+)
- Cross-platform mobile (post-launch consideration)

### Deliverable

The game has real visual identity. Players who want active battle have a minigame; players who prefer Discord-native keep the channel turn-resolve.

### Verification

- Activity launches from Discord, loads fleet, runs a match end-to-end
- Tiered art fallback works: every rarity renders something, no broken image
- Match results from activity write back to the same ranked ladder as Phase 4

---

## Cross-cutting concerns

### Scheduler durability (Phase 2+)

The scheduler must:

- Persist all scheduled jobs to the database as source of truth
- Use Redis for fast-path queue behavior but recover from DB on restart
- Be idempotent (a job firing twice should not double-resolve)
- Emit OpenTelemetry spans for every fire
- Emit Prometheus counters `dare2drive_scheduler_jobs_total{job_type, result}`

### Notification etiquette

Every user-facing notification path must:

- Be opt-out-able per category (timer completion, event spawn, villain alerts)
- Rate-limit per user (max N notifications/hour, configurable)
- Batch where possible (one message covering multiple completions instead of N messages)

### Observability expectations

Every new command and background job adds:

- Trace span with `user_id`, `system_id`, `sector_id`, relevant entity IDs
- Metric counter for invocation and result
- Structured log entry with correlation IDs

### Migration discipline

- All migrations are reviewed for up/down correctness
- Data backfills use separate scripts under `scripts/backfills/` — not embedded in migrations
- No destructive migrations without explicit approval

---

## Open questions (deferred to phase specs)

Each is resolved when the corresponding phase is brainstormed. None need answers now.

- **Phase 0:** Final slot rename list (is `tires → landing_gear` or `tires → thrusters`?). Encounter type rename list. Tutorial copy voice.
- **Phase 1:** Crew archetype → stat-boost mapping table. Crew XP curve. Naming generator approach.
- **Phase 2a:** Scheduler technology choice (rq vs arq vs custom). Where the scheduler runs (in-bot, in-API, or its own worker process). Notification transport (DM vs thread mention vs both). Single polymorphic `Timer` table vs separate Training/Research/BuildJob.
- **Phase 2b:** Expedition event pool depth at launch. Response-window length per event. Auto-resolution defaults (best/median/worst branch).
- **Phase 3:** Villain catalog seed list. Job rotation cadence. Debuff magnitudes — need playtesting. Control tribute rate, inactivity lapse threshold, Control Contract difficulty tuning. Controller banner rendering in channel (embed style).
- **Phase 4:** Ranked matchmaker choice (MMR, Elo, Glicko-2). Tournament formats supported. Challenge cooldown duration, response-window length, whether auto-forfeit counts toward challenger MMR.
- **Phase 5:** Activity client framework. Art pipeline (manual commission vs. solicit vs. AI-assist starter art).

---

## Universe-wide bigger-picture notes

- **Future ideas the user deferred:** guild/faction sector, alliances, expanded player-to-player trading beyond the existing market. All additive; can slot into Phases 3–5 when surfaced.
- **Guilds/alliances will hang off system control.** The `SectorControl` schema is deliberately single-user for now but should be extensible to group ownership in a later phase: a guild could hold a system collectively, split tribute by contribution, and defend as a group in challenges. When guilds land, the natural shape is adding a `controller_guild_id` column (nullable, mutually exclusive with `controller_user_id`) plus a `GuildMembership` and `Guild` table, rather than re-modeling.
- **Artist freedom is the creative constraint we optimized for.** Every phase preserves it.
- **The scheduler, crew, and multi-tenancy are the three foundations.** Phases 0–2b exist to make Phases 3+ possible. Don't rush them.
