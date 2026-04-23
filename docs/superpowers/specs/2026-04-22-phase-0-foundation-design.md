# Phase 0 — Foundation: Theme Pivot + Multi-Tenant Sector Model

**Status:** Approved 2026-04-22
**Phase:** 0 of 6 (see [salvage-pulp revamp roadmap](../../roadmap/2026-04-22-salvage-pulp-revamp.md))
**Owner:** Jordan
**Estimated scope:** Single PR; no live users, so a big rename + restructure is acceptable.

---

## Context

This phase lays the foundation for the larger Salvage-Pulp revamp by doing two structurally heavy things at once:

1. **Theme pivot.** Rename every car/race noun to its salvage-pulp ship equivalent across the schema, code, copy, card data, tutorial, and API surface. The existing game loop (pack → build → race) functions identically post-pivot — only the vocabulary changes.
2. **Multi-tenant foundation.** Introduce `System` (= Discord guild) and `Sector` (= enabled Discord channel) tables, register them on bot install / admin command, and constrain gameplay commands to enabled sectors. Player state remains universe-wide.

The reason both land together: the project has zero live users today. Adding the multi-tenant layer in a separate PR after the rename would require a second migration that touches many of the same models again. Doing them in one fresh `0001_initial.py` is cheaper and gives Phase 0 a clean canonical shape.

Phase 0 ships **no new mechanics**. No crew (Phase 1), no scheduler (Phase 2), no events or sector control (Phase 3). The deliverable is "the existing game, in the new universe, ready for multi-tenant deployment."

---

## Locked decisions

These were settled during brainstorming. Implementation must respect them — re-litigation belongs in a follow-on spec.

### Migration strategy

- **Squash all 10 existing migrations into a single fresh `0001_initial.py`.**
- Reasoning: zero live users; preserving migration history has no operational value because no production environment will ever roll back to the car-era schema. New contributors only ever see the post-pivot schema as the canonical starting point.
- Post-pivot, normal migration discipline resumes — Phase 1+ adds incremental migrations on top of `0001`.

### Slot renames (load-bearing)

| Old | New |
|---|---|
| `engine` | `reactor` |
| `transmission` | `drive` |
| `tires` | `thrusters` |
| `suspension` | `stabilizers` |
| `chassis` | `hull` |
| `turbo` | `overdrive` |
| `brakes` | `retros` |

### Race format (cut from 6 to 3)

`CarClass` enum replaced by `RaceFormat` enum with three values:

| Value | Meaning |
|---|---|
| `sprint` | Short, all-out (replaces `drag`) |
| `endurance` | Long-haul / multi-leg (replaces `circuit`) |
| `gauntlet` | Hazard-heavy / maneuver-heavy (collapses `drift` + `rally`) |

Removed: `street` (was a casual default — no longer modeled as a format, just the implicit baseline) and `elite` (was a prestige tier — not a format; can be added later as a separate `prestige` field if needed).

### Hull class (replaces BodyType)

| Old | New |
|---|---|
| `muscle` | `hauler` (heavy, slow, durable) |
| `sport` | `skirmisher` (balanced, agile) |
| `compact` | `scout` (fast, fragile) |

### Model renames

| Old | New |
|---|---|
| `RigTitle` | `ShipTitle` |
| `RigRelease` | `ShipRelease` |
| `RigStatus` | `ShipStatus` |
| `BodyType` | `HullClass` |
| `CarClass` | `RaceFormat` |

`Race`, `Build`, `Card`, `UserCard`, `User`, `MarketListing`, `WreckLog` keep their model names. (`Race` stays specific; `mission` is reserved as a *UI/copy umbrella term* for any ship activity in later phases — it does not become a single polymorphic table.)

### Universe term

- **System** = Discord guild
- **Sector** = enabled Discord channel
- **Universe** = federation of all D2D systems

### Player state scope

- Universe-wide. No FK from `User`, `UserCard`, `Build`, `MarketListing`, `WreckLog`, `ShipTitle`, or `ShipRelease` to `System` or `Sector`.
- Only `Race` gains a sector FK (where the race happened — useful for later sector-scoped leaderboards).

