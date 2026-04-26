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

These were intentionally stubbed in the initial Phase 2a ship — or surfaced during the post-merge deploy — and need addressing before Phase 2b expeditions, or in a Phase 2a.1 patch. They are independent and can land separately. Items are grouped by category so they can be triaged.

#### Gameplay completeness

- **Ship-build hull creation + input consumption + slash command surface.** `scheduler/jobs/timer_complete.py:_resolve_ship_build` writes a `RewardLedger` entry with `delta={"new_ship": {...}}` and emits a "Ship build complete" DM, but does not actually create a `Build` row, mint a Ship Title, or consume the recipe's `input_scrapped_ship_count` wrecks. The `/build construct/status/cancel` slash commands were also removed before launch (the chosen group name `build` collided with hangar's existing `/build` for parts management). Re-introduce as `/shipyard construct/status/cancel` once the hull-creation logic is built. Open questions: does "Reconstructed Hull" produce a fresh empty `Build`, or one pre-equipped with parts salvaged from the input wrecks? Which `hull_class` is selected — fixed (`hauler`) per recipe, or chosen by the player at start time?
- **Research fleet-buff application + expiry.** `scheduler/jobs/timer_complete.py:_resolve_research` writes a `RewardLedger` entry with `delta={"fleet_buff": {"stat": ..., "pct": ..., "duration_hours": 48}}` but `engine/stat_resolver.py` does not read active fleet buffs. Players see "Research complete" DMs but their `effective_acceleration` / `effective_durability` / `effective_weather_performance` never actually change. Needs (a) a `FleetBuff` table or derived view from `reward_ledger`, (b) `stat_resolver` integration to apply active buffs at resolve time, (c) expiry — buffs naturally drop off after `duration_hours` (could be a scheduler job, or just an `applied_at + duration > now()` filter at read time).
- **DM-closed user feedback loop.** `bot/notifications.py:_deliver_batch` silently XACKs entries when `discord.Forbidden` fires (player has DMs closed), incrementing the `dm_closed` notification metric. Players never learn their notifications are being dropped. Optional follow-on: track per-user `dm_closed` streaks and surface a one-time warning in a guild channel the player has used recently, prompting them to either re-open DMs or set the relevant `notification_prefs` category to `off`.

#### Test quality

- **Cog test mocks accept any signature.** All four cog test files use `monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))`. `AsyncMock` accepts any positional/keyword arguments, so when `get_active_system`'s real signature was `(interaction, session)` and the cog called it as `get_active_system(interaction)`, the tests passed but production crashed with `TypeError: missing 1 required positional argument`. Remediation: replace these monkeypatches with `AsyncMock(spec=get_active_system)` (or a typed protocol stub), so signature drift fails the relevant test at collection time. Same pattern applies to any future cog test that mocks shared helpers — consider a shared fixture in `tests/conftest.py`.

#### Security / correctness

- **Tutorial gating uses leaf names; subcommands bypass restrictions.** `bot/cogs/tutorial.py:STEP_ALLOWED_COMMANDS` and `ALWAYS_ALLOWED` are keyed by the slash command's leaf name. `interaction.command.name` returns the leaf only, so `/training start`, `/research start`, and the top-level `/start` all match `"start"` in `ALWAYS_ALLOWED` (originally meant only for `/start`). Result: every group-subcommand whose leaf name happens to match a leaf in the allow-list is unintentionally allowed pre-tutorial. Fix is to (a) switch the gating call in `bot/main.py:TutorialCommandTree.interaction_check` from `interaction.command.name` to `qualified_name`, (b) update `STEP_ALLOWED_COMMANDS` and `ALWAYS_ALLOWED` to use full paths (`"build preview"`, `"build mint"`, etc.). Observability already uses qualified name — only the gating call still uses leaf as a transitional measure.

#### Operational / deploy hygiene

