# Phase 1 — Crew Sector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent crew members (Pilot / Engineer / Gunner / Navigator / Medic) that boost ship stats in encounters, gain XP over races, and are acquired via dossiers + daily leads.

**Architecture:** Three new tables (`crew_members`, `crew_assignments`, `crew_daily_leads`) layered on Phase 0's schema. A new pure engine module `engine/crew_recruit.py` handles rolling and persisting crew. `engine/stat_resolver.py` gains an `apply_crew_boosts` function that folds crew-level boosts into `BuildStats` after `aggregate_build` and before environment weighting. The race cog loads crew for each participant, threads them through `compute_race` via an added `crew` key on build dicts, and awards XP post-race.

**Tech Stack:** Python 3.11, SQLAlchemy async, Alembic, discord.py, Pillow (unused for Phase 1 — emoji only), pytest + pytest-asyncio, Prometheus client, OpenTelemetry.

**Spec:** [docs/superpowers/specs/2026-04-24-phase-1-crew-sector-design.md](../specs/2026-04-24-phase-1-crew-sector-design.md)

**Dev loop:** All tests run via `pytest` from the repo root. The `db_session` fixture in `tests/conftest.py` opens a per-test transaction against the Docker Postgres (localhost:5432). Ensure `docker-compose up db` is running for DB-backed tests.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0002_phase1_crew.py` | Alembic migration adding crew tables + enum |
| `data/crew/archetypes.json` | Archetype → primary/secondary stat mapping |
| `data/crew/rarity_boosts.json` | Rarity → base boost % (primary) |
| `data/crew/dossier_tables.json` | Dossier tier weights + prices |
| `data/crew/name_pool.json` | First names / last names / callsigns pools |
| `engine/crew_recruit.py` | Pure-ish recruitment logic: roll archetype + rarity + name; persist `CrewMember` |
| `engine/crew_xp.py` | Pure XP-award / level-up math |
| `bot/reveal.py` | Shared `RevealEntry` protocol + helpers (extracted from `cards.py`) |
| `bot/cogs/hiring.py` | Slash commands: `/dossier`, `/hire`, `/crew`, `/assign`, `/unassign` |
| `monitoring/grafana-stack/provisioning/dashboards/dare2drive-crew.json` | Grafana dashboard |
| `monitoring/grafana-stack/provisioning/alerting/crew-alerts.yaml` | Rarity-drift + constraint-violation alerts |
| `tests/test_crew_recruit.py` | Recruitment unit tests |
| `tests/test_crew_xp.py` | XP/level-up unit tests |
| `tests/test_crew_assignments.py` | DB-level assignment constraint tests |
| `tests/test_scenarios/test_crew_flow.py` | End-to-end recruit → assign → race → XP → level-up |
| `tests/test_scenarios/test_daily_lead_flow.py` | `/daily` → `/hire` flow |
| `tests/test_crew_perf.py` | Load test: 100 crew/user, 10 concurrent races, p99 < 50ms |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add `CrewArchetype` enum + `CrewMember`, `CrewAssignment`, `CrewDailyLead` models |
| `engine/stat_resolver.py` | Add `apply_crew_boosts(bs, crew) -> BuildStats` |
| `engine/race_engine.py` | Read new `crew` key from build dict; call `apply_crew_boosts` in `compute_race` |
| `bot/cogs/race.py` | Load crew per participant; thread through compute; award XP post-race |
| `bot/cogs/cards.py` | Refactor `_PackRevealView` to use `RevealEntry` protocol; extend `/daily` to roll + display today's crew lead |
| `bot/main.py` | Register `HiringCog` |
| `api/metrics.py` | Add `crew_recruited_total`, `crew_boost_apply_total`, `crew_level_up_total`, `dossier_purchased_total`, `crew_assignment_total` |
| `tests/test_pack_reveal_view.py` | Cover `CrewRevealEntry` path |
| `tests/test_stat_resolver.py` | Add `apply_crew_boosts` cases |
| `tests/test_race_engine.py` | Cover crew-in-build-dict path |
| `tests/conftest.py` | Add `sample_user`, `sample_build`, `sample_crew_*` fixtures |

---

## Task 1: Add `CrewArchetype` enum and crew models

**Files:**
- Modify: `db/models.py`
- Test: `tests/test_models.py` (existing file — we'll add cases)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_models.py`:

```python
def test_crew_archetype_enum_values():
    from db.models import CrewArchetype

    assert {a.value for a in CrewArchetype} == {
        "pilot", "engineer", "gunner", "navigator", "medic"
    }


def test_crew_member_has_required_fields():
    from db.models import CrewMember

    fields = {c.name for c in CrewMember.__table__.columns}
    assert fields >= {
        "id", "user_id", "first_name", "last_name", "callsign",
        "archetype", "rarity", "level", "xp",
        "portrait_key", "acquired_at", "retired_at",
    }


def test_crew_assignment_has_required_fields():
    from db.models import CrewAssignment

    fields = {c.name for c in CrewAssignment.__table__.columns}
    assert fields >= {"id", "crew_id", "build_id", "archetype", "assigned_at"}


def test_crew_daily_lead_has_required_fields():
    from db.models import CrewDailyLead

    fields = {c.name for c in CrewDailyLead.__table__.columns}
    assert fields >= {
        "user_id", "rolled_for_date", "archetype", "rarity",
        "first_name", "last_name", "callsign", "claimed_at", "created_at",
    }
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_models.py -v -k crew`
Expected: 4 FAILs, `ImportError` on `CrewArchetype`.

- [ ] **Step 3: Add `CrewArchetype` enum and three models to `db/models.py`**

Insert after the `Rarity` enum definition:

```python
class CrewArchetype(str, enum.Enum):
    PILOT = "pilot"
    ENGINEER = "engineer"
    GUNNER = "gunner"
    NAVIGATOR = "navigator"
    MEDIC = "medic"
```

Append at the bottom of `db/models.py` (after the existing last model):

```python
class CrewMember(Base):
    __tablename__ = "crew_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    callsign: Mapped[str] = mapped_column(String(60), nullable=False)
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    portrait_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "first_name", "last_name", "callsign",
            name="uq_crew_members_user_name",
        ),
        Index("ix_crew_members_user_archetype", "user_id", "archetype"),
    )


class CrewAssignment(Base):
    __tablename__ = "crew_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crew_members.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("build_id", "archetype", name="uq_crew_assignments_build_archetype"),
    )


class CrewDailyLead(Base):
    __tablename__ = "crew_daily_leads"

    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), primary_key=True
    )
    rolled_for_date: Mapped[Date] = mapped_column(Date, primary_key=True)
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    callsign: Mapped[str] = mapped_column(String(60), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Also update the imports at the top of `db/models.py` to include what's needed:

```python
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
```

(Adds `Date`, `Index`, `UniqueConstraint` to the existing import list.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v -k crew`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_models.py
git commit -m "feat(phase1): add CrewArchetype enum and crew models"
```

---

## Task 2: Alembic migration `0002_phase1_crew`

**Files:**
- Create: `db/migrations/versions/0002_phase1_crew.py`
- Test: `tests/test_crew_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crew_migration.py`:

```python
"""Round-trip test for the 0002 crew migration."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings


@pytest.mark.asyncio
async def test_crew_tables_exist_after_migration():
    """crew_members, crew_assignments, crew_daily_leads all exist."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return set(insp.get_table_names())
        names = await conn.run_sync(_inspect)
    await engine.dispose()
    assert {"crew_members", "crew_assignments", "crew_daily_leads"} <= names


@pytest.mark.asyncio
async def test_crew_member_unique_constraint():
    """Unique on (user_id, first_name, last_name, callsign)."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [uc["name"] for uc in insp.get_unique_constraints("crew_members")]
        uqs = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "uq_crew_members_user_name" in uqs


@pytest.mark.asyncio
async def test_crew_assignment_unique_crew_id():
    """crew_id is unique (enforces one-crew-one-build)."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            uqs = insp.get_unique_constraints("crew_assignments")
            # SQLAlchemy reports unique column constraints via get_indexes too
            indexes = insp.get_indexes("crew_assignments")
            return uqs, indexes
        uqs, indexes = await conn.run_sync(_inspect)
    await engine.dispose()
    # crew_id should be unique — may be surfaced as unique index or constraint
    has_uniq_crew_id = (
        any(set(uc["column_names"]) == {"crew_id"} for uc in uqs)
        or any(set(i["column_names"]) == {"crew_id"} and i.get("unique") for i in indexes)
    )
    assert has_uniq_crew_id


@pytest.mark.asyncio
async def test_crew_assignment_unique_build_archetype():
    """(build_id, archetype) is unique."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [uc["name"] for uc in insp.get_unique_constraints("crew_assignments")]
        uqs = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "uq_crew_assignments_build_archetype" in uqs
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_crew_migration.py -v`
Expected: FAIL — `crew_members` table doesn't exist.

- [ ] **Step 3: Write migration**

Create `db/migrations/versions/0002_phase1_crew.py`:

```python
"""phase 1 crew sector

Revision ID: 0002_phase1_crew
Revises: 0001_initial
Create Date: 2026-04-24

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_phase1_crew"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


CREW_ARCHETYPE_VALUES = ("pilot", "engineer", "gunner", "navigator", "medic")
RARITY_VALUES = ("common", "uncommon", "rare", "epic", "legendary", "ghost")


