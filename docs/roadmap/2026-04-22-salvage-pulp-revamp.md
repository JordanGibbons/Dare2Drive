# Dare2Drive → Salvage-Pulp Space Revamp — Roadmap

**Status:** Approved 2026-04-22
**Owner:** Jordan
**Scope:** Multi-phase revamp of Dare2Drive from a car-racing game into a salvage-pulp spaceship game with multi-tenant support across Discord servers.

---

## Context

Dare2Drive today is a Discord bot + FastAPI game where players open packs of car parts, build a 7-slot car, and race. The system is well-architected (async SQLAlchemy, 10 migrations, observability already wired up via Prometheus/Loki/Tempo/Grafana, no live users yet).

Two problems with the current premise:

1. **Art pipeline risk.** Getting artists to draw endless fully-fictional-but-not-infringing cars is a real creative constraint that will throttle content velocity.
2. **Weak bot heartbeat.** The bot only acts when players act. There's nothing ticking in the background that brings players back, and nothing that makes the server itself feel alive.

This plan pivots the game to a **salvage-pulp spaceship universe** (outer-rim scrappers meet 70s pulp sci-fi — rusted junker hulls alongside chrome psychic cruisers alongside bio-organic alien ships). The pivot unlocks maximum artist freedom, enables a fleshed-out fictional universe with crew characters and scheduled villain events, and reframes the Discord-server-installed-base as the in-fiction universe map.

The intended outcome is a multi-server Discord game where:

- Players collect cards (parts + crew), build ships, and field them in events
- The bot runs persistent background systems (training timers, passive yield, multi-hour expeditions with choice points) that give players things to come back to
- A revolving job board and scheduled channel events drive server-wide engagement
- Scheduled villain takeovers create memorable moments with shared debuffs if the server loses
- Players can claim **control of sectors**, earning tribute from other players' activity there; control can be contested by villains (PvE) or by other players (PvP), laying foundations for later guild/alliance play
- Every installed server is a system in one shared universe — your fleet follows you anywhere
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
  - **Server (Discord guild) = "System"** (a collection of sectors, e.g., a star system or constellation).
  - **Channel = "Sector"** (specific game-enabled channels within a system).
  - **Universe = federation** of all D2D-enabled systems.
- **Player state is universe-wide.** Cards, crew, ship builds, and credits live on the player profile and follow them to any server. No per-server save file. Leaderboards and ongoing storylines can still be sector/system/universe scoped.
- **Travel is implicit.** Players are "active" in whichever sector (channel) they're typing in. No `/travel` command in Phase 0–3. Explicit fleet deployment may be added in Phase 4+ as a PvP mechanic.
- **Admin opt-in.** Server owners explicitly register which channels are sectors. The bot does not auto-enable itself in every channel it can see.
- **Scheduler is load-bearing.** A durable, restart-safe scheduler is the backbone of Phases 2+. Invest in it properly in Phase 2.
- **Observability from day one.** All new systems emit traces (OpenTelemetry), metrics (`dare2drive_*` Prometheus), and structured logs. Existing infra handles the rest.

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

## Phase 0 — Foundation: Theme Pivot + Multi-Tenant Sector Model

**Status:** Not started. No live users, so rename + restructure can land together.

### Goal

- Every model, enum, copy string, card JSON, and tutorial step reads as ships/salvage-pulp.
- The codebase supports multi-tenant operation: servers (systems) register, channels (sectors) are explicitly enabled, and player state is server-agnostic.
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

- **`System`** (one row per Discord guild using the bot). `guild_id`, `name`, `registered_at`, `owner_discord_id`, optional `flavor_text`.
- **`Sector`** (one row per enabled channel). `channel_id`, `system_id`, `name`, `enabled_at`, config JSONB.
- **Player-active-sector tracking** — no persistent column needed; derived from message context per command.

### Files likely touched

- `db/models.py` — rename models and enums
- `db/migrations/versions/` — new migration for renames + System/Sector tables
- `data/cards/*.json` — rewrite copy, keep stat structure
- `data/loot_tables.json` — rewrite pack display names/flavor
- `bot/cogs/*.py` — every cog needs copy updates; race cog becomes encounter cog
- `bot/cogs/tutorial.py` — rewrite tutorial script
- `bot/cogs/admin.py` — add `/sector enable`, `/sector disable`, `/system info` commands
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

- No crew system (Phase 1)
- No timers/scheduler (Phase 2)
- No job board or events (Phase 3)
- No new art — existing card art stays as placeholder

### Deliverable