- **Re-connect `scheduler-worker` Railway service to GitHub for auto-deploy.** The service was created via `railway add` and the first deploy was via `railway up` from a local checkout. It currently has no GitHub source bound, so commits to `demo` will not auto-deploy the worker. In the Railway dashboard for the `scheduler-worker` service: Settings → Source → connect to `JordanGibbons/Dare2Drive`, Branch = `demo`. After connecting, the start command in dashboard ("Custom Start Command") must remain `python -m scheduler.worker` (currently set manually).
- **Un-pause `scheduler-worker-down` alert.** Set to `isPaused: true` in `monitoring/grafana-stack/grafana/alerting/rules.yml` until Prometheus is confirmed scraping `up{job="scheduler-worker"} == 1`. After Phase 2a #4 (the prom.yml scrape job) lands and Prometheus redeploys, verify in Grafana → Alerting that `up{job="scheduler-worker"}` returns `1`, then flip `isPaused` back to `false` in a small follow-up PR (or via the Grafana UI; git-sync will write back).
- **Bump parent repo's `monitoring/grafana-stack` submodule pointer.** The submodule on `dare2drive-monitoring` `main` is ahead of the parent's recorded SHA. Railway-side this doesn't matter (each Grafana service tracks the submodule repo directly), but for source-of-truth correctness anyone cloning the parent and running `git submodule update --init` should land on the latest submodule commit. One small follow-up PR.
- **Clean up the no-op `RAILWAY_RUN_COMMAND` variable on `scheduler-worker`.** Set during deploy debugging hoping Railway honored it as a start-command override; it doesn't. Harmless but confusing in the variables list. Remove via dashboard.
- **Delete stale `feat/scheduler-worker-scrape` branch on `dare2drive-monitoring`.** Was merged via PR #4 (squash) but the local branch on origin still has my orphan dashboard commit pushed before #4 merged. Trivial cleanup: `gh api -X DELETE repos/JordanGibbons/dare2drive-monitoring/git/refs/heads/feat/scheduler-worker-scrape`.
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

## Phase 3 — Job Board + Channel Events + Villain Takeovers + System Control

**Status:** Blocked on Phase 2b.

### Goal

Bot drives server-wide engagement. A rotating job board, scheduled events that appear in system channels, rare villain takeovers with real consequences, and a persistent **system control** layer that rewards long-term investment in specific systems.

### Mechanics

- **Job board** (`/jobs`): rotating pool of contracts. Each job is a parameterized expedition or encounter template with rewards (credits, dossier leads, XP, rare parts, unique crew). Jobs expire. Some jobs are system-local, some sector-wide, some universe-wide.
- **Channel events:** bot posts a timed event to an enabled system channel (e.g., "Pirate convoy spotted — 2 hr window"). Multiple players participate. Results aggregate for shared rewards.
- **Villain takeovers:** rare scheduled events. A named villain seizes one or more systems (can span multiple sectors for universe-level takeovers). Players across affected servers rally fleets. Resolution window is ~24–72 hours.
  - If villain wins: system/sector debuff applied (e.g., credit yields -20%, encounter stats -5%) for a duration.
  - If villain seizes a player-controlled system and wins: the controller **loses control** on top of the debuff.
  - If players win: shared reward, possible unique crew drop, defeated villain added to rotation for future callbacks.
- **System control:** one player can hold control of a system at a time. Control is fiction-flavored as "kingpin / harbormaster / warden" — the controller's banner appears in the channel.
  - **Claim:** completing a special Control Contract (from the job board) while no current controller exists grants control. Contracts are harder than normal jobs and have a cooldown after any control change.
  - **Benefits** (starting list — tune in spec): small % tribute on credit rewards earned by other players in the system, priority access to rare system-local jobs, cosmetic banner/flair, bonus share of villain-defeat rewards in controlled systems.
  - **Defense in Phase 3:** PvE only. Villain takeovers are the primary contest. Also: if the controller goes inactive for a threshold duration (e.g., 14 days no encounters in that system), control lapses and the system becomes claimable again.
  - **Defense in Phase 4:** player-vs-player challenges open the control up to PvP contestation (see Phase 4).
  - **Multi-system:** a player may hold control of multiple systems simultaneously — more holdings mean more tribute but also more defense burden.