def upgrade() -> None:
    crew_archetype = postgresql.ENUM(
        *CREW_ARCHETYPE_VALUES, name="crewarchetype", create_type=False
    )
    crew_archetype.create(op.get_bind(), checkfirst=True)

    rarity = postgresql.ENUM(*RARITY_VALUES, name="rarity", create_type=False)

    op.create_table(
        "crew_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("first_name", sa.String(60), nullable=False),
        sa.Column("last_name", sa.String(60), nullable=False),
        sa.Column("callsign", sa.String(60), nullable=False),
        sa.Column("archetype", crew_archetype, nullable=False),
        sa.Column("rarity", rarity, nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("portrait_key", sa.String(60), nullable=True),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id", "first_name", "last_name", "callsign",
            name="uq_crew_members_user_name",
        ),
    )
    op.create_index(
        "ix_crew_members_user_archetype", "crew_members", ["user_id", "archetype"]
    )

    op.create_table(
        "crew_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "build_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("builds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("archetype", crew_archetype, nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "build_id", "archetype", name="uq_crew_assignments_build_archetype"
        ),
    )

    op.create_table(
        "crew_daily_leads",
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            primary_key=True,
        ),
        sa.Column("rolled_for_date", sa.Date(), primary_key=True),
        sa.Column("archetype", crew_archetype, nullable=False),
        sa.Column("rarity", rarity, nullable=False),
        sa.Column("first_name", sa.String(60), nullable=False),
        sa.Column("last_name", sa.String(60), nullable=False),
        sa.Column("callsign", sa.String(60), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("crew_daily_leads")
    op.drop_table("crew_assignments")
    op.drop_index("ix_crew_members_user_archetype", table_name="crew_members")
    op.drop_table("crew_members")
    sa.Enum(name="crewarchetype").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 4: Apply migration and verify**

Run: `alembic upgrade head`
Expected: Migration applies cleanly.

Run: `pytest tests/test_crew_migration.py -v`
Expected: All 4 PASS.

- [ ] **Step 5: Verify down migration**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: Clean round-trip. Final state matches head.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/versions/0002_phase1_crew.py tests/test_crew_migration.py
git commit -m "feat(phase1): add 0002 crew tables migration"
```

---

## Task 3: Data files — archetypes, rarity_boosts, dossiers, names

**Files:**
- Create: `data/crew/archetypes.json`
- Create: `data/crew/rarity_boosts.json`
- Create: `data/crew/dossier_tables.json`
- Create: `data/crew/name_pool.json`
- Test: `tests/test_crew_data_files.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crew_data_files.py`:

```python
"""Validate shape + coverage of Phase 1 crew data files."""

from __future__ import annotations

import json
from pathlib import Path

from db.models import CrewArchetype, Rarity

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "crew"


def _load(name: str) -> dict:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


BUILD_STATS_FIELDS = {
    "effective_power", "effective_handling", "effective_top_speed",
    "effective_grip", "effective_braking", "effective_durability",
    "effective_acceleration", "effective_stability", "effective_weather_performance",
}


def test_archetypes_covers_all_five_and_valid_stats():
    data = _load("archetypes.json")
    assert set(data.keys()) == {a.value for a in CrewArchetype}
    for arch, mapping in data.items():
        assert set(mapping.keys()) == {"primary", "secondary"}
        assert mapping["primary"] in BUILD_STATS_FIELDS
        assert mapping["secondary"] in BUILD_STATS_FIELDS


def test_rarity_boosts_covers_all_rarities_as_floats():
    data = _load("rarity_boosts.json")
    assert set(data.keys()) == {r.value for r in Rarity}
    for rarity, val in data.items():
        assert isinstance(val, (int, float))
        assert 0 < val < 1  # sanity: boost is a sub-unity fraction


def test_dossier_tables_has_three_tiers_with_correct_shape():
    data = _load("dossier_tables.json")
    assert set(data.keys()) == {"recruit_lead", "dossier", "elite_dossier"}
    for tier, cfg in data.items():
        assert set(cfg.keys()) >= {"display_name", "flavor", "size", "price", "weights"}
        assert cfg["size"] == 1
        assert isinstance(cfg["price"], int) and cfg["price"] > 0
        assert set(cfg["weights"].keys()) == {r.value for r in Rarity}


def test_name_pool_has_three_lists_each_nonempty():
    data = _load("name_pool.json")
    assert set(data.keys()) >= {"first_names", "last_names", "callsigns"}
    for key in ("first_names", "last_names", "callsigns"):
        assert isinstance(data[key], list)
        assert len(data[key]) >= 60, f"{key} must have at least 60 entries"
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_crew_data_files.py -v`
Expected: 4 FAILs (`FileNotFoundError`).

- [ ] **Step 3: Create `data/crew/archetypes.json`**

```json
{
  "pilot":     { "primary": "effective_handling",             "secondary": "effective_stability" },
  "engineer":  { "primary": "effective_power",                "secondary": "effective_acceleration" },
  "gunner":    { "primary": "effective_top_speed",            "secondary": "effective_braking" },
  "navigator": { "primary": "effective_weather_performance",  "secondary": "effective_grip" },
  "medic":     { "primary": "effective_durability",           "secondary": "effective_stability" }
}
```

- [ ] **Step 4: Create `data/crew/rarity_boosts.json`**

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

- [ ] **Step 5: Create `data/crew/dossier_tables.json`**

```json
{
  "recruit_lead": {
    "display_name": "Recruit Lead",
    "flavor": "A scratchy transmission from a washed-up outer-rim recruiter.",
    "size": 1,
    "price": 150,
    "weights": { "common": 65, "uncommon": 25, "rare": 8, "epic": 1.8, "legendary": 0.19, "ghost": 0.01 }
  },
  "dossier": {
    "display_name": "Dossier",
    "flavor": "A sealed manila folder. Someone's whole life in ten pages.",
    "size": 1,
    "price": 500,
    "weights": { "common": 10, "uncommon": 35, "rare": 35, "epic": 15, "legendary": 4.8, "ghost": 0.2 }
  },
  "elite_dossier": {
    "display_name": "Elite Dossier",
    "flavor": "Security-cleared. Names you weren't supposed to see.",
    "size": 1,
    "price": 1500,
    "weights": { "common": 0, "uncommon": 0, "rare": 40, "epic": 40, "legendary": 17, "ghost": 3 }
  }
}
```

- [ ] **Step 6: Create `data/crew/name_pool.json`**

Seed with ≥60 entries per list. Pulp-salvage voice.

```json
{
  "first_names": [
    "Jax", "Mira", "Rook", "Vash", "Nova", "Cas", "Sable", "Orin", "Lyra", "Hale",
    "Dax", "Kira", "Tov", "Ren", "Ash", "Bren", "Cyril", "Donna", "Eiko", "Finch",
    "Garm", "Hex", "Iyla", "Jett", "Kale", "Lox", "Mags", "Nix", "Ode", "Pell",
    "Quinn", "Rae", "Saff", "Tam", "Uzi", "Vale", "Wren", "Xan", "Yara", "Zed",
    "Brim", "Ciri", "Dove", "Eli", "Fable", "Gil", "Huck", "Ira", "Jolan", "Kest",
    "Lark", "Moth", "Niko", "Otto", "Pax", "Quill", "Ros", "Sev", "Thorne", "Una",
    "Vek", "Wade", "Xero", "Yuri", "Zan"
  ],
  "last_names": [
    "Krell", "Voss", "Marek", "Ren", "Cask", "Thorn", "Vex", "Harrow", "Drax", "Lund",
    "Oro", "Solch", "Tain", "Urbane", "Weld", "Yark", "Zhou", "Abrek", "Bessel", "Crosh",
    "Duvin", "Escher", "Felk", "Grash", "Halk", "Itzel", "Jarn", "Korzun", "Luma", "Mosk",
    "Nine", "Orlov", "Pram", "Quist", "Rake", "Sakar", "Tull", "Ushi", "Velk", "Wold",
    "Yoruba", "Zek", "Brock", "Cleft", "Dome", "Eyre", "Fuller", "Grave", "Holt", "Ince",
    "Jasp", "Klang", "Lithe", "Mule", "Nash", "Osk", "Prax", "Quench", "Rowe", "Strat",
    "Tovek", "Urn", "Vance", "Wurt", "Yost"
  ],
  "callsigns": [
    "Blackjack", "Sixgun", "Crow", "Ironhand", "Ghostwhistle", "Dustdevil", "Prowler",
    "Shade", "Briar", "Hollowpoint", "Driftwood", "Tin-Man", "Ratchet", "Patchwork",
    "Skinflint", "Holdout", "Scrapjaw", "Rustlung", "Saltwire", "Bonecold",
    "Clockwork", "Deadeye", "Echoback", "Flashfire", "Gutterball", "Halfpenny", "Ironjaw",
    "Junker", "Knucklehead", "Lightfoot", "Muzzleflash", "Nightcrawler", "Outrunner", "Panhandle",
    "Quickdraw", "Roadkill", "Salvager", "Tumbleweed", "Undercut", "Vagrant",
    "Warpath", "Xerox", "Yardbird", "Zincwright", "Ashcloud", "Bramblehand", "Coalfoot",
    "Ditchrunner", "Edgewise", "Fenceline", "Gravedigger", "Hellbent", "Ironshore", "Jawsmith",
    "Kerosene", "Latenight", "Moonshine", "Nearside", "Overhang", "Pitworker",
    "Quicksilver", "Rawhide", "Shinwreck", "Tarpit", "Underwire"
  ]
}
```

- [ ] **Step 7: Run tests to verify**

Run: `pytest tests/test_crew_data_files.py -v`
Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add data/crew/ tests/test_crew_data_files.py
git commit -m "feat(phase1): add crew data files (archetypes, boosts, dossiers, names)"
```

---

## Task 4: Extend `engine/stat_resolver.py` with `apply_crew_boosts`

**Files:**
- Modify: `engine/stat_resolver.py`
- Test: `tests/test_stat_resolver.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_stat_resolver.py`:

```python
from unittest.mock import MagicMock

from db.models import CrewArchetype, Rarity
from engine.stat_resolver import BuildStats, apply_crew_boosts


def _crew(archetype_value: str, rarity_value: str, level: int = 1) -> MagicMock:
    m = MagicMock()
    m.archetype = MagicMock(value=archetype_value)
    m.rarity = MagicMock(value=rarity_value)
    m.level = level
    return m


class TestApplyCrewBoosts:
    def test_empty_crew_is_identity(self):
        bs = BuildStats(effective_handling=100.0)
        out = apply_crew_boosts(bs, [])
        assert out.effective_handling == 100.0

    def test_common_pilot_l1_gives_2pct_handling(self):
        bs = BuildStats(effective_handling=100.0, effective_stability=100.0)
        apply_crew_boosts(bs, [_crew("pilot", "common", level=1)])
        assert bs.effective_handling == pytest.approx(100.0 * 1.02)
        # secondary = primary / 2 = 1%
        assert bs.effective_stability == pytest.approx(100.0 * 1.01)

    def test_legendary_pilot_l10_gives_19pct_handling(self):
        bs = BuildStats(effective_handling=100.0)
        apply_crew_boosts(bs, [_crew("pilot", "legendary", level=10)])
        # 0.10 * (1 + 9*0.1) = 0.10 * 1.9 = 0.19
        assert bs.effective_handling == pytest.approx(100.0 * 1.19)

    def test_two_pilots_stack_multiplicatively(self):
        bs = BuildStats(effective_handling=100.0)
        apply_crew_boosts(
            bs,
            [_crew("pilot", "rare", 1), _crew("pilot", "rare", 1)],
        )
        # Each +5% compounds: 100 * 1.05 * 1.05
        assert bs.effective_handling == pytest.approx(100.0 * 1.05 * 1.05)

    def test_engineer_boosts_power_and_acceleration(self):
        bs = BuildStats(effective_power=200.0, effective_acceleration=50.0)
        apply_crew_boosts(bs, [_crew("engineer", "rare", 1)])
        assert bs.effective_power == pytest.approx(200.0 * 1.05)
        assert bs.effective_acceleration == pytest.approx(50.0 * 1.025)

    def test_medic_stability_stacks_with_pilot_stability(self):
        bs = BuildStats(effective_durability=100.0, effective_stability=100.0)
        apply_crew_boosts(
            bs,
            [_crew("medic", "rare", 1), _crew("pilot", "rare", 1)],
        )
        # medic secondary: +2.5%, pilot secondary: +2.5% — compound
        assert bs.effective_stability == pytest.approx(100.0 * 1.025 * 1.025)
```

Add `import pytest` at the top of the test file if not already present.

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_stat_resolver.py -v -k Crew`
Expected: `ImportError` on `apply_crew_boosts`.

- [ ] **Step 3: Implement `apply_crew_boosts`**

Append to `engine/stat_resolver.py`:

```python
_ARCHETYPE_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "crew" / "archetypes.json"
_RARITY_BOOSTS_PATH = Path(__file__).resolve().parent.parent / "data" / "crew" / "rarity_boosts.json"

_archetype_mapping_cache: dict[str, dict[str, str]] | None = None
_rarity_boosts_cache: dict[str, float] | None = None


def _get_archetype_mapping() -> dict[str, dict[str, str]]:
    global _archetype_mapping_cache
    if _archetype_mapping_cache is None:
        with open(_ARCHETYPE_MAPPING_PATH, "r", encoding="utf-8") as f:
            _archetype_mapping_cache = json.load(f)
    return _archetype_mapping_cache


def _get_rarity_boosts() -> dict[str, float]:
    global _rarity_boosts_cache
    if _rarity_boosts_cache is None:
        with open(_RARITY_BOOSTS_PATH, "r", encoding="utf-8") as f:
            _rarity_boosts_cache = json.load(f)
    return _rarity_boosts_cache


def _bump(bs: BuildStats, stat_name: str, pct: float) -> None:
    """Multiplicatively bump a BuildStats attribute by `pct` (e.g. 0.05 = +5%)."""
    current = getattr(bs, stat_name)
    setattr(bs, stat_name, current * (1.0 + pct))


def apply_crew_boosts(bs: BuildStats, crew: list[Any]) -> BuildStats:
    """Fold assigned crew boosts into the BuildStats in place.

    Called AFTER aggregate_build and BEFORE environment weighting. Pure — no DB access.

    Each crew member's archetype determines primary/secondary stats. Rarity and
    level determine magnitude. Multiple crew on the same stat compound multiplicatively.
    """
    mapping = _get_archetype_mapping()
    base_boosts = _get_rarity_boosts()
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

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_stat_resolver.py -v -k Crew`
Expected: All 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/stat_resolver.py tests/test_stat_resolver.py
git commit -m "feat(phase1): add apply_crew_boosts to stat resolver"
```

---

## Task 5: Create `engine/crew_xp.py` — pure XP math

**Files:**
- Create: `engine/crew_xp.py`
- Test: `tests/test_crew_xp.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crew_xp.py`:

```python
"""Unit tests for engine.crew_xp — pure XP math."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine.crew_xp import MAX_LEVEL, award_xp, xp_for_next


def _member(level: int = 1, xp: int = 0) -> MagicMock:
    m = MagicMock()
    m.level = level
    m.xp = xp
    return m


class TestXpForNext:
    def test_level_1_to_2_is_50(self):
        assert xp_for_next(1) == 50

    def test_level_2_to_3_is_200(self):
        assert xp_for_next(2) == 200

    def test_level_9_to_10_is_4050(self):
        assert xp_for_next(9) == 4050


class TestAwardXp:
    def test_below_threshold_no_level_up(self):
        m = _member(level=1, xp=0)
        leveled = award_xp(m, 30)
        assert m.xp == 30
        assert m.level == 1
        assert leveled is False

    def test_exact_threshold_levels_up(self):
        m = _member(level=1, xp=0)
        leveled = award_xp(m, 50)
        assert m.level == 2
        assert m.xp == 0  # consumed
        assert leveled is True

    def test_multi_level_in_one_grant(self):
        # 50 XP → L2, 200 XP → L3, 450 XP → L4. Total 700 jumps from L1 to L4.
        m = _member(level=1, xp=0)
        leveled = award_xp(m, 700)
        assert m.level == 4
        # After L4, xp remains 700 - 50 - 200 - 450 = 0
        assert m.xp == 0
        assert leveled is True

    def test_partial_xp_after_level_up_retained(self):
        m = _member(level=1, xp=0)
        award_xp(m, 75)
        assert m.level == 2
        assert m.xp == 25  # 75 - 50 = 25

    def test_level_cap_at_10(self):
        m = _member(level=10, xp=0)
        leveled = award_xp(m, 100_000)
        assert m.level == MAX_LEVEL
        assert m.xp == 0  # capped; excess discarded
        assert leveled is False

    def test_approaching_cap_caps_cleanly(self):
        m = _member(level=9, xp=0)
        # L9 → L10 needs 4050 XP; award 10_000 should land at L10 with 0 xp
        award_xp(m, 10_000)
        assert m.level == MAX_LEVEL
        assert m.xp == 0
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_crew_xp.py -v`
Expected: `ImportError` on `engine.crew_xp`.

- [ ] **Step 3: Implement `engine/crew_xp.py`**

```python
"""Pure XP / level-up math for crew members.

No DB access. Callers mutate `member.xp` and `member.level` in place and are
responsible for persisting.
"""

from __future__ import annotations

from typing import Any

MAX_LEVEL = 10


def xp_for_next(level: int) -> int:
    """XP required to advance FROM `level` TO `level + 1`. 50 * level^2."""
    return 50 * level * level


def award_xp(member: Any, amount: int) -> bool:
    """Add XP to a crew member, level up as long as thresholds are crossed.

    At `MAX_LEVEL`, any further XP is discarded (xp stays at 0; level does not rise).
    Returns True if the member gained at least one level.
    """
    if member.level >= MAX_LEVEL:
        member.xp = 0
        return False

    member.xp += amount
    leveled = False
    while member.level < MAX_LEVEL and member.xp >= xp_for_next(member.level):
        member.xp -= xp_for_next(member.level)
        member.level += 1
        leveled = True

    if member.level >= MAX_LEVEL:
        member.xp = 0  # cap cleanup

    return leveled
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_crew_xp.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/crew_xp.py tests/test_crew_xp.py
git commit -m "feat(phase1): pure XP/level-up math in engine/crew_xp.py"
```

---

## Task 6: Create `engine/crew_recruit.py`

**Files:**
- Create: `engine/crew_recruit.py`
- Test: `tests/test_crew_recruit.py`

- [ ] **Step 1: Write the failing unit tests (pure function parts)**

Create `tests/test_crew_recruit.py`:

```python
"""Unit tests for engine.crew_recruit."""

from __future__ import annotations

import random
from collections import Counter

import pytest

from db.models import CrewArchetype, Rarity
from engine.crew_recruit import (
    CrewRollResult,
    InsufficientCreditsError,
    roll_crew,
)


class TestRollCrew:
    def test_archetype_is_uniform_over_10k_rolls(self):
        random.seed(42)
        counts = Counter()
        for _ in range(10_000):
            r = roll_crew(weights={"common": 100}, existing_names=set())
            counts[r.archetype] += 1
        # Each archetype should land roughly 2000 ± 300 at 10k samples (χ² ballpark)
        for arch in CrewArchetype:
            assert 1700 < counts[arch.value] < 2300

    def test_rarity_follows_weights_within_tolerance(self):
        random.seed(42)
        weights = {"common": 0, "uncommon": 0, "rare": 40, "epic": 40, "legendary": 17, "ghost": 3}
        counts = Counter()
        for _ in range(10_000):
            r = roll_crew(weights=weights, existing_names=set())
            counts[r.rarity] += 1
        # Expected: rare ~4000, epic ~4000, legendary ~1700, ghost ~300
        assert 3700 < counts["rare"] < 4300
        assert 3700 < counts["epic"] < 4300
        assert 1500 < counts["legendary"] < 1900
        assert 200 < counts["ghost"] < 400
        assert counts.get("common", 0) == 0
        assert counts.get("uncommon", 0) == 0

    def test_name_collision_reroll(self):
        random.seed(42)
        # Pre-seed existing_names with 5 fixed tuples to simulate collisions.
        # We can't guarantee these get hit without replicating the rolling logic,
        # so instead we fill existing_names with a huge block of possible triples
        # and assert that roll_crew's fallback (numeric suffix) fires.
        ...
        # Simpler assertion: rolling 500 times with fully-growing existing_names
        # produces 500 unique names.
        existing: set[tuple[str, str, str]] = set()
        for _ in range(500):
            r = roll_crew(weights={"common": 100}, existing_names=existing)
            key = (r.first_name, r.last_name, r.callsign)
            assert key not in existing
            existing.add(key)


class TestCrewRollResultShape:
    def test_result_has_expected_fields(self):
        r = roll_crew(weights={"common": 100}, existing_names=set())
        assert isinstance(r, CrewRollResult)
        assert r.archetype in {a.value for a in CrewArchetype}
        assert r.rarity in {ra.value for ra in Rarity}
        assert r.first_name and r.last_name and r.callsign
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_crew_recruit.py -v`
Expected: `ImportError` on `engine.crew_recruit`.

- [ ] **Step 3: Implement pure-function portion of `engine/crew_recruit.py`**

Create `engine/crew_recruit.py`:

```python
"""Crew recruitment engine — archetype / rarity / name rolls + DB persist."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import CrewArchetype, CrewDailyLead, CrewMember, Rarity, User

log = get_logger(__name__)

_NAME_POOL_PATH = Path(__file__).resolve().parent.parent / "data" / "crew" / "name_pool.json"
_DOSSIER_TABLES_PATH = Path(__file__).resolve().parent.parent / "data" / "crew" / "dossier_tables.json"

_name_pool_cache: dict[str, list[str]] | None = None
_dossier_tables_cache: dict[str, dict[str, Any]] | None = None


class InsufficientCreditsError(Exception):
    """Raised when a user lacks creds to buy a dossier."""


class NoDailyLeadError(Exception):
    """Raised when a user runs /hire without a rolled-and-unclaimed lead."""


class LeadAlreadyClaimedError(Exception):
    """Raised when /hire is run twice on the same day."""


@dataclass
class CrewRollResult:
    archetype: str
    rarity: str
    first_name: str
    last_name: str
    callsign: str


def _get_name_pool() -> dict[str, list[str]]:
    global _name_pool_cache
    if _name_pool_cache is None:
        with open(_NAME_POOL_PATH, "r", encoding="utf-8") as f:
            _name_pool_cache = json.load(f)
    return _name_pool_cache


def _get_dossier_tables() -> dict[str, dict[str, Any]]:
    global _dossier_tables_cache
    if _dossier_tables_cache is None:
        with open(_DOSSIER_TABLES_PATH, "r", encoding="utf-8") as f:
            _dossier_tables_cache = json.load(f)
    return _dossier_tables_cache


def _roll_name(
    existing_names: set[tuple[str, str, str]], max_attempts: int = 5
) -> tuple[str, str, str]:
    """Roll (first, last, callsign) avoiding collisions with `existing_names`.

    After `max_attempts` full rerolls, appends a numeric suffix to callsign
    until unique.
    """
    pool = _get_name_pool()
    for _ in range(max_attempts):
        triple = (
            random.choice(pool["first_names"]),
            random.choice(pool["last_names"]),
            random.choice(pool["callsigns"]),
        )
        if triple not in existing_names:
            return triple
    # Fallback: suffix the callsign
    base = (
        random.choice(pool["first_names"]),
        random.choice(pool["last_names"]),
        random.choice(pool["callsigns"]),
    )
    suffix = 2
    while (base[0], base[1], f"{base[2]}-{suffix}") in existing_names:
        suffix += 1
    return (base[0], base[1], f"{base[2]}-{suffix}")


def roll_crew(
    weights: dict[str, float],
    existing_names: set[tuple[str, str, str]],
) -> CrewRollResult:
    """Pure: roll archetype (uniform), rarity (weighted), name (unique-ish)."""
    archetype = random.choice([a.value for a in CrewArchetype])
    rarities = [r for r, w in weights.items() if w > 0]
    rarity_weights = [weights[r] for r in rarities]
    rarity = random.choices(rarities, weights=rarity_weights, k=1)[0]
    first, last, callsign = _roll_name(existing_names)
    return CrewRollResult(
        archetype=archetype,
        rarity=rarity,
        first_name=first,
        last_name=last,
        callsign=callsign,
    )


async def _load_existing_names(
    session: AsyncSession, user_id: str
) -> set[tuple[str, str, str]]:
    result = await session.execute(
        select(CrewMember.first_name, CrewMember.last_name, CrewMember.callsign).where(
            CrewMember.user_id == user_id
        )
    )
    return {(r[0], r[1], r[2]) for r in result.all()}


async def recruit_crew_from_dossier(
    session: AsyncSession, user: User, tier: str
) -> CrewMember:
    """Deduct creds, roll, persist a CrewMember.

    Raises `InsufficientCreditsError` if user can't afford the tier.
    Raises `KeyError` if tier is unknown.
    """
    tables = _get_dossier_tables()
    cfg = tables[tier]
    price = cfg["price"]
    if user.currency < price:
        raise InsufficientCreditsError(
            f"User {user.discord_id} has {user.currency} creds; needs {price}."
        )

    existing = await _load_existing_names(session, user.discord_id)
    roll = roll_crew(cfg["weights"], existing)
    user.currency -= price

    member = CrewMember(
        user_id=user.discord_id,
        first_name=roll.first_name,
        last_name=roll.last_name,
        callsign=roll.callsign,
        archetype=CrewArchetype(roll.archetype),
        rarity=Rarity(roll.rarity),
    )
    session.add(member)
    await session.flush()
    log.info(
        "crew recruited",
        extra={
            "event": "crew_recruited",
            "user_id": user.discord_id,
            "crew_id": str(member.id),
            "archetype": member.archetype.value,
            "rarity": member.rarity.value,
            "source": "dossier",
            "tier": tier,
        },
    )
    return member


async def recruit_crew_from_daily_lead(
    session: AsyncSession, user: User, lead: CrewDailyLead
) -> CrewMember:
    """Consume today's unclaimed lead, persist as CrewMember, stamp claimed_at.

    Raises `LeadAlreadyClaimedError` if already claimed.
    """
    if lead.claimed_at is not None:
        raise LeadAlreadyClaimedError(
            f"User {user.discord_id} already claimed today's lead."
        )

    member = CrewMember(
        user_id=user.discord_id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        callsign=lead.callsign,
        archetype=lead.archetype,
        rarity=lead.rarity,
    )
    session.add(member)
    lead.claimed_at = datetime.now(timezone.utc)
    await session.flush()
    log.info(
        "crew recruited",
        extra={
            "event": "crew_recruited",
            "user_id": user.discord_id,
            "crew_id": str(member.id),
            "archetype": member.archetype.value,
            "rarity": member.rarity.value,
            "source": "daily_lead",
        },
    )
    return member


async def get_or_roll_today_lead(
    session: AsyncSession, user: User, today: date | None = None
) -> CrewDailyLead:
    """Return today's lead, rolling one if not already present. Idempotent."""
    today = today or datetime.now(timezone.utc).date()
    existing = await session.get(CrewDailyLead, (user.discord_id, today))
    if existing is not None:
        return existing

    tables = _get_dossier_tables()
    weights = tables["recruit_lead"]["weights"]
    existing_names = await _load_existing_names(session, user.discord_id)
    roll = roll_crew(weights, existing_names)

    lead = CrewDailyLead(
        user_id=user.discord_id,
        rolled_for_date=today,
        archetype=CrewArchetype(roll.archetype),
        rarity=Rarity(roll.rarity),
        first_name=roll.first_name,
        last_name=roll.last_name,
        callsign=roll.callsign,
    )
    session.add(lead)
    await session.flush()
    return lead
```

- [ ] **Step 4: Run unit tests to verify pure-function portion**

Run: `pytest tests/test_crew_recruit.py -v`
Expected: All PASS.

- [ ] **Step 5: Add DB-backed tests for `recruit_crew_from_dossier` + `get_or_roll_today_lead`**

Append to `tests/test_crew_recruit.py`:

```python
from datetime import date

from db.models import Build, CrewDailyLead, CrewMember, HullClass, User
from engine.crew_recruit import (
    get_or_roll_today_lead,
    recruit_crew_from_daily_lead,
    recruit_crew_from_dossier,
)


@pytest_asyncio.fixture
async def sample_user_with_creds(db_session):
    user = User(
        discord_id="777777777",
        username="testpilot",
        hull_class=HullClass.SKIRMISHER,
        currency=2000,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_recruit_from_dossier_deducts_creds_and_creates_crew(
    db_session, sample_user_with_creds
):
    user = sample_user_with_creds
    member = await recruit_crew_from_dossier(db_session, user, "dossier")
    assert user.currency == 1500  # 2000 - 500
    assert member.id is not None
    assert member.archetype.value in {a.value for a in CrewArchetype}


@pytest.mark.asyncio
async def test_recruit_from_dossier_insufficient_creds_raises(db_session):
    user = User(
        discord_id="888888888",
        username="broke",
        hull_class=HullClass.SKIRMISHER,
        currency=10,
    )
    db_session.add(user)
    await db_session.flush()
    with pytest.raises(InsufficientCreditsError):
        await recruit_crew_from_dossier(db_session, user, "dossier")


@pytest.mark.asyncio
async def test_get_or_roll_today_lead_is_idempotent(
    db_session, sample_user_with_creds
):
    user = sample_user_with_creds
    today = date(2026, 4, 24)
    lead1 = await get_or_roll_today_lead(db_session, user, today=today)
    lead2 = await get_or_roll_today_lead(db_session, user, today=today)
    assert (lead1.user_id, lead1.rolled_for_date) == (lead2.user_id, lead2.rolled_for_date)
    assert lead1.first_name == lead2.first_name  # same roll returned


@pytest.mark.asyncio
async def test_recruit_from_daily_lead_stamps_claimed(
    db_session, sample_user_with_creds
):
    user = sample_user_with_creds
    lead = await get_or_roll_today_lead(db_session, user)
    member = await recruit_crew_from_daily_lead(db_session, user, lead)
    assert lead.claimed_at is not None
    assert member.first_name == lead.first_name


@pytest.mark.asyncio
async def test_recruit_from_daily_lead_twice_raises(
    db_session, sample_user_with_creds
):
    user = sample_user_with_creds
    lead = await get_or_roll_today_lead(db_session, user)
    await recruit_crew_from_daily_lead(db_session, user, lead)
    with pytest.raises(LeadAlreadyClaimedError):
        await recruit_crew_from_daily_lead(db_session, user, lead)
```

Add `import pytest_asyncio` at the top of `tests/test_crew_recruit.py`.

- [ ] **Step 6: Run DB-backed tests to verify**

Run: `pytest tests/test_crew_recruit.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/crew_recruit.py tests/test_crew_recruit.py
git commit -m "feat(phase1): crew recruitment engine"
```

---

## Task 7: DB-level assignment constraint tests

**Files:**
- Test: `tests/test_crew_assignments.py`

This task only verifies the constraints added in Task 1 behave correctly at the DB level. No new production code.

- [ ] **Step 1: Write the tests**

Create `tests/test_crew_assignments.py`:

```python
"""DB-level constraint tests for crew_assignments."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from db.models import (
    Build,
    CrewArchetype,
    CrewAssignment,
    CrewMember,
    HullClass,
    Rarity,
    User,
)


@pytest_asyncio.fixture
async def user_with_build(db_session):
    u = User(
        discord_id="333333333",
        username="assigner",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
    )
    db_session.add(u)
    await db_session.flush()
    b = Build(user_id=u.discord_id, name="Test Ship", hull_class=HullClass.SKIRMISHER)
    db_session.add(b)
    await db_session.flush()
    return u, b


@pytest_asyncio.fixture
async def two_pilots(db_session, user_with_build):
    u, _ = user_with_build
    c1 = CrewMember(
        user_id=u.discord_id,
        first_name="A",
        last_name="B",
        callsign="C1",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    c2 = CrewMember(
        user_id=u.discord_id,
        first_name="D",
        last_name="E",
        callsign="C2",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    db_session.add_all([c1, c2])
    await db_session.flush()
    return c1, c2


@pytest.mark.asyncio
async def test_unique_build_archetype_constraint(db_session, user_with_build, two_pilots):
    """Two pilots on the same build should error via (build_id, archetype) unique."""
    _, build = user_with_build
    c1, c2 = two_pilots
    db_session.add(
        CrewAssignment(crew_id=c1.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()
    db_session.add(
        CrewAssignment(crew_id=c2.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_unique_crew_id_constraint(db_session, user_with_build, two_pilots):
    """Same crew on two builds should error via crew_id unique."""
    u, build = user_with_build
    c1, _ = two_pilots
    b2 = Build(user_id=u.discord_id, name="Ship 2", hull_class=HullClass.SKIRMISHER)
    db_session.add(b2)
    await db_session.flush()

    db_session.add(
        CrewAssignment(crew_id=c1.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()
    db_session.add(
        CrewAssignment(crew_id=c1.id, build_id=b2.id, archetype=CrewArchetype.PILOT)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_cascade_on_crew_delete(db_session, user_with_build, two_pilots):
    """Deleting a crew member cascades to its assignment."""
    from sqlalchemy import select

    _, build = user_with_build
    c1, _ = two_pilots
    db_session.add(
        CrewAssignment(crew_id=c1.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    await db_session.delete(c1)
    await db_session.flush()

    result = await db_session.execute(
        select(CrewAssignment).where(CrewAssignment.crew_id == c1.id)
    )
    assert result.first() is None
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_crew_assignments.py -v`
Expected: All PASS (constraints were created in Task 1/2).

- [ ] **Step 3: Commit**

```bash
git add tests/test_crew_assignments.py
git commit -m "test(phase1): DB constraint tests for crew_assignments"
```

---

## Task 8: Thread crew through `compute_race` (race_engine)

**Files:**
- Modify: `engine/race_engine.py`
- Test: `tests/test_race_engine.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_race_engine.py`:

```python
class TestComputeRaceWithCrew:
    def test_crew_in_build_dict_moves_score(self, full_build):
        """A build with crew should have a different score than without."""
        from unittest.mock import MagicMock

        def _crew(arch, rarity, lvl=10):
            m = MagicMock()
            m.archetype = MagicMock(value=arch)
            m.rarity = MagicMock(value=rarity)
            m.level = lvl
            return m

        build_with_crew = {
            **full_build,
            "crew": [_crew("pilot", "legendary", 10), _crew("engineer", "legendary", 10)],
        }
        build_without_crew = {**full_build, "user_id": full_build["user_id"] + "x", "crew": []}

        from engine.environment import EnvironmentCondition

        env = EnvironmentCondition(
            name="clear",
            display_name="Clear Track",
            weights={k: 1.0 for k in [
                "power", "handling", "top_speed", "grip", "braking",
                "durability", "acceleration", "stability", "weather_performance",
            ]},
            variance_multiplier=0.0,
        )
        from engine.race_engine import compute_race

        # Seed variance-free runs
        import random
        random.seed(42)
        r1 = compute_race([build_with_crew, build_without_crew], environment=env)
        random.seed(42)
        r2 = compute_race([build_without_crew, build_with_crew], environment=env)

        # With same variance, the crewed ship should outscore the uncrewed in both runs
        def _score(result, user_id):
            for p in result.placements:
                if p.user_id == user_id:
                    return p.score
            raise KeyError(user_id)

        assert _score(r1, build_with_crew["user_id"]) > _score(
            r1, build_without_crew["user_id"]
        )
        assert _score(r2, build_with_crew["user_id"]) > _score(
            r2, build_without_crew["user_id"]
        )

    def test_build_without_crew_key_still_works(self, full_build):
        """Backward compat: build dict without a 'crew' key computes normally."""
        from engine.race_engine import compute_race

        # Explicitly no 'crew' key
        result = compute_race([full_build])
        assert len(result.placements) == 1
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_race_engine.py -v -k Crew`
Expected: Second test passes (backward compat), first test may pass or fail depending on variance — but is not currently reading `build["crew"]`, so crewed and uncrewed produce identical scores and the `>` assertion FAILs.

- [ ] **Step 3: Thread crew into `compute_race`**

In `engine/race_engine.py`, add import at top:

```python
from engine.stat_resolver import BuildStats, aggregate_build, apply_crew_boosts
```

Modify the loop in `compute_race` (around line 161) to call `apply_crew_boosts` after `aggregate_build`:

```python
        # 1. Aggregate build stats
        hull_class = build.get("hull_class")
        build_stats = aggregate_build(slots, cards, hull_class=hull_class)

        # 1b. Fold crew boosts (if any)
        crew = build.get("crew", [])
        if crew:
            build_stats = apply_crew_boosts(build_stats, crew)

        # 2. Convert to flat dict and apply environment weights
        flat = _build_stats_to_flat(build_stats)
        weighted = apply_environment_weights(flat, environment)
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_race_engine.py -v -k Crew`
Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/race_engine.py tests/test_race_engine.py
git commit -m "feat(phase1): thread crew into compute_race"
```

---

## Task 9: Race cog — load crew per participant, award XP post-race

**Files:**
- Modify: `bot/cogs/race.py`
- Test: `tests/test_scenarios/test_crew_flow.py` (coverage here)

This task adds two pieces:
1. Before `compute_race`, for each participant, load their assigned crew and attach to the build dict.
2. After `compute_race`, iterate placements, award XP to each crew, persist level changes, and append a level-up line to the result embed.

- [ ] **Step 1: Add helper `_load_assigned_crew_for_user`**

Append to `bot/cogs/race.py` (e.g., near existing helpers, before the cog class):

```python
from sqlalchemy.orm import selectinload

from db.models import Build as _BuildModel, CrewAssignment, CrewMember


async def _load_assigned_crew_for_user(
    session: AsyncSession, user_id: str
) -> tuple[uuid.UUID | None, list[CrewMember]]:
    """Return (active_build_id, list_of_assigned_crew) for a user, or (None, [])."""
    result = await session.execute(
        select(_BuildModel)
        .where(_BuildModel.user_id == user_id, _BuildModel.is_active.is_(True))
        .limit(1)
    )
    build = result.scalar_one_or_none()
    if build is None:
        return None, []

    ca_result = await session.execute(
        select(CrewMember)
        .join(CrewAssignment, CrewAssignment.crew_id == CrewMember.id)
        .where(CrewAssignment.build_id == build.id)
    )
    return build.id, list(ca_result.scalars().all())
```

- [ ] **Step 2: Thread crew + build_id into the race dicts**

Find each `compute_race(...)` call site in `bot/cogs/race.py` (race.py:275 and race.py:739 per the earlier grep). Immediately before each, load crew for every participant and add to their build dict. Example for `race.py:275`:

```python
# Before compute_race — load crew for challenger + opponent
challenger_build_id, challenger_crew = await _load_assigned_crew_for_user(
    session, challenger_build["user_id"]
)
challenger_build["crew"] = challenger_crew
challenger_build["_active_build_id"] = challenger_build_id

opp_build_id, opp_crew = await _load_assigned_crew_for_user(
    session, opp_build["user_id"]
)
opp_build["crew"] = opp_crew
opp_build["_active_build_id"] = opp_build_id

race_result = compute_race([challenger_build, opp_build])
```

Do the same at race.py:739 for each item in `all_builds`.

- [ ] **Step 3: After `compute_race`, award XP to crew**

Add a helper near the other helpers:

```python
from engine.crew_xp import award_xp


async def _award_xp_to_crew(
    session: AsyncSession,
    builds_with_crew: list[dict[str, Any]],
    race_result: "RaceResult",
) -> dict[str, list[tuple[CrewMember, int]]]:
    """For each placement, award XP to that user's crew. Return a map user_id → list of (member, new_level)
    for crew that leveled up (for embed footer)."""
    level_ups: dict[str, list[tuple[CrewMember, int]]] = {}
    pos_by_user = {p.user_id: p.position for p in race_result.placements}
    for build in builds_with_crew:
        user_id = build["user_id"]
        crew = build.get("crew") or []
        position = pos_by_user.get(user_id)
        if position is None:
            continue
        xp_gain = 20 + (10 if position == 1 else 0)
        for member in crew:
            leveled = award_xp(member, xp_gain)
            if leveled:
                level_ups.setdefault(user_id, []).append((member, member.level))
    await session.flush()
    return level_ups
```

At each call site after `compute_race(...)`, invoke `_award_xp_to_crew` and include a footer in the result embed:

```python
level_ups = await _award_xp_to_crew(session, [challenger_build, opp_build], race_result)

# ... later when building the response embed ...
for user_id, bumps in level_ups.items():
    lines = [f"⭐ {m.first_name} \"{m.callsign}\" {m.last_name} reached Level {lvl}."
             for m, lvl in bumps]
    embed.add_field(
        name="Crew Level-Ups",
        value="\n".join(lines),
        inline=False,
    )
```

- [ ] **Step 4: Write / run a smoke test**

A full integration scenario lives in Task 15 (`test_crew_flow.py`). For now, verify the module still imports cleanly:

Run: `pytest tests/test_race_engine.py -v`
Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/race.py
git commit -m "feat(phase1): race cog loads crew and awards post-race XP"
```

---

## Task 10: Extract reveal entry protocol into `bot/reveal.py`

**Files:**
- Create: `bot/reveal.py`
- Modify: `bot/cogs/cards.py`
- Test: `tests/test_pack_reveal_view.py`

- [ ] **Step 1: Add a failing test for the crew reveal path**

Append to `tests/test_pack_reveal_view.py`:

```python
class TestCrewRevealEntry:
    def test_crew_reveal_builds_embed(self):
        from bot.reveal import CrewRevealEntry

        entry = CrewRevealEntry(
            name='Jax "Blackjack" Krell',
            rarity="rare",
            archetype="pilot",
            level=1,
            primary_stat="handling",
            secondary_stat="stability",
        )
        fields = entry.build_embed_fields()
        flat = " ".join(f"{n}: {v}" for n, v, _ in fields)
        assert "pilot" in flat.lower()
        assert "handling" in flat.lower()
        assert "stability" in flat.lower()


class TestPackRevealViewWithCrew:
    def test_single_crew_reveal(self):
        from bot.reveal import CrewRevealEntry
        from bot.cogs.cards import _PackRevealView

        entry = CrewRevealEntry(
            name='Mira "Sixgun" Voss',
            rarity="epic",
            archetype="engineer",
            level=1,
            primary_stat="power",
            secondary_stat="acceleration",
        )
        view = _PackRevealView(
            entries=[entry],
            display_name="Dossier",
            owner_id=42,
        )
        embed = view.build_embed()
        assert "Mira" in embed.description or "Mira" in " ".join(
            f.value for f in embed.fields
        )
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_pack_reveal_view.py -v -k Crew`
Expected: `ImportError` on `bot.reveal`.

- [ ] **Step 3: Create `bot/reveal.py`**

```python
"""Shared reveal-entry protocol used by pack + dossier reveal views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class RevealEntry(Protocol):
    name: str
    rarity: str

    def build_embed_fields(self) -> list[tuple[str, str, bool]]:
        """Return a list of (field_name, field_value, inline) tuples for embed."""
        ...


@dataclass
class PartRevealEntry:
    """Adapter wrapping (Card, UserCard) for the reveal view."""
    name: str
    rarity: str
    slot: str
    serial_number: int
    print_max: int | None
    primary_stats: dict[str, float] = field(default_factory=dict)
    secondary_stats: dict[str, float] = field(default_factory=dict)

    def build_embed_fields(self) -> list[tuple[str, str, bool]]:
        fields: list[tuple[str, str, bool]] = []
        fields.append(("Slot", self.slot, True))
        fields.append(("Rarity", self.rarity, True))
        serial = f"#{self.serial_number}"
        if self.print_max:
            serial += f" / {self.print_max}"
        fields.append(("Serial", serial, True))
        if self.primary_stats:
            lines = [f"**{k}**: {v}" for k, v in self.primary_stats.items()]
            fields.append(("Stats", "\n".join(lines), False))
        return fields


@dataclass
class CrewRevealEntry:
    """Adapter wrapping a CrewMember for the reveal view."""
    name: str
    rarity: str
    archetype: str
    level: int
    primary_stat: str
    secondary_stat: str

    def build_embed_fields(self) -> list[tuple[str, str, bool]]:
        return [
            ("Archetype", self.archetype.title(), True),
            ("Rarity", self.rarity.title(), True),
            ("Level", str(self.level), True),
            (
                "Boosts",
                f"**Primary:** {self.primary_stat}\n**Secondary:** {self.secondary_stat}",
                False,
            ),
        ]
```

- [ ] **Step 4: Refactor `_PackRevealView` in `bot/cogs/cards.py` to accept `list[RevealEntry]`**

Locate `_PackRevealView` in `bot/cogs/cards.py`. Change its constructor signature to accept `entries: list[RevealEntry]` instead of `minted: list[tuple[Card, UserCard]]`. Build the embed fields via `entry.build_embed_fields()` instead of directly pulling from card/user_card objects.

At the call site (inside `/pack`), adapt the existing tuples to `PartRevealEntry` objects before passing:

```python
from bot.reveal import PartRevealEntry

entries = [
    PartRevealEntry(
        name=card.name,
        rarity=card.rarity.value,
        slot=card.slot.value,
        serial_number=uc.serial_number,
        print_max=card.print_max,
        primary_stats=card.stats.get("primary", {}),
        secondary_stats=card.stats.get("secondary", {}),
    )
    for card, uc in minted
]
view = _PackRevealView(entries=entries, display_name=display_name, owner_id=interaction.user.id)
```

Preserve any paging behavior (left/right arrows) by keying on `len(entries)` just like the old `len(minted)`.

- [ ] **Step 5: Run existing pack reveal tests + new crew tests**

Run: `pytest tests/test_pack_reveal_view.py -v`
Expected: All PASS (existing pack tests adapted via adapter, new crew tests green).

If the old tests break because they pass `minted=[...]` directly, update those tests to construct `PartRevealEntry` objects.

- [ ] **Step 6: Commit**

```bash
git add bot/reveal.py bot/cogs/cards.py tests/test_pack_reveal_view.py
git commit -m "refactor(phase1): extract RevealEntry protocol; add CrewRevealEntry"
```

---

## Task 11: `HiringCog` scaffold + register in `bot/main.py`

**Files:**
- Create: `bot/cogs/hiring.py`
- Modify: `bot/main.py`

- [ ] **Step 1: Write scaffold test**

Create `tests/test_hiring_cog.py`:

```python
"""Smoke test: HiringCog loads and registers its commands."""

from __future__ import annotations

import pytest


def test_hiring_cog_imports():
    from bot.cogs import hiring  # noqa: F401
    assert hasattr(hiring, "HiringCog")


def test_hiring_cog_registers_commands():
    from discord.ext import commands
    from bot.cogs.hiring import HiringCog

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)
    command_names = {c.name for c in cog.walk_app_commands()}
    assert {"dossier", "hire", "crew", "assign", "unassign"} <= command_names
```

- [ ] **Step 2: Create cog scaffold**

Create `bot/cogs/hiring.py`:

```python
"""Hiring cog — /dossier, /hire, /crew, /assign, /unassign."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config.logging import get_logger
from config.tracing import traced_command

log = get_logger(__name__)


class HiringCog(commands.Cog):
    """Crew recruitment, listing, and assignment."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="dossier", description="Buy a dossier and recruit a crew member.")
    @traced_command
    async def dossier(self, interaction: discord.Interaction, tier: str) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="hire", description="Claim today's free crew lead.")
    @traced_command
    async def hire(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="crew", description="View your crew roster.")
    @traced_command
    async def crew(
        self, interaction: discord.Interaction, filter: str | None = None
    ) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="assign", description="Assign a crew member to your active build.")
    @traced_command
    async def assign(self, interaction: discord.Interaction, crew: str) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="unassign", description="Remove a crew member from your build.")
    @traced_command
    async def unassign(self, interaction: discord.Interaction, crew: str) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HiringCog(bot))
```

- [ ] **Step 3: Register cog in `bot/main.py`**

Find the existing cog loader block (search for `load_extension` or `add_cog`). Add:

```python
await bot.load_extension("bot.cogs.hiring")
```

- [ ] **Step 4: Run scaffold tests**

Run: `pytest tests/test_hiring_cog.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/hiring.py bot/main.py tests/test_hiring_cog.py
git commit -m "feat(phase1): HiringCog scaffold with command skeletons"
```

---

## Task 12: Implement `/dossier` command

**Files:**
- Modify: `bot/cogs/hiring.py`
- Modify: `api/metrics.py`
- Test: add to `tests/test_hiring_cog.py`

- [ ] **Step 1: Add new metrics to `api/metrics.py`**

Append:

```python
# ---------------------------------------------------------------------------
# Crew metrics
# ---------------------------------------------------------------------------

crew_recruited = Counter(
    "dare2drive_crew_recruited_total",
    "Total number of crew recruited.",
    ["source", "archetype", "rarity"],  # source: dossier | daily_lead
)

dossier_purchased = Counter(
    "dare2drive_dossier_purchased_total",
    "Total number of dossiers purchased.",
    ["tier"],
)

crew_assignment = Counter(
    "dare2drive_crew_assignment_total",
    "Crew assignment actions.",
    ["action"],  # assign | unassign | auto_unassign
)

crew_level_up = Counter(
    "dare2drive_crew_level_up_total",
    "Crew level-up events.",
    ["archetype", "from_level", "to_level"],
)

crew_boost_apply = Counter(
    "dare2drive_crew_boost_apply_total",
    "Crew boost applications during stat resolution.",
    ["archetype", "rarity"],
)
```

- [ ] **Step 2: Write failing test for `/dossier`**

Append to `tests/test_hiring_cog.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

from db.models import CrewMember, HullClass, User


@pytest_asyncio.fixture
async def hiring_user(db_session):
    u = User(
        discord_id="555555555",
        username="hiringtest",
        hull_class=HullClass.SKIRMISHER,
        currency=3000,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_dossier_command_deducts_creds_and_creates_crew(hiring_user, db_session):
    from bot.cogs.hiring import HiringCog
    from discord.ext import commands

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)

    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(hiring_user.discord_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # Patch async_session to yield our test session
    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        # Patch system gate to allow the call
        with patch("bot.cogs.hiring.get_active_system", new=AsyncMock(return_value=MagicMock())):
            await cog.dossier.callback(cog, interaction, tier="dossier")

    await db_session.refresh(hiring_user)
    assert hiring_user.currency == 2500  # 3000 - 500

    from sqlalchemy import select
    res = await db_session.execute(
        select(CrewMember).where(CrewMember.user_id == hiring_user.discord_id)
    )
    members = list(res.scalars().all())
    assert len(members) == 1
```

- [ ] **Step 3: Run and confirm fail**

Run: `pytest tests/test_hiring_cog.py::test_dossier_command_deducts_creds_and_creates_crew -v`
Expected: FAIL — scaffold returns "Not implemented yet".

- [ ] **Step 4: Implement `/dossier`**

Replace the placeholder `dossier` method in `bot/cogs/hiring.py`:

```python
from api.metrics import crew_recruited, currency_spent, dossier_purchased
from bot.reveal import CrewRevealEntry
from bot.system_gating import get_active_system, system_required_message
from config.metrics import trace_exemplar
from db.models import User
from db.session import async_session
from engine.crew_recruit import InsufficientCreditsError, recruit_crew_from_dossier

_DOSSIER_TIERS = ("recruit_lead", "dossier", "elite_dossier")


@app_commands.command(name="dossier", description="Buy a dossier and recruit a crew member.")
@app_commands.describe(tier="Which dossier tier to purchase")
@app_commands.choices(
    tier=[
        app_commands.Choice(name="Recruit Lead (150 Creds)", value="recruit_lead"),
        app_commands.Choice(name="Dossier (500 Creds)", value="dossier"),
        app_commands.Choice(name="Elite Dossier (1500 Creds)", value="elite_dossier"),
    ]
)
@traced_command
async def dossier(self, interaction: discord.Interaction, tier: str) -> None:
    if tier not in _DOSSIER_TIERS:
        await interaction.response.send_message("Invalid tier.", ephemeral=True)
        return

    async with async_session() as session:
        system = await get_active_system(interaction, session)
        if system is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return

        user = await session.get(User, str(interaction.user.id))
        if not user:
            await interaction.response.send_message("Use `/start` first!", ephemeral=True)
            return

        try:
            member = await recruit_crew_from_dossier(session, user, tier)
        except InsufficientCreditsError:
            await interaction.response.send_message(
                "Not enough Creds for this dossier.", ephemeral=True
            )
            return

        # Load archetype mapping for display
        from engine.stat_resolver import _get_archetype_mapping
        mapping = _get_archetype_mapping()[member.archetype.value]

        await session.commit()

    dossier_purchased.labels(tier=tier).inc(exemplar=trace_exemplar())
    crew_recruited.labels(
        source="dossier",
        archetype=member.archetype.value,
        rarity=member.rarity.value,
    ).inc(exemplar=trace_exemplar())
    currency_spent.labels(reason=f"dossier_{tier}").inc(
        {"recruit_lead": 150, "dossier": 500, "elite_dossier": 1500}[tier],
        exemplar=trace_exemplar(),
    )

    entry = CrewRevealEntry(
        name=f'{member.first_name} "{member.callsign}" {member.last_name}',
        rarity=member.rarity.value,
        archetype=member.archetype.value,
        level=member.level,
        primary_stat=mapping["primary"].replace("effective_", "").replace("_", " "),
        secondary_stat=mapping["secondary"].replace("effective_", "").replace("_", " "),
    )

    from bot.cogs.cards import _PackRevealView

    display_name = {
        "recruit_lead": "Recruit Lead",
        "dossier": "Dossier",
        "elite_dossier": "Elite Dossier",
    }[tier]
    view = _PackRevealView(
        entries=[entry], display_name=display_name, owner_id=interaction.user.id
    )
    await interaction.response.send_message(embed=view.build_embed(), view=view)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_hiring_cog.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/hiring.py api/metrics.py tests/test_hiring_cog.py
git commit -m "feat(phase1): /dossier command recruits crew via dossier purchase"
```

---

## Task 13: Implement `/crew` list + autocomplete

**Files:**
- Modify: `bot/cogs/hiring.py`
- Test: `tests/test_hiring_cog.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_hiring_cog.py`:

```python
@pytest.mark.asyncio
async def test_crew_command_lists_user_crew(hiring_user, db_session):
    from bot.cogs.hiring import HiringCog
    from db.models import CrewArchetype, CrewMember, Rarity
    from discord.ext import commands

    # Pre-seed two crew
    c1 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Jax", last_name="Krell", callsign="Blackjack",
        archetype=CrewArchetype.PILOT, rarity=Rarity.RARE,
    )
    c2 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Mira", last_name="Voss", callsign="Sixgun",
        archetype=CrewArchetype.ENGINEER, rarity=Rarity.EPIC,
    )
    db_session.add_all([c1, c2])
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)

    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(hiring_user.discord_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        await cog.crew.callback(cog, interaction, filter=None)

    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    embed = kwargs.get("embed")
    assert embed is not None
    flat = embed.description + " ".join(f.value for f in embed.fields)
    assert "Jax" in flat
    assert "Mira" in flat
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_hiring_cog.py::test_crew_command_lists_user_crew -v`
Expected: FAIL — scaffold returns "Not implemented yet".

- [ ] **Step 3: Implement `/crew` + autocomplete**

Add to `bot/cogs/hiring.py` at module scope:

```python
from typing import Any

from db.models import CrewArchetype, CrewAssignment, CrewMember

_ARCHETYPE_EMOJI = {
    "pilot": "🧑‍✈️",
    "engineer": "🔧",
    "gunner": "🔫",
    "navigator": "🧭",
    "medic": "🩹",
}
_RARITY_EMOJI = {
    "common": "⬜", "uncommon": "🟩", "rare": "🟦",
    "epic": "🟪", "legendary": "🟨", "ghost": "👻",
}


def _format_crew_line(member: CrewMember, assigned: bool) -> str:
    emoji = _ARCHETYPE_EMOJI[member.archetype.value]
    rarity_emoji = _RARITY_EMOJI[member.rarity.value]
    name = f'{member.first_name} "{member.callsign}" {member.last_name}'
    tag = " *(assigned)*" if assigned else ""
    return f"{emoji} {rarity_emoji} **{name}** — {member.archetype.value.title()} L{member.level}{tag}"


async def _crew_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /crew inspect, /assign, /unassign."""
    async with async_session() as session:
        result = await session.execute(
            select(CrewMember).where(CrewMember.user_id == str(interaction.user.id))
        )
        members = list(result.scalars().all())
    q = current.lower()
    out: list[app_commands.Choice[str]] = []
    for m in members:
        name = f'{m.first_name} "{m.callsign}" {m.last_name}'
        if q in name.lower():
            out.append(app_commands.Choice(name=name[:100], value=name[:100]))
        if len(out) >= 25:
            break
    return out
```

Replace the `crew` method:

```python
@app_commands.command(name="crew", description="View your crew roster.")
@app_commands.describe(filter="Optional filter: all, unassigned, assigned, or an archetype name.")
@app_commands.choices(
    filter=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Unassigned", value="unassigned"),
        app_commands.Choice(name="Assigned", value="assigned"),
        app_commands.Choice(name="Pilot", value="pilot"),
        app_commands.Choice(name="Engineer", value="engineer"),
        app_commands.Choice(name="Gunner", value="gunner"),
        app_commands.Choice(name="Navigator", value="navigator"),
        app_commands.Choice(name="Medic", value="medic"),
    ]
)
@traced_command
async def crew(
    self, interaction: discord.Interaction, filter: str | None = None
) -> None:
    """Universe-wide roster — no system gating."""
    user_id = str(interaction.user.id)
    async with async_session() as session:
        members_q = await session.execute(
            select(CrewMember).where(CrewMember.user_id == user_id)
        )
        members = list(members_q.scalars().all())
        if not members:
            await interaction.response.send_message(
                "No crew yet — try `/dossier` or `/hire`.", ephemeral=True
            )
            return

        assigned_q = await session.execute(
            select(CrewAssignment.crew_id).where(
                CrewAssignment.crew_id.in_([m.id for m in members])
            )
        )
        assigned_ids = {row[0] for row in assigned_q.all()}

    f = (filter or "all").lower()
    if f == "unassigned":
        members = [m for m in members if m.id not in assigned_ids]
    elif f == "assigned":
        members = [m for m in members if m.id in assigned_ids]
    elif f in {"pilot", "engineer", "gunner", "navigator", "medic"}:
        members = [m for m in members if m.archetype.value == f]
    # else: all — no filter

    if not members:
        await interaction.response.send_message(
            f"No crew match filter `{f}`.", ephemeral=True
        )
        return

    # Sort: rarity desc, level desc, name
    rarity_order = {"ghost": 0, "legendary": 1, "epic": 2, "rare": 3, "uncommon": 4, "common": 5}
    members.sort(
        key=lambda m: (
            rarity_order.get(m.rarity.value, 99),
            -m.level,
            m.first_name,
        )
    )

    lines = [_format_crew_line(m, m.id in assigned_ids) for m in members[:25]]

    embed = discord.Embed(
        title=f"🛰️ Crew Roster — {len(members)} total",
        description="\n".join(lines),
        color=0x3B82F6,
    )
    if len(members) > 25:
        embed.set_footer(text=f"Showing 25 of {len(members)}. Use filters to narrow.")
    await interaction.response.send_message(embed=embed)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_hiring_cog.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/hiring.py tests/test_hiring_cog.py
git commit -m "feat(phase1): /crew list command + autocomplete helper"
```

---

## Task 14: Implement `/crew inspect`

**Files:**
- Modify: `bot/cogs/hiring.py`
- Test: `tests/test_hiring_cog.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_hiring_cog.py`:

```python
@pytest.mark.asyncio
async def test_crew_inspect_command_shows_detail(hiring_user, db_session):
    from bot.cogs.hiring import HiringCog
    from db.models import CrewArchetype, CrewMember, Rarity
    from discord.ext import commands

    c = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Cas", last_name="Harrow", callsign="Crow",
        archetype=CrewArchetype.NAVIGATOR, rarity=Rarity.EPIC, level=3, xp=120,
    )
    db_session.add(c)
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(hiring_user.discord_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        await cog.crew_inspect.callback(cog, interaction, name='Cas "Crow" Harrow')

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.call_args.kwargs["embed"]
    flat = embed.description + " ".join(f.value for f in embed.fields)
    assert "Navigator" in flat
    assert "Epic" in flat
    assert "L3" in flat or "Level 3" in flat
    assert "120" in flat  # xp
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_hiring_cog.py::test_crew_inspect_command_shows_detail -v`
Expected: FAIL — `crew_inspect` does not exist.

- [ ] **Step 3: Implement `/crew inspect`**

Add to `HiringCog` in `bot/cogs/hiring.py`:

```python
@app_commands.command(name="crew_inspect", description="Inspect a crew member.")
@app_commands.describe(name="Crew member name")
@app_commands.autocomplete(name=_crew_name_autocomplete)
@traced_command
async def crew_inspect(self, interaction: discord.Interaction, name: str) -> None:
    from engine.crew_xp import xp_for_next
    from engine.stat_resolver import _get_archetype_mapping

    user_id = str(interaction.user.id)
    async with async_session() as session:
        # name format: First "Callsign" Last
        member = await _lookup_crew_by_display(session, user_id, name)
        if member is None:
            await interaction.response.send_message(
                f"No crew named `{name}`.", ephemeral=True
            )
            return

        assigned_q = await session.execute(
            select(CrewAssignment).where(CrewAssignment.crew_id == member.id)
        )
        assignment = assigned_q.scalar_one_or_none()

    mapping = _get_archetype_mapping()[member.archetype.value]
    display = f'{member.first_name} "{member.callsign}" {member.last_name}'
    arch_emoji = _ARCHETYPE_EMOJI[member.archetype.value]
    rarity_emoji = _RARITY_EMOJI[member.rarity.value]

    embed = discord.Embed(
        title=f"{arch_emoji} {display}",
        description=f"{rarity_emoji} **{member.rarity.value.title()}** {member.archetype.value.title()}",
        color=0x3B82F6,
    )
    embed.add_field(name="Level", value=f"L{member.level}", inline=True)
    if member.level >= 10:
        embed.add_field(name="XP", value="MAX", inline=True)
    else:
        embed.add_field(
            name="XP",
            value=f"{member.xp} / {xp_for_next(member.level)}",
            inline=True,
        )
    embed.add_field(
        name="Boosts",
        value=(
            f"**Primary:** {mapping['primary'].replace('effective_', '').replace('_', ' ')}\n"
            f"**Secondary:** {mapping['secondary'].replace('effective_', '').replace('_', ' ')}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Assigned",
        value=("Yes" if assignment is not None else "In quarters"),
        inline=True,
    )
    embed.set_footer(
        text=f"Acquired {member.acquired_at.strftime('%Y-%m-%d')}"
    )

    await interaction.response.send_message(embed=embed)


async def _lookup_crew_by_display(
    session: AsyncSession, user_id: str, display_name: str
) -> CrewMember | None:
    """Parse 'First "Callsign" Last' and look up the crew member."""
    import re

    m = re.match(r'^(.+?)\s+"(.+?)"\s+(.+)$', display_name.strip())
    if not m:
        return None
    first, callsign, last = m.group(1), m.group(2), m.group(3)
    result = await session.execute(
        select(CrewMember).where(
            CrewMember.user_id == user_id,
            CrewMember.first_name == first,
            CrewMember.last_name == last,
            CrewMember.callsign == callsign,
        )
    )
    return result.scalar_one_or_none()
```

Note: The command is named `crew_inspect` in Discord (underscore) since Discord app commands cannot have spaces. Presentation-wise this will surface as `/crew_inspect`. If the user prefers grouped `/crew inspect` syntax, that is a `Group` refactor — note for later and keep the simple flat command for Phase 1.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_hiring_cog.py::test_crew_inspect_command_shows_detail -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/hiring.py tests/test_hiring_cog.py
git commit -m "feat(phase1): /crew_inspect command"
```

---

## Task 15: Implement `/assign` and `/unassign`

**Files:**
- Modify: `bot/cogs/hiring.py`
- Test: `tests/test_hiring_cog.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_hiring_cog.py`:

```python
@pytest.mark.asyncio
async def test_assign_auto_unassigns_prior_same_archetype(hiring_user, db_session):
    """Assigning a new pilot auto-replaces the old one."""
    from bot.cogs.hiring import HiringCog
    from db.models import Build, CrewArchetype, CrewAssignment, CrewMember, Rarity
    from discord.ext import commands

    build = Build(user_id=hiring_user.discord_id, name="Flagship", hull_class=HullClass.SKIRMISHER)
    db_session.add(build)
    await db_session.flush()

    pilot1 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Jax", last_name="Krell", callsign="Blackjack",
        archetype=CrewArchetype.PILOT, rarity=Rarity.COMMON,
    )
    pilot2 = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Mira", last_name="Voss", callsign="Sixgun",
        archetype=CrewArchetype.PILOT, rarity=Rarity.RARE,
    )
    db_session.add_all([pilot1, pilot2])
    await db_session.flush()

    db_session.add(
        CrewAssignment(crew_id=pilot1.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(hiring_user.discord_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        with patch("bot.cogs.hiring.get_active_system", new=AsyncMock(return_value=MagicMock())):
            await cog.assign.callback(cog, interaction, crew='Mira "Sixgun" Voss')

    # Only pilot2 should be assigned now
    from sqlalchemy import select
    res = await db_session.execute(select(CrewAssignment))
    rows = list(res.scalars().all())
    assert len(rows) == 1
    assert rows[0].crew_id == pilot2.id


@pytest.mark.asyncio
async def test_unassign_removes_crew_from_build(hiring_user, db_session):
    from bot.cogs.hiring import HiringCog
    from db.models import Build, CrewArchetype, CrewAssignment, CrewMember, Rarity
    from discord.ext import commands

    build = Build(user_id=hiring_user.discord_id, name="Flagship", hull_class=HullClass.SKIRMISHER)
    db_session.add(build)
    await db_session.flush()

    pilot = CrewMember(
        user_id=hiring_user.discord_id,
        first_name="Jax", last_name="Krell", callsign="Blackjack",
        archetype=CrewArchetype.PILOT, rarity=Rarity.COMMON,
    )
    db_session.add(pilot)
    await db_session.flush()

    db_session.add(
        CrewAssignment(crew_id=pilot.id, build_id=build.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(hiring_user.discord_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        with patch("bot.cogs.hiring.get_active_system", new=AsyncMock(return_value=MagicMock())):
            await cog.unassign.callback(cog, interaction, crew='Jax "Blackjack" Krell')

    from sqlalchemy import select
    res = await db_session.execute(select(CrewAssignment))
    rows = list(res.scalars().all())
    assert len(rows) == 0
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_hiring_cog.py -v -k assign`
Expected: Two FAILs.

- [ ] **Step 3: Implement `/assign` and `/unassign`**

Replace the `assign` and `unassign` methods in `HiringCog`:

```python
from db.models import Build
from api.metrics import crew_assignment


@app_commands.command(name="assign", description="Assign a crew member to your active build.")
@app_commands.describe(crew="Crew member name")
@app_commands.autocomplete(crew=_crew_name_autocomplete)
@traced_command
async def assign(self, interaction: discord.Interaction, crew: str) -> None:
    user_id = str(interaction.user.id)
    async with async_session() as session:
        system = await get_active_system(interaction, session)
        if system is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return

        member = await _lookup_crew_by_display(session, user_id, crew)
        if member is None:
            await interaction.response.send_message(
                f"No crew named `{crew}`.", ephemeral=True
            )
            return

        build_q = await session.execute(
            select(Build).where(Build.user_id == user_id, Build.is_active.is_(True)).limit(1)
        )
        build = build_q.scalar_one_or_none()
        if build is None:
            await interaction.response.send_message(
                "You don't have an active build. Use `/hangar` to create one.",
                ephemeral=True,
            )
            return

        # Remove any existing assignment of THIS crew
        existing_q = await session.execute(
            select(CrewAssignment).where(CrewAssignment.crew_id == member.id)
        )
        existing = existing_q.scalar_one_or_none()
        if existing is not None:
            await session.delete(existing)
            await session.flush()

        # Auto-unassign prior same-archetype crew on THIS build
        prior_q = await session.execute(
            select(CrewAssignment).where(
                CrewAssignment.build_id == build.id,
                CrewAssignment.archetype == member.archetype,
            )
        )
        prior = prior_q.scalar_one_or_none()
        prior_name: str | None = None
        if prior is not None and prior.crew_id != member.id:
            prior_member = await session.get(CrewMember, prior.crew_id)
            prior_name = (
                f'{prior_member.first_name} "{prior_member.callsign}" {prior_member.last_name}'
                if prior_member else None
            )
            await session.delete(prior)
            await session.flush()
            crew_assignment.labels(action="auto_unassign").inc()

        session.add(
            CrewAssignment(
                crew_id=member.id,
                build_id=build.id,
                archetype=member.archetype,
            )
        )
        await session.commit()

    crew_assignment.labels(action="assign").inc()
    display = f'{member.first_name} "{member.callsign}" {member.last_name}'
    msg = f"Assigned **{display}** as {member.archetype.value.title()}."
    if prior_name:
        msg += f" (Replaced {prior_name}.)"
    await interaction.response.send_message(msg)


@app_commands.command(name="unassign", description="Remove a crew member from your build.")
@app_commands.describe(crew="Crew member name")
@app_commands.autocomplete(crew=_crew_name_autocomplete)
@traced_command
async def unassign(self, interaction: discord.Interaction, crew: str) -> None:
    user_id = str(interaction.user.id)
    async with async_session() as session:
        system = await get_active_system(interaction, session)
        if system is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return

        member = await _lookup_crew_by_display(session, user_id, crew)
        if member is None:
            await interaction.response.send_message(
                f"No crew named `{crew}`.", ephemeral=True
            )
            return

        assignment_q = await session.execute(
            select(CrewAssignment).where(CrewAssignment.crew_id == member.id)
        )
        assignment = assignment_q.scalar_one_or_none()
        if assignment is None:
            await interaction.response.send_message(
                f"`{crew}` isn't assigned.", ephemeral=True
            )
            return

        await session.delete(assignment)
        await session.commit()

    crew_assignment.labels(action="unassign").inc()
    display = f'{member.first_name} "{member.callsign}" {member.last_name}'
    await interaction.response.send_message(f"Unassigned **{display}** back to quarters.")
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_hiring_cog.py -v -k assign`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/hiring.py tests/test_hiring_cog.py
git commit -m "feat(phase1): /assign and /unassign with auto-swap"
```

---

## Task 16: Implement `/hire` + extend `/daily` with today's lead

**Files:**
- Modify: `bot/cogs/hiring.py` (`/hire`)
- Modify: `bot/cogs/cards.py` (`/daily` extension)
- Test: `tests/test_hiring_cog.py`, `tests/test_scenarios/test_daily_lead_flow.py`

- [ ] **Step 1: Write failing test for `/hire`**

Append to `tests/test_hiring_cog.py`:

```python
@pytest.mark.asyncio
async def test_hire_claims_todays_lead(hiring_user, db_session):
    from bot.cogs.hiring import HiringCog
    from db.models import CrewMember
    from discord.ext import commands
    from engine.crew_recruit import get_or_roll_today_lead

    lead = await get_or_roll_today_lead(db_session, hiring_user)
    await db_session.flush()

    bot = commands.Bot(command_prefix="!", intents=None)
    cog = HiringCog(bot)
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(hiring_user.discord_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("bot.cogs.hiring.async_session") as sess_ctx:
        sess_ctx.return_value.__aenter__.return_value = db_session
        with patch("bot.cogs.hiring.get_active_system", new=AsyncMock(return_value=MagicMock())):
            await cog.hire.callback(cog, interaction)

    from sqlalchemy import select
    res = await db_session.execute(
        select(CrewMember).where(CrewMember.user_id == hiring_user.discord_id)
    )
    members = list(res.scalars().all())
    assert len(members) == 1
    assert members[0].first_name == lead.first_name
    assert lead.claimed_at is not None
```

- [ ] **Step 2: Run and confirm fail**

Run: `pytest tests/test_hiring_cog.py::test_hire_claims_todays_lead -v`
Expected: FAIL.

- [ ] **Step 3: Implement `/hire`**

Replace the `hire` method in `HiringCog`:

```python
from datetime import datetime, timezone

from engine.crew_recruit import (
    LeadAlreadyClaimedError,
    get_or_roll_today_lead,
    recruit_crew_from_daily_lead,
)


@app_commands.command(name="hire", description="Claim today's free crew lead.")
@traced_command
async def hire(self, interaction: discord.Interaction) -> None:
    user_id = str(interaction.user.id)
    async with async_session() as session:
        system = await get_active_system(interaction, session)
        if system is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return

        user = await session.get(User, user_id)
        if not user:
            await interaction.response.send_message("Use `/start` first!", ephemeral=True)
            return

        today = datetime.now(timezone.utc).date()
        from db.models import CrewDailyLead
        lead = await session.get(CrewDailyLead, (user_id, today))
        if lead is None:
            await interaction.response.send_message(
                "No lead today — run `/daily` first to see today's candidate.",
                ephemeral=True,
            )
            return
        if lead.claimed_at is not None:
            await interaction.response.send_message(
                "You've already hired today's lead.", ephemeral=True
            )
            return

        try:
            member = await recruit_crew_from_daily_lead(session, user, lead)
        except LeadAlreadyClaimedError:
            await interaction.response.send_message(
                "Lead already claimed.", ephemeral=True
            )
            return

        from engine.stat_resolver import _get_archetype_mapping
        mapping = _get_archetype_mapping()[member.archetype.value]
        await session.commit()

    crew_recruited.labels(
        source="daily_lead",
        archetype=member.archetype.value,
        rarity=member.rarity.value,
    ).inc(exemplar=trace_exemplar())

    entry = CrewRevealEntry(
        name=f'{member.first_name} "{member.callsign}" {member.last_name}',
        rarity=member.rarity.value,
        archetype=member.archetype.value,
        level=member.level,
        primary_stat=mapping["primary"].replace("effective_", "").replace("_", " "),
        secondary_stat=mapping["secondary"].replace("effective_", "").replace("_", " "),
    )
    from bot.cogs.cards import _PackRevealView
    view = _PackRevealView(
        entries=[entry], display_name="Today's Lead", owner_id=interaction.user.id
    )
    await interaction.response.send_message(embed=view.build_embed(), view=view)
```

- [ ] **Step 4: Run `/hire` test**

Run: `pytest tests/test_hiring_cog.py::test_hire_claims_todays_lead -v`
Expected: PASS.

- [ ] **Step 5: Extend `/daily` in `bot/cogs/cards.py` to preview today's lead**

Find the `daily` method in `bot/cogs/cards.py`. After the existing parts grant and *before* the final `send_message`, add:

```python
from engine.crew_recruit import get_or_roll_today_lead

# -- Phase 1: daily crew lead --
async with async_session() as session2:
    # Re-open session to persist the lead alongside /daily parts
    db_user = await session2.get(User, str(interaction.user.id))
    if db_user is not None:
        lead = await get_or_roll_today_lead(session2, db_user)
        await session2.commit()

if lead is not None:
    claimed_note = " *(already claimed)*" if lead.claimed_at else ""
    embed.add_field(
        name="👤 Today's Lead",
        value=(
            f'{_ARCHETYPE_EMOJI_FROM_HIRING.get(lead.archetype.value, "")} '
            f'**{lead.first_name} "{lead.callsign}" {lead.last_name}** — '
            f'{lead.archetype.value.title()} [{lead.rarity.value.title()}]{claimed_note}\n'
            f'Run `/hire` to recruit them.'
        ),
        inline=False,
    )
```

Add at the top of `bot/cogs/cards.py`:

```python
# Emoji mapping shared with hiring cog (single source of truth would be nice;
# for Phase 1 we duplicate to avoid a circular import).
_ARCHETYPE_EMOJI_FROM_HIRING = {
    "pilot": "🧑‍✈️",
    "engineer": "🔧",
    "gunner": "🔫",
    "navigator": "🧭",
    "medic": "🩹",
}
```

- [ ] **Step 6: Write integration test for daily + hire flow**

Create `tests/test_scenarios/test_daily_lead_flow.py`:

```python
"""Integration: /daily creates lead → /hire claims → idempotence."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.models import CrewDailyLead, CrewMember, HullClass, User


@pytest_asyncio.fixture
async def lead_user(db_session):
    u = User(
        discord_id="222111111",
        username="dailytest",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_get_or_roll_is_idempotent_then_hire_succeeds(lead_user, db_session):
    from engine.crew_recruit import (
        get_or_roll_today_lead,
        recruit_crew_from_daily_lead,
    )

    lead1 = await get_or_roll_today_lead(db_session, lead_user)
    lead2 = await get_or_roll_today_lead(db_session, lead_user)
    assert lead1.first_name == lead2.first_name

    member = await recruit_crew_from_daily_lead(db_session, lead_user, lead1)
    assert member.first_name == lead1.first_name

    res = await db_session.execute(
        select(CrewMember).where(CrewMember.user_id == lead_user.discord_id)
    )
    assert len(list(res.scalars().all())) == 1


@pytest.mark.asyncio
async def test_next_day_rolls_fresh_lead(lead_user, db_session):
    from engine.crew_recruit import get_or_roll_today_lead

    today = date(2026, 4, 24)
    tomorrow = today + timedelta(days=1)

    lead_today = await get_or_roll_today_lead(db_session, lead_user, today=today)
    lead_tomorrow = await get_or_roll_today_lead(db_session, lead_user, today=tomorrow)

    assert lead_today.rolled_for_date != lead_tomorrow.rolled_for_date
    # Same PK can coexist because rolled_for_date differs
    res = await db_session.execute(
        select(CrewDailyLead).where(CrewDailyLead.user_id == lead_user.discord_id)
    )
    assert len(list(res.scalars().all())) == 2
```

Create `tests/test_scenarios/__init__.py` if not already present (it already exists per the file inventory).

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_scenarios/test_daily_lead_flow.py -v`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add bot/cogs/hiring.py bot/cogs/cards.py tests/test_hiring_cog.py tests/test_scenarios/test_daily_lead_flow.py
git commit -m "feat(phase1): /hire claims daily lead; /daily previews today's lead"
```

---

## Task 17: Wire crew metrics into `apply_crew_boosts` and `race_engine` level-ups

**Files:**
- Modify: `engine/stat_resolver.py`
- Modify: `bot/cogs/race.py`

- [ ] **Step 1: Bump `crew_boost_apply` counter in `apply_crew_boosts`**

In `engine/stat_resolver.py`, extend `apply_crew_boosts`:

```python
def apply_crew_boosts(bs: BuildStats, crew: list[Any]) -> BuildStats:
    from api.metrics import crew_boost_apply  # local import avoids cycles at test time

    mapping = _get_archetype_mapping()
    base_boosts = _get_rarity_boosts()
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
        crew_boost_apply.labels(archetype=arch, rarity=member.rarity.value).inc()
    return bs
```

- [ ] **Step 2: Bump `crew_level_up` counter in `bot/cogs/race.py`**

In the `_award_xp_to_crew` helper from Task 9, before the `leveled_up` check, record the pre-level:

```python
async def _award_xp_to_crew(
    session: AsyncSession,
    builds_with_crew: list[dict[str, Any]],
    race_result: "RaceResult",
) -> dict[str, list[tuple[CrewMember, int]]]:
    from api.metrics import crew_level_up

    level_ups: dict[str, list[tuple[CrewMember, int]]] = {}
    pos_by_user = {p.user_id: p.position for p in race_result.placements}
    for build in builds_with_crew:
        user_id = build["user_id"]
        crew = build.get("crew") or []
        position = pos_by_user.get(user_id)
        if position is None:
            continue
        xp_gain = 20 + (10 if position == 1 else 0)
        for member in crew:
            pre_level = member.level
            leveled = award_xp(member, xp_gain)
            if leveled:
                crew_level_up.labels(
                    archetype=member.archetype.value,
                    from_level=str(pre_level),
                    to_level=str(member.level),
                ).inc()
                level_ups.setdefault(user_id, []).append((member, member.level))
    await session.flush()
    return level_ups
```

- [ ] **Step 3: Run all tests to confirm nothing regressed**

Run: `pytest -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add engine/stat_resolver.py bot/cogs/race.py
git commit -m "feat(phase1): instrument crew boost + level-up with metrics"
```

---

## Task 18: End-to-end scenario `test_crew_flow.py`

**Files:**
- Create: `tests/test_scenarios/test_crew_flow.py`

- [ ] **Step 1: Write the scenario**

```python
"""End-to-end: recruit → assign → race → XP gained → level-up triggers higher boost."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.models import (
    Build,
    CrewArchetype,
    CrewAssignment,
    CrewMember,
    HullClass,
    Rarity,
    User,
)


@pytest_asyncio.fixture
async def full_player(db_session):
    u = User(
        discord_id="444111111",
        username="fullpath",
        hull_class=HullClass.SKIRMISHER,
        currency=5000,
    )
    db_session.add(u)
    await db_session.flush()
    build = Build(user_id=u.discord_id, name="Flagship", hull_class=HullClass.SKIRMISHER)
    db_session.add(build)
    await db_session.flush()
    return u, build


@pytest.mark.asyncio
async def test_recruit_assign_race_xp_level_up(full_player, db_session, full_build):
    from engine.crew_recruit import recruit_crew_from_dossier
    from engine.crew_xp import award_xp, xp_for_next

    user, build = full_player

    member = await recruit_crew_from_dossier(db_session, user, "recruit_lead")
    await db_session.flush()

    # Assign
    db_session.add(
        CrewAssignment(
            crew_id=member.id,
            build_id=build.id,
            archetype=member.archetype,
        )
    )
    await db_session.flush()

    # Simulate a race that grants XP to hit L2
    threshold_xp = xp_for_next(1)
    leveled = award_xp(member, threshold_xp)
    assert leveled is True
    assert member.level == 2

    # Crew query by build_id returns the assigned member
    res = await db_session.execute(
        select(CrewMember)
        .join(CrewAssignment, CrewAssignment.crew_id == CrewMember.id)
        .where(CrewAssignment.build_id == build.id)
    )
    crew = list(res.scalars().all())
    assert len(crew) == 1
    assert crew[0].level == 2


@pytest.mark.asyncio
async def test_same_build_with_vs_without_crew_produces_different_stats(full_build):
    from unittest.mock import MagicMock

    from engine.environment import EnvironmentCondition
    from engine.race_engine import compute_race

    def _crew(arch, rarity, lvl=1):
        m = MagicMock()
        m.archetype = MagicMock(value=arch)
        m.rarity = MagicMock(value=rarity)
        m.level = lvl
        return m

    with_crew = {**full_build, "crew": [_crew("pilot", "legendary", 5)]}
    without_crew = {**full_build, "user_id": full_build["user_id"] + "x", "crew": []}

    env = EnvironmentCondition(
        name="clear", display_name="Clear",
        weights={k: 1.0 for k in [
            "power", "handling", "top_speed", "grip", "braking",
            "durability", "acceleration", "stability", "weather_performance",
        ]},
        variance_multiplier=0.0,
    )
    import random
    random.seed(7)
    r = compute_race([with_crew, without_crew], environment=env)
    scores = {p.user_id: p.score for p in r.placements}
    assert scores[with_crew["user_id"]] > scores[without_crew["user_id"]]
```

- [ ] **Step 2: Run the scenario**

Run: `pytest tests/test_scenarios/test_crew_flow.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scenarios/test_crew_flow.py
git commit -m "test(phase1): end-to-end crew flow scenario"
```

---

## Task 19: Load test — 100 crew/user, 10 concurrent races

**Files:**
- Create: `tests/test_crew_perf.py`

- [ ] **Step 1: Write the load test**

```python
"""Perf sanity: apply_crew_boosts at 100 crew/build stays fast."""

from __future__ import annotations

import time
from statistics import quantiles
from unittest.mock import MagicMock

import pytest

from engine.stat_resolver import BuildStats, apply_crew_boosts


def _crew(arch, rarity, lvl):
    m = MagicMock()
    m.archetype = MagicMock(value=arch)
    m.rarity = MagicMock(value=rarity)
    m.level = lvl
    return m


@pytest.mark.perf
def test_apply_crew_boosts_p99_under_50ms_with_100_crew():
    """Called 100 times (10 races × 10 participants) with 100 crew each."""
    archetypes = ["pilot", "engineer", "gunner", "navigator", "medic"]
    rarities = ["common", "uncommon", "rare", "epic", "legendary", "ghost"]

    # Build 100 crew members (crew per user — not a realistic assignment, but stresses the fn)
    crew_list = []
    for i in range(100):
        crew_list.append(_crew(archetypes[i % 5], rarities[i % 6], (i % 10) + 1))

    timings: list[float] = []
    for _ in range(100):
        bs = BuildStats(
            effective_power=200.0, effective_handling=200.0, effective_top_speed=200.0,
            effective_grip=100.0, effective_braking=100.0, effective_durability=100.0,
            effective_acceleration=200.0, effective_stability=100.0,
            effective_weather_performance=100.0,
        )
        t0 = time.perf_counter()
        apply_crew_boosts(bs, crew_list)
        timings.append((time.perf_counter() - t0) * 1000)  # ms

    p50, p90, p99 = quantiles(timings, n=100)[49], quantiles(timings, n=100)[89], quantiles(timings, n=100)[98]
    print(f"apply_crew_boosts p50={p50:.2f}ms p90={p90:.2f}ms p99={p99:.2f}ms")
    assert p99 < 50.0, f"p99 {p99:.2f}ms exceeds 50ms budget"
```

Register the `perf` marker in `pytest.ini` (or `pyproject.toml`) if it's not already. Search for `[tool.pytest.ini_options]` in `pyproject.toml`; add:

```toml
markers = [
    "perf: performance sanity tests",
]
```

- [ ] **Step 2: Run the perf test**

Run: `pytest tests/test_crew_perf.py -v -m perf -s`
Expected: PASS with p99 well under 50ms (typical: sub-millisecond for 100 pure-Python ops).

- [ ] **Step 3: Commit**

```bash
git add tests/test_crew_perf.py pyproject.toml
git commit -m "test(phase1): perf test for apply_crew_boosts at 100 crew"
```

---

## Task 20: Grafana dashboard `dare2drive-crew.json`

**Files:**
- Create: `monitoring/grafana-stack/provisioning/dashboards/dare2drive-crew.json`

- [ ] **Step 1: Create the dashboard JSON**

Copy the shape from an existing dashboard in `monitoring/grafana-stack/provisioning/dashboards/` and adapt panels. Minimum panel set:

1. **Recruit rate** — query: `sum by (source, rarity) (rate(dare2drive_crew_recruited_total[5m]))` as stacked area.
2. **Dossier purchases** — query: `sum by (tier) (rate(dare2drive_dossier_purchased_total[1h]))`.
3. **Level-up cadence** — query: `sum (rate(dare2drive_crew_level_up_total[15m]))`.
4. **Assignment churn** — query: `sum by (action) (rate(dare2drive_crew_assignment_total[15m]))`.
5. **Crew boost applications** — query: `sum by (archetype) (rate(dare2drive_crew_boost_apply_total[5m]))`.
6. **Dossier vs Parts revenue** — query pair: `sum (rate(dare2drive_currency_spent_total{reason=~"dossier_.*"}[1h]))` and `sum (rate(dare2drive_currency_spent_total{reason=~".*_crate"}[1h]))` for comparison.

Use the existing dashboards as templates for the surrounding JSON scaffolding (datasource refs, tags, refresh interval). Mark dashboard `tags: ["dare2drive", "crew"]` so it shows up in the Dare2Drive folder.

- [ ] **Step 2: Smoke-load the dashboard**

Run: `docker-compose restart grafana`
Open the local Grafana instance (per `monitoring/` README). Confirm `dare2drive-crew` dashboard appears without panel errors.

- [ ] **Step 3: Commit**

```bash
git add monitoring/grafana-stack/provisioning/dashboards/dare2drive-crew.json
git commit -m "feat(phase1): dare2drive-crew grafana dashboard"
```

---

## Task 21: Alerting rules (rarity drift + constraint violation)

**Files:**
- Create: `monitoring/grafana-stack/provisioning/alerting/crew-alerts.yaml`

- [ ] **Step 1: Inspect existing alert conventions**

Run: `ls monitoring/grafana-stack/provisioning/alerting/` and open one file to mirror its layout (group, rules, annotations, labels).

- [ ] **Step 2: Write `crew-alerts.yaml`**

Model on the existing example, but with crew-specific rules:

```yaml
apiVersion: 1
groups:
  - orgId: 1
    name: crew-alerts
    folder: dare2drive
    interval: 1m
    rules:
      - uid: crew-rarity-drift
        title: Crew ghost-rarity drift from elite_dossier
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 86400
              to: 0
            datasourceUid: PROMETHEUS_DATASOURCE_UID
            model:
              expr: |
                sum(rate(dare2drive_crew_recruited_total{source="dossier",rarity="ghost"}[24h]))
                /
                sum(rate(dare2drive_dossier_purchased_total{tier="elite_dossier"}[24h]))
              refId: A
        noDataState: NoData
        execErrState: Alerting
        for: 30m
        annotations:
          summary: Ghost-rarity rate from elite_dossier drifted from expected 3%
        labels:
          severity: warning

      - uid: crew-assignment-integrity
        title: Crew assignment integrity error
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 3600
              to: 0
            datasourceUid: LOKI_DATASOURCE_UID
            model:
              expr: |
                count_over_time({app="dare2drive"} |= "IntegrityError" |= "crew_assignments" [5m])
              refId: A
        noDataState: NoData
        execErrState: Alerting
        for: 5m
        annotations:
          summary: IntegrityError on crew_assignments — investigate concurrency bug
        labels:
          severity: page
```

Replace `PROMETHEUS_DATASOURCE_UID` and `LOKI_DATASOURCE_UID` with the actual UIDs from your Grafana provisioning (check `monitoring/grafana-stack/provisioning/datasources/`).

- [ ] **Step 3: Validate YAML**

Run: `python -c "import yaml; yaml.safe_load(open('monitoring/grafana-stack/provisioning/alerting/crew-alerts.yaml'))"`
Expected: No error.

Run: `docker-compose restart grafana`
Confirm no alert-provisioning errors in Grafana logs.

- [ ] **Step 4: Commit**

```bash
git add monitoring/grafana-stack/provisioning/alerting/crew-alerts.yaml
git commit -m "feat(phase1): alert rules for crew rarity drift + constraint violations"
```

---

## Task 22: Final full-suite regression + docs update

**Files:**
- Modify: `tests/test_seed_data.py` (if it asserts file inventory)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All PASS. If any pre-existing tests break (e.g., `test_pack_reveal_view.py` assertions on shape changed by the protocol refactor), fix them inline.

- [ ] **Step 2: Run Alembic round-trip**

Run: `alembic downgrade base && alembic upgrade head`
Expected: Clean.

- [ ] **Step 3: Manual smoke in dev**

Bring up dev stack: `docker-compose up -d`
In Discord test server:
1. `/daily` — confirm "Today's Lead" field appears
2. `/hire` — confirm crew appears in `/crew`
3. `/dossier tier:dossier` — confirm reveal + creds deducted
4. `/assign crew:<name>` — confirm assignment message
5. `/race start` — confirm race outcome differs vs. pre-crew baseline; check embed for level-up footer after several races

- [ ] **Step 4: Update CLAUDE.md changelog if present**

Search the repo for a CLAUDE.md changelog section. If present, add a line to the "Recent phases" or equivalent:

```
- Phase 1 (2026-04-24): Crew Sector — CrewMember/CrewAssignment/CrewDailyLead tables, /dossier + /hire + /crew + /assign + /unassign, archetype × stat boost mapping, XP-based leveling, Grafana dashboard + alerts.
```

- [ ] **Step 5: Commit final docs update**

```bash
git add CLAUDE.md  # if modified
git commit -m "docs(phase1): note crew sector completion"
```

---

## Self-review notes

**Spec coverage check:** Every spec section maps to a task:
- Schema → Task 1, 2
- Data files → Task 3
- Stat-resolver integration → Task 4, 17
- Crew recruitment → Task 5, 6
- Race flow integration → Task 8, 9
- Reveal UX → Task 10
- Command surface → Tasks 11–16
- Observability → Tasks 12, 17, 20, 21
- Testing → Tasks 4, 5, 6, 7, 18, 19, 22
- Migration → Task 2
- Scope boundary + carry-forward → documented in the spec, not in code

**Known pragmatic deviations from spec:**

1. Spec mentioned `/crew inspect` as a subcommand; Phase 1 ships it as flat `/crew_inspect` because Discord flat commands are simpler than Groups. Call out in a commit note; migrating to a `Group` is trivial later if preferred.
2. Spec mentioned `bot/cogs/race.py` not being listed in "modified files" — it's added here since `compute_race` is pure and the cog must carry the cross-cutting load/save work.
3. Spec described sequential-architecture refactor of `_PackRevealView`; plan extracts `RevealEntry` to a new `bot/reveal.py` for cleanliness. Original tests still green.

**Risk callouts for the executor:**

- **Alembic enum shared-type collision.** `Rarity` already exists as a Postgres enum from Phase 0. The migration references `postgresql.ENUM(*RARITY_VALUES, name="rarity", create_type=False)` — `create_type=False` is load-bearing, do not flip it or the migration will error.
- **`/crew inspect` autocomplete performance.** Autocomplete runs per keystroke. If a user has 500+ crew, this query is fine (index on `user_id`), but if perf gets slow, add a `LIMIT 100` to `_crew_name_autocomplete` before substring-filtering in Python.
- **`_PackRevealView` refactor may ripple into `tests/test_pack_reveal_view.py`.** Existing tests that pass `minted=[...]` directly will need to be rewritten against `PartRevealEntry`. Part of Task 10.
