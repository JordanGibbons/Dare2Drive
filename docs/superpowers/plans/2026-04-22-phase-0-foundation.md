# Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot Dare2Drive from car/race vocabulary to ship/salvage-pulp vocabulary while introducing multi-tenant Sector/System tables — single PR, fresh schema, no live users.

**Architecture:** Squash all 10 existing migrations into a fresh `0001_initial.py` reflecting the post-pivot schema. Add `Sector` and `System` tables. Rename `BodyType→HullClass`, `CarClass→RaceFormat` (cut 6→3 values: sprint/endurance/gauntlet), `Rig*→Ship*`, slot keys (`engine→reactor`, `transmission→drive`, `tires→thrusters`, `suspension→stabilizers`, `chassis→hull`, `turbo→overdrive`, `brakes→retros`). Player state stays universe-wide; only `Race` gains `system_id` FK. Gameplay commands gated to enabled systems via central registry. No mechanical behavior changes.

**Tech Stack:** Python 3.11+, FastAPI, discord.py 2.x, SQLAlchemy 2 async, Alembic, PostgreSQL 16, Redis 7, pytest.

**Spec:** [docs/superpowers/specs/2026-04-22-phase-0-foundation-design.md](../specs/2026-04-22-phase-0-foundation-design.md)

**Branch:** `d2d-space` (already checked out)

---

## Working principles

- **Big rename, no live users.** Be aggressive. The goal is one cohesive PR ready to merge to `main`.
- **Renames first, then new behavior.** Schema → engine → data files → cogs → new system commands → tests → verification.
- **Tests are the safety net.** After each rename layer, run the full suite. Fix breakage immediately, don't let it pile up.
- **Frequent commits.** Commit after each task at minimum. Use `feat:` for new behavior, `refactor:` for renames, `chore:` for data file updates.
- **TDD applies to new code.** System gating helper, admin commands, and the audit script get test-first treatment. Pure renames don't — the existing tests are the test, just with renamed fixtures.

---

## File structure (what gets created / modified)

### Created

- `bot/system_gating.py` — Helper `get_active_system()` + registry of system-gated vs universe-wide commands
- `db/migrations/versions/0001_initial.py` — **New**, replaces all 10 existing migrations
- `scripts/audit_pivot.py` — Grep audit script that fails CI on car-vocabulary leaks
- `tests/test_system_gating.py` — Tests for the gating helper
- `tests/test_sectors_systems.py` — Tests for Sector/System model + admin commands

### Renamed (file moves)

- `bot/cogs/garage.py` → `bot/cogs/hangar.py`
- `engine/rig_namer.py` → `engine/ship_namer.py`
- `data/cards/engines.json` → `data/cards/reactors.json`
- `data/cards/transmissions.json` → `data/cards/drives.json`
- `data/cards/tires.json` → `data/cards/thrusters.json`
- `data/cards/suspension.json` → `data/cards/stabilizers.json`
- `data/cards/chassis.json` → `data/cards/hulls.json`
- `data/cards/turbos.json` → `data/cards/overdrives.json`
- `data/cards/brakes.json` → `data/cards/retros.json`
- `data/rig_names.json` → `data/ship_names.json`
- `tests/test_rig_namer.py` → `tests/test_ship_namer.py`

### Modified

- `db/models.py` — model + enum renames + new Sector/System
- `engine/race_engine.py`, `engine/stat_resolver.py`, `engine/card_mint.py`, `engine/class_engine.py`, `engine/durability.py`, `engine/environment.py` — slot/enum refs
- `bot/main.py` — `on_guild_join` listener + startup reconciliation
- `bot/cogs/race.py`, `cards.py`, `market.py`, `tutorial.py`, `admin.py` — copy + gating
- `api/routes/races.py`, `cards.py`, `users.py` — serializer renames
- `data/environments.json` — replaced with space conditions
- `data/tutorial.json`, `data/loot_tables.json`, `data/class_thresholds.json`, `data/salvage_rates.json` — content rewrites
- `scripts/dev.py` — d2d CLI command name updates
- All `tests/test_*.py` — fixture + reference renames
- `config/settings.py` — add `BOT_OWNER_DISCORD_ID` env var (if not present)

### Deleted

- `db/migrations/versions/0001_initial.py` through `0010_add_mint_tutorial_step.py` (all 10 existing migrations)

---

## Task 1: Baseline snapshot

Capture the pre-pivot test pass rate and any flaky tests so we know what "broken" means downstream.

**Files:**
- No file changes; this task is verification only.

- [ ] **Step 1: Confirm clean working tree**

```bash
cd c:/Users/jorda/dev/dare2drive
git status
```

Expected: only the unrelated in-progress changes (`monitoring/grafana-stack`, `.claude/settings.json`). No conflicting Phase 0 work.

- [ ] **Step 2: Verify Postgres + Redis available**

```bash
docker compose ps
```

Expected: `db` and `redis` services running. If not: `docker compose up -d db redis`.

- [ ] **Step 3: Run full test suite, capture baseline**

```bash
pytest -x --tb=short 2>&1 | tee /tmp/baseline_tests.log
```