### New entities

- **`Job`** — `id`, `title`, `scope` (system/sector/universe), `expedition_template_id` or `encounter_template_id`, `reward` JSONB, `expires_at`, `system_id` nullable, `sector_id` nullable.
- **`JobAcceptance`** — player takes a job; links to a scheduled expedition/encounter.
- **`ChannelEvent`** — timed event posted to a system. `system_id`, `spawned_at`, `expires_at`, `event_type`, `payload`, aggregated `participant_results`.
- **`VillainEvent`** — `id`, `villain_id`, `scope` (system/sector/universe), `affected_system_ids`, `started_at`, `ends_at`, `resolution` enum, `collective_progress` (damage vs. villain HP).
- **`Villain`** — catalog of recurring villains. `id`, `name`, `tier`, `archetype`, `portrait_key`, `debuff_template` JSONB.
- **`ActiveDebuff`** — `system_id` or `sector_id`, `debuff_template_id`, `applied_at`, `expires_at`.
- **`SectorControl`** — `system_id` (unique), `controller_user_id`, `claimed_at`, `last_active_at`, `tribute_rate`, `lapses_at` (nullable — inactivity-based expiry).
- **`ControlHistory`** — audit log of control changes. `system_id`, `previous_controller_id`, `new_controller_id` (nullable = lapsed/villain-stripped), `changed_at`, `reason` enum (claimed/lapsed/villain/challenge).

### Files likely touched

- `bot/cogs/jobs.py` — `/jobs list`, `/jobs accept`, `/jobs status`
- `bot/cogs/events.py` — channel event command handlers
- `bot/cogs/villains.py` — villain status, participation
- `bot/cogs/control.py` — `/system info`, `/system claim`, `/system tribute` (view)
- `engine/system_control.py` — claim validation, tribute calculation, lapse check
- `scheduler/jobs/control_lapse_checker.py` — periodic job that expires inactive control
- `scheduler/jobs/job_rotator.py` — rotates job board hourly/daily
- `scheduler/jobs/event_spawner.py` — spawns channel events per system config
- `scheduler/jobs/villain_scheduler.py` — triggers villain takeovers
- `engine/villain_engine.py` — aggregate player damage, determine resolution
- `engine/stat_resolver.py` — apply `ActiveDebuff` modifiers when player is in a debuffed system/sector
- `data/villains/` — villain catalog
- `data/jobs/templates.json` — job template pool
- `bot/cogs/admin.py` — extend `/system` config for event frequency, villain opt-out

### Reuse pointers

- **Scheduler from Phase 2** — all spawning uses the durable scheduler
- **Expedition engine from Phase 2** — jobs are parameterized expeditions/encounters
- **Stat resolver** — debuffs plug in as another modifier layer

### Scope boundary (OUT of Phase 3)

- PvP between players (Phase 4) — jobs and events here are PvE
- **PvP control challenges** (Phase 4) — Phase 3 system control is PvE only; villains and inactivity are the sole threats
- Guild/alliance mechanics (future) — Phase 3 models control as single-player only; the schema should not preclude future group ownership but no group logic is built
- Real-time battle experience (Phase 5)

### Deliverable

Players see a living job board. Systems feel alive with scheduled events. Villain takeovers are memorable server-wide moments that change gameplay for a bounded time. Systems have named kingpins whose banners appear in channel, creating identity and long-term stakes.

### Verification

- Job board rotation: jobs expire on time, new ones appear, counts are correct
- Channel event lifecycle: spawn → participate → resolve → rewards paid
- Villain takeover: simulate both win and loss, confirm debuff applied + expired correctly
- Villain strips player control when seizing a controlled system and winning
- Cross-server: a universe-scale villain affects multiple test servers simultaneously
- System claim: completing a Control Contract on an uncontrolled system grants control; tribute flows correctly on subsequent other-player credit rewards
- Lapse: simulate controller inactivity past threshold → control lapses, history row written

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