Existing game loop functional in the new ship vocabulary. Server owners can register sectors. Player state is not tied to any single server.

### Verification

- Run existing test suite — all tests pass after renames
- Manual smoke test: open pack, build ship, run encounter, in two different test Discord servers with the same player account — cards should appear in both
- Grep for "car", "race", car-slot names to confirm no leaks in copy
- Alembic migration up/down round-trips cleanly
- Tutorial walkthrough end-to-end in new vocabulary

---

## Phase 1 — Crew System

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

## Phase 2 — Background Progression (Scheduler + Timers + Accrual + Expeditions)

**Status:** Blocked on Phase 1.

### Goal

The bot heartbeat. Three time-scale engagement rhythms running in the background:

- **Timers** (15 min – 2 hr): crew training, research projects, ship builds
- **Accrual** (overnight): crew assigned to stations generate credits/XP/resources passively
- **Expeditions** (4 – 12 hr): narrative missions with mid-flight decision points

The scheduler infrastructure built here is load-bearing for Phases 3+.

### Mechanics

- **Scheduler:** durable, restart-safe. Must survive bot restarts without missing ticks or duplicating fires. Recommended approach: Redis-backed durable queue (bot already uses Redis) with DB-persisted job records as source of truth.
- **Timers:** finite-duration tasks tied to a user. Completion DMs the user (rate-limited, opt-outable).
- **Accrual:** periodic yield computation (e.g., every N minutes) for crew assigned to stations. Collected on next login via `/claim`.
- **Expeditions:** scheduled jobs with interior "events" that fire partway through. If the user responds to an event in the response window, their choice applies. If they don't, it auto-resolves.

### New entities

- **`ScheduledJob`** — durable job record. `id`, `user_id`, `job_type` enum, `payload` JSONB, `scheduled_for`, `fired_at`, `resolved_at`, `state` enum.
- **`Training`**, **`Research`**, **`BuildJob`** (or one polymorphic `Timer` table) — concrete timer types.
- **`Expedition`** — `id`, `user_id`, `ship_id`, `assigned_crew_ids`, `started_at`, `duration`, `scheduled_events` JSONB, `state`, `outcome_summary`.
- **`StationAssignment`** — `crew_id` → `station_type` for accrual.

### Files likely touched

- `scheduler/` — new top-level module
- `scheduler/engine.py` — durable scheduler loop
- `scheduler/jobs/` — per-job-type handlers
- `bot/cogs/fleet.py` — `/fleet`, `/training`, `/research`, `/stations`, `/claim`
- `bot/cogs/expeditions.py` — `/expedition start`, `/expedition status`, `/expedition respond`
- `engine/expedition_engine.py` — event rolling, resolution, narrative output
- `data/expeditions/` — expedition templates (routes, event tables, reward tables)
- `db/migrations/versions/` — new migrations
- `bot/notifications.py` — DM rate limiter + opt-out

### Reuse pointers

- **Redis connection pooling** — existing `config/redis.py` (or equivalent) pattern
- **OpenTelemetry spans** — wrap every scheduler fire with a span for trace correlation with Grafana
- **Prometheus counters** — add `dare2drive_scheduler_jobs_total{job_type, result}` for observability
- **Encounter engine** — expedition outcome rolls reuse `engine/stat_resolver.py` for stat-dependent event odds

### Scope boundary (OUT of Phase 2)

- Job board (Phase 3) — expeditions here are user-initiated, not advertised on a board
- Villain events (Phase 3)
- PvP mechanics (Phase 4)

### Deliverable

Players start timers, assign crew to stations, launch expeditions. Bot pings them when work completes (respectfully). Scheduler survives deploys.

### Verification

- Chaos test: kill bot mid-job → jobs resume correctly on restart
- Load test: 1000 concurrent scheduled jobs
- Rate-limit test: notification throttling respects user opt-out + per-hour cap
- Integration: full expedition with interior event choice → outcome narrative delivered

---

## Phase 3 — Job Board + Channel Events + Villain Takeovers + Sector Control

**Status:** Blocked on Phase 2.

### Goal

Bot drives server-wide engagement. A rotating job board, scheduled events that appear in sector channels, rare villain takeovers with real consequences, and a persistent **sector control** layer that rewards long-term investment in specific sectors.

### Mechanics