### Sector cap

- Each `System` starts with `sector_cap = 1`.
- Phase 0 enforces the cap on `/sector enable` but does **not** implement any progression mechanism that grows it. Growth is deferred to Phase 2 or 3.
- A bot-owner-only `/system admin set-sector-cap <n>` command exists for manual overrides during testing and early server bootstrapping.

### Tutorial voice

- Existing snarky/gritty/gearhead voice retained. It already reads as salvage-pulp.
- Add 2–3 lines at tutorial open establishing the sector concept.
- "Sketchy Dave" stays — pulp loves mundane names alongside weird tech.

---

## Schema (full)

The fresh `0001_initial.py` reflects this state. All other migration files are deleted.

### `systems`

| Column | Type | Notes |
|---|---|---|
| `guild_id` | `String(20)` PK | Discord guild snowflake |
| `name` | `String(100)` not null | Default: guild name at registration; admin can override |
| `flavor_text` | `String(500)` nullable | Optional system-level fiction (e.g., "The Tannhäuser Cluster") |
| `sector_cap` | `Integer` not null default `1` | How many sectors this system can currently enable |
| `owner_discord_id` | `String(20)` not null | Whoever invited the bot or first claimed the system |
| `registered_at` | `DateTime(timezone=True)` not null | Auto-set on bot guild-join |

### `sectors`

| Column | Type | Notes |
|---|---|---|
| `channel_id` | `String(20)` PK | Discord channel snowflake |
| `system_id` | `String(20)` FK → `systems.guild_id` not null | Parent system |
| `name` | `String(100)` not null | Default: channel name; admin can override |
| `flavor_text` | `String(500)` nullable | Optional sector-level fiction |
| `config` | `JSONB` not null default `{}` | Reserved for per-sector config (Phase 3+) |
| `enabled_at` | `DateTime(timezone=True)` not null | Set by `/sector enable` |

### `users` (renames only)

No new columns. No FK additions. Existing schema preserved with `body_type` → `hull_class` and the underlying enum renamed.

| Column | Type | Notes |
|---|---|---|
| `discord_id` | `String(20)` PK | Unchanged |
| `username` | `String(100)` not null | Unchanged |
| `hull_class` | `Enum(HullClass)` not null | **Renamed** from `body_type` |
| `currency` | `Integer` not null default `0` | Unchanged |
| `xp` | `Integer` not null default `0` | Unchanged |
| `tutorial_step` | `Enum(TutorialStep)` not null default `STARTED` | Unchanged values |
| `last_daily` | `DateTime` nullable | Unchanged |
| `created_at` | `DateTime` not null default `now()` | Unchanged |

### `cards` (renames only)

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Unchanged |
| `name` | `String(120)` not null unique | Unchanged shape; values rewritten for ship vocabulary |
| `slot` | `Enum(CardSlot)` not null | **Same enum name**, **new values** (reactor/drive/thrusters/stabilizers/hull/overdrive/retros) |
| `rarity` | `Enum(Rarity)` not null | Unchanged values |
| `stats` | `JSONB` not null | Unchanged shape |
| `art_path` | `String(255)` nullable | Unchanged (existing placeholder art retained) |
| `print_number` | `Integer` nullable | Unchanged |
| `print_max` | `Integer` nullable | Unchanged |
| `total_minted` | `Integer` not null default `0` | Unchanged |
| `compatible_hull_classes` | `JSONB` nullable | **Renamed** from `compatible_body_types` |

### `user_cards` (no changes)

Schema identical. Copy/help references updated to new vocabulary.

### `builds`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Unchanged |
| `user_id` | `String(20)` FK → `users.discord_id` not null | Unchanged |
| `name` | `String(120)` not null default `"My Ship"` | **Default value updated** |
| `slots` | `JSONB` not null | **Default keys renamed** to `{reactor, drive, thrusters, stabilizers, hull, overdrive, retros}` all `null` |
| `is_active` | `Boolean` not null default `true` | Unchanged |
| `hull_class` | `Enum(HullClass)` nullable | **Renamed** from `body_type` |
| `core_locked` | `Boolean` not null default `false` | Unchanged |
| `ship_title_id` | `UUID` FK → `ship_titles.id` nullable | **Renamed** from `rig_title_id` |