Expected: all tests pass (or note any pre-existing failures — they aren't Phase 0's problem and shouldn't be counted as regressions).

- [ ] **Step 4: Note baseline pass count**

Record the "X passed" line. Every downstream task must end with at least this many passing tests (until tests are intentionally rewritten).

- [ ] **Step 5: No commit needed.** Move to Task 2.

---

## Task 2: Update `db/models.py` with full post-pivot schema

Single atomic rewrite of the models file. All model renames, enum renames, slot enum value changes, and new `Sector`/`System` models land together. Migrations don't run yet — this only updates Python definitions.

**Files:**
- Modify: `db/models.py`

- [ ] **Step 1: Rewrite `db/models.py` end-to-end**

Replace the file's contents with the post-pivot schema. The diff is large; read the existing file first to ensure no constraints are dropped accidentally. Key shape:

```python
"""SQLAlchemy async models for Dare2Drive (Salvage-Pulp universe)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ──────────── Enums ────────────

class HullClass(str, enum.Enum):
    HAULER = "hauler"
    SKIRMISHER = "skirmisher"
    SCOUT = "scout"


class RaceFormat(str, enum.Enum):
    SPRINT = "sprint"
    ENDURANCE = "endurance"
    GAUNTLET = "gauntlet"


class ShipStatus(str, enum.Enum):
    ACTIVE = "active"
    SCRAPPED = "scrapped"


class TutorialStep(str, enum.Enum):
    """Tracks player progress through the onboarding tutorial."""
    STARTED = "started"
    INVENTORY = "inventory"
    INSPECT = "inspect"
    EQUIP = "equip"
    MINT = "mint"
    GARAGE = "garage"   # name retained internally; UI shows /hangar
    RACE = "race"
    PACK = "pack"
    COMPLETE = "complete"


class CardSlot(str, enum.Enum):
    REACTOR = "reactor"
    DRIVE = "drive"
    THRUSTERS = "thrusters"
    STABILIZERS = "stabilizers"
    HULL = "hull"
    OVERDRIVE = "overdrive"
    RETROS = "retros"


class Rarity(str, enum.Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    GHOST = "ghost"


# ──────────── New Multi-Tenant Models ────────────

class Sector(Base):
    __tablename__ = "sectors"

    guild_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flavor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_cap: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    owner_discord_id: Mapped[str] = mapped_column(String(20), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    systems: Mapped[list["System"]] = relationship(back_populates="sector", lazy="selectin")


class System(Base):
    __tablename__ = "systems"

    channel_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    sector_id: Mapped[str] = mapped_column(String(20), ForeignKey("sectors.guild_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flavor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sector: Mapped[Sector] = relationship(back_populates="systems")


# ──────────── Existing Models (renamed) ────────────

class User(Base):
    __tablename__ = "users"

    discord_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    hull_class: Mapped[HullClass] = mapped_column(
        Enum(HullClass, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    currency: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tutorial_step: Mapped[TutorialStep] = mapped_column(
        Enum(TutorialStep, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TutorialStep.STARTED,
    )
    last_daily: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user_cards: Mapped[list["UserCard"]] = relationship(back_populates="user", lazy="selectin")
    builds: Mapped[list["Build"]] = relationship(back_populates="user", lazy="selectin")
    market_listings: Mapped[list["MarketListing"]] = relationship(back_populates="seller", lazy="selectin")
    wreck_logs: Mapped[list["WreckLog"]] = relationship(back_populates="user", lazy="selectin")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slot: Mapped[CardSlot] = mapped_column(
        Enum(CardSlot, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    art_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    print_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_minted: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    compatible_hull_classes: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

    user_cards: Mapped[list["UserCard"]] = relationship(back_populates="card", lazy="selectin")


class UserCard(Base):
    __tablename__ = "user_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False)
    serial_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stat_modifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_foil: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    races_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="user_cards")
    card: Mapped[Card] = relationship(back_populates="user_cards")


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="My Ship")
    slots: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "reactor": None, "drive": None, "thrusters": None, "stabilizers": None,
            "hull": None, "overdrive": None, "retros": None,
        },
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hull_class: Mapped[HullClass] = mapped_column(
        Enum(HullClass, values_callable=lambda x: [e.value for e in x]), nullable=True
    )
    core_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ship_title_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ship_titles.id"), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="builds")
    ship_title: Mapped["ShipTitle | None"] = relationship(
        "ShipTitle", foreign_keys="[Build.ship_title_id]", lazy="selectin"
    )


class Race(Base):
    __tablename__ = "races"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participants: Mapped[dict] = mapped_column(JSONB, nullable=False)
    environment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    format: Mapped[RaceFormat] = mapped_column(
        Enum(RaceFormat, values_callable=lambda x: [e.value for e in x]),
        nullable=False, server_default="sprint",
    )
    system_id: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("systems.channel_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wreck_logs: Mapped[list["WreckLog"]] = relationship(back_populates="race", lazy="selectin")


class MarketListing(Base):
    __tablename__ = "market_listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False)
    user_card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_cards.id"), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    listed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped[User] = relationship(back_populates="market_listings")
    card: Mapped[Card] = relationship()
    user_card: Mapped[UserCard] = relationship()


class WreckLog(Base):
    __tablename__ = "wreck_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("races.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    lost_parts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    race: Mapped[Race] = relationship(back_populates="wreck_logs")
    user: Mapped[User] = relationship(back_populates="wreck_logs")


class ShipRelease(Base):
    __tablename__ = "ship_releases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    serial_counter: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")

    titles: Mapped[list["ShipTitle"]] = relationship(
        "ShipTitle", back_populates="release", lazy="selectin"
    )


class ShipTitle(Base):
    __tablename__ = "ship_titles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ship_releases.id"), nullable=False
    )
    release_serial: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    build_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("builds.id"), nullable=True)
    hull_class: Mapped[HullClass] = mapped_column(
        Enum(HullClass, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    race_format: Mapped[RaceFormat] = mapped_column(
        Enum(RaceFormat, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    status: Mapped[ShipStatus] = mapped_column(
        Enum(ShipStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False, default=ShipStatus.ACTIVE,
    )
    auto_name: Mapped[str] = mapped_column(String(120), nullable=False)
    custom_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    build_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pedigree_bonus: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, server_default="0.0")
    ownership_log: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    part_swap_log: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    race_record: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default='{"wins": 0, "losses": 0}'
    )
    minted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    release: Mapped[ShipRelease] = relationship(back_populates="titles")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
```

- [ ] **Step 2: Verify Python compiles the new models**

```bash
python -c "from db.models import (Sector, System, User, Card, UserCard, Build, Race, MarketListing, WreckLog, ShipRelease, ShipTitle, HullClass, RaceFormat, ShipStatus, CardSlot, Rarity, TutorialStep)"
```

Expected: no output (success). If `ImportError` or `NameError`, fix the broken reference before continuing.

- [ ] **Step 3: Do NOT run tests or migrations yet** — they will fail because the rest of the codebase still references old names. Continue to Task 3.

- [ ] **Step 4: Stage but do not commit yet**

```bash
git add db/models.py
```

We commit after Task 3 completes — the schema and migration land together.

---

## Task 3: Squash migrations into fresh `0001_initial.py`

Delete all 10 existing migration files and write one new `0001_initial.py` that creates the entire post-pivot schema.

**Files:**
- Delete: `db/migrations/versions/0001_initial.py` through `db/migrations/versions/0010_add_mint_tutorial_step.py`
- Create: `db/migrations/versions/0001_initial.py` (new content)

- [ ] **Step 1: Delete old migration files**

```bash
cd c:/Users/jorda/dev/dare2drive
rm db/migrations/versions/0001_initial.py
rm db/migrations/versions/0002_add_tutorial_step.py
rm db/migrations/versions/0003_individual_card_copies.py
rm db/migrations/versions/0004_market_listing_user_card_id.py
rm db/migrations/versions/0005_add_last_daily.py
rm db/migrations/versions/0006_add_races_used.py
rm db/migrations/versions/0007_add_body_type_to_builds.py
rm db/migrations/versions/0008_add_compatible_body_types_to_cards.py
rm db/migrations/versions/0009_create_rig_titles.py
rm db/migrations/versions/0010_add_mint_tutorial_step.py
```

- [ ] **Step 2: Drop the existing dev database**

The squashed migration is incompatible with any existing schema. Drop and recreate:

```bash
docker compose exec db psql -U postgres -c "DROP DATABASE IF EXISTS dare2drive;"
docker compose exec db psql -U postgres -c "CREATE DATABASE dare2drive;"
```

(Adjust user/db names if `docker-compose.yml` uses different values — check with `docker compose config`.)

- [ ] **Step 3: Auto-generate the new initial migration from the updated models**

```bash
alembic revision --autogenerate -m "initial salvage-pulp schema"
```

Expected: a new file appears in `db/migrations/versions/` with a hash filename. Rename it to `0001_initial.py`:

```bash
# Find the generated file (it has a hash in the name)
ls db/migrations/versions/
# Rename it
mv db/migrations/versions/<generated_hash>_initial_salvage_pulp_schema.py db/migrations/versions/0001_initial.py
```

- [ ] **Step 4: Inspect the generated migration**

Open `db/migrations/versions/0001_initial.py` and verify:
- All 11 tables created (`sectors`, `systems`, `users`, `cards`, `user_cards`, `builds`, `races`, `market_listings`, `wreck_logs`, `ship_releases`, `ship_titles`)
- Enums: `hullclass`, `raceformat`, `shipstatus`, `tutorialstep`, `cardslot`, `rarity` all defined with the new values
- `races.system_id` FK present
- `races.format` column present
- No leftover references to `bodytype`, `carclass`, `rigstatus`, `engine`/`transmission`/etc as enum values

If autogenerate missed anything, edit by hand. Set `revision = "0001_initial"` and `down_revision = None` to ensure clean naming.

- [ ] **Step 5: Run the migration up**

```bash
alembic upgrade head
```

Expected: success, all tables created.

- [ ] **Step 6: Test downgrade round-trip**

```bash
alembic downgrade base
alembic upgrade head
```

Expected: both succeed without error.

- [ ] **Step 7: Commit schema + migration together**

```bash
git add db/models.py db/migrations/versions/0001_initial.py
git rm db/migrations/versions/0002_*.py db/migrations/versions/0003_*.py db/migrations/versions/0004_*.py db/migrations/versions/0005_*.py db/migrations/versions/0006_*.py db/migrations/versions/0007_*.py db/migrations/versions/0008_*.py db/migrations/versions/0009_*.py db/migrations/versions/0010_*.py
git commit -m "refactor!: squash migrations to fresh 0001 with salvage-pulp schema

Replaces 10 car-era migrations with a single initial migration
reflecting the post-pivot ship schema. Adds Sector and System
tables. No live users, so squash is safe.

BREAKING: drops all existing data. Dev environments must drop
and recreate the database before pulling.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Rename slot keys in `engine/stat_resolver.py`

The stat resolver iterates the 7 build slots. Update slot key references — math is unchanged.

**Files:**
- Modify: `engine/stat_resolver.py`

- [ ] **Step 1: Read the file to find every slot reference**

```bash
grep -n "engine\|transmission\|tires\|suspension\|chassis\|turbo\|brakes\|body_type\|car_class" engine/stat_resolver.py
```

- [ ] **Step 2: Apply replacements**

Use Edit with `replace_all=true` for each slot key (case-sensitive on string keys):

| Find | Replace |
|---|---|
| `"engine"` | `"reactor"` |
| `"transmission"` | `"drive"` |
| `"tires"` | `"thrusters"` |
| `"suspension"` | `"stabilizers"` |
| `"chassis"` | `"hull"` |
| `"turbo"` | `"overdrive"` |
| `"brakes"` | `"retros"` |
| `body_type` (variable name) | `hull_class` |
| `BodyType` (type ref) | `HullClass` |
| `CarClass` | `RaceFormat` |
| `car_class` | `race_format` |

Walk through the file carefully — some replacements may be in docstrings or comments and are still correct to update.

- [ ] **Step 3: Verify Python parses**

```bash
python -c "from engine.stat_resolver import *"
```

Expected: no error.

- [ ] **Step 4: Run targeted test**

```bash
pytest tests/test_stat_resolver.py -x --tb=short
```

Expected: tests fail because fixtures still use old slot keys. We fix fixtures in Task 26. For now, note the failure pattern — we want failures to be "key not found" / "enum value not found", not import errors.

- [ ] **Step 5: Commit**

```bash
git add engine/stat_resolver.py
git commit -m "refactor: rename slot keys + body_type/car_class in stat_resolver"
```

---

## Task 5: Rename references in `engine/race_engine.py`

**Files:**
- Modify: `engine/race_engine.py`

- [ ] **Step 1: Find all references**

```bash
grep -n "engine\|transmission\|tires\|suspension\|chassis\|turbo\|brakes\|body_type\|BodyType\|car_class\|CarClass\|RigTitle\|RigStatus" engine/race_engine.py
```

- [ ] **Step 2: Apply replacements per Task 4 mapping plus:**

| Find | Replace |
|---|---|
| `RigTitle` | `ShipTitle` |
| `rig_title` | `ship_title` |
| `RigStatus` | `ShipStatus` |
| `rig_release` | `ship_release` |

- [ ] **Step 3: Verify import**

```bash
python -c "from engine.race_engine import *"
```

- [ ] **Step 4: Commit**

```bash
git add engine/race_engine.py
git commit -m "refactor: rename slot/class refs in race_engine"
```

---

## Task 6: Rename in `engine/card_mint.py`

**Files:**
- Modify: `engine/card_mint.py`

- [ ] **Step 1: Find references**

```bash
grep -n "engine\|transmission\|tires\|suspension\|chassis\|turbo\|brakes\|body_type\|BodyType\|compatible_body_types" engine/card_mint.py
```

- [ ] **Step 2: Apply replacements**

Per Task 4 mapping plus:

| Find | Replace |
|---|---|
| `compatible_body_types` | `compatible_hull_classes` |

- [ ] **Step 3: Verify import**

```bash
python -c "from engine.card_mint import *"
```

- [ ] **Step 4: Commit**

```bash
git add engine/card_mint.py
git commit -m "refactor: rename in card_mint"
```

---

## Task 7: Rewrite `engine/class_engine.py` for 3 race formats

This module assigns `CarClass` from a build's stat profile. Cut from 6 → 3 formats, fold `drift` + `rally` logic into `gauntlet`.

**Files:**
- Modify: `engine/class_engine.py`
- Reference: `data/class_thresholds.json` (will be rewritten in Task 16)

- [ ] **Step 1: Read existing logic to understand stat-based classification**

Note which stats currently push toward drag/circuit/drift/rally/elite. For the 3-format collapse:
- old `drag` → new `sprint`
- old `circuit` → new `endurance`
- old `drift` + `rally` → new `gauntlet`
- old `street` (default) → if a ship doesn't qualify for any specific format, default to `sprint`
- old `elite` → not a format anymore; remove from output. Prestige can be tracked separately later.

- [ ] **Step 2: Update the classification function**

Replace `CarClass` enum returns with `RaceFormat` returns. Adjust threshold logic to map the 6 buckets into 3.

- [ ] **Step 3: Verify import**

```bash
python -c "from engine.class_engine import *"
```

- [ ] **Step 4: Run targeted test (will fail until fixtures updated)**

```bash
pytest tests/test_class_engine.py -x --tb=short
```

Note failure pattern.

- [ ] **Step 5: Commit**

```bash
git add engine/class_engine.py
git commit -m "refactor: collapse class_engine to 3 race formats"
```

---

## Task 8: Rename references in `engine/durability.py`

**Files:**
- Modify: `engine/durability.py`

- [ ] **Step 1: Find references**

```bash
grep -n "engine\|transmission\|tires\|suspension\|chassis\|turbo\|brakes" engine/durability.py
```

- [ ] **Step 2: Apply slot rename mapping (Task 4 list)**

- [ ] **Step 3: Verify import**

```bash
python -c "from engine.durability import *"
```

- [ ] **Step 4: Commit**

```bash
git add engine/durability.py
git commit -m "refactor: rename slot refs in durability"
```

---

## Task 9: Replace `data/environments.json` + update `engine/environment.py`

Replace 7 track-condition entries with 7 space-condition entries, preserving stat-weight schema.

**Files:**
- Modify: `data/environments.json`
- Modify: `engine/environment.py`

- [ ] **Step 1: Read current `data/environments.json`** to see the existing weight schema.

- [ ] **Step 2: Replace contents**

Map old → new while preserving the same stat-weight keys. Sketch:

```json
{
  "clear_space": {
    "display_name": "Clear Space",
    "description": "An empty stretch of system. Nothing to see, nothing to dodge.",
    "weights": {<neutral baseline weights>}
  },
  "nebula": {
    "display_name": "Nebula",
    "description": "Visibility down to a few klicks. Stabilizers are how you keep your bearing.",
    "weights": {<emphasize handling, stabilizers>}
  },
  "asteroid_field": {
    "display_name": "Asteroid Field",
    "description": "Rocks bigger than your hull, every direction. Pray you brought spare plating.",
    "weights": {<emphasize hull, stabilizers, durability>}
  },
  "solar_flare": {
    "display_name": "Solar Flare",
    "description": "Reactor temps spiking. Heat tolerance matters more than raw power right now.",
    "weights": {<emphasize reactor temp tolerance, durability>}
  },
  "gravity_well": {
    "display_name": "Gravity Well",
    "description": "A heavy pull dragging on every sector. Drive power is what gets you out.",
    "weights": {<emphasize drive power, raw acceleration>}
  },
  "ion_storm": {
    "display_name": "Ion Storm",
    "description": "Electrical disruption fouling thruster feedback. Precision over power.",
    "weights": {<emphasize thruster precision, handling>}
  },
  "debris_field": {
    "display_name": "Debris Field",
    "description": "Shredded ships and salvage drifting in slow currents. The floor of every scrapper's nightmares.",
    "weights": {<similar to asteroid_field, slightly different bias>}
  }
}
```

Port stat weights from the closest old environment for each new one. Don't try to rebalance — just preserve numbers.

- [ ] **Step 3: Update `engine/environment.py` for any hard-coded environment names**

```bash
grep -n "wet\|dry\|night\|dawn\|street\|highway" engine/environment.py
```

Replace any string keys with the new ones. Logic untouched.

- [ ] **Step 4: Verify imports**

```bash
python -c "from engine.environment import *"
python -c "import json; json.load(open('data/environments.json'))"
```

- [ ] **Step 5: Commit**

```bash
git add data/environments.json engine/environment.py
git commit -m "refactor: replace track conditions with space conditions"
```

---

## Task 10: Rename + rewrite `data/cards/*.json` (7 files)

Each file gets renamed to its new slot name AND its content rewritten to use the new slot value + ship-flavored card names. Stats and rarity weights unchanged where possible.

**Files:**
- Rename + rewrite each of: `engines.json`, `transmissions.json`, `tires.json`, `suspension.json`, `chassis.json`, `turbos.json`, `brakes.json`

- [ ] **Step 1: Rename files**

```bash
cd c:/Users/jorda/dev/dare2drive
git mv data/cards/engines.json data/cards/reactors.json
git mv data/cards/transmissions.json data/cards/drives.json
git mv data/cards/tires.json data/cards/thrusters.json
git mv data/cards/suspension.json data/cards/stabilizers.json
git mv data/cards/chassis.json data/cards/hulls.json
git mv data/cards/turbos.json data/cards/overdrives.json
git mv data/cards/brakes.json data/cards/retros.json
```

- [ ] **Step 2: Rewrite each file's `slot` field**

For each renamed file, update the `"slot": "engine"` → `"slot": "reactor"`, etc., per the slot rename mapping.

- [ ] **Step 3: Rewrite card names in each file**

Card names need ship-flavor while preserving the same scrappy/junker voice. Examples:
- `data/cards/reactors.json`: "V8 Crate Motor" → "Old Cruiser Reactor", "Boosted Inline-6" → "Patched Power-Cell", etc.
- `data/cards/drives.json`: gearbox names → drive names
- etc.

For each card, preserve `rarity`, `stats`, `print_max` exactly. Only `name`, `slot`, and any flavor `description` (if present) change.

- [ ] **Step 4: Validate JSON parses**

```bash
for f in data/cards/*.json; do python -c "import json; json.load(open('$f'))" || echo "BROKEN: $f"; done
```

Expected: no "BROKEN" lines.

- [ ] **Step 5: Commit**

```bash
git add data/cards/
git commit -m "chore(data): rewrite card data for ship vocabulary"
```

---

## Task 11: Rewrite `data/tutorial.json`

**Files:**
- Modify: `data/tutorial.json`

- [ ] **Step 1: Rewrite top-level keys + content**

- `body_type_base_stats` → `hull_class_base_stats`
- Inside, rename keys: `muscle` → `hauler`, `sport` → `skirmisher`, `compact` → `scout`. Stat values unchanged.
- `starter_cards`: rewrite the 7 names per spec:
  - "Rustbucket Inline-4" → "Rustbucket Reactor"
  - "Clunker 3-Speed" → "Clunker Drive"
  - "Bald Eagles" → "Bald Thrusters"
  - "Scrapheap Frame" → "Scrapheap Hull"
  - "Drum Stoppers" → "Drum Retros"
  - "Springboard Basics" → "Springboard Stabilizers"
  - "Junkyard Snail" → "Junkyard Overdrive"
- `npc_opponent.cards`: rename each card:
  - "Sketchy Dave's Taped-Together V4" → "Sketchy Dave's Taped-Together Crawler"
  - "Dave's Mystery Gearbox" → "Dave's Mystery Drive"
  - "Mismatched Retreads" → "Mismatched Vector-Jets"
  - "Dave's Bent Struts" → "Dave's Bent Stabilizers"
  - "Dave's Dented Cage" → "Dave's Dented Hull"
  - (Add brakes/turbo equivalents as needed): "Dave's Sticky Pads" → "Dave's Sticky Retros", "Dave's Junkyard Snail" → "Dave's Junkyard Overdrive"
- Inside each card's stats, rename any stat keys that are car-specific (e.g., `max_engine_temp` → `max_reactor_temp`). Keep numeric values.

- [ ] **Step 2: Validate JSON**

```bash
python -c "import json; json.load(open('data/tutorial.json'))"
```

- [ ] **Step 3: Commit**

```bash
git add data/tutorial.json
git commit -m "chore(data): rewrite tutorial data for ship vocabulary"
```

---

## Task 12: Rewrite `data/loot_tables.json`

**Files:**
- Modify: `data/loot_tables.json`

- [ ] **Step 1: Rename pack keys + display names**

| Old key | New key | Display name |
|---|---|---|
| `junkyard_pack` | `salvage_crate` | "Salvage Crate" |
| `performance_pack` | `gear_crate` | "Gear Crate" |
| `legend_crate` | `legend_crate` | "Legend Crate" (keep — already works) |

- [ ] **Step 2: Update flavor text** in each pack entry to ship vocabulary. Example: "A grimy box of salvaged auto parts" → "A grimy crate of scavenged ship parts."

- [ ] **Step 3: Preserve all weight tables and prices unchanged.**

- [ ] **Step 4: Validate JSON**

```bash
python -c "import json; json.load(open('data/loot_tables.json'))"
```

- [ ] **Step 5: Commit**

```bash
git add data/loot_tables.json
git commit -m "chore(data): rewrite loot table flavor for ship vocabulary"
```

---

## Task 13: Rewrite `data/class_thresholds.json` for 3 race formats

**Files:**
- Modify: `data/class_thresholds.json`

- [ ] **Step 1: Read current 6-bucket thresholds.**

- [ ] **Step 2: Collapse to 3 buckets:**
  - `sprint`: thresholds from old `drag`
  - `endurance`: thresholds from old `circuit`
  - `gauntlet`: combined thresholds from old `drift` and `rally` (use the more permissive of the two for each stat — easier qualification by design)

Drop `street` (was the default no-qualifier bucket) and `elite` (was prestige).

- [ ] **Step 3: Validate JSON + ensure `engine/class_engine.py` reads only the new keys**

```bash
python -c "import json; data = json.load(open('data/class_thresholds.json')); assert set(data.keys()) <= {'sprint', 'endurance', 'gauntlet'}, data.keys()"
```

- [ ] **Step 4: Commit**

```bash
git add data/class_thresholds.json
git commit -m "chore(data): collapse class thresholds to 3 race formats"
```

---

## Task 14: Rename `engine/rig_namer.py` → `engine/ship_namer.py` + rewrite name pool

**Files:**
- Rename: `engine/rig_namer.py` → `engine/ship_namer.py`
- Rename: `data/rig_names.json` → `data/ship_names.json`
- Rename: `tests/test_rig_namer.py` → `tests/test_ship_namer.py`

- [ ] **Step 1: Move files**

```bash
cd c:/Users/jorda/dev/dare2drive
git mv engine/rig_namer.py engine/ship_namer.py
git mv data/rig_names.json data/ship_names.json
git mv tests/test_rig_namer.py tests/test_ship_namer.py
```

- [ ] **Step 2: Update internal imports + references in the renamed module**

In `engine/ship_namer.py`, find references to `rig_names.json` and update to `ship_names.json`. Update any function/class names containing `rig` → `ship`.

- [ ] **Step 3: Update import sites**

```bash
grep -rn "rig_namer\|RigNamer" --include="*.py" .
```

Update each match (likely in `engine/race_engine.py`, `bot/cogs/race.py`, `tests/test_ship_namer.py`).

- [ ] **Step 4: Rewrite `data/ship_names.json` content**

The existing file has car-flavored name parts. Replace prefixes/suffixes/middles with ship-flavored equivalents (e.g., "Mustang" → "Mongoose", "GT" → "MK-VII", etc.). Keep the schema unchanged (same JSON shape, just replaced strings).

- [ ] **Step 5: Verify imports**

```bash
python -c "from engine.ship_namer import *"
```

- [ ] **Step 6: Commit**

```bash
git add engine/ship_namer.py data/ship_names.json tests/test_ship_namer.py
# also stage the deletions
git add -u engine/rig_namer.py data/rig_names.json tests/test_rig_namer.py
git commit -m "refactor: rename rig_namer to ship_namer + rewrite name pool"
```

---

## Task 15: Add `BOT_OWNER_DISCORD_ID` env var to settings

**Files:**
- Modify: `config/settings.py`

- [ ] **Step 1: Read current settings module**

Check if `BOT_OWNER_DISCORD_ID` already exists. If yes, skip this task.

- [ ] **Step 2: Add the field if missing**

```python
class Settings(BaseSettings):
    # ... existing fields ...
    bot_owner_discord_id: str = Field(default="", description="Discord user ID of the bot operator (for admin commands)")
```

- [ ] **Step 3: Verify import**

```bash
python -c "from config.settings import settings; print(settings.bot_owner_discord_id)"
```

- [ ] **Step 4: Update `.env.example`** (if present) to document the new var.

- [ ] **Step 5: Commit**

```bash
git add config/settings.py .env.example
git commit -m "feat(config): add BOT_OWNER_DISCORD_ID setting"
```

---

## Task 16: Create `bot/system_gating.py` with helper + command registry (TDD)

**Files:**
- Create: `bot/system_gating.py`
- Create: `tests/test_system_gating.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_system_gating.py`:

```python
"""Tests for the system gating helper."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from bot.system_gating import (
    UNIVERSE_WIDE_COMMANDS,
    SYSTEM_GATED_COMMANDS,
    get_active_system,
    requires_system,
)
from db.models import System


@pytest.mark.asyncio
async def test_get_active_system_returns_system_when_enabled(db_session, sample_sector, sample_system):
    """When the channel is an enabled system, the helper returns the System row."""
    interaction = MagicMock()
    interaction.channel_id = int(sample_system.channel_id)
    interaction.guild_id = int(sample_system.sector_id)

    result = await get_active_system(interaction, db_session)
    assert result is not None
    assert result.channel_id == sample_system.channel_id


@pytest.mark.asyncio
async def test_get_active_system_returns_none_for_unregistered_channel(db_session, sample_sector):
    """An unregistered channel returns None."""
    interaction = MagicMock()
    interaction.channel_id = 999999
    interaction.guild_id = int(sample_sector.guild_id)

    result = await get_active_system(interaction, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_get_active_system_returns_none_in_dm(db_session):
    """A DM (no guild) returns None."""
    interaction = MagicMock()
    interaction.channel_id = 12345
    interaction.guild_id = None

    result = await get_active_system(interaction, db_session)
    assert result is None


def test_command_registries_are_disjoint():
    """A command can't be both universe-wide and system-gated."""
    assert UNIVERSE_WIDE_COMMANDS.isdisjoint(SYSTEM_GATED_COMMANDS)


def test_known_universe_wide_commands_listed():
    """Profile, inventory, help, etc. are universe-wide."""
    for cmd in {"profile", "inventory", "help", "start", "skip_tutorial"}:
        assert cmd in UNIVERSE_WIDE_COMMANDS


def test_known_system_gated_commands_listed():
    """Race, pack, equip, etc. require an enabled system."""
    for cmd in {"race", "pack", "equip", "autoequip", "preview", "mint"}:
        assert cmd in SYSTEM_GATED_COMMANDS


def test_requires_system_helper():
    """requires_system('race') returns True; requires_system('profile') returns False."""
    assert requires_system("race") is True
    assert requires_system("profile") is False
```

Add the `sample_sector` and `sample_system` fixtures to `tests/conftest.py`:

```python
@pytest.fixture
async def sample_sector(db_session):
    from db.models import Sector
    sys = Sector(guild_id="111111111", name="Test Sector", owner_discord_id="999999999")
    db_session.add(sys)
    await db_session.commit()
    await db_session.refresh(sys)
    return sys


@pytest.fixture
async def sample_system(db_session, sample_sector):
    from db.models import System
    sec = System(channel_id="222222222", sector_id=sample_sector.guild_id, name="Test System")
    db_session.add(sec)
    await db_session.commit()
    await db_session.refresh(sec)
    return sec
```

- [ ] **Step 2: Run test, confirm failures are about missing `bot.system_gating` module**

```bash
pytest tests/test_system_gating.py -v
```

Expected: ImportError on `bot.system_gating`.

- [ ] **Step 3: Create `bot/system_gating.py`**

```python
"""Central registry + helper for system gating of gameplay commands."""
from __future__ import annotations

import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import System

# Commands that work anywhere (DMs, any channel, registered or not).
UNIVERSE_WIDE_COMMANDS: frozenset[str] = frozenset({
    "profile",
    "inventory",
    "inspect",
    "help",
    "start",
    "skip_tutorial",
    "garage",  # alias for legacy; primary is /hangar
    "hangar",
    # admin
    "admin_reset_player",
    "admin_set_tutorial_step",
    "admin_give_creds",
    # system/sector commands themselves
    "system",
    "sector",
})

# Commands that require an enabled system.
SYSTEM_GATED_COMMANDS: frozenset[str] = frozenset({
    "race",
    "challenge",
    "pack",
    "daily",
    "equip",
    "autoequip",
    "preview",
    "mint",
    "leaderboard",
    "wrecks",
    "market",
    "list",
    "buy",
})


def requires_system(command_name: str) -> bool:
    """Return True if a command requires an enabled system to run."""
    return command_name in SYSTEM_GATED_COMMANDS


async def get_active_system(
    interaction: discord.Interaction, session: AsyncSession
) -> System | None:
    """Return the System row for this interaction's channel, or None if unregistered/DM."""
    if interaction.guild_id is None:
        return None
    result = await session.execute(
        select(System).where(System.channel_id == str(interaction.channel_id))
    )
    return result.scalar_one_or_none()


def system_required_message() -> str:
    """User-facing message when a gameplay command runs in an unregistered channel."""
    return (
        "Game not enabled here. Ask a server admin to `/system enable` this channel."
    )
```

- [ ] **Step 4: Run tests, confirm all pass**

```bash
pytest tests/test_system_gating.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/system_gating.py tests/test_system_gating.py tests/conftest.py
git commit -m "feat(bot): add system gating helper + command registry"
```

---

## Task 17: Add `on_guild_join` listener + startup reconciliation

**Files:**
- Modify: `bot/main.py`
- Create test: `tests/test_sectors_systems.py`

- [ ] **Step 1: Write failing test for guild auto-registration**

Create `tests/test_sectors_systems.py`:

```python
"""Tests for Sector/System models and admin commands."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy import select

from db.models import Sector, System
from bot.main import register_sector_for_guild, reconcile_sectors_with_guilds


@pytest.mark.asyncio
async def test_register_sector_for_guild_creates_row(db_session):
    """register_sector_for_guild inserts a Sector row with correct fields."""
    guild = MagicMock()
    guild.id = 111111111
    guild.name = "Test Guild"
    guild.owner_id = 999999999

    await register_sector_for_guild(guild, db_session)

    result = await db_session.execute(select(Sector).where(Sector.guild_id == "111111111"))
    sys = result.scalar_one()
    assert sys.name == "Test Guild"
    assert sys.owner_discord_id == "999999999"
    assert sys.system_cap == 1


@pytest.mark.asyncio
async def test_register_sector_idempotent(db_session, sample_sector):
    """Calling register_sector_for_guild twice does not duplicate."""
    guild = MagicMock()
    guild.id = int(sample_sector.guild_id)
    guild.name = sample_sector.name
    guild.owner_id = int(sample_sector.owner_discord_id)

    await register_sector_for_guild(guild, db_session)
    await register_sector_for_guild(guild, db_session)

    result = await db_session.execute(select(Sector).where(Sector.guild_id == sample_sector.guild_id))
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_reconcile_creates_missing_sectors(db_session):
    """reconcile_sectors_with_guilds inserts rows for guilds the bot is in but DB has not seen."""
    guild_a = MagicMock(id=111, name="A", owner_id=999)
    guild_b = MagicMock(id=222, name="B", owner_id=999)

    await reconcile_sectors_with_guilds([guild_a, guild_b], db_session)

    result = await db_session.execute(select(Sector))
    sectors = result.scalars().all()
    assert {s.guild_id for s in sectors} == {"111", "222"}
```

- [ ] **Step 2: Run, confirm failure on missing `register_sector_for_guild`**

```bash
pytest tests/test_sectors_systems.py -v
```

- [ ] **Step 3: Add the helpers + listener to `bot/main.py`**

```python
# Near the other imports
from db.models import Sector
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def register_sector_for_guild(guild: discord.Guild, session: AsyncSession) -> Sector:
    """Insert a Sector row for this guild if not already present. Idempotent."""
    existing = await session.execute(
        select(Sector).where(Sector.guild_id == str(guild.id))
    )
    sys = existing.scalar_one_or_none()
    if sys is not None:
        return sys
    sys = Sector(
        guild_id=str(guild.id),
        name=guild.name,
        owner_discord_id=str(guild.owner_id) if guild.owner_id else "0",
    )
    session.add(sys)
    await session.commit()
    await session.refresh(sys)
    return sys


async def reconcile_sectors_with_guilds(
    guilds: list[discord.Guild], session: AsyncSession
) -> None:
    """Ensure every current guild has a Sector row. Call on bot startup."""
    for guild in guilds:
        await register_sector_for_guild(guild, session)


@bot.event
async def on_guild_join(guild: discord.Guild):
    """Auto-register a Sector row when the bot joins a new guild."""
    async with async_session() as session:
        await register_sector_for_guild(guild, session)
    log.info("registered_sector", guild_id=guild.id, guild_name=guild.name)


@bot.event
async def on_ready():
    """On startup, reconcile guild list with sectors table."""
    # ... existing on_ready logic ...
    async with async_session() as session:
        await reconcile_sectors_with_guilds(list(bot.guilds), session)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_sectors_systems.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/main.py tests/test_sectors_systems.py
git commit -m "feat(bot): auto-register sectors on guild_join + startup reconcile"
```

---

## Task 18: Add new system/sector admin commands (TDD)

**Files:**
- Modify: `bot/cogs/admin.py`
- Modify: `tests/test_sectors_systems.py` (extend with command tests)

- [ ] **Step 1: Extend `tests/test_sectors_systems.py`** with tests for each new command. Cover:
- `/system enable` happy path
- `/system enable` rejects when at cap
- `/system enable` rejects non-admin
- `/system disable`
- `/system rename`
- `/sector info`
- `/sector set-flavor` owner-only
- `/sector admin set-system-cap` bot-owner-only

```python
# Add to tests/test_sectors_systems.py:

@pytest.mark.asyncio
async def test_system_enable_creates_system_when_under_cap(db_session, sample_sector):
    """Admin can enable a system when under cap."""
    from bot.cogs.admin import _system_enable_logic
    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 333333
    interaction.channel.name = "test-channel"
    interaction.user.guild_permissions.manage_channels = True

    result = await _system_enable_logic(interaction, db_session)
    assert result.success is True

    sec = (await db_session.execute(
        select(System).where(System.channel_id == "333333")
    )).scalar_one()
    assert sec.sector_id == sample_sector.guild_id


@pytest.mark.asyncio
async def test_system_enable_rejects_at_cap(db_session, sample_sector, sample_system):
    """When at cap, system enable rejects with cap message."""
    from bot.cogs.admin import _system_enable_logic
    # sample_sector has system_cap=1, sample_system already counts as 1
    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 444444
    interaction.user.guild_permissions.manage_channels = True

    result = await _system_enable_logic(interaction, db_session)
    assert result.success is False
    assert "cap" in result.message.lower() or "sustain" in result.message.lower()


@pytest.mark.asyncio
async def test_system_enable_rejects_non_admin(db_session, sample_sector):
    """Non-admin gets permission rejection."""
    from bot.cogs.admin import _system_enable_logic
    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 555555
    interaction.user.guild_permissions.manage_channels = False

    result = await _system_enable_logic(interaction, db_session)
    assert result.success is False
    assert "admin" in result.message.lower() or "permission" in result.message.lower()


@pytest.mark.asyncio
async def test_system_disable_removes_row(db_session, sample_sector, sample_system):
    """Disable removes the System row."""
    from bot.cogs.admin import _system_disable_logic
    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = int(sample_system.channel_id)
    interaction.user.guild_permissions.manage_channels = True

    result = await _system_disable_logic(interaction, db_session)
    assert result.success is True
    sec = (await db_session.execute(
        select(System).where(System.channel_id == sample_system.channel_id)
    )).scalar_one_or_none()
    assert sec is None


@pytest.mark.asyncio
async def test_sector_admin_set_system_cap_bot_owner_only(db_session, sample_sector, monkeypatch):
    """Only bot owner can set system cap."""
    from bot.cogs.admin import _set_system_cap_logic
    monkeypatch.setattr("config.settings.settings.bot_owner_discord_id", "999999999")

    interaction_owner = MagicMock()
    interaction_owner.user.id = 999999999
    interaction_owner.guild_id = int(sample_sector.guild_id)

    result_ok = await _set_system_cap_logic(interaction_owner, 5, db_session)
    assert result_ok.success is True

    interaction_other = MagicMock()
    interaction_other.user.id = 111
    interaction_other.guild_id = int(sample_sector.guild_id)

    result_deny = await _set_system_cap_logic(interaction_other, 10, db_session)
    assert result_deny.success is False
```

- [ ] **Step 2: Run tests, confirm failures on missing `_system_enable_logic`, etc.**

```bash
pytest tests/test_sectors_systems.py -v
```

- [ ] **Step 3: Add the command implementations to `bot/cogs/admin.py`**

Use a small `Result` dataclass to make logic testable without going through Discord:

```python
from dataclasses import dataclass

@dataclass
class CommandResult:
    success: bool
    message: str

async def _system_enable_logic(interaction, session) -> CommandResult:
    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins (manage_channels) can enable systems.")
    sys = (await session.execute(
        select(Sector).where(Sector.guild_id == str(interaction.guild_id))
    )).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered. Try kicking and re-inviting the bot.")
    enabled_count = (await session.execute(
        select(func.count()).select_from(System).where(System.sector_id == sys.guild_id)
    )).scalar_one()
    if enabled_count >= sys.system_cap:
        return CommandResult(
            False,
            f"The {sys.name} can only sustain {sys.system_cap} active system"
            f"{'s' if sys.system_cap != 1 else ''} at its current influence. "
            f"Disable another to relocate, or grow the sector to expand."
        )
    existing = (await session.execute(
        select(System).where(System.channel_id == str(interaction.channel_id))
    )).scalar_one_or_none()
    if existing is not None:
        return CommandResult(False, "This channel is already an enabled system.")
    sec = System(
        channel_id=str(interaction.channel_id),
        sector_id=sys.guild_id,
        name=interaction.channel.name,
    )
    session.add(sec)
    await session.commit()
    return CommandResult(
        True,
        f"#{sec.name} enabled as a system. ({enabled_count + 1}/{sys.system_cap} systems active.)"
    )


async def _system_disable_logic(interaction, session) -> CommandResult:
    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins (manage_channels) can disable systems.")
    sec = (await session.execute(
        select(System).where(System.channel_id == str(interaction.channel_id))
    )).scalar_one_or_none()
    if sec is None:
        return CommandResult(False, "This channel is not an enabled system.")
    await session.delete(sec)
    await session.commit()
    return CommandResult(True, "System disabled. Gameplay commands will no longer work here.")


async def _system_rename_logic(interaction, new_name: str, session) -> CommandResult:
    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins can rename systems.")
    sec = (await session.execute(
        select(System).where(System.channel_id == str(interaction.channel_id))
    )).scalar_one_or_none()
    if sec is None:
        return CommandResult(False, "This channel is not an enabled system.")
    sec.name = new_name[:100]
    await session.commit()
    return CommandResult(True, f"System renamed to {sec.name}.")


async def _sector_info_logic(interaction, session) -> CommandResult:
    sys = (await session.execute(
        select(Sector).where(Sector.guild_id == str(interaction.guild_id))
    )).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered.")
    systems = (await session.execute(
        select(System).where(System.sector_id == sys.guild_id)
    )).scalars().all()
    system_lines = "\n".join(f"  • #{s.name}" for s in systems) or "  (none enabled)"
    msg = (
        f"**{sys.name}**\n"
        f"{sys.flavor_text or '(no flavor set)'}\n\n"
        f"Capacity: {len(systems)}/{sys.system_cap} systems\n"
        f"Active systems:\n{system_lines}"
    )
    return CommandResult(True, msg)


async def _sector_set_flavor_logic(interaction, flavor: str, session) -> CommandResult:
    sys = (await session.execute(
        select(Sector).where(Sector.guild_id == str(interaction.guild_id))
    )).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered.")
    if str(interaction.user.id) != sys.owner_discord_id:
        return CommandResult(False, "Only the sector owner can set flavor text.")
    sys.flavor_text = flavor[:500]
    await session.commit()
    return CommandResult(True, "Sector flavor updated.")


async def _set_system_cap_logic(interaction, new_cap: int, session) -> CommandResult:
    from config.settings import settings
    if str(interaction.user.id) != settings.bot_owner_discord_id:
        return CommandResult(False, "Unknown command.")  # no info leak
    sys = (await session.execute(
        select(Sector).where(Sector.guild_id == str(interaction.guild_id))
    )).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered.")
    sys.system_cap = new_cap
    await session.commit()
    return CommandResult(True, f"System cap for {sys.name} set to {new_cap}.")
```

Then add the discord-side wrappers (slash command decorators) that call these helpers and respond to interactions. These are not unit-tested directly; the helpers are.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_sectors_systems.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/admin.py tests/test_sectors_systems.py
git commit -m "feat(bot): add system/sector admin commands"
```

---

## Task 19: Apply system gating + ship copy to `bot/cogs/race.py`

**Files:**
- Modify: `bot/cogs/race.py`

- [ ] **Step 1: Read the cog to identify command bodies**

- [ ] **Step 2: Apply slot/enum/copy renames per the standard mapping** (Task 4 list).

- [ ] **Step 3: At the top of each gameplay command, add gating check**

```python
from bot.system_gating import get_active_system, system_required_message

@app_commands.command(name="race", description="...")
async def race(self, interaction: discord.Interaction):
    async with async_session() as session:
        system = await get_active_system(interaction, session)
        if system is None:
            await interaction.response.send_message(
                system_required_message(), ephemeral=True
            )
            return
        # ... existing race logic ...
        # Pass system.channel_id to Race(...) on creation:
        race = Race(
            participants=...,
            environment=...,
            results=...,
            format=resolved_format,
            system_id=system.channel_id,
        )
```

- [ ] **Step 4: Verify import + lint**

```bash
python -c "from bot.cogs.race import *"
```

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/race.py
git commit -m "feat(bot): gate race commands by system + ship vocabulary"
```

---

## Task 20: Apply system gating + ship copy to `bot/cogs/cards.py`

**Files:**
- Modify: `bot/cogs/cards.py`

- [ ] **Step 1: Apply slot/enum/copy renames + add gating check at the top of each gameplay command (`/pack`, `/daily`).**

Pattern matches Task 19. Universe-wide commands (`/inventory`, `/inspect`) skip the gating check.

- [ ] **Step 2: Update card display strings to use new slot names** (e.g., "Engine" → "Reactor" in embed labels).

- [ ] **Step 3: Verify import**

```bash
python -c "from bot.cogs.cards import *"
```

- [ ] **Step 4: Commit**

```bash
git add bot/cogs/cards.py
git commit -m "feat(bot): gate card commands by system + ship vocabulary"
```

---

## Task 21: Rename `bot/cogs/garage.py` → `bot/cogs/hangar.py` + apply gating

**Files:**
- Rename: `bot/cogs/garage.py` → `bot/cogs/hangar.py`
- Modify: `bot/main.py` (cog loading)

- [ ] **Step 1: Move file**

```bash
git mv bot/cogs/garage.py bot/cogs/hangar.py
```

- [ ] **Step 2: Inside `hangar.py`, rename slash command `/garage` → `/hangar`** and update class name `Garage` → `Hangar`. Apply slot/enum/copy renames.

- [ ] **Step 3: Update `bot/main.py` cog-loading list** to load `bot.cogs.hangar` instead of `bot.cogs.garage`.

- [ ] **Step 4: Note: `/hangar` stays universe-wide** (`UNIVERSE_WIDE_COMMANDS` already includes both `garage` and `hangar` for legacy/transitional listing — see `bot/system_gating.py`).

- [ ] **Step 5: Verify import**

```bash
python -c "from bot.cogs.hangar import *"
```

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/hangar.py bot/main.py
git add -u bot/cogs/garage.py
git commit -m "refactor(bot): rename garage cog to hangar"
```

---

## Task 22: Apply system gating + ship copy to `bot/cogs/market.py`

**Files:**
- Modify: `bot/cogs/market.py`

- [ ] **Step 1: Apply slot/enum/copy renames + gating at top of `/market list`, `/market buy`, etc.** Pattern matches Task 19.

- [ ] **Step 2: Verify import**

```bash
python -c "from bot.cogs.market import *"
```

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/market.py
git commit -m "feat(bot): gate market commands by system + ship vocabulary"
```

---

## Task 23: Update `bot/cogs/tutorial.py` with new copy

**Files:**
- Modify: `bot/cogs/tutorial.py`

- [ ] **Step 1: Update `step_hints` text per spec:**

```python
step_hints = {
    TutorialStep.STARTED: "Hold on, your story's still unfolding. Sit tight.",
    TutorialStep.INVENTORY: "Easy there. Use `/inventory` first — gotta know what you've got before you do anything with it.",
    TutorialStep.INSPECT: "You've got parts but haven't looked at them. Try `/inspect` on one of your cards first.",
    TutorialStep.EQUIP: "Parts on the floor don't make the ship fly. Use `/equip` or `/autoequip best` to install them.",
    TutorialStep.MINT: "All slots filled — use `/build preview` to see your format, then `/build mint` to lock it in.",
    TutorialStep.GARAGE: "Your ship's minted. Use `/hangar` to look it over, then head out for a run.",
    TutorialStep.RACE: "Your ship's ready. Stop stalling and use `/race` already.",
    TutorialStep.PACK: "You've got a salvage crate to open. Patience.",
}
```

- [ ] **Step 2: Add opening system line** in the `STARTED` step rendering function. Get system name via:

```python
from bot.system_gating import get_active_system

# In the /start command body, before sending the body-type prompt:
async with async_session() as session:
    system = await get_active_system(interaction, session)
system_label = system.name if system else "the outer rim"
opening_line = f"You've drifted into **{system_label}**. Sketchy Dave runs the strip here — he'll show you the ropes."
```

- [ ] **Step 3: Replace any car/race noun references with ship vocabulary** (engine, transmission, etc.).

- [ ] **Step 4: Verify import**

```bash
python -c "from bot.cogs.tutorial import *"
```

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/tutorial.py
git commit -m "feat(tutorial): rewrite copy for ship vocabulary + opening system line"
```

---

## Task 24: Update existing admin cog commands for renames

**Files:**
- Modify: `bot/cogs/admin.py` (existing commands only — new ones added in Task 18)

- [ ] **Step 1: Apply slot/enum/copy renames** to existing admin commands like `/admin_reset_player`, `/admin_set_tutorial_step`, `/admin_give_creds`. References to `body_type`, slot keys, `RigTitle`, etc.

- [ ] **Step 2: Verify import**

```bash
python -c "from bot.cogs.admin import *"
```

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/admin.py
git commit -m "refactor(admin): rename slot/class refs in existing admin commands"
```

---

## Task 25: Update API routes for renames

**Files:**
- Modify: `api/routes/races.py`, `api/routes/cards.py`, `api/routes/users.py`

- [ ] **Step 1: For each route file, find and replace per slot/enum/copy rename mapping.**

```bash
grep -rn "body_type\|car_class\|engine\|transmission\|tires\|suspension\|chassis\|turbo\|brakes\|RigTitle" api/routes/
```

Apply the standard mapping. Pay attention to Pydantic schema field names — those are part of the API contract.

- [ ] **Step 2: Verify imports**

```bash
python -c "from api.routes import races, cards, users"
```

- [ ] **Step 3: Commit**

```bash
git add api/routes/
git commit -m "refactor(api): rename slot/class refs in routes"
```

---

## Task 26: Update existing test files with new vocabulary + fixtures

**Files:**
- Modify: every `tests/test_*.py` that references old names

- [ ] **Step 1: Audit which tests reference old names**

```bash
grep -rln "body_type\|BodyType\|car_class\|CarClass\|RigTitle\|RigStatus\|engine\|transmission\|tires\|suspension\|chassis\|turbo\|brakes" tests/
```

- [ ] **Step 2: For each file, apply slot/enum/copy renames per the standard mapping.**

Special attention:
- `tests/conftest.py` — fixtures use old field names. Update.
- `tests/test_seed_data.py` — verify it loads new card files
- `tests/test_models.py` — verify it tests new model class names

- [ ] **Step 3: Run full test suite**

```bash
pytest --tb=short
```

Expected: most tests pass. Fix any remaining failures by updating test data.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update fixtures and assertions for ship vocabulary"
```

---

## Task 27: Update `scripts/dev.py` (`d2d` CLI)

**Files:**
- Modify: `scripts/dev.py`

- [ ] **Step 1: Find car/race refs in CLI subcommands**

```bash
grep -n "body_type\|car_class\|rig\|engine\|transmission" scripts/dev.py
```

- [ ] **Step 2: Apply renames. Behavior unchanged.**

- [ ] **Step 3: Verify CLI runs**

```bash
python scripts/dev.py --help
```

- [ ] **Step 4: Commit**

```bash
git add scripts/dev.py
git commit -m "refactor(scripts): rename car refs in d2d CLI"
```

---

## Task 28: Create `scripts/audit_pivot.py` (TDD)

**Files:**
- Create: `scripts/audit_pivot.py`
- Create: `tests/test_audit_pivot.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for the audit_pivot script that flags car-vocabulary leaks."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_audit_passes_on_clean_repo():
    """When no car-vocab leaks exist in player-facing files, the script exits 0."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_pivot.py")],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        pytest.fail(f"Audit failed:\n{result.stdout}\n{result.stderr}")


def test_audit_fails_when_leak_introduced(tmp_path):
    """Adding a file with 'car' as a noun in a player-facing context fails the audit."""
    # Run the audit pointed at a tmp dir with a known-bad file
    bad_file = tmp_path / "bot" / "cogs" / "leak.py"
    bad_file.parent.mkdir(parents=True)
    bad_file.write_text('MESSAGE = "Your car is ready"\n')

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_pivot.py"), str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "leak.py" in result.stdout or "leak.py" in result.stderr
```

- [ ] **Step 2: Run tests, confirm failures (script doesn't exist)**

```bash
pytest tests/test_audit_pivot.py -v
```

- [ ] **Step 3: Create `scripts/audit_pivot.py`**

```python
#!/usr/bin/env python3
"""Audit script: fail if car-era vocabulary leaks into player-facing strings."""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that should not appear in player-facing files (cogs, copy, data files).
# Use \b for word boundaries to avoid matching "carousel" or "racing" (sub-string).
LEAK_PATTERNS = [
    (re.compile(r"\bcar\b", re.IGNORECASE), "'car' as a noun"),
    (re.compile(r"\bautomobile\b", re.IGNORECASE), "'automobile'"),
    (re.compile(r"\bvehicle\b", re.IGNORECASE), "'vehicle' (use 'ship' instead)"),
    (re.compile(r"\brig\b"), "'rig' (use 'ship' or 'fleet' instead)"),
    (re.compile(r"\bbody_type\b"), "'body_type' (renamed to hull_class)"),
    (re.compile(r"\bcar_class\b"), "'car_class' (renamed to race_format)"),
]

# Old slot enum values that must no longer appear as string keys
OLD_SLOT_VALUES = ["engine", "transmission", "tires", "suspension", "chassis", "turbo", "brakes"]
SLOT_LEAK_PATTERN = re.compile(
    r'"(' + "|".join(OLD_SLOT_VALUES) + r')"'
)

# Files/dirs to scan for player-facing leaks
SCAN_DIRS = ["bot/cogs", "data", "engine"]
# Files to ignore (tests, this script, deleted files)
EXCLUDE_PATTERNS = ["test_", "audit_pivot.py", "__pycache__", ".git"]


def should_scan(path: Path) -> bool:
    s = str(path)
    return not any(p in s for p in EXCLUDE_PATTERNS)


def scan_repo(root: Path) -> list[str]:
    """Return list of leak descriptions found."""
    leaks = []
    for scan_dir in SCAN_DIRS:
        d = root / scan_dir
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if not f.is_file() or not should_scan(f):
                continue
            if f.suffix not in {".py", ".json", ".md"}:
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern, desc in LEAK_PATTERNS:
                for m in pattern.finditer(content):
                    line_no = content[:m.start()].count("\n") + 1
                    leaks.append(f"{f}:{line_no}: {desc}")
            for m in SLOT_LEAK_PATTERN.finditer(content):
                line_no = content[:m.start()].count("\n") + 1
                leaks.append(f"{f}:{line_no}: old slot value {m.group(0)}")
    return leaks


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    leaks = scan_repo(root)
    if leaks:
        print("Pivot audit FAILED. Player-facing files contain car-era vocabulary:")
        for leak in leaks:
            print(f"  {leak}")
        sys.exit(1)
    print("Pivot audit passed. No car-era vocabulary leaks found.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_audit_pivot.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the audit against the actual repo**

```bash
python scripts/audit_pivot.py
```

If any leaks remain in the actual repo, fix them — they represent real misses from earlier tasks. Re-run until clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/audit_pivot.py tests/test_audit_pivot.py
git commit -m "feat(scripts): add audit_pivot script for car-vocabulary leaks"
```

---

## Task 29: Final verification

This task runs end-to-end checks before declaring Phase 0 complete.

- [ ] **Step 1: Full test suite**

```bash
pytest --tb=short
```

Expected: pass count >= baseline (Task 1) plus the new system/audit tests added in Tasks 16, 17, 18, 28.

- [ ] **Step 2: Audit script clean**

```bash
python scripts/audit_pivot.py
```

Expected: "Pivot audit passed."

- [ ] **Step 3: Alembic round-trip**

```bash
alembic downgrade base && alembic upgrade head
```

Expected: success.

- [ ] **Step 4: Manual smoke test**

Bring up the bot and Postgres locally:

```bash
docker compose up -d db redis
python scripts/dev.py bot   # or whatever the existing bot start command is
```

In a test Discord guild:
1. Confirm `sectors` row was auto-created on bot join
2. Run `/system enable` in a channel as admin → verify system created
3. Run `/system enable` in a second channel → verify cap rejection
4. Run a gameplay command (e.g., `/race`) in the unregistered channel → verify "Game not enabled here" message
5. Run `/start` in the enabled system, walk through tutorial — verify ship vocabulary, opening system line, tutorial completes
6. Open a salvage crate, build a ship, run a race — verify slot names, hull class, race format, `Race.system_id` populated

In a second test guild with the same player:
7. Run `/inventory` — verify cards from guild 1 appear (universe-wide state)

- [ ] **Step 5: Bot-owner override smoke test**

```bash
# Set BOT_OWNER_DISCORD_ID env var to your test user
# Run /sector admin set-system-cap 3 in the test guild
# Verify system cap raised; verify second system enable now succeeds
```

- [ ] **Step 6: Tag the completion**

```bash
git tag -a phase-0-foundation -m "Phase 0: salvage-pulp foundation complete"
```

(Don't push the tag yet — wait for code review.)

- [ ] **Step 7: Push branch + open PR for review**

```bash
git push -u origin d2d-space
# Then open PR via gh CLI or web UI to merge d2d-space → main
```

PR body should reference both [the roadmap](docs/roadmap/2026-04-22-salvage-pulp-revamp.md) and [the Phase 0 spec](docs/superpowers/specs/2026-04-22-phase-0-foundation-design.md), and include the manual smoke test checklist as the "Test plan" section.

---

## Self-review notes

- **Spec coverage:** Every locked decision in the spec maps to a task. Schema → T2/T3. Slot renames → T4-8. Race format → T7+T13. Environments → T9. Card data → T10. Tutorial → T11+T23. Loot tables → T12. Ship namer → T14. Settings → T15. System gating → T16. Auto-register → T17. Admin commands → T18. Cog gating + copy → T19-T24. API → T25. Tests → T26. Scripts/CLI → T27. Audit → T28. Verification → T29.
- **No placeholders:** Every step has either real code or a precise instruction with a grep pattern.
- **Type consistency:** `CommandResult` dataclass introduced in T18 used consistently. `get_active_system()` signature consistent across T16 (definition), T19/T20/T22 (callers), T23 (tutorial caller).
- **Worktree note:** Working directly on `d2d-space`. Phase 0 is the natural completion of this branch.

---

## Open issues for the implementer

These are real decisions left to discover during implementation; they should be quick:

- Exact location/shape of `async_session()` import in `bot/main.py`. Confirm against `db/session.py`.
- Whether `bot/cogs/admin.py` already has app_command decorator patterns to mimic for the new commands.
- Whether `tests/conftest.py` already has a `db_session` async fixture with rollback isolation, or whether one needs to be created.
- Whether the existing class_engine has tests that hard-code expected output for specific stat profiles — those need updating to the 3-format output.