- **Job board** (`/jobs`): rotating pool of contracts. Each job is a parameterized expedition or encounter template with rewards (credits, dossier leads, XP, rare parts, unique crew). Jobs expire. Some jobs are sector-local, some system-wide, some universe-wide.
- **Channel events:** bot posts a timed event to an enabled sector channel (e.g., "Pirate convoy spotted — 2 hr window"). Multiple players participate. Results aggregate for shared rewards.
- **Villain takeovers:** rare scheduled events. A named villain seizes one or more sectors (can span multiple systems for universe-level takeovers). Players across affected servers rally fleets. Resolution window is ~24–72 hours.
  - If villain wins: sector/system debuff applied (e.g., credit yields -20%, encounter stats -5%) for a duration.
  - If villain seizes a player-controlled sector and wins: the controller **loses control** on top of the debuff.
  - If players win: shared reward, possible unique crew drop, defeated villain added to rotation for future callbacks.
- **Sector control:** one player can hold control of a sector at a time. Control is fiction-flavored as "kingpin / harbormaster / warden" — the controller's banner appears in the channel.
  - **Claim:** completing a special Control Contract (from the job board) while no current controller exists grants control. Contracts are harder than normal jobs and have a cooldown after any control change.
  - **Benefits** (starting list — tune in spec): small % tribute on credit rewards earned by other players in the sector, priority access to rare sector-local jobs, cosmetic banner/flair, bonus share of villain-defeat rewards in controlled sectors.
  - **Defense in Phase 3:** PvE only. Villain takeovers are the primary contest. Also: if the controller goes inactive for a threshold duration (e.g., 14 days no encounters in that sector), control lapses and the sector becomes claimable again.
  - **Defense in Phase 4:** player-vs-player challenges open the control up to PvP contestation (see Phase 4).
  - **Multi-sector:** a player may hold control of multiple sectors simultaneously — more holdings mean more tribute but also more defense burden.

### New entities

- **`Job`** — `id`, `title`, `scope` (sector/system/universe), `expedition_template_id` or `encounter_template_id`, `reward` JSONB, `expires_at`, `sector_id` nullable, `system_id` nullable.
- **`JobAcceptance`** — player takes a job; links to a scheduled expedition/encounter.
- **`ChannelEvent`** — timed event posted to a sector. `sector_id`, `spawned_at`, `expires_at`, `event_type`, `payload`, aggregated `participant_results`.
- **`VillainEvent`** — `id`, `villain_id`, `scope` (sector/system/universe), `affected_sector_ids`, `started_at`, `ends_at`, `resolution` enum, `collective_progress` (damage vs. villain HP).
- **`Villain`** — catalog of recurring villains. `id`, `name`, `tier`, `archetype`, `portrait_key`, `debuff_template` JSONB.
- **`ActiveDebuff`** — `sector_id` or `system_id`, `debuff_template_id`, `applied_at`, `expires_at`.
- **`SectorControl`** — `sector_id` (unique), `controller_user_id`, `claimed_at`, `last_active_at`, `tribute_rate`, `lapses_at` (nullable — inactivity-based expiry).
- **`ControlHistory`** — audit log of control changes. `sector_id`, `previous_controller_id`, `new_controller_id` (nullable = lapsed/villain-stripped), `changed_at`, `reason` enum (claimed/lapsed/villain/challenge).

### Files likely touched

- `bot/cogs/jobs.py` — `/jobs list`, `/jobs accept`, `/jobs status`
- `bot/cogs/events.py` — channel event command handlers
- `bot/cogs/villains.py` — villain status, participation
- `bot/cogs/control.py` — `/sector info`, `/sector claim`, `/sector tribute` (view)
- `engine/sector_control.py` — claim validation, tribute calculation, lapse check
- `scheduler/jobs/control_lapse_checker.py` — periodic job that expires inactive control
- `scheduler/jobs/job_rotator.py` — rotates job board hourly/daily
- `scheduler/jobs/event_spawner.py` — spawns channel events per sector config
- `scheduler/jobs/villain_scheduler.py` — triggers villain takeovers
- `engine/villain_engine.py` — aggregate player damage, determine resolution
- `engine/stat_resolver.py` — apply `ActiveDebuff` modifiers when player is in a debuffed sector/system
- `data/villains/` — villain catalog
- `data/jobs/templates.json` — job template pool
- `bot/cogs/admin.py` — extend `/sector` config for event frequency, villain opt-out

### Reuse pointers

- **Scheduler from Phase 2** — all spawning uses the durable scheduler
- **Expedition engine from Phase 2** — jobs are parameterized expeditions/encounters
- **Stat resolver** — debuffs plug in as another modifier layer

### Scope boundary (OUT of Phase 3)