### `races`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Unchanged |
| `participants` | `JSONB` not null | Unchanged |
| `environment` | `JSONB` not null | Unchanged shape; values reflect new space conditions |
| `results` | `JSONB` not null | Unchanged |
| `format` | `Enum(RaceFormat)` not null default `sprint` | **New column** — captures sprint/endurance/gauntlet |
| `sector_id` | `String(20)` FK → `sectors.channel_id` nullable | **New column** — where the race happened (nullable for DM/test races) |
| `created_at` | `DateTime` not null default `now()` | Unchanged |

### `market_listings` (no schema changes)

Copy updates only.

### `wreck_logs` (no schema changes)

Copy updates only — wrecks fit salvage-pulp without rewording.

### `ship_releases` (was `rig_releases`)

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Unchanged |
| `name` | `String(120)` not null | Unchanged shape |
| `description` | `String(500)` nullable | Unchanged |
| `started_at` | `DateTime` not null default `now()` | Unchanged |
| `ended_at` | `DateTime` nullable | Unchanged |
| `serial_counter` | `Integer` not null default `0` | Unchanged |

### `ship_titles` (was `rig_titles`)

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Unchanged |
| `release_id` | `UUID` FK → `ship_releases.id` not null | Unchanged shape |
| `release_serial` | `Integer` not null | Unchanged |
| `owner_id` | `String(20)` FK → `users.discord_id` not null | Unchanged |
| `build_id` | `UUID` FK → `builds.id` nullable | Unchanged |
| `hull_class` | `Enum(HullClass)` not null | **Renamed** from `body_type` |
| `race_format` | `Enum(RaceFormat)` not null | **Renamed** from `car_class`; captures the format the ship was minted for |
| `status` | `Enum(ShipStatus)` not null default `ACTIVE` | **Enum renamed** from `RigStatus`; same values (`active`, `scrapped`) |
| `auto_name` | `String(120)` not null | Unchanged |
| `custom_name` | `String(120)` nullable | Unchanged |
| `build_snapshot` | `JSONB` not null | Unchanged shape (snapshot keys reflect new slot names) |
| `pedigree_bonus` | `Float` not null default `0.0` | Unchanged |
| `ownership_log` | `JSONB` not null default `[]` | Unchanged |
| `part_swap_log` | `JSONB` not null default `[]` | Unchanged |
| `race_record` | `JSONB` not null default `{"wins": 0, "losses": 0}` | Unchanged |
| `minted_at` | `DateTime` not null default `now()` | Unchanged |

---

## Code rename surface

### `db/`

- `db/models.py` — full enum + model rewrite per schema above
- `db/migrations/versions/0001_*.py` through `0010_*.py` — **deleted**
- `db/migrations/versions/0001_initial.py` — **new**, reflects entire post-pivot schema

### `engine/`

- `engine/race_engine.py` — module name unchanged; internal rename of body_type → hull_class, car_class → race_format, slot key references throughout
- `engine/environment.py` — track-condition data replaced with seven space conditions (see Environment section below); function signatures unchanged
- `engine/stat_resolver.py` — slot dict key names updated; aggregation math unchanged
- `engine/card_mint.py` — slot enum + name pool updates

### `bot/`

- `bot/main.py` — register the new `on_guild_join` listener and the startup guild-list reconciliation
- `bot/sector_gating.py` — **new module** holding the gameplay-vs-universe-wide command registry and the `get_active_sector()` helper
- `bot/cogs/race.py` — copy: "race" stays as gameplay term but car-specific phrases (parts, engine, etc.) rewritten for ships; gating helper applied at command top
- `bot/cogs/cards.py` — pack-opening copy + slot displays rewritten; gating helper applied
- `bot/cogs/garage.py` → `bot/cogs/hangar.py` (slash command renamed `/garage` → `/hangar`); copy updated
- `bot/cogs/market.py` — copy updates
- `bot/cogs/tutorial.py` — see Tutorial Copy section
- `bot/cogs/admin.py` — extended with new sector/system commands (see Sector Registration section)
- All cogs: `body_type` → `hull_class`, slot key references, etc.

### `api/`

- `api/routes/races.py` — copy + serializer key renames
- `api/routes/cards.py` — copy + slot enum updates
- `api/routes/users.py` — `body_type` → `hull_class` in serializers
- `api/main.py` — no functional changes; OpenTelemetry instrumentation untouched

### `data/`

- `data/cards/engines.json` → `data/cards/reactors.json` (rename + content rewrite)
- `data/cards/transmissions.json` → `data/cards/drives.json`
- `data/cards/tires.json` → `data/cards/thrusters.json`
- `data/cards/suspension.json` → `data/cards/stabilizers.json`
- `data/cards/chassis.json` → `data/cards/hulls.json`
- `data/cards/turbos.json` → `data/cards/overdrives.json`
- `data/cards/brakes.json` → `data/cards/retros.json`
- `data/tutorial.json` — `body_type_base_stats` → `hull_class_base_stats`; starter card names + Sketchy Dave NPC rewritten (see Tutorial Copy section)
- `data/environments.json` — replaced with the seven space conditions (see Environment section)
- `data/loot_tables.json` — pack `display_name` and `flavor` rewritten; pack mechanic structure unchanged
- `data/class_thresholds.json` — reworked for three race formats (sprint/endurance/gauntlet); thresholds preserved where the old format maps cleanly, collapsed where two old formats fold into `gauntlet`
- `data/rig_names.json` → `data/ship_names.json` — name pool rewritten for ship vocabulary
- `data/salvage_rates.json` — copy/key updates if any car-specific terms exist

### `tests/`

All existing tests updated for new vocabulary, model names, and enum values. Test fixtures using car-era models/data must be rewritten. Test pytest names may also be updated where they reference cars/rigs explicitly (e.g., `test_pack_reveal_view.py` keeps its name; `test_rig_*` files rename to `test_ship_*`).

### `scripts/`

- `scripts/dev.py` (`d2d` CLI) — any subcommands referencing cars/races/rigs by name updated. Functional behavior unchanged.
- `scripts/audit_pivot.py` — **new**, the verification audit script described in Verification section.

---

## Sector registration logic

### Auto-register System on guild join

Bot listener `on_guild_join`:

1. Insert `systems` row with `guild_id`, `name = guild.name`, `owner_discord_id = guild.owner_id`, `registered_at = now()`, `sector_cap = 1`.
2. Send a welcome embed in the guild's system channel (or first writable channel) explaining: "D2D installed. An admin needs to `/sector enable` a channel before gameplay can begin."

If the bot is restarted into a guild it had previously joined (no event fires), a guild-list reconciliation on bot startup ensures every current guild has a `systems` row. Missing rows are inserted.

### `/sector enable` (admin-only)

Permission check: `interaction.user.guild_permissions.manage_channels` is true OR user is the guild owner. Otherwise reject ephemerally with "Only server admins (manage_channels) can enable sectors."

Logic:

1. Look up `systems` row for current guild. (Should always exist due to auto-register.)
2. Count existing `sectors` rows where `system_id = guild_id`. If `count >= sector_cap`, reject:
   > "The [system name] can only sustain [sector_cap] active sector[s] at its current influence. Disable another to relocate, or grow the system to expand."
3. If channel already a sector: reject with "This channel is already an enabled sector."
4. Otherwise, insert `sectors` row with `channel_id`, `system_id`, `name = channel.name`, `enabled_at = now()`, `config = {}`.
5. Reply with confirmation embed: "[Channel name] enabled as sector [sector name]. Run gameplay commands here. (System: [system name], [count]/[cap] sectors.)"

### `/sector disable` (admin-only)

Permission check: same as enable.

Logic:

1. If channel is not a sector: reject ephemerally.
2. Delete `sectors` row.
3. Confirmation: "Sector disabled. Gameplay commands will no longer work in this channel until re-enabled."

Player data (cards, builds, race history) is untouched; only the channel-level enablement flips.

### `/sector rename <name>` (admin-only)

Updates `sectors.name` for the current channel.

### `/system info`