- PvP between players (Phase 4) — jobs and events here are PvE
- **PvP control challenges** (Phase 4) — Phase 3 sector control is PvE only; villains and inactivity are the sole threats
- Guild/alliance mechanics (future) — Phase 3 models control as single-player only; the schema should not preclude future group ownership but no group logic is built
- Real-time battle experience (Phase 5)

### Deliverable

Players see a living job board. Sectors feel alive with scheduled events. Villain takeovers are memorable server-wide moments that change gameplay for a bounded time. Sectors have named kingpins whose banners appear in channel, creating identity and long-term stakes.

### Verification

- Job board rotation: jobs expire on time, new ones appear, counts are correct
- Channel event lifecycle: spawn → participate → resolve → rewards paid
- Villain takeover: simulate both win and loss, confirm debuff applied + expired correctly
- Villain strips player control when seizing a controlled sector and winning
- Cross-server: a universe-scale villain affects multiple test servers simultaneously
- Sector claim: completing a Control Contract on an uncontrolled sector grants control; tribute flows correctly on subsequent other-player credit rewards
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
- **Sector control challenges (PvP):** a non-controller can formally challenge a controller for a sector. Challenge has a response window (e.g., 48 hr) — if the controller accepts, a scheduled fleet match resolves control. If the controller declines or ignores past the window, control transfers by default (prevents turtling). Cooldowns prevent a controller from being challenge-spammed. This extends Phase 3's `SectorControl` — no new column, reuses `ControlHistory` with `reason = challenge`.

### New entities

- **`Fleet`** — a player's curated set of ships + assigned crew for PvP
- **`PvPMatch`** — match record with round-by-round log
- **`Tournament`** — bracket structure, rounds, prizes
- **`RankedSeason`** — season metadata, MMR tracking per player
- **`SectorChallenge`** — `sector_id`, `challenger_user_id`, `defender_user_id`, `opened_at`, `responds_by`, `scheduled_match_id` nullable, `resolution` enum (pending / accepted / auto-forfeit / resolved)

### Files likely touched

- `engine/fleet_engine.py` — new multi-ship combat resolver
- `bot/cogs/pvp.py` — `/challenge`, `/fleet`, `/tournament`, `/ladder`
- `bot/cogs/control.py` — extend from Phase 3 with `/sector challenge`, `/sector defend`
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

Ranked PvP ladder, seasonal rewards, tournaments with real stakes. Player-vs-player sector challenges give controlled sectors political life. Competitive endgame lives entirely inside Discord.

### Verification

- Match determinism: same inputs → same outputs (for replay / dispute resolution)
- MMR correctness across a simulated season
- Tournament bracket edge cases: odd player counts, dropouts, byes
- Spectator update rate doesn't spam channels
- Sector challenge flow: open → accept → match → winner takes control (recorded in `ControlHistory`)
- Sector challenge auto-forfeit: unresponsive defender loses control at window expiry
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

- Trace span with `user_id`, `sector_id`, `system_id`, relevant entity IDs
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
- **Phase 2:** Scheduler technology choice (rq vs arq vs custom). Notification transport (DM vs thread mention vs both). Expedition event pool depth at launch.
- **Phase 3:** Villain catalog seed list. Job rotation cadence. Debuff magnitudes — need playtesting. Control tribute rate, inactivity lapse threshold, Control Contract difficulty tuning. Controller banner rendering in channel (embed style).
- **Phase 4:** Ranked matchmaker choice (MMR, Elo, Glicko-2). Tournament formats supported. Challenge cooldown duration, response-window length, whether auto-forfeit counts toward challenger MMR.
- **Phase 5:** Activity client framework. Art pipeline (manual commission vs. solicit vs. AI-assist starter art).

---

## Universe-wide bigger-picture notes

- **Future ideas the user deferred:** guild/faction system, alliances, expanded player-to-player trading beyond the existing market. All additive; can slot into Phases 3–5 when surfaced.
- **Guilds/alliances will hang off sector control.** The `SectorControl` schema is deliberately single-user for now but should be extensible to group ownership in a later phase: a guild could hold a sector collectively, split tribute by contribution, and defend as a group in challenges. When guilds land, the natural shape is adding a `controller_guild_id` column (nullable, mutually exclusive with `controller_user_id`) plus a `GuildMembership` and `Guild` table, rather than re-modeling.
- **Artist freedom is the creative constraint we optimized for.** Every phase preserves it.
- **The scheduler, crew, and multi-tenancy are the three foundations.** Phases 0–2 exist to make Phases 3+ possible. Don't rush them.