Public read command. Shows: system name, flavor_text (if set), owner, sector_cap, list of enabled sectors with their names + flavor.

### `/system set-flavor <text>`

Owner-only (system.owner_discord_id must match interaction.user.id). Updates `systems.flavor_text`.

### `/system admin set-sector-cap <n>` (bot-owner-only)

Permission check: interaction.user.id matches the configured `BOT_OWNER_DISCORD_ID` env var. Reject all other invocations with no information leak.

Logic: updates `systems.sector_cap` for the specified system (defaults to current guild). Used for manual overrides during testing and bootstrapping early communities.

### Gameplay command gating

Define a helper:

```python
async def get_active_sector(interaction: discord.Interaction, session: AsyncSession) -> Sector | None:
    """Return the Sector for this interaction's channel, or None if not enabled."""
```

Each gameplay command (`/race`, `/pack`, `/equip`, etc.) calls this helper at the top:

- If `None` → reject with: "Game not enabled here. Ask a server admin to `/sector enable` this channel."
- If a `Sector` → proceed; pass `sector.channel_id` into `Race.sector_id` on race creation.

DM commands and universe-wide commands (`/profile`, `/inventory`, `/help`, etc.) skip the helper entirely.

A central registry of which commands require a sector vs. are universe-wide lives in `bot/sector_gating.py` (new module). This file is the single source of truth for gating decisions, parallel to the existing `STEP_ALLOWED_COMMANDS` table in `tutorial.py`.

---

## Environment (space conditions)

`data/environments.json` replaces seven track conditions with seven space conditions. Stat-weight structure preserved; values rebalanced where semantics demand it but kept close to existing tuning.

| Condition | Stat weights favored (sketch — final values match existing condition closely) |
|---|---|
| `clear_space` | Neutral — baseline |
| `nebula` | Handling, stabilizers (low visibility) |
| `asteroid_field` | Hull, stabilizers (hazard avoidance) |
| `solar_flare` | Reactor temp tolerance, durability |
| `gravity_well` | Drive power, raw acceleration |
| `ion_storm` | Thruster precision, handling |
| `debris_field` | Hull, stabilizers (salvage-flavored variant of asteroid_field) |

Implementation maps each old environment 1:1 to a new one where stat-weight semantics match (e.g., old `wet_road` → new `nebula` since both penalize visibility/handling) and rebalances any orphans.

---

## Tutorial copy

### Voice

Unchanged. The existing snarky/gritty/gearhead tone reads as salvage-pulp without rewriting.

### Opening line addition

Insert at the start of the `STARTED` step, before the body-type pick:

> "You've drifted into [sector name]. Sketchy Dave runs the strip here — he'll show you the ropes."

`[sector name]` is interpolated from the active sector. If the player is in a DM (no sector), substitute `"the outer rim"`.

### NPC

- Name: "Sketchy Dave" (unchanged)
- Ship: "Sketchy Dave's Taped-Together Crawler" (was "Taped-Together V4")
- Tutorial dialogue: existing lines retained; only car-specific nouns swapped (e.g., "race" can stay; "engine" → "reactor"; "transmission" → "drive")
- Sketchy Dave's parts (in `data/tutorial.json`): names rewritten as ship parts, e.g., "Dave's Mystery Gearbox" → "Dave's Mystery Drive"

### Starter cards

Renamed in both `data/tutorial.json` and the relevant `data/cards/*.json` files:

| Old | New |
|---|---|
| Rustbucket Inline-4 | Rustbucket Reactor |
| Clunker 3-Speed | Clunker Drive |
| Bald Eagles | Bald Thrusters |
| Scrapheap Frame | Scrapheap Hull |
| Drum Stoppers | Drum Retros |
| Springboard Basics | Springboard Stabilizers |
| Junkyard Snail | Junkyard Overdrive |

### Hint copy

`STEP_ALLOWED_COMMANDS` table retained as-is. `step_hints` strings updated:

| Step | New hint |
|---|---|
| `STARTED` | "Hold on, your story's still unfolding. Sit tight." (unchanged) |
| `INVENTORY` | "Easy there. Use `/inventory` first — gotta know what you've got before you do anything with it." (unchanged) |
| `INSPECT` | "You've got parts but haven't looked at them. Try `/inspect` on one of your cards first." (unchanged) |
| `EQUIP` | "Parts on the floor don't make the ship fly. Use `/equip` or `/autoequip best` to install them." |
| `MINT` | "All slots filled — use `/build preview` to see your format, then `/build mint` to lock it in." |
| `GARAGE` | "Your ship's minted. Use `/hangar` to look it over, then head out for a run." |
| `RACE` | "Your ship's ready. Stop stalling and use `/race` already." (unchanged) |
| `PACK` | "You've got a salvage crate to open. Patience." |

---

## Out of scope

Explicitly NOT in Phase 0:

- Crew system (Phase 1)
- Scheduler / timers / accrual / expeditions (Phase 2)
- Job board, channel events, villains, sector control (Phase 3)
- Fleet PvP (Phase 4)
- New artist tiers, Discord activity (Phase 5)
- Sector-cap progression mechanic — only the cap and override exist; growth comes later
- Any data migration logic — no live users, so squashing is safe; if Phase 0 ships and *then* gains users before Phase 1 is built, a separate hotfix migration handles any real-world data evolution
- Renaming "race" to "run" or "mission" — race stays as the model name; "mission" is reserved as a UI/copy umbrella for later phases when battles/expeditions/events join
- Renaming `/garage` to `/hangar` is in scope for Phase 0 (small, fits the rename pass); renaming user-facing `/race` to anything else is out of scope

---

## Verification

### Automated

- Full pytest suite passes after the rename
- Alembic migration round-trips: `alembic upgrade head` then `alembic downgrade base` succeeds against a clean Postgres
- Type checks (mypy/ruff) pass
- A grep/ripgrep audit script in `scripts/audit_pivot.py` (new) checks for the following leak patterns and exits non-zero if any match in player-facing strings:
  - `\bcar\b` (case-insensitive, excluding tests + comments + this spec)
  - `\brig\b` (excluding `Sketchy Dave's Taped-Together Crawler`-style allowed retains and external library references)
  - Old slot names (`engine`, `transmission`, `tires`, `suspension`, `chassis`, `turbo`, `brakes`) in non-code contexts
  - `body_type` in any context

### Manual

- Tutorial end-to-end: register, pick hull class, walk through each tutorial step, verify all copy reads naturally
- Open a salvage crate: card names, slot names, art display all reflect new vocabulary
- Build a ship, mint a ShipTitle, run a race — confirm `Race.sector_id` is populated and `Race.format` is one of the three new values
- Two-server smoke test:
  - Install bot in two test guilds; verify `systems` rows auto-created
  - `/sector enable` in one channel of each guild
  - Same player runs commands in both guilds; verify cards / builds / credits visible in both
  - `/sector enable` a second channel in either guild → verify cap rejection message
  - `/system admin set-sector-cap 2` from bot-owner account → second `/sector enable` succeeds
- Wreck a ship in a race → confirm `wreck_logs` row written with new slot names in `lost_parts`

### Observability

- Existing OpenTelemetry spans continue to fire on every command and race
- Existing Prometheus metrics (`dare2drive_*`) continue to emit; metric names stay car-agnostic where they already are, get renamed where they aren't
- New: `dare2drive_systems_registered_total`, `dare2drive_sectors_enabled_total` counters

---

## Open implementation questions (resolve in implementation plan, not in this spec)

These are mechanical / not-load-bearing decisions left to the implementation step:

- Whether `/garage` becomes `/hangar` (recommended) or `/fleet-bay`. Pick during implementation; default to `/hangar` for brevity.
- Whether `data/loot_tables.json` pack names get full rewrites (e.g., `junkyard_pack` → `salvage_crate`) or stay as keys with display-name overrides. Recommend rewriting keys for cleanliness since no users.
- Exact stat-weight values for the 7 environments — port from existing values where semantics align, eyeball-tune the orphans, defer real balancing to playtest.
- Welcome embed copy on `on_guild_join`.
- Whether the bot-owner override env var is `BOT_OWNER_DISCORD_ID` or matches an existing settings convention (check `config/settings.py`).
