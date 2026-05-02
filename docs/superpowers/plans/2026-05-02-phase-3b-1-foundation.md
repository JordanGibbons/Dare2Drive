# Phase 3b-1 — Foundation: System Character + Lighthouse + Citizenship Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the schema, deterministic procgen, citizenship table, and read-only `/lighthouse` view that every later sub-plan in Phase 3b builds on. After this plan ships, every `/system enable` produces a fully-characterized system (star + planets + features + flavor paragraph) and an unclaimed `Lighthouse` row, players can `/dock` to a system with a 24-hour switch cooldown, and `/system info` + `/lighthouse [system]` render the new state. **Wardenship claim, donations, flares, tribute, lapse, and Pride do not ship in this plan** — those land in 3b-2 through 3b-5.

**Architecture:**
- One Alembic migration (`0006_phase3b_foundation`) introduces five new tables (`lighthouses`, `system_planets`, `system_features`, `citizenships`, `lighthouse_upgrades`) plus three new enum columns on `systems`. A backfill block in the same migration retro-rolls a `generator_seed`, runs procgen, and creates a `Lighthouse` row for every existing system so the demo Sector keeps working post-deploy.
- `engine/system_generator.py` is the pure, deterministic core: `generate(seed) -> SystemCharacter`. Given the same seed, planets/features/star are byte-identical. Persistence is a separate function (`persist_character`) so tests can exercise generation without a DB.
- `engine/lighthouse_engine.py` owns Lighthouse creation (band roll). It is intentionally narrow in 3b-1 — claim/upgrade/tribute logic land in later sub-plans.
- The "LLM narrative seed pass" is **stubbed in 3b-1**: `engine/system_narrative.py::generate_flavor()` returns a deterministic templated paragraph. The function is named and called from the activation hook so 3b-2..5 (or a follow-on) can swap in a real LLM call without touching every call site. See [§Open Questions](#open-questions) for context — this is a deliberate scope choice, not a bug.
- `/dock` lives in a new `bot/cogs/dock.py` cog; `/lighthouse` lives in a new `bot/cogs/lighthouse.py` cog. Both follow the existing `_*_logic` module-level testable function pattern from `bot/cogs/admin.py`. Citizenship state is stored as a row in `citizenships` (not a column on `users`) — the spec locks this for forward-compat with alliance Wardenship (Phase 4+).
- `/lighthouse [system]` ships a static embed in 3b-1 (no Select tabs, no buttons). The full tabbed `DynamicItem` view ships in later sub-plans as the relevant tabs come online.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, discord.py 2.x, pytest + pytest-asyncio, PyYAML (already a dep). No new top-level dependencies.

**Spec:** [docs/roadmap/2026-05-02-phase-3b-lighthouses-design.md](../../roadmap/2026-05-02-phase-3b-lighthouses-design.md) — sections covered: §4 (system character & generation), §5 (citizenship & dock), §6 (Lighthouse object — creation only), parts of §15 (data model: the six tables touched here), §16.1 (`/dock`, read-only `/lighthouse`).

**Sections deferred to later sub-plans:** §7 (claim) → 3b-2; §8–11 (donations, upgrades, tribute passive, citizen buffs) → 3b-3; §12–13 (flares, Pride, activity-cut tribute) → 3b-4; §14 + §10.3 (lapse, vacation, tribute spending) → 3b-5.

**Dev loop:** `pytest` from the repo root. The `db_session` fixture in `tests/conftest.py` opens a per-test savepoint against the Docker Postgres (localhost:5432). `docker compose up db redis` must be running for DB-backed tests. Apply migrations with `DATABASE_URL=postgresql://dare2drive:dare2drive@localhost:5432/dare2drive python -m alembic upgrade head` after pulling new migrations. Roundtrip migrations once with `alembic downgrade -1 && alembic upgrade head` before merging.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0006_phase3b_foundation.py` | Schema for `lighthouses`/`system_planets`/`system_features`/`citizenships`/`lighthouse_upgrades`; new enum columns on `systems`; idempotent backfill that procgens existing systems and creates their Lighthouse rows |
| `data/system/star_types.yaml` | Star type/color/age combos with planet-count and feature-count distribution biases |
| `data/system/planet_types.yaml` | 7 planet types: name templates and one-line descriptors per type |
| `data/system/feature_types.yaml` | 5 feature types: named templates and descriptor templates |
| `engine/system_generator.py` | Deterministic procgen — `generate(seed) -> SystemCharacter`; persistence helper `persist_character(session, system_id, character)` |
| `engine/lighthouse_engine.py` | `roll_band(rng) -> LighthouseBand` (70/25/5); `create_lighthouse(session, system_id, rng) -> Lighthouse` |
| `engine/system_narrative.py` | `generate_flavor(character, sector_name) -> str` — deterministic templated paragraph (LLM hook) |
| `bot/cogs/dock.py` | `/dock <system>` command + `_dock_logic`; system-name autocomplete |
| `bot/cogs/lighthouse.py` | `/lighthouse [system]` command + `_lighthouse_logic`; renders Status embed |
| `tests/test_engine_system_generator.py` | Determinism, planet count bias, feature placement, fallback for unknown enums |
| `tests/test_engine_lighthouse_engine.py` | Band distribution and `create_lighthouse` row contents |
| `tests/test_engine_system_narrative.py` | Deterministic paragraph for fixed input; non-empty for any character |
| `tests/test_system_data_files.py` | Schema check for `star_types.yaml`, `planet_types.yaml`, `feature_types.yaml` |
| `tests/test_phase3b_migration.py` | Migration upgrade/downgrade roundtrip; backfill creates planets/features/Lighthouse for existing systems |
| `tests/test_phase3b_models.py` | ORM model invariants (relationships, constraints) |
| `tests/test_cog_dock.py` | `/dock` happy path, switch cooldown, autocomplete, undock |
| `tests/test_cog_lighthouse.py` | `/lighthouse` shows correct embed for unclaimed system; defaults to current channel |
| `tests/test_scenarios/test_system_activation_flow.py` | End-to-end: enable system → procgen → Lighthouse exists → `/system info` + `/lighthouse` render correctly |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add enums (`LighthouseBand`, `LighthouseState`, `StarType`, `StarColor`, `StarAge`, `PlanetType`, `PlanetSize`, `Richness`, `FeatureType`, `SlotCategory`); add `System.star_type/star_color/star_age`; add models `Lighthouse`, `SystemPlanet`, `SystemFeature`, `Citizenship`, `LighthouseUpgrade`; expand `System.flavor_text` to `Text` (was `String(500)`) |
| `bot/cogs/admin.py` | `_system_enable_logic` calls `engine.system_generator.persist_character()`, `engine.lighthouse_engine.create_lighthouse()`, then writes flavor text. Idempotent on re-run |
| `bot/cogs/admin.py` | `_sector_info_logic` (or new `_system_info_logic`) extends to show star, planet count, feature count, Lighthouse band/state/Warden, Pride |
| `bot/main.py` | `setup_hook` loads `bot.cogs.dock` and `bot.cogs.lighthouse` |
| `bot/system_gating.py` | `/dock` and `/lighthouse` added to the universe-wide allow list (no system-channel gating) |
| `tests/conftest.py` | `sample_system` fixture extended to populate planets/features/star/Lighthouse so existing tests stay green |

---

## Task 1: Schema migration — new tables, enums, system extensions

**Files:**
- Create: `db/migrations/versions/0006_phase3b_foundation.py`
- Create: `tests/test_phase3b_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3b_migration.py`:

```python
"""Phase 3b-1 migration: schema + backfill round-trips and creates expected rows."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def test_migration_creates_new_tables(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    names = set(insp.get_table_names())
    for table in (
        "lighthouses",
        "system_planets",
        "system_features",
        "citizenships",
        "lighthouse_upgrades",
    ):
        assert table in names, f"missing table: {table}"


async def test_migration_extends_systems_with_star_columns(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {col["name"] for col in insp.get_columns("systems")}
    assert "star_type" in cols
    assert "star_color" in cols
    assert "star_age" in cols


async def test_migration_creates_lighthouse_band_enum(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'lighthouse_band' "
                "ORDER BY e.enumsortorder"
            )
        )
    ).scalars().all()
    assert rows == ["rim", "middle", "inner"]


async def test_migration_creates_planet_type_enum(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'planet_type' "
                "ORDER BY enumlabel"
            )
        )
    ).scalars().all()
    assert set(rows) == {"rocky", "gas", "frozen", "exotic", "ocean", "desert", "barren"}


async def test_lighthouses_has_pride_score_default_zero(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {c["name"]: c for c in insp.get_columns("lighthouses")}
    assert "pride_score" in cols
    # default is 0 — verified via insert-then-read in the model tests, not here


async def test_citizenships_uniqueness_active_per_player(db_session):
    """A partial unique index ensures a player has at most one active (ended_at IS NULL) citizenship."""
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    indexes = insp.get_indexes("citizenships")
    names = {idx["name"] for idx in indexes}
    assert any("active_player" in n for n in names), (
        f"expected partial unique index containing 'active_player' on citizenships; got {names}"
    )
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase3b_migration.py -v --no-cov`
Expected: 6 FAIL — tables don't exist yet.

- [ ] **Step 3: Write the migration**

Create `db/migrations/versions/0006_phase3b_foundation.py`:

```python
"""Phase 3b-1 — Lighthouses, citizenship, system character.

Revision ID: 0006_phase3b_foundation
Revises: 0005_phase2b_crew_stats
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_phase3b_foundation"
down_revision = "0005_phase2b_crew_stats"
branch_labels = None
depends_on = None


# ──────────── Enums ────────────

LIGHTHOUSE_BAND = postgresql.ENUM("rim", "middle", "inner", name="lighthouse_band")
LIGHTHOUSE_STATE = postgresql.ENUM("active", "contested", "dormant", name="lighthouse_state")
STAR_TYPE = postgresql.ENUM("single", "binary", "trinary", name="star_type")
STAR_COLOR = postgresql.ENUM("red", "yellow", "white", "blue", "exotic", name="star_color")
STAR_AGE = postgresql.ENUM("young", "mature", "aging", "dying", name="star_age")
PLANET_TYPE = postgresql.ENUM(
    "rocky", "gas", "frozen", "exotic", "ocean", "desert", "barren", name="planet_type"
)
PLANET_SIZE = postgresql.ENUM("small", "medium", "large", name="planet_size")
RICHNESS = postgresql.ENUM("low", "medium", "high", name="richness")
FEATURE_TYPE = postgresql.ENUM(
    "relic_field", "hazard_zone", "industrial_ruin", "phenomenon", "derelict", name="feature_type"
)
SLOT_CATEGORY = postgresql.ENUM(
    "fog", "weather", "defense", "network", "wildcard", name="slot_category"
)
ALL_NEW_ENUMS = [
    LIGHTHOUSE_BAND,
    LIGHTHOUSE_STATE,
    STAR_TYPE,
    STAR_COLOR,
    STAR_AGE,
    PLANET_TYPE,
    PLANET_SIZE,
    RICHNESS,
    FEATURE_TYPE,
    SLOT_CATEGORY,
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create new enum types.
    for e in ALL_NEW_ENUMS:
        e.create(bind, checkfirst=True)

    # 2. Extend systems with star_*, expand flavor_text to TEXT.
    op.add_column(
        "systems",
        sa.Column(
            "star_type",
            postgresql.ENUM(name="star_type", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "systems",
        sa.Column(
            "star_color",
            postgresql.ENUM(name="star_color", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "systems",
        sa.Column(
            "star_age",
            postgresql.ENUM(name="star_age", create_type=False),
            nullable=True,
        ),
    )
    op.alter_column("systems", "flavor_text", type_=sa.Text(), existing_nullable=True)

    # 3. system_planets
    op.create_table(
        "system_planets",
        sa.Column(
            "system_id",
            sa.String(20),
            sa.ForeignKey("systems.channel_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("slot_index", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "planet_type",
            postgresql.ENUM(name="planet_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "size",
            postgresql.ENUM(name="planet_size", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "richness",
            postgresql.ENUM(name="richness", create_type=False),
            nullable=False,
        ),
        sa.Column("descriptor", sa.String(255), nullable=False),
    )

    # 4. system_features
    op.create_table(
        "system_features",
        sa.Column(
            "system_id",
            sa.String(20),
            sa.ForeignKey("systems.channel_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("slot_index", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "feature_type",
            postgresql.ENUM(name="feature_type", create_type=False),
            nullable=False,
        ),
        sa.Column("descriptor", sa.String(255), nullable=False),
    )

    # 5. lighthouses
    op.create_table(
        "lighthouses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "system_id",
            sa.String(20),
            sa.ForeignKey("systems.channel_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "band",
            postgresql.ENUM(name="lighthouse_band", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="lighthouse_state", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "warden_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("lapse_warning_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vacation_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "pride_score", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 6. lighthouse_upgrades — empty rows allowed; presence != installation
    op.create_table(
        "lighthouse_upgrades",
        sa.Column(
            "lighthouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lighthouses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "slot_category",
            postgresql.ENUM(name="slot_category", create_type=False),
            primary_key=True,
        ),
        sa.Column("slot_subindex", sa.Integer(), primary_key=True, server_default="0"),
        sa.Column("installed_upgrade_id", sa.String(60), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wildcard_chosen_effect", sa.String(60), nullable=True),
    )

    # 7. citizenships
    op.create_table(
        "citizenships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "player_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "system_id",
            sa.String(20),
            sa.ForeignKey("systems.channel_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "docked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("switched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial unique index: at most one active citizenship per player.
    op.create_index(
        "ix_citizenships_active_player",
        "citizenships",
        ["player_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    # 8. Backfill existing systems with deterministic procgen + Lighthouse rows.
    _backfill_existing_systems(bind)


def _backfill_existing_systems(bind) -> None:
    """For every existing System row, roll a seed, generate character data,
    create the Lighthouse, and write a placeholder flavor_text. Idempotent
    on re-run because we skip systems whose config already has generator_seed.
    """
    # NOTE: Imports kept local so Alembic env doesn't pick up engine modules
    # at boot before the migration is even running.
    import json
    import random

    from engine.system_generator import generate, persist_character_sync
    from engine.lighthouse_engine import roll_band
    from engine.system_narrative import generate_flavor

    rows = bind.execute(
        sa.text("SELECT channel_id, name, sector_id, config FROM systems")
    ).fetchall()
    for channel_id, name, sector_id, config in rows:
        cfg = config if isinstance(config, dict) else (json.loads(config) if config else {})
        if cfg.get("generator_seed") is not None:
            continue
        seed = random.SystemRandom().randint(1, 2**63 - 1)
        cfg["generator_seed"] = seed

        rng = random.Random(seed)
        character = generate(seed)
        persist_character_sync(bind, channel_id, character)

        band = roll_band(rng)
        bind.execute(
            sa.text(
                "INSERT INTO lighthouses (system_id, band, state, pride_score) "
                "VALUES (:sid, :band, 'active', 0)"
            ),
            {"sid": channel_id, "band": band.value},
        )

        sector_name = bind.execute(
            sa.text("SELECT name FROM sectors WHERE guild_id = :sid"),
            {"sid": sector_id},
        ).scalar() or ""
        flavor = generate_flavor(character, sector_name=sector_name)

        bind.execute(
            sa.text("UPDATE systems SET config = :cfg, flavor_text = :flav, "
                    "star_type = :st, star_color = :sc, star_age = :sa "
                    "WHERE channel_id = :cid"),
            {
                "cfg": json.dumps(cfg),
                "flav": flavor,
                "st": character.star.type,
                "sc": character.star.color,
                "sa": character.star.age,
                "cid": channel_id,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_citizenships_active_player", table_name="citizenships")
    op.drop_table("citizenships")
    op.drop_table("lighthouse_upgrades")
    op.drop_table("lighthouses")
    op.drop_table("system_features")
    op.drop_table("system_planets")

    op.alter_column("systems", "flavor_text", type_=sa.String(500), existing_nullable=True)
    op.drop_column("systems", "star_age")
    op.drop_column("systems", "star_color")
    op.drop_column("systems", "star_type")

    bind = op.get_bind()
    for e in reversed(ALL_NEW_ENUMS):
        e.drop(bind, checkfirst=True)
```

- [ ] **Step 4: Run, confirm tests pass**

Run: `DATABASE_URL=postgresql://dare2drive:dare2drive@localhost:5432/dare2drive python -m alembic upgrade head` then `pytest tests/test_phase3b_migration.py -v --no-cov`.

Expected: 6 PASS. Note: `_backfill_existing_systems` references `engine.system_generator` etc. — those are created in Tasks 4–7. If the migration is run *before* those modules exist, the backfill block will fail. **Order of task execution matters:** complete Tasks 4, 6, 7 (generator + lighthouse_engine + system_narrative) before running `alembic upgrade head` on a DB that has any existing System rows. The migration test file uses an empty DB so it doesn't hit the backfill path; the scenario test in Task 13 verifies backfill.

- [ ] **Step 5: Round-trip migration**

Run:
```
DATABASE_URL=... python -m alembic downgrade -1
DATABASE_URL=... python -m alembic upgrade head
```
Expected: both succeed; no orphaned enum types remain after downgrade.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/versions/0006_phase3b_foundation.py tests/test_phase3b_migration.py
git commit -m "feat(phase3b-1): add lighthouse/citizenship/system character schema"
```

---

## Task 2: ORM models for new tables + System extensions

**Files:**
- Modify: `db/models.py`
- Create: `tests/test_phase3b_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3b_models.py`:

```python
"""Phase 3b-1 ORM model invariants."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


async def test_lighthouse_creates_and_reads(db_session, sample_system):
    from db.models import Lighthouse, LighthouseBand, LighthouseState

    lh = Lighthouse(system_id=sample_system.channel_id, band=LighthouseBand.RIM)
    db_session.add(lh)
    await db_session.flush()
    await db_session.refresh(lh)

    assert lh.id is not None
    assert lh.state == LighthouseState.ACTIVE
    assert lh.pride_score == 0
    assert lh.warden_id is None


async def test_lighthouse_one_per_system(db_session, sample_system):
    from db.models import Lighthouse, LighthouseBand

    db_session.add(Lighthouse(system_id=sample_system.channel_id, band=LighthouseBand.RIM))
    await db_session.flush()
    db_session.add(Lighthouse(system_id=sample_system.channel_id, band=LighthouseBand.MIDDLE))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_system_planet_composite_key(db_session, sample_system):
    from db.models import PlanetSize, PlanetType, Richness, SystemPlanet

    p = SystemPlanet(
        system_id=sample_system.channel_id,
        slot_index=0,
        name="Veyra Hesper",
        planet_type=PlanetType.ROCKY,
        size=PlanetSize.MEDIUM,
        richness=Richness.MEDIUM,
        descriptor="a wind-scoured world",
    )
    db_session.add(p)
    await db_session.flush()
    found = (
        await db_session.execute(select(SystemPlanet).where(SystemPlanet.system_id == sample_system.channel_id))
    ).scalar_one()
    assert found.name == "Veyra Hesper"


async def test_citizenship_one_active_per_player(db_session, sample_system, sample_user):
    from db.models import Citizenship

    db_session.add(Citizenship(player_id=sample_user.discord_id, system_id=sample_system.channel_id))
    await db_session.flush()
    db_session.add(Citizenship(player_id=sample_user.discord_id, system_id=sample_system.channel_id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_citizenship_allows_multiple_after_ended(db_session, sample_system, sample_user):
    from db.models import Citizenship

    a = Citizenship(
        player_id=sample_user.discord_id,
        system_id=sample_system.channel_id,
        ended_at=datetime.now(timezone.utc),
    )
    db_session.add(a)
    await db_session.flush()
    db_session.add(Citizenship(player_id=sample_user.discord_id, system_id=sample_system.channel_id))
    await db_session.flush()  # no IntegrityError — partial index excludes ended rows


async def test_lighthouse_upgrade_composite_key(db_session, sample_system):
    from db.models import Lighthouse, LighthouseBand, LighthouseUpgrade, SlotCategory

    lh = Lighthouse(system_id=sample_system.channel_id, band=LighthouseBand.MIDDLE)
    db_session.add(lh)
    await db_session.flush()
    db_session.add(
        LighthouseUpgrade(lighthouse_id=lh.id, slot_category=SlotCategory.FOG, slot_subindex=0)
    )
    await db_session.flush()  # baseline empty slot row OK
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase3b_models.py -v --no-cov`
Expected: 6 FAIL with `ImportError` — none of the models exist yet.

- [ ] **Step 3: Add enums and models to `db/models.py`**

Append after the existing enums (after the `BuildActivity` enum, around line 154):

```python
class LighthouseBand(str, enum.Enum):
    RIM = "rim"
    MIDDLE = "middle"
    INNER = "inner"


class LighthouseState(str, enum.Enum):
    ACTIVE = "active"
    CONTESTED = "contested"
    DORMANT = "dormant"


class StarType(str, enum.Enum):
    SINGLE = "single"
    BINARY = "binary"
    TRINARY = "trinary"


class StarColor(str, enum.Enum):
    RED = "red"
    YELLOW = "yellow"
    WHITE = "white"
    BLUE = "blue"
    EXOTIC = "exotic"


class StarAge(str, enum.Enum):
    YOUNG = "young"
    MATURE = "mature"
    AGING = "aging"
    DYING = "dying"


class PlanetType(str, enum.Enum):
    ROCKY = "rocky"
    GAS = "gas"
    FROZEN = "frozen"
    EXOTIC = "exotic"
    OCEAN = "ocean"
    DESERT = "desert"
    BARREN = "barren"


class PlanetSize(str, enum.Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class Richness(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FeatureType(str, enum.Enum):
    RELIC_FIELD = "relic_field"
    HAZARD_ZONE = "hazard_zone"
    INDUSTRIAL_RUIN = "industrial_ruin"
    PHENOMENON = "phenomenon"
    DERELICT = "derelict"


class SlotCategory(str, enum.Enum):
    FOG = "fog"
    WEATHER = "weather"
    DEFENSE = "defense"
    NETWORK = "network"
    WILDCARD = "wildcard"
```

Then extend `System`:

```python
# In class System(Base): replace flavor_text and add three new columns
class System(Base):
    __tablename__ = "systems"

    channel_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    sector_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("sectors.guild_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flavor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    star_type: Mapped[StarType | None] = mapped_column(
        Enum(StarType, values_callable=lambda x: [e.value for e in x], name="star_type"),
        nullable=True,
    )
    star_color: Mapped[StarColor | None] = mapped_column(
        Enum(StarColor, values_callable=lambda x: [e.value for e in x], name="star_color"),
        nullable=True,
    )
    star_age: Mapped[StarAge | None] = mapped_column(
        Enum(StarAge, values_callable=lambda x: [e.value for e in x], name="star_age"),
        nullable=True,
    )
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sector: Mapped[Sector] = relationship(back_populates="systems")
    planets: Mapped[list[SystemPlanet]] = relationship(
        back_populates="system", cascade="all, delete-orphan", lazy="selectin"
    )
    features: Mapped[list[SystemFeature]] = relationship(
        back_populates="system", cascade="all, delete-orphan", lazy="selectin"
    )
    lighthouse: Mapped[Lighthouse | None] = relationship(
        back_populates="system", uselist=False, lazy="selectin"
    )
```

(`Text` needs to be imported from `sqlalchemy` at top of file if not already.)

Add the new models at the end of the file (or near the other multi-tenant models):

```python
class SystemPlanet(Base):
    __tablename__ = "system_planets"

    system_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("systems.channel_id", ondelete="CASCADE"), primary_key=True
    )
    slot_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    planet_type: Mapped[PlanetType] = mapped_column(
        Enum(PlanetType, values_callable=lambda x: [e.value for e in x], name="planet_type"),
        nullable=False,
    )
    size: Mapped[PlanetSize] = mapped_column(
        Enum(PlanetSize, values_callable=lambda x: [e.value for e in x], name="planet_size"),
        nullable=False,
    )
    richness: Mapped[Richness] = mapped_column(
        Enum(Richness, values_callable=lambda x: [e.value for e in x], name="richness"),
        nullable=False,
    )
    descriptor: Mapped[str] = mapped_column(String(255), nullable=False)

    system: Mapped[System] = relationship(back_populates="planets")


class SystemFeature(Base):
    __tablename__ = "system_features"

    system_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("systems.channel_id", ondelete="CASCADE"), primary_key=True
    )
    slot_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    feature_type: Mapped[FeatureType] = mapped_column(
        Enum(FeatureType, values_callable=lambda x: [e.value for e in x], name="feature_type"),
        nullable=False,
    )
    descriptor: Mapped[str] = mapped_column(String(255), nullable=False)

    system: Mapped[System] = relationship(back_populates="features")


class Lighthouse(Base):
    __tablename__ = "lighthouses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("systems.channel_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    band: Mapped[LighthouseBand] = mapped_column(
        Enum(LighthouseBand, values_callable=lambda x: [e.value for e in x], name="lighthouse_band"),
        nullable=False,
    )
    state: Mapped[LighthouseState] = mapped_column(
        Enum(LighthouseState, values_callable=lambda x: [e.value for e in x], name="lighthouse_state"),
        nullable=False,
        default=LighthouseState.ACTIVE,
        server_default=LighthouseState.ACTIVE.value,
    )
    warden_id: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("users.discord_id", ondelete="SET NULL"), nullable=True
    )
    lapse_warning_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vacation_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pride_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    system: Mapped[System] = relationship(back_populates="lighthouse")
    upgrades: Mapped[list[LighthouseUpgrade]] = relationship(
        back_populates="lighthouse", cascade="all, delete-orphan", lazy="selectin"
    )


class LighthouseUpgrade(Base):
    __tablename__ = "lighthouse_upgrades"

    lighthouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lighthouses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    slot_category: Mapped[SlotCategory] = mapped_column(
        Enum(SlotCategory, values_callable=lambda x: [e.value for e in x], name="slot_category"),
        primary_key=True,
    )
    slot_subindex: Mapped[int] = mapped_column(Integer, primary_key=True, default=0, server_default="0")
    installed_upgrade_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wildcard_chosen_effect: Mapped[str | None] = mapped_column(String(60), nullable=True)

    lighthouse: Mapped[Lighthouse] = relationship(back_populates="upgrades")


class Citizenship(Base):
    __tablename__ = "citizenships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("systems.channel_id", ondelete="CASCADE"), nullable=False, index=True
    )
    docked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Don't add any `__table_args__` — the partial unique index lives in the migration only (it doesn't have a clean SQLAlchemy equivalent across dialects).

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_phase3b_models.py -v --no-cov`
Expected: 6 PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ --no-cov -q`
Expected: All previously-green tests stay green. (The fixture `sample_system` may need to be extended in Task 9; if `test_systems_sectors.py` fails because the fixture doesn't yet have planets/features, defer that fix to Task 9 — it's tracked there.)

- [ ] **Step 6: Commit**

```bash
git add db/models.py tests/test_phase3b_models.py
git commit -m "feat(phase3b-1): ORM models + enums for lighthouses, citizenship, system character"
```

---

## Task 3: Author data — star_types.yaml, planet_types.yaml, feature_types.yaml

**Files:**
- Create: `data/system/star_types.yaml`
- Create: `data/system/planet_types.yaml`
- Create: `data/system/feature_types.yaml`
- Create: `tests/test_system_data_files.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_system_data_files.py`:

```python
"""Schema and content checks for system character data files."""

from __future__ import annotations

from pathlib import Path

import yaml


DATA_DIR = Path(__file__).parent.parent / "data" / "system"


def _load(name: str) -> dict:
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


def test_star_types_loads():
    data = _load("star_types.yaml")
    assert "weights" in data
    # Each weight key is a "type:color" pair (age is rolled separately)
    for key, weight in data["weights"].items():
        parts = key.split(":")
        assert len(parts) == 2, key
        assert weight > 0
    assert "age_weights" in data
    for age in ("young", "mature", "aging", "dying"):
        assert age in data["age_weights"]


def test_star_types_planet_count_bias():
    data = _load("star_types.yaml")
    assert "planet_count_range" in data
    pcr = data["planet_count_range"]
    # Default + per-color overrides
    assert "default" in pcr
    lo, hi = pcr["default"]
    assert 3 <= lo <= hi <= 7


def test_planet_types_per_type_pool():
    data = _load("planet_types.yaml")
    expected = {"rocky", "gas", "frozen", "exotic", "ocean", "desert", "barren"}
    assert set(data.keys()) == expected
    for ptype, cfg in data.items():
        assert "name_templates" in cfg and len(cfg["name_templates"]) >= 5
        assert "descriptors" in cfg and len(cfg["descriptors"]) >= 3


def test_feature_types_per_type_pool():
    data = _load("feature_types.yaml")
    expected = {"relic_field", "hazard_zone", "industrial_ruin", "phenomenon", "derelict"}
    assert set(data.keys()) == expected
    for ftype, cfg in data.items():
        assert "name_templates" in cfg and len(cfg["name_templates"]) >= 3
        assert "descriptors" in cfg and len(cfg["descriptors"]) >= 3
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_system_data_files.py -v --no-cov`
Expected: 4 FAIL — files don't exist.

- [ ] **Step 3: Author the YAMLs**

Create `data/system/star_types.yaml`:

```yaml
# Type:color combo weights for star generation.
# Age is rolled independently from age_weights.
weights:
  single:red: 14
  single:yellow: 16
  single:white: 8
  single:blue: 5
  single:exotic: 2
  binary:red: 4
  binary:yellow: 5
  binary:white: 3
  binary:blue: 2
  binary:exotic: 1
  trinary:red: 1
  trinary:yellow: 1
  trinary:white: 1
  trinary:blue: 1
  trinary:exotic: 1
age_weights:
  young: 4
  mature: 10
  aging: 5
  dying: 2
# (lo, hi) inclusive planet-count range per scenario.
planet_count_range:
  default: [3, 7]
  by_color:
    red:    [4, 7]    # red giants tend toward more planets
    blue:   [3, 5]    # blue stars: harsher, fewer survive
    exotic: [3, 6]
# Number of features per system. Long-tail toward 1.
feature_count_weights:
  "0": 2
  "1": 5
  "2": 2
  "3": 1
# Type bias for planet generation by star color (renormalized after pick).
planet_type_bias:
  red:
    barren: 2.0
    rocky: 1.5
    gas: 1.5
    desert: 1.2
    frozen: 0.8
    ocean: 0.6
    exotic: 0.5
  yellow:
    rocky: 1.5
    ocean: 1.2
    desert: 1.0
    gas: 1.0
    frozen: 0.8
    barren: 0.8
    exotic: 0.5
  white:
    rocky: 1.0
    frozen: 1.2
    barren: 1.0
    gas: 1.0
    desert: 0.8
    ocean: 0.7
    exotic: 0.5
  blue:
    barren: 1.5
    rocky: 1.2
    exotic: 1.5
    gas: 1.0
    frozen: 0.6
    ocean: 0.5
    desert: 0.6
  exotic:
    exotic: 3.0
    rocky: 1.0
    gas: 1.0
    frozen: 1.0
    barren: 0.8
    ocean: 0.5
    desert: 0.5
# Feature type bias by star age (older = more derelicts/relic_fields).
feature_type_bias:
  young:
    phenomenon: 2.0
    hazard_zone: 1.2
    relic_field: 0.4
    derelict: 0.3
    industrial_ruin: 0.5
  mature:
    phenomenon: 1.0
    hazard_zone: 1.0
    relic_field: 1.0
    derelict: 1.0
    industrial_ruin: 1.0
  aging:
    relic_field: 1.5
    derelict: 1.5
    industrial_ruin: 1.2
    phenomenon: 0.8
    hazard_zone: 1.0
  dying:
    derelict: 2.5
    relic_field: 2.0
    industrial_ruin: 1.5
    hazard_zone: 1.2
    phenomenon: 0.5
```

Create `data/system/planet_types.yaml`:

```yaml
rocky:
  name_templates:
    - "{prefix}-{number}"
    - "{adj} {noun}"
    - "{noun} {greek}"
    - "Old {noun}"
    - "{prefix} {greek}"
  descriptors:
    - "a dense rocky world streaked with old impact scars"
    - "tide-locked grey rock with slow basalt floes"
    - "fractured crust held together by deep magnetism"
    - "salt flats from end to end"
gas:
  name_templates:
    - "{adj} {noun}"
    - "Great {noun}"
    - "{prefix}-{greek}"
    - "{noun} Veil"
    - "Outer {noun}"
  descriptors:
    - "a banded gas giant with auroral crowns at both poles"
    - "lazy windless atmosphere thick with hydrocarbons"
    - "silver-streaked methane rolls visible from orbit"
    - "perpetual storm-belt at the equator, clear caps"
frozen:
  name_templates:
    - "Cold {noun}"
    - "{adj} {noun}"
    - "{noun}-{greek}"
    - "Pale {noun}"
    - "Last {noun}"
  descriptors:
    - "ice-shell world over a deep liquid mantle"
    - "ammonia frost shows teal under the system primary"
    - "cryovolcanoes drift slow blue plumes for centuries"
    - "single fault crack runs nearly pole to pole"
exotic:
  name_templates:
    - "{adj} {noun}"
    - "{noun} of {prefix}"
    - "Spire-{number}"
    - "Strange {noun}"
    - "{noun}-{greek}-{number}"
  descriptors:
    - "metallic-hydrogen ocean under a lattice of standing waves"
    - "crystalline mantle that rings on long timescales"
    - "fluorescent atmosphere; spectroscopy disagrees with itself"
    - "albedo flickers on a 47-second cycle nobody can explain"
ocean:
  name_templates:
    - "{adj} {noun}"
    - "{noun} of Tides"
    - "Blue {noun}"
    - "{prefix} Sea"
    - "Old Tide-{greek}"
  descriptors:
    - "single shoreless ocean under a thin atmosphere"
    - "ice-locked above, liquid below, currents in twelve layers"
    - "the world is a sea; whatever continents existed are gone"
    - "tidal range so deep the shore moves kilometers per hour"
desert:
  name_templates:
    - "{adj} {noun}"
    - "{noun}'s Reach"
    - "Long {noun}"
    - "{prefix} Wastes"
    - "{noun}-{number}"
  descriptors:
    - "endless dune fields with wind that never falls below 40 knots"
    - "salt-glass plains where the old sea boiled away"
    - "red rust country broken by deep canyons"
    - "rock and dust, nothing else, for as far as anyone has flown"
barren:
  name_templates:
    - "Bare {noun}"
    - "{adj} {noun}"
    - "{noun}-{greek}"
    - "Ash {noun}"
    - "{prefix}-{number}"
  descriptors:
    - "airless rock, vacuum-welded boulders kilometers across"
    - "stripped of atmosphere, mantle still visibly warm"
    - "cratered to its bones, no surface activity for ages"
    - "regolith packed like concrete; nothing has stirred it in eons"

# Pools used by name_templates {placeholders}.
_pools:
  prefix:
    - Veyra
    - Tarsus
    - Iolan
    - Hespera
    - Drum
    - Outer
    - Inner
    - Long-Eye
    - Sable
    - Marrow
  noun:
    - Hesper
    - Reach
    - Drift
    - Anchor
    - Hollow
    - Cinder
    - Brine
    - Kiln
    - Atrium
    - Mark
  adj:
    - Pale
    - Slow
    - Iron
    - Quiet
    - Thin
    - Cold
    - Salt
    - Glass
    - Old
    - Far
  greek:
    - Alpha
    - Beta
    - Gamma
    - Delta
    - Epsilon
    - Zeta
    - Eta
    - Theta
  number:
    - "I"
    - "II"
    - "III"
    - "IV"
    - "V"
    - "VI"
```

Create `data/system/feature_types.yaml`:

```yaml
relic_field:
  name_templates:
    - "the {prefix} Belt"
    - "the Eastern Belt of {prefix} {greek}"
    - "{prefix} Reliquary Drift"
    - "the Drift of {noun}"
    - "the Old Mark"
  descriptors:
    - "a kilometers-wide sheet of pre-Authority debris in slow procession"
    - "the bones of a fleet that never came home"
    - "salvage thick enough to obscure the parent body"
hazard_zone:
  name_templates:
    - "the {prefix} Maelstrom"
    - "{noun} Squall"
    - "the {adj} Throat"
    - "Hot Lane {greek}"
  descriptors:
    - "magnetic shears across navigation lanes; AI pilots don't fly here"
    - "radiation belt that hums on the survey instruments"
    - "gravitic chop nobody has fully mapped"
industrial_ruin:
  name_templates:
    - "the Conducting Spire"
    - "{prefix} Forge-{greek}"
    - "the {adj} Foundry"
    - "Old {prefix} Yard"
  descriptors:
    - "vacuum-mothballed hulls of an extraction op the Authority shut down"
    - "tower-frame standing kilometers above an old open-pit mine"
    - "an industrial complex stripped to skeleton; it still hums faintly"
phenomenon:
  name_templates:
    - "the Fog Atrium"
    - "the {prefix} Slow Light"
    - "{noun}'s Echo"
    - "the Halt"
  descriptors:
    - "a region where light arrives noticeably late"
    - "a standing-wave fog that swallows transponders inside it"
    - "subspace inversion that shows the system from the wrong angle"
derelict:
  name_templates:
    - "the {prefix} Wreck"
    - "{adj}-{greek} Hulk"
    - "the {noun} Drift"
    - "Bone Lane {greek}"
  descriptors:
    - "a ship the size of a moon, half-submerged in the gas giant"
    - "a kilometer-class hulk with the running lights still on"
    - "an ancient hauler with a name nobody speaks anymore"

_pools:
  prefix:
    - Veyra
    - Tarsus
    - Iolan
    - Hespera
    - Drum
    - Sable
    - Marrow
    - Far-Mark
  noun:
    - Reach
    - Drift
    - Anchor
    - Hollow
    - Cinder
    - Atrium
    - Mark
    - Whisper
  adj:
    - Pale
    - Slow
    - Iron
    - Quiet
    - Old
    - Thin
    - Far
    - Sable
  greek:
    - Alpha
    - Beta
    - Gamma
    - Delta
    - Epsilon
    - Zeta
```

- [ ] **Step 4: Run, confirm tests pass**

Run: `pytest tests/test_system_data_files.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add data/system/star_types.yaml data/system/planet_types.yaml data/system/feature_types.yaml tests/test_system_data_files.py
git commit -m "feat(phase3b-1): system character data files (star/planet/feature pools)"
```

---

## Task 4: Deterministic procgen — `engine/system_generator.py`

**Files:**
- Create: `engine/system_generator.py`
- Create: `tests/test_engine_system_generator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_system_generator.py`:

```python
"""Deterministic procgen for system character."""

from __future__ import annotations

import pytest


def test_generate_is_deterministic():
    from engine.system_generator import generate

    a = generate(seed=12345)
    b = generate(seed=12345)
    assert a == b


def test_generate_distinct_seeds_differ():
    from engine.system_generator import generate

    a = generate(seed=1)
    b = generate(seed=2)
    assert a != b


def test_generate_planet_count_in_range():
    from engine.system_generator import generate

    for seed in range(1, 50):
        c = generate(seed=seed)
        assert 3 <= len(c.planets) <= 7


def test_generate_feature_count_in_range():
    from engine.system_generator import generate

    counts = [len(generate(seed=s).features) for s in range(1, 200)]
    assert min(counts) == 0
    assert max(counts) <= 3


def test_generate_planet_unique_names_within_system():
    from engine.system_generator import generate

    for seed in range(1, 30):
        c = generate(seed=seed)
        names = [p.name for p in c.planets]
        assert len(names) == len(set(names)), (seed, names)


def test_generate_star_fields_populated():
    from engine.system_generator import generate

    c = generate(seed=99)
    assert c.star.type in ("single", "binary", "trinary")
    assert c.star.color in ("red", "yellow", "white", "blue", "exotic")
    assert c.star.age in ("young", "mature", "aging", "dying")


def test_generate_persist_roundtrip(db_session, sample_system):
    from engine.system_generator import generate, persist_character

    c = generate(seed=4242)
    await_persist = persist_character(db_session, sample_system.channel_id, c)
    # Re-read planets
    from db.models import SystemPlanet
    from sqlalchemy import select

    async def _read():
        result = await db_session.execute(
            select(SystemPlanet).where(SystemPlanet.system_id == sample_system.channel_id)
        )
        return result.scalars().all()
    # persist_character is async; the test is async (db_session is async)
    # but pytest-asyncio handles that via the test function's own async def above.
    # Convert: rewrite the test as an async one.


async def test_persist_writes_planets_and_features(db_session, sample_system):
    from db.models import SystemFeature, SystemPlanet
    from engine.system_generator import generate, persist_character
    from sqlalchemy import select

    c = generate(seed=4242)
    await persist_character(db_session, sample_system.channel_id, c)
    await db_session.flush()

    planets = (
        await db_session.execute(
            select(SystemPlanet).where(SystemPlanet.system_id == sample_system.channel_id)
        )
    ).scalars().all()
    assert len(planets) == len(c.planets)

    features = (
        await db_session.execute(
            select(SystemFeature).where(SystemFeature.system_id == sample_system.channel_id)
        )
    ).scalars().all()
    assert len(features) == len(c.features)


# Drop the broken sync version
def test_generate_persist_roundtrip_REMOVED():  # placeholder so test file remains stable
    pass
```

(The `test_generate_persist_roundtrip` function above is intentionally non-async-broken — replace it with `test_persist_writes_planets_and_features` once the implementation lands. Easier path: delete the broken test and keep only the async one. Do that in Step 4.)

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_system_generator.py -v --no-cov`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `engine/system_generator.py`**

Create `engine/system_generator.py`:

```python
"""Deterministic procgen for per-system character.

`generate(seed)` is a pure function: same seed → identical SystemCharacter.
`persist_character(session, system_id, character)` writes the character to
`system_planets`/`system_features` and updates `systems.star_*` columns.

There is also a `persist_character_sync(bind, system_id, character)` variant
used by the Alembic backfill — see Task 1.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_DATA_DIR = Path(__file__).parent.parent / "data" / "system"


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((_DATA_DIR / name).read_text(encoding="utf-8"))


_STAR_DATA = _load("star_types.yaml")
_PLANET_DATA = _load("planet_types.yaml")
_FEATURE_DATA = _load("feature_types.yaml")


@dataclass(frozen=True)
class Star:
    type: str  # one of single/binary/trinary
    color: str  # one of red/yellow/white/blue/exotic
    age: str  # one of young/mature/aging/dying


@dataclass(frozen=True)
class Planet:
    slot_index: int
    name: str
    planet_type: str
    size: str
    richness: str
    descriptor: str


@dataclass(frozen=True)
class Feature:
    slot_index: int
    name: str
    feature_type: str
    descriptor: str


@dataclass(frozen=True)
class SystemCharacter:
    seed: int
    star: Star
    planets: tuple[Planet, ...] = field(default_factory=tuple)
    features: tuple[Feature, ...] = field(default_factory=tuple)


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    values = [float(weights[k]) for k in keys]
    return rng.choices(keys, weights=values, k=1)[0]


def _roll_star(rng: random.Random) -> Star:
    type_color = _weighted(rng, _STAR_DATA["weights"])
    star_type, color = type_color.split(":")
    age = _weighted(rng, _STAR_DATA["age_weights"])
    return Star(type=star_type, color=color, age=age)


def _planet_count(rng: random.Random, color: str) -> int:
    by_color = _STAR_DATA.get("planet_count_range", {}).get("by_color", {})
    lo, hi = by_color.get(color, _STAR_DATA["planet_count_range"]["default"])
    return rng.randint(lo, hi)


def _feature_count(rng: random.Random) -> int:
    weights = {int(k): float(v) for k, v in _STAR_DATA["feature_count_weights"].items()}
    return rng.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]


def _fill_template(rng: random.Random, template: str, pools: dict[str, list[str]]) -> str:
    # Standard library str.format with kwargs from picked pool entries.
    # Each placeholder is filled independently per call.
    fields = {key: rng.choice(values) for key, values in pools.items()}
    return template.format(**fields)


def _build_planet(rng: random.Random, slot: int, color: str, used_names: set[str]) -> Planet:
    bias = _STAR_DATA["planet_type_bias"].get(color, {})
    if not bias:
        bias = {pt: 1.0 for pt in _PLANET_DATA.keys() if not pt.startswith("_")}
    ptype = _weighted(rng, bias)
    cfg = _PLANET_DATA[ptype]
    pools = _PLANET_DATA["_pools"]
    for _attempt in range(20):
        template = rng.choice(cfg["name_templates"])
        name = _fill_template(rng, template, pools)
        if name not in used_names:
            used_names.add(name)
            break
    else:
        # Defensive: append the slot index to disambiguate if pools are exhausted.
        name = f"{name}-{slot}"
        used_names.add(name)
    size = rng.choice(["small", "medium", "large"])
    richness = rng.choices(["low", "medium", "high"], weights=[3, 4, 2], k=1)[0]
    descriptor = rng.choice(cfg["descriptors"])
    return Planet(
        slot_index=slot,
        name=name,
        planet_type=ptype,
        size=size,
        richness=richness,
        descriptor=descriptor,
    )


def _build_feature(rng: random.Random, slot: int, age: str, used_names: set[str]) -> Feature:
    bias = _STAR_DATA["feature_type_bias"].get(age, {})
    if not bias:
        bias = {ft: 1.0 for ft in _FEATURE_DATA.keys() if not ft.startswith("_")}
    ftype = _weighted(rng, bias)
    cfg = _FEATURE_DATA[ftype]
    pools = _FEATURE_DATA["_pools"]
    for _attempt in range(20):
        template = rng.choice(cfg["name_templates"])
        name = _fill_template(rng, template, pools)
        if name not in used_names:
            used_names.add(name)
            break
    else:
        name = f"{name} {slot}"
        used_names.add(name)
    descriptor = rng.choice(cfg["descriptors"])
    return Feature(
        slot_index=slot,
        name=name,
        feature_type=ftype,
        descriptor=descriptor,
    )


def generate(seed: int) -> SystemCharacter:
    """Pure deterministic character generation. Same seed → identical output."""
    rng = random.Random(seed)
    star = _roll_star(rng)
    n_planets = _planet_count(rng, star.color)
    used_planet_names: set[str] = set()
    planets = tuple(
        _build_planet(rng, i, star.color, used_planet_names) for i in range(n_planets)
    )
    n_features = _feature_count(rng)
    used_feature_names: set[str] = set()
    features = tuple(
        _build_feature(rng, i, star.age, used_feature_names) for i in range(n_features)
    )
    return SystemCharacter(seed=seed, star=star, planets=planets, features=features)


# ──────────── Persistence (async, via SQLAlchemy session) ────────────

async def persist_character(
    session: AsyncSession, system_id: str, character: SystemCharacter
) -> None:
    """Write character rows + update System.star_* + System.config[generator_seed].

    Idempotent: deletes any existing planet/feature rows for the system first.
    Caller is responsible for the surrounding transaction.
    """
    from db.models import (  # local import keeps engine/ tests light
        StarAge,
        StarColor,
        StarType,
        System,
        SystemFeature,
        SystemPlanet,
    )

    sys_obj = await session.get(System, system_id)
    if sys_obj is None:
        raise LookupError(f"System {system_id} not found")

    # Replace existing planet/feature rows.
    await session.execute(
        text("DELETE FROM system_planets WHERE system_id = :sid"), {"sid": system_id}
    )
    await session.execute(
        text("DELETE FROM system_features WHERE system_id = :sid"), {"sid": system_id}
    )
    for p in character.planets:
        session.add(
            SystemPlanet(
                system_id=system_id,
                slot_index=p.slot_index,
                name=p.name,
                planet_type=p.planet_type,
                size=p.size,
                richness=p.richness,
                descriptor=p.descriptor,
            )
        )
    for f in character.features:
        session.add(
            SystemFeature(
                system_id=system_id,
                slot_index=f.slot_index,
                name=f.name,
                feature_type=f.feature_type,
                descriptor=f.descriptor,
            )
        )

    sys_obj.star_type = StarType(character.star.type)
    sys_obj.star_color = StarColor(character.star.color)
    sys_obj.star_age = StarAge(character.star.age)
    cfg = dict(sys_obj.config or {})
    cfg["generator_seed"] = character.seed
    sys_obj.config = cfg


def persist_character_sync(bind, system_id: str, character: SystemCharacter) -> None:
    """Synchronous variant for the Alembic backfill. Uses raw SQL on `bind`.

    Does NOT update systems.config / star_* / flavor_text — the migration
    itself does that in one combined UPDATE after this function returns,
    because the migration also writes flavor_text from a different module.
    """
    bind.execute(
        text("DELETE FROM system_planets WHERE system_id = :sid"), {"sid": system_id}
    )
    bind.execute(
        text("DELETE FROM system_features WHERE system_id = :sid"), {"sid": system_id}
    )
    for p in character.planets:
        bind.execute(
            text(
                "INSERT INTO system_planets "
                "(system_id, slot_index, name, planet_type, size, richness, descriptor) "
                "VALUES (:sid, :i, :n, :t, :sz, :r, :d)"
            ),
            {
                "sid": system_id,
                "i": p.slot_index,
                "n": p.name,
                "t": p.planet_type,
                "sz": p.size,
                "r": p.richness,
                "d": p.descriptor,
            },
        )
    for f in character.features:
        bind.execute(
            text(
                "INSERT INTO system_features "
                "(system_id, slot_index, name, feature_type, descriptor) "
                "VALUES (:sid, :i, :n, :t, :d)"
            ),
            {
                "sid": system_id,
                "i": f.slot_index,
                "n": f.name,
                "t": f.feature_type,
                "d": f.descriptor,
            },
        )
```

- [ ] **Step 4: Clean up the test file**

In `tests/test_engine_system_generator.py`, remove the broken sync `test_generate_persist_roundtrip` and `test_generate_persist_roundtrip_REMOVED` placeholder. Keep only the async `test_persist_writes_planets_and_features` test.

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_engine_system_generator.py -v --no-cov`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/system_generator.py tests/test_engine_system_generator.py
git commit -m "feat(phase3b-1): deterministic system character procgen + persistence"
```

---

## Task 5: Lighthouse band roller — `engine/lighthouse_engine.py`

**Files:**
- Create: `engine/lighthouse_engine.py`
- Create: `tests/test_engine_lighthouse_engine.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_lighthouse_engine.py`:

```python
"""Lighthouse band roller + create_lighthouse helper."""

from __future__ import annotations

import random


def test_roll_band_returns_enum_member():
    from db.models import LighthouseBand
    from engine.lighthouse_engine import roll_band

    rng = random.Random(0)
    band = roll_band(rng)
    assert isinstance(band, LighthouseBand)


def test_roll_band_distribution():
    from engine.lighthouse_engine import roll_band

    rng = random.Random(1)
    counts = {"rim": 0, "middle": 0, "inner": 0}
    n = 5000
    for _ in range(n):
        band = roll_band(rng)
        counts[band.value] += 1
    # 70/25/5 — allow ±5pp tolerance for sample noise.
    assert 0.65 <= counts["rim"] / n <= 0.75
    assert 0.20 <= counts["middle"] / n <= 0.30
    assert 0.02 <= counts["inner"] / n <= 0.08


def test_roll_band_deterministic_given_rng_state():
    from engine.lighthouse_engine import roll_band

    rng_a = random.Random(42)
    rng_b = random.Random(42)
    seq_a = [roll_band(rng_a).value for _ in range(20)]
    seq_b = [roll_band(rng_b).value for _ in range(20)]
    assert seq_a == seq_b


async def test_create_lighthouse_persists_row(db_session, sample_system):
    from db.models import Lighthouse
    from engine.lighthouse_engine import create_lighthouse
    from sqlalchemy import select

    rng = random.Random(7)
    lh = await create_lighthouse(db_session, sample_system.channel_id, rng)
    await db_session.flush()
    found = (
        await db_session.execute(select(Lighthouse).where(Lighthouse.system_id == sample_system.channel_id))
    ).scalar_one()
    assert found.id == lh.id
    assert found.warden_id is None
    assert found.pride_score == 0
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_lighthouse_engine.py -v --no-cov`
Expected: 4 FAIL.

- [ ] **Step 3: Implement `engine/lighthouse_engine.py`**

Create `engine/lighthouse_engine.py`:

```python
"""Lighthouse-level operations.

In Phase 3b-1 this is intentionally narrow: band rolling and Lighthouse row
creation. Claim resolution (3b-2), upgrade install (3b-3), tribute and lapse
(3b-4/3b-5) extend this module in their respective sub-plans.
"""

from __future__ import annotations

import random

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Lighthouse, LighthouseBand, LighthouseState

# Spec §6.1: band weighted distribution.
_BAND_WEIGHTS: dict[LighthouseBand, float] = {
    LighthouseBand.RIM: 0.70,
    LighthouseBand.MIDDLE: 0.25,
    LighthouseBand.INNER: 0.05,
}


def roll_band(rng: random.Random) -> LighthouseBand:
    """Sample a band per the 70/25/5 weighted distribution."""
    keys = list(_BAND_WEIGHTS.keys())
    weights = [_BAND_WEIGHTS[k] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


async def create_lighthouse(
    session: AsyncSession,
    system_id: str,
    rng: random.Random,
) -> Lighthouse:
    """Create the Lighthouse row for a system. Caller owns the transaction."""
    band = roll_band(rng)
    lh = Lighthouse(
        system_id=system_id,
        band=band,
        state=LighthouseState.ACTIVE,
        pride_score=0,
    )
    session.add(lh)
    await session.flush()
    await session.refresh(lh)
    return lh
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_lighthouse_engine.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lighthouse_engine.py tests/test_engine_lighthouse_engine.py
git commit -m "feat(phase3b-1): lighthouse band roller + create_lighthouse helper"
```

---

## Task 6: System narrative seed (LLM stub) — `engine/system_narrative.py`

**Files:**
- Create: `engine/system_narrative.py`
- Create: `tests/test_engine_system_narrative.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_system_narrative.py`:

```python
"""System narrative seed — deterministic templated paragraph (LLM stub)."""

from __future__ import annotations


def _sample_character(seed: int = 1):
    from engine.system_generator import generate
    return generate(seed=seed)


def test_generate_flavor_returns_nonempty_string():
    from engine.system_narrative import generate_flavor

    text = generate_flavor(_sample_character(), sector_name="Marquee")
    assert isinstance(text, str)
    assert len(text) >= 80


def test_generate_flavor_deterministic_for_same_input():
    from engine.system_narrative import generate_flavor

    a = generate_flavor(_sample_character(seed=1), sector_name="Marquee")
    b = generate_flavor(_sample_character(seed=1), sector_name="Marquee")
    assert a == b


def test_generate_flavor_mentions_at_least_one_planet_or_feature():
    from engine.system_narrative import generate_flavor

    char = _sample_character(seed=42)
    text = generate_flavor(char, sector_name="Marquee")
    # At least one of the procedurally-named bodies should be mentioned by name.
    candidates = [p.name for p in char.planets] + [f.name for f in char.features]
    assert any(c in text for c in candidates), f"no character name in: {text!r}"


def test_generate_flavor_handles_zero_features():
    from engine.system_narrative import generate_flavor
    from engine.system_generator import SystemCharacter, Star

    char = SystemCharacter(
        seed=7,
        star=Star(type="single", color="yellow", age="mature"),
        planets=(),
        features=(),
    )
    # Edge: no planets, no features. Output should still be a sentence or two.
    text = generate_flavor(char, sector_name="Empty")
    assert isinstance(text, str) and len(text) > 0
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_system_narrative.py -v --no-cov`
Expected: 4 FAIL.

- [ ] **Step 3: Implement `engine/system_narrative.py`**

Create `engine/system_narrative.py`:

```python
"""Narrative flavor for a freshly-generated system.

In 3b-1 this is a deterministic templated paragraph — no LLM call. The
real LLM pass lands in sub-plan 3b-6 (queued via the Phase 2a scheduler,
with the same inputs and a fallback to this stub on failure). The signature
and call site here are stable; 3b-6 swaps the body, not the contract.

Spec §4.4 / §4.6: 2–4 sentences, mentions a signature detail, written in
the encyclopedic-yet-grounded voice of `docs/lore/setting.md`. The stub
hits this voice imperfectly but consistently — good enough to ship.
"""

from __future__ import annotations

import random

from engine.system_generator import SystemCharacter

_OPENERS = {
    "young": "{sector} maps {color} {type}-class system {sigil}, surveyed within living memory.",
    "mature": "{sector} maps {color} {type}-class system {sigil}; long-charted and well-flown.",
    "aging": "{sector} maps the {color} {type}-class system {sigil}; old enough to be on the older charts.",
    "dying": "{sector} maps {color} {type}-class system {sigil}; older than the charts have reckoned.",
}

_SIGNATURE_DETAIL_TEMPLATES = (
    "The signature detail is {body}: {descriptor}.",
    "What pilots remember is {body} — {descriptor}.",
    "The thing pilots tell stories about is {body}: {descriptor}.",
    "{body} is the part that lingers — {descriptor}.",
)

_PLANET_LINE_TEMPLATES = (
    "Locally there are {n} bodies of note, of which {body} is {descriptor}.",
    "Surveyed bodies number {n}; the cataloguers' note on {body} reads: {descriptor}.",
    "Of {n} mapped bodies in-system, {body} is the one navigators recommend you remember — {descriptor}.",
)

_FEATURE_LINE_TEMPLATES = (
    "Beyond the bodies, there is {feature}: {fdesc}.",
    "Beyond the planets, the chart-makers note {feature} — {fdesc}.",
    "{feature} is the other thing in this system worth a captain's attention: {fdesc}.",
)

_NO_FEATURE_LINE_TEMPLATES = (
    "The system has no charted anomaly; its bodies are its only features.",
    "Survey notes record nothing remarkable beyond the bodies themselves.",
)


def _sigil(seed: int) -> str:
    # Stable Greek-letter sigil from the seed for the system's chart designation.
    letters = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa")
    n = (seed % 9999) + 1
    return f"{letters[seed % len(letters)]}-{n}"


def generate_flavor(character: SystemCharacter, sector_name: str = "") -> str:
    """Return a 2–4 sentence flavor paragraph for the system.

    Deterministic: same character + same sector_name → same paragraph.
    """
    rng = random.Random(character.seed ^ hash(sector_name) & 0xFFFFFFFF)

    sector = sector_name.strip() or "the chart"
    sigil = _sigil(character.seed)

    opener_tpl = _OPENERS[character.star.age]
    opener = opener_tpl.format(
        sector=sector,
        color=character.star.color,
        type=character.star.type,
        sigil=sigil,
    )

    sentences: list[str] = [opener]

    if character.planets:
        body = rng.choice(character.planets)
        sentences.append(
            rng.choice(_PLANET_LINE_TEMPLATES).format(
                n=len(character.planets), body=body.name, descriptor=body.descriptor
            )
        )

    if character.features:
        feat = rng.choice(character.features)
        sentences.append(
            rng.choice(_FEATURE_LINE_TEMPLATES).format(
                feature=feat.name, fdesc=feat.descriptor
            )
        )
    elif character.planets:
        sentences.append(rng.choice(_NO_FEATURE_LINE_TEMPLATES))

    if character.planets and character.features:
        signature = rng.choice([*character.planets, *character.features])
        sentences.append(
            rng.choice(_SIGNATURE_DETAIL_TEMPLATES).format(
                body=signature.name, descriptor=signature.descriptor
            )
        )

    return " ".join(sentences)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_system_narrative.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/system_narrative.py tests/test_engine_system_narrative.py
git commit -m "feat(phase3b-1): deterministic system narrative stub (LLM hook)"
```

---

## Task 7: Activation hook — extend `_system_enable_logic`

**Files:**
- Modify: `bot/cogs/admin.py`
- Modify: `tests/test_systems_sectors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_systems_sectors.py`:

```python
async def test_system_enable_runs_procgen_and_creates_lighthouse(db_session, sample_sector):
    """Enabling a system should populate planets/features/star/Lighthouse."""
    import discord
    from sqlalchemy import select
    from unittest.mock import MagicMock, PropertyMock

    from bot.cogs.admin import _system_enable_logic
    from db.models import Lighthouse, SystemFeature, SystemPlanet

    interaction = MagicMock()
    interaction.user.guild_permissions = MagicMock()
    interaction.user.guild_permissions.manage_channels = True
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 88888888
    interaction.channel = MagicMock()
    interaction.channel.name = "veyra-hesper"

    result = await _system_enable_logic(interaction, db_session)
    assert result.success, result.message
    await db_session.flush()

    planets = (
        await db_session.execute(select(SystemPlanet).where(SystemPlanet.system_id == "88888888"))
    ).scalars().all()
    assert len(planets) >= 3

    features = (
        await db_session.execute(select(SystemFeature).where(SystemFeature.system_id == "88888888"))
    ).scalars().all()
    assert len(features) <= 3

    lh = (
        await db_session.execute(select(Lighthouse).where(Lighthouse.system_id == "88888888"))
    ).scalar_one()
    assert lh.warden_id is None
    assert lh.band.value in ("rim", "middle", "inner")


async def test_system_enable_idempotent_re_enable_after_disable(db_session, sample_sector):
    """Enable → disable → enable produces a fresh Lighthouse and new procgen."""
    from sqlalchemy import select
    from unittest.mock import MagicMock

    from bot.cogs.admin import _system_disable_logic, _system_enable_logic
    from db.models import Lighthouse, System

    interaction = MagicMock()
    interaction.user.guild_permissions = MagicMock()
    interaction.user.guild_permissions.manage_channels = True
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 99999999
    interaction.channel = MagicMock()
    interaction.channel.name = "tarsus-drift"

    r1 = await _system_enable_logic(interaction, db_session)
    assert r1.success
    await db_session.flush()
    r2 = await _system_disable_logic(interaction, db_session)
    assert r2.success
    await db_session.flush()
    r3 = await _system_enable_logic(interaction, db_session)
    assert r3.success
    await db_session.flush()

    lh = (
        await db_session.execute(select(Lighthouse).where(Lighthouse.system_id == "99999999"))
    ).scalar_one()
    assert lh.warden_id is None
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_systems_sectors.py::test_system_enable_runs_procgen_and_creates_lighthouse -v --no-cov`
Expected: FAIL — current `_system_enable_logic` doesn't create Lighthouse rows.

- [ ] **Step 3: Modify `_system_enable_logic`**

Replace the body of `_system_enable_logic` in `bot/cogs/admin.py`:

```python
async def _system_enable_logic(interaction, session) -> CommandResult:
    """Enable the current channel as a system (idempotency-safe).

    Phase 3b-1: also runs procgen, creates a Lighthouse, writes flavor text.
    """
    import random

    from engine.lighthouse_engine import create_lighthouse
    from engine.system_generator import generate, persist_character
    from engine.system_narrative import generate_flavor

    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins (manage_channels) can enable systems.")

    sec = (
        await session.execute(select(Sector).where(Sector.guild_id == str(interaction.guild_id)))
    ).scalar_one_or_none()
    if sec is None:
        return CommandResult(False, "Sector not registered. Try kicking and re-inviting the bot.")

    enabled_count = (
        await session.execute(
            select(func.count()).select_from(System).where(System.sector_id == sec.guild_id)
        )
    ).scalar_one()
    if enabled_count >= sec.system_cap:
        plural = "s" if sec.system_cap != 1 else ""
        return CommandResult(
            False,
            f"The {sec.name} can only sustain {sec.system_cap} active system{plural} "
            f"at its current influence. Disable another to relocate, or grow "
            f"the sector to expand.",
        )

    existing = (
        await session.execute(
            select(System).where(System.channel_id == str(interaction.channel_id))
        )
    ).scalar_one_or_none()
    if existing is not None:
        return CommandResult(False, "This channel is already an enabled system.")

    sys_obj = System(
        channel_id=str(interaction.channel_id),
        sector_id=sec.guild_id,
        name=interaction.channel.name,
    )
    session.add(sys_obj)
    await session.flush()

    # Phase 3b-1: deterministic character generation + Lighthouse creation.
    seed = random.SystemRandom().randint(1, 2**63 - 1)
    rng = random.Random(seed)
    character = generate(seed)
    await persist_character(session, sys_obj.channel_id, character)
    sys_obj.flavor_text = generate_flavor(character, sector_name=sec.name)
    await create_lighthouse(session, sys_obj.channel_id, rng)
    await session.flush()

    return CommandResult(
        True,
        f"#{sys_obj.name} enabled as a system. "
        f"({enabled_count + 1}/{sec.system_cap} systems active.) "
        f"A {character.star.color} {character.star.type}-class system, "
        f"{len(character.planets)} planets, {len(character.features)} features.",
    )
```

(Replace the existing `sys = ...` variable name with `sec` everywhere in the function body — the original code shadowed the `sys` module name; the rewrite uses `sec` for Sector and `sys_obj` for System.)

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_systems_sectors.py -v --no-cov`
Expected: All previously-green sector/system tests pass + the two new tests pass.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/admin.py tests/test_systems_sectors.py
git commit -m "feat(phase3b-1): /system enable runs procgen, creates Lighthouse, writes flavor"
```

---

## Task 8: `/dock` command + 24h switch cooldown

**Files:**
- Create: `bot/cogs/dock.py`
- Create: `tests/test_cog_dock.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cog_dock.py`:

```python
"""/dock command — citizenship + 24h switch cooldown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select


async def test_dock_creates_citizenship(db_session, sample_user, sample_system):
    from bot.cogs.dock import _dock_logic
    from db.models import Citizenship

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)

    r = await _dock_logic(interaction, sample_system.name, db_session)
    assert r.success, r.message

    rows = (
        await db_session.execute(
            select(Citizenship).where(Citizenship.player_id == sample_user.discord_id)
        )
    ).scalars().all()
    active = [c for c in rows if c.ended_at is None]
    assert len(active) == 1
    assert active[0].system_id == sample_system.channel_id


async def test_dock_to_unknown_system_fails(db_session, sample_user):
    from bot.cogs.dock import _dock_logic

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)

    r = await _dock_logic(interaction, "no-such-system", db_session)
    assert not r.success
    assert "not found" in r.message.lower()


async def test_dock_switch_within_24h_blocked(db_session, sample_user, sample_system, sample_system2):
    from bot.cogs.dock import _dock_logic
    from db.models import Citizenship

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)

    r1 = await _dock_logic(interaction, sample_system.name, db_session)
    assert r1.success
    await db_session.flush()

    r2 = await _dock_logic(interaction, sample_system2.name, db_session)
    assert not r2.success
    assert "cooldown" in r2.message.lower() or "24" in r2.message


async def test_dock_switch_after_24h_allowed(db_session, sample_user, sample_system, sample_system2):
    from bot.cogs.dock import _dock_logic
    from db.models import Citizenship

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)

    # Plant an active citizenship that's > 24h old.
    db_session.add(
        Citizenship(
            player_id=sample_user.discord_id,
            system_id=sample_system.channel_id,
            docked_at=datetime.now(timezone.utc) - timedelta(hours=25),
            switched_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
    )
    await db_session.flush()

    r = await _dock_logic(interaction, sample_system2.name, db_session)
    assert r.success, r.message

    rows = (
        await db_session.execute(
            select(Citizenship).where(Citizenship.player_id == sample_user.discord_id)
        )
    ).scalars().all()
    active = [c for c in rows if c.ended_at is None]
    assert len(active) == 1
    assert active[0].system_id == sample_system2.channel_id
    closed = [c for c in rows if c.ended_at is not None]
    assert len(closed) == 1
    assert closed[0].system_id == sample_system.channel_id


async def test_dock_to_already_docked_system_is_no_op(db_session, sample_user, sample_system):
    from bot.cogs.dock import _dock_logic
    from db.models import Citizenship

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)

    r1 = await _dock_logic(interaction, sample_system.name, db_session)
    await db_session.flush()
    r2 = await _dock_logic(interaction, sample_system.name, db_session)
    assert r2.success
    assert "already" in r2.message.lower()

    rows = (
        await db_session.execute(
            select(Citizenship).where(Citizenship.player_id == sample_user.discord_id)
        )
    ).scalars().all()
    active = [c for c in rows if c.ended_at is None]
    assert len(active) == 1
```

The fixture `sample_system2` is referenced — add it to `tests/conftest.py` in this task's Step 3 if missing.

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_dock.py -v --no-cov`
Expected: 5 FAIL — `bot.cogs.dock` doesn't exist.

- [ ] **Step 3: Add `sample_system2` fixture**

In `tests/conftest.py`, after the existing `sample_system` fixture:

```python
@pytest.fixture
async def sample_system2(db_session, sample_sector):
    from db.models import System

    sys = System(
        channel_id="22222222",
        sector_id=sample_sector.guild_id,
        name="tarsus-drift",
    )
    db_session.add(sys)
    await db_session.flush()
    await db_session.refresh(sys)
    return sys
```

- [ ] **Step 4: Implement `bot/cogs/dock.py`**

Create `bot/cogs/dock.py`:

```python
"""`/dock <system>` — set or switch citizenship.

Citizenship is stored as a row in `citizenships`. Switching closes the
previous active row and opens a new one; a 24h cooldown applies to the
*switch*, not to the first dock or to redocking the same system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from db.models import Citizenship, System
from db.session import async_session


SWITCH_COOLDOWN = timedelta(hours=24)


@dataclass
class CommandResult:
    success: bool
    message: str


async def _resolve_system_by_name(name: str, session) -> System | None:
    return (
        await session.execute(select(System).where(System.name == name))
    ).scalar_one_or_none()


async def _dock_logic(interaction, system_name: str, session) -> CommandResult:
    """Set or switch citizenship to <system_name>. Returns CommandResult."""
    sys_obj = await _resolve_system_by_name(system_name, session)
    if sys_obj is None:
        return CommandResult(False, f"System {system_name!r} not found.")

    player_id = str(interaction.user.id)
    active = (
        await session.execute(
            select(Citizenship)
            .where(Citizenship.player_id == player_id, Citizenship.ended_at.is_(None))
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    # No-op if already docked at this system.
    if active is not None and active.system_id == sys_obj.channel_id:
        return CommandResult(True, f"You are already docked at #{sys_obj.name}.")

    # First dock — no cooldown.
    if active is None:
        session.add(
            Citizenship(player_id=player_id, system_id=sys_obj.channel_id, docked_at=now)
        )
        await session.flush()
        return CommandResult(True, f"Docked at #{sys_obj.name}.")

    # Switch — check 24h cooldown.
    last_switch = active.switched_at or active.docked_at
    if (now - last_switch) < SWITCH_COOLDOWN:
        remaining = SWITCH_COOLDOWN - (now - last_switch)
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return CommandResult(
            False,
            f"Switch cooldown: {hours}h {minutes}m remaining since your last dock change.",
        )

    active.ended_at = now
    session.add(
        Citizenship(
            player_id=player_id,
            system_id=sys_obj.channel_id,
            docked_at=now,
            switched_at=now,
        )
    )
    await session.flush()
    return CommandResult(True, f"Docked at #{sys_obj.name}.")


class DockCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="dock", description="Become a citizen of a system.")
    @app_commands.describe(system="System to dock at")
    async def dock(self, interaction: discord.Interaction, system: str) -> None:
        async with async_session() as session, session.begin():
            result = await _dock_logic(interaction, system, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @dock.autocomplete("system")
    async def dock_autocomplete(self, interaction: discord.Interaction, current: str):
        # Suggest systems in any sector the bot is in. Cap at 25 (Discord limit).
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(System).where(System.name.ilike(f"%{current}%")).limit(25)
                )
            ).scalars().all()
        return [app_commands.Choice(name=s.name, value=s.name) for s in rows]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DockCog(bot))
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_cog_dock.py -v --no-cov`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/dock.py tests/test_cog_dock.py tests/conftest.py
git commit -m "feat(phase3b-1): /dock command + 24h switch cooldown"
```

---

## Task 9: `/lighthouse [system]` — read-only Status embed

**Files:**
- Create: `bot/cogs/lighthouse.py`
- Create: `tests/test_cog_lighthouse.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cog_lighthouse.py`:

```python
"""/lighthouse [system] — Phase 3b-1 read-only Status embed."""

from __future__ import annotations

from unittest.mock import MagicMock


async def test_lighthouse_default_to_current_channel(db_session, sample_system_with_lighthouse):
    from bot.cogs.lighthouse import _lighthouse_logic

    interaction = MagicMock()
    interaction.channel_id = int(sample_system_with_lighthouse.channel_id)

    result = await _lighthouse_logic(interaction, system_name=None, session=db_session)
    assert result.success
    assert sample_system_with_lighthouse.name in result.message
    assert "rim" in result.message.lower() or "middle" in result.message.lower() or "inner" in result.message.lower()


async def test_lighthouse_explicit_system(db_session, sample_system_with_lighthouse):
    from bot.cogs.lighthouse import _lighthouse_logic

    interaction = MagicMock()
    interaction.channel_id = 0  # not a system

    result = await _lighthouse_logic(
        interaction, system_name=sample_system_with_lighthouse.name, session=db_session
    )
    assert result.success
    assert "Warden" in result.message
    assert "unclaimed" in result.message.lower()


async def test_lighthouse_no_system_in_channel_no_arg_fails(db_session):
    from bot.cogs.lighthouse import _lighthouse_logic

    interaction = MagicMock()
    interaction.channel_id = 0

    result = await _lighthouse_logic(interaction, system_name=None, session=db_session)
    assert not result.success


async def test_lighthouse_unknown_system_fails(db_session):
    from bot.cogs.lighthouse import _lighthouse_logic

    interaction = MagicMock()
    interaction.channel_id = 0

    result = await _lighthouse_logic(interaction, system_name="no-such-system", session=db_session)
    assert not result.success
```

The fixture `sample_system_with_lighthouse` is referenced — add it to `tests/conftest.py` in Step 3.

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_lighthouse.py -v --no-cov`
Expected: 4 FAIL.

- [ ] **Step 3: Add fixture**

In `tests/conftest.py`:

```python
@pytest.fixture
async def sample_system_with_lighthouse(db_session, sample_system):
    """A system that already has a Lighthouse row + procgen data attached.

    Useful for /lighthouse and /system info tests in 3b-1.
    """
    import random

    from engine.lighthouse_engine import create_lighthouse
    from engine.system_generator import generate, persist_character

    seed = 31415
    rng = random.Random(seed)
    character = generate(seed)
    await persist_character(db_session, sample_system.channel_id, character)
    await create_lighthouse(db_session, sample_system.channel_id, rng)
    await db_session.flush()
    await db_session.refresh(sample_system)
    return sample_system
```

- [ ] **Step 4: Implement `bot/cogs/lighthouse.py`**

Create `bot/cogs/lighthouse.py`:

```python
"""`/lighthouse [system]` — read-only Lighthouse Status surface (Phase 3b-1).

Phase 3b-2..5 will replace the static text response with a tabbed
DynamicItem view (Status / Upgrades / Flares / Tribute / Vacation).
For 3b-1 we ship Status only as a plain message so /lighthouse does
something meaningful from day one.
"""

from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from db.models import Lighthouse, System, User
from db.session import async_session


@dataclass
class CommandResult:
    success: bool
    message: str


def _band_descriptor(band: str) -> str:
    return {"rim": "Rim (3 slots)", "middle": "Middle (5 slots)", "inner": "Inner (7 slots)"}[band]


async def _resolve_target_system(interaction, system_name: str | None, session) -> System | None:
    if system_name:
        return (
            await session.execute(select(System).where(System.name == system_name))
        ).scalar_one_or_none()
    return (
        await session.execute(select(System).where(System.channel_id == str(interaction.channel_id)))
    ).scalar_one_or_none()


async def _lighthouse_logic(interaction, system_name: str | None, session) -> CommandResult:
    sys_obj = await _resolve_target_system(interaction, system_name, session)
    if sys_obj is None:
        if system_name is None:
            return CommandResult(
                False,
                "Run this in a system channel, or pass a system name: `/lighthouse <system>`.",
            )
        return CommandResult(False, f"System {system_name!r} not found.")

    lh = (
        await session.execute(select(Lighthouse).where(Lighthouse.system_id == sys_obj.channel_id))
    ).scalar_one_or_none()
    if lh is None:
        return CommandResult(
            False,
            f"#{sys_obj.name} has no Lighthouse on record. Try `/system disable` and `/system enable` "
            "to repair.",
        )

    if lh.warden_id is None:
        warden = "unclaimed"
    else:
        u = await session.get(User, lh.warden_id)
        warden = u.username if u else f"<unknown:{lh.warden_id}>"

    star_line = (
        f"{(sys_obj.star_color or 'unknown').title()} "
        f"{(sys_obj.star_type or 'unknown').title()}-class star, "
        f"{(sys_obj.star_age or 'unknown')}"
    )

    msg = (
        f"**Lighthouse — #{sys_obj.name}**\n"
        f"{sys_obj.flavor_text or '(no flavor on record)'}\n\n"
        f"Star: {star_line}\n"
        f"Band: {_band_descriptor(lh.band.value)}\n"
        f"State: {lh.state.value}\n"
        f"Warden: {warden}\n"
        f"Pride: {lh.pride_score}\n"
        f"Slots: 0 occupied (upgrades land in Phase 3b-3)\n"
    )
    return CommandResult(True, msg)


class LighthouseCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="lighthouse",
        description="Show the Lighthouse status of a system (defaults to this channel).",
    )
    @app_commands.describe(system="Optional system name; defaults to this channel.")
    async def lighthouse(
        self, interaction: discord.Interaction, system: str | None = None
    ) -> None:
        async with async_session() as session:
            result = await _lighthouse_logic(interaction, system, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @lighthouse.autocomplete("system")
    async def lighthouse_autocomplete(self, interaction: discord.Interaction, current: str):
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(System).where(System.name.ilike(f"%{current}%")).limit(25)
                )
            ).scalars().all()
        return [app_commands.Choice(name=s.name, value=s.name) for s in rows]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LighthouseCog(bot))
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_cog_lighthouse.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/lighthouse.py tests/test_cog_lighthouse.py tests/conftest.py
git commit -m "feat(phase3b-1): /lighthouse read-only Status surface"
```

---

## Task 10: Extend `/system info` to show character + Lighthouse

**Files:**
- Modify: `bot/cogs/admin.py`
- Modify: `tests/test_systems_sectors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_systems_sectors.py`:

```python
async def test_sector_info_includes_system_character(db_session, sample_sector, sample_system_with_lighthouse):
    from bot.cogs.admin import _sector_info_logic
    from unittest.mock import MagicMock

    interaction = MagicMock()
    interaction.guild_id = int(sample_sector.guild_id)

    r = await _sector_info_logic(interaction, db_session)
    assert r.success
    # Sector info should now also show the per-system band/star.
    assert "rim" in r.message.lower() or "middle" in r.message.lower() or "inner" in r.message.lower()
    assert "star" in r.message.lower()
```

- [ ] **Step 2: Run, confirm fails**

Run the new test — expected FAIL (current `_sector_info_logic` doesn't render band/star).

- [ ] **Step 3: Modify `_sector_info_logic`**

In `bot/cogs/admin.py`, replace `_sector_info_logic`:

```python
async def _sector_info_logic(interaction, session) -> CommandResult:
    """Return a formatted summary of this guild's sector + Lighthouse status."""
    from db.models import Lighthouse

    sec = (
        await session.execute(select(Sector).where(Sector.guild_id == str(interaction.guild_id)))
    ).scalar_one_or_none()
    if sec is None:
        return CommandResult(False, "Sector not registered.")

    systems = (
        (await session.execute(select(System).where(System.sector_id == sec.guild_id)))
        .scalars()
        .all()
    )
    if not systems:
        return CommandResult(
            True,
            f"**{sec.name}**\n"
            f"{sec.flavor_text or '(no flavor set)'}\n\n"
            f"Capacity: 0/{sec.system_cap} systems\n"
            f"Active systems:\n  (none enabled)",
        )

    # Bulk-fetch Lighthouse rows for all systems.
    lhs = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.system_id.in_([s.channel_id for s in systems]))
        )
    ).scalars().all()
    by_system = {lh.system_id: lh for lh in lhs}

    lines: list[str] = []
    for s in systems:
        lh = by_system.get(s.channel_id)
        band = lh.band.value if lh else "?"
        star = (
            f"{(s.star_color or '?').title()} {(s.star_type or '?').title()}-class star"
        )
        warden_part = ""
        if lh and lh.warden_id:
            warden_part = " · warden held"
        elif lh:
            warden_part = " · unclaimed"
        lines.append(f"  • #{s.name} — {band} band, {star}{warden_part}")
    system_lines = "\n".join(lines)

    msg = (
        f"**{sec.name}**\n"
        f"{sec.flavor_text or '(no flavor set)'}\n\n"
        f"Capacity: {len(systems)}/{sec.system_cap} systems\n"
        f"Active systems:\n{system_lines}"
    )
    return CommandResult(True, msg)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_systems_sectors.py -v --no-cov`
Expected: All previously-green tests + the new test pass.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/admin.py tests/test_systems_sectors.py
git commit -m "feat(phase3b-1): /system info renders band/star/warden per system"
```

---

## Task 11: Register cogs in `bot/main.py`

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1: Verify the load order**

The cogs should load *after* `bot.cogs.admin` (which owns `/system enable`) so that any startup event tied to the new cogs sees a stable admin tree, but order across the existing list isn't strictly required since each cog defines its own command tree leaf.

- [ ] **Step 2: Modify `setup_hook`**

In `bot/main.py`, in `Dare2DriveBot.setup_hook`, extend the `cog_modules` list:

```python
        cog_modules = [
            "bot.cogs.tutorial",
            "bot.cogs.cards",
            "bot.cogs.hangar",
            "bot.cogs.hiring",
            "bot.cogs.race",
            "bot.cogs.market",
            "bot.cogs.admin",
            "bot.cogs.fleet",
            "bot.cogs.expeditions",  # Phase 2b — gated by settings.EXPEDITIONS_ENABLED
            "bot.cogs.dock",         # Phase 3b-1
            "bot.cogs.lighthouse",   # Phase 3b-1
        ]
```

- [ ] **Step 3: Run smoke test**

Run: `pytest tests/test_bot_notifications.py tests/test_systems_sectors.py -v --no-cov`
Expected: All pass — bot import / cog load doesn't crash. (If the project has a dedicated bot-load smoke test, run that too.)

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "feat(phase3b-1): register dock and lighthouse cogs at startup"
```

---

## Task 12: System gating — allow `/dock` and `/lighthouse` universe-wide

**Files:**
- Modify: `bot/system_gating.py`
- Modify: `tests/test_system_gating.py`

- [ ] **Step 1: Decide gating policy**

`/dock` and `/lighthouse` are universe-wide commands per the spec (§5.1: "The command can be issued from any channel — docking is a player-level state, not channel-bound."). They must NOT require the executing channel to be a system. This matches the existing universe-wide policy from MEMORY.md ("system gating universal" / "system gating policy").

- [ ] **Step 2: Add to allow list**

In `bot/system_gating.py`, in whichever data structure the universe-wide allow list lives, add:

```python
UNIVERSE_WIDE_COMMANDS = {
    # ... existing entries ...
    "dock",
    "lighthouse",
}
```

(If the gating module reads from a different structure — e.g. a per-channel-type registry — match that pattern instead. Read the file first; the spec name above is a placeholder for whatever the actual constant is.)

- [ ] **Step 3: Add a test**

In `tests/test_system_gating.py`:

```python
def test_dock_is_universe_wide():
    from bot.system_gating import UNIVERSE_WIDE_COMMANDS  # or whatever the real export is

    assert "dock" in UNIVERSE_WIDE_COMMANDS
    assert "lighthouse" in UNIVERSE_WIDE_COMMANDS
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_system_gating.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/system_gating.py tests/test_system_gating.py
git commit -m "feat(phase3b-1): /dock and /lighthouse are universe-wide commands"
```

---

## Task 13: Scenario test — full activation + dock + view flow

**Files:**
- Create: `tests/test_scenarios/test_system_activation_flow.py`

- [ ] **Step 1: Write the scenario test**

Create `tests/test_scenarios/test_system_activation_flow.py`:

```python
"""End-to-end: enable a system → procgen + Lighthouse exist → dock → render views."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import select


async def test_full_activation_and_dock_flow(db_session, sample_sector, sample_user):
    from bot.cogs.admin import _sector_info_logic, _system_enable_logic
    from bot.cogs.dock import _dock_logic
    from bot.cogs.lighthouse import _lighthouse_logic
    from db.models import Citizenship, Lighthouse, System, SystemFeature, SystemPlanet

    # 1. Enable a new system.
    enable_int = MagicMock()
    enable_int.user.guild_permissions = MagicMock()
    enable_int.user.guild_permissions.manage_channels = True
    enable_int.guild_id = int(sample_sector.guild_id)
    enable_int.channel_id = 12121212
    enable_int.channel = MagicMock()
    enable_int.channel.name = "iolan-reach"

    r = await _system_enable_logic(enable_int, db_session)
    assert r.success
    await db_session.flush()

    # 2. Verify procgen wrote planets, features, star fields, Lighthouse.
    sys_obj = (
        await db_session.execute(select(System).where(System.channel_id == "12121212"))
    ).scalar_one()
    assert sys_obj.star_type is not None
    assert sys_obj.star_color is not None
    assert sys_obj.star_age is not None
    assert sys_obj.flavor_text and len(sys_obj.flavor_text) > 50

    planets = (
        await db_session.execute(select(SystemPlanet).where(SystemPlanet.system_id == "12121212"))
    ).scalars().all()
    assert 3 <= len(planets) <= 7
    lh = (
        await db_session.execute(select(Lighthouse).where(Lighthouse.system_id == "12121212"))
    ).scalar_one()
    assert lh.warden_id is None

    # 3. /dock to it.
    dock_int = MagicMock()
    dock_int.user.id = int(sample_user.discord_id)
    r = await _dock_logic(dock_int, "iolan-reach", db_session)
    assert r.success, r.message
    await db_session.flush()
    citz = (
        await db_session.execute(
            select(Citizenship)
            .where(Citizenship.player_id == sample_user.discord_id, Citizenship.ended_at.is_(None))
        )
    ).scalar_one()
    assert citz.system_id == "12121212"

    # 4. /lighthouse — read-only Status renders.
    lh_int = MagicMock()
    lh_int.channel_id = 12121212
    r = await _lighthouse_logic(lh_int, system_name=None, session=db_session)
    assert r.success
    assert "iolan-reach" in r.message
    assert "Pride: 0" in r.message

    # 5. /system info — sector summary now mentions band + star.
    info_int = MagicMock()
    info_int.guild_id = int(sample_sector.guild_id)
    r = await _sector_info_logic(info_int, db_session)
    assert r.success
    assert "iolan-reach" in r.message
    assert "band" in r.message.lower()
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_scenarios/test_system_activation_flow.py -v --no-cov`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scenarios/test_system_activation_flow.py
git commit -m "test(phase3b-1): scenario — activation + dock + view flow"
```

---

## Task 14: Backfill verification — migration on a populated DB

**Files:**
- Modify: `tests/test_phase3b_migration.py`

- [ ] **Step 1: Add a backfill test**

The existing migration tests in Task 1 verify schema. This task adds a test that exercises the data backfill path against a DB that has pre-existing System rows.

Add to `tests/test_phase3b_migration.py`:

```python
async def test_backfill_creates_lighthouse_for_pre_existing_system(db_session, sample_sector):
    """A System inserted before 3b-1 must end up with a Lighthouse + planets after backfill.

    We simulate this by manually inserting a System row that mimics a 'pre-3b'
    state (no star_*, empty config), then re-running the backfill helper.
    """
    import json
    from sqlalchemy import select, text

    from db.migrations.versions.zzz_phase3b_foundation_helpers import _retro_backfill_one
    from db.models import Lighthouse, SystemPlanet

    await db_session.execute(
        text(
            "INSERT INTO systems (channel_id, sector_id, name, config) "
            "VALUES (:cid, :sid, :n, :cfg)"
        ),
        {
            "cid": "55555555",
            "sid": sample_sector.guild_id,
            "n": "marrow-reach",
            "cfg": json.dumps({}),
        },
    )
    await db_session.flush()
    # Backfill exists on the migration module; we extract a small helper for tests.
    bind = await db_session.connection()
    _retro_backfill_one(bind.sync_connection, "55555555", sample_sector.name)
    await db_session.flush()

    planets = (
        await db_session.execute(select(SystemPlanet).where(SystemPlanet.system_id == "55555555"))
    ).scalars().all()
    assert len(planets) >= 3

    lh = (
        await db_session.execute(select(Lighthouse).where(Lighthouse.system_id == "55555555"))
    ).scalar_one()
    assert lh is not None
```

- [ ] **Step 2: Refactor the backfill helper out of the migration**

The migration in Task 1 has `_backfill_existing_systems` as a private function. Extract a per-row helper so tests can exercise it without running the whole migration:

In `db/migrations/versions/0006_phase3b_foundation.py`, replace the `_backfill_existing_systems` body with:

```python
def _retro_backfill_one(bind, channel_id: str, sector_name: str = "") -> None:
    import json
    import random as _random

    from engine.lighthouse_engine import roll_band
    from engine.system_generator import generate, persist_character_sync
    from engine.system_narrative import generate_flavor

    config_row = bind.execute(
        sa.text("SELECT config FROM systems WHERE channel_id = :cid"), {"cid": channel_id}
    ).scalar()
    cfg = config_row if isinstance(config_row, dict) else (json.loads(config_row) if config_row else {})
    if cfg.get("generator_seed") is not None:
        return

    seed = _random.SystemRandom().randint(1, 2**63 - 1)
    cfg["generator_seed"] = seed
    rng = _random.Random(seed)
    character = generate(seed)
    persist_character_sync(bind, channel_id, character)

    band = roll_band(rng)
    bind.execute(
        sa.text(
            "INSERT INTO lighthouses (system_id, band, state, pride_score) "
            "VALUES (:sid, :band, 'active', 0)"
        ),
        {"sid": channel_id, "band": band.value},
    )

    flavor = generate_flavor(character, sector_name=sector_name)
    bind.execute(
        sa.text(
            "UPDATE systems SET config = :cfg, flavor_text = :flav, "
            "star_type = :st, star_color = :sc, star_age = :sa "
            "WHERE channel_id = :cid"
        ),
        {
            "cfg": json.dumps(cfg),
            "flav": flavor,
            "st": character.star.type,
            "sc": character.star.color,
            "sa": character.star.age,
            "cid": channel_id,
        },
    )


def _backfill_existing_systems(bind) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT s.channel_id, COALESCE(sec.name, '') "
            "FROM systems s LEFT JOIN sectors sec ON s.sector_id = sec.guild_id"
        )
    ).fetchall()
    for channel_id, sector_name in rows:
        _retro_backfill_one(bind, channel_id, sector_name)
```

Update the import in the test from `db.migrations.versions.zzz_phase3b_foundation_helpers` to `db.migrations.versions._0006_phase3b_foundation_helpers` if you choose to factor the helper into its own module — or, simpler, re-export it from the migration module:

```python
# In test:
from db.migrations.versions._import_helper import retro_backfill_one
```

The simplest path that doesn't hit Alembic's "no module named" rule for revision files starting with digits is to use Python's importlib in the test:

```python
import importlib
mod = importlib.import_module("db.migrations.versions.0006_phase3b_foundation".replace("0006", "_0006") if False else "db.migrations.versions.0006_phase3b_foundation")
mod._retro_backfill_one(bind.sync_connection, "55555555", sample_sector.name)
```

Or — cleaner — move the helper to `db/migrations/_phase3b_helpers.py` and import from both the migration and the test:

Create `db/migrations/_phase3b_helpers.py`:

```python
"""Helpers for the 0006_phase3b_foundation migration. Importable from tests."""

from __future__ import annotations

import json
import random as _random

import sqlalchemy as sa


def retro_backfill_one(bind, channel_id: str, sector_name: str = "") -> None:
    from engine.lighthouse_engine import roll_band
    from engine.system_generator import generate, persist_character_sync
    from engine.system_narrative import generate_flavor

    config_row = bind.execute(
        sa.text("SELECT config FROM systems WHERE channel_id = :cid"), {"cid": channel_id}
    ).scalar()
    cfg = config_row if isinstance(config_row, dict) else (json.loads(config_row) if config_row else {})
    if cfg.get("generator_seed") is not None:
        return

    seed = _random.SystemRandom().randint(1, 2**63 - 1)
    cfg["generator_seed"] = seed
    rng = _random.Random(seed)
    character = generate(seed)
    persist_character_sync(bind, channel_id, character)

    band = roll_band(rng)
    bind.execute(
        sa.text(
            "INSERT INTO lighthouses (system_id, band, state, pride_score) "
            "VALUES (:sid, :band, 'active', 0)"
        ),
        {"sid": channel_id, "band": band.value},
    )

    flavor = generate_flavor(character, sector_name=sector_name)
    bind.execute(
        sa.text(
            "UPDATE systems SET config = :cfg, flavor_text = :flav, "
            "star_type = :st, star_color = :sc, star_age = :sa "
            "WHERE channel_id = :cid"
        ),
        {
            "cfg": json.dumps(cfg),
            "flav": flavor,
            "st": character.star.type,
            "sc": character.star.color,
            "sa": character.star.age,
            "cid": channel_id,
        },
    )
```

Then have the migration's `_backfill_existing_systems` simply call the shared helper:

```python
def _backfill_existing_systems(bind) -> None:
    from db.migrations._phase3b_helpers import retro_backfill_one

    rows = bind.execute(
        sa.text(
            "SELECT s.channel_id, COALESCE(sec.name, '') "
            "FROM systems s LEFT JOIN sectors sec ON s.sector_id = sec.guild_id"
        )
    ).fetchall()
    for channel_id, sector_name in rows:
        retro_backfill_one(bind, channel_id, sector_name)
```

And update the test to import from `db.migrations._phase3b_helpers`:

```python
from db.migrations._phase3b_helpers import retro_backfill_one
```

- [ ] **Step 3: Run, confirm passes**

Run: `pytest tests/test_phase3b_migration.py -v --no-cov`
Expected: All migration tests pass, including the new backfill test.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/versions/0006_phase3b_foundation.py db/migrations/_phase3b_helpers.py tests/test_phase3b_migration.py
git commit -m "feat(phase3b-1): factor backfill helper, add backfill scenario test"
```

---

## Task 15: Authoring documentation

**Files:**
- Create: `docs/authoring/system_character.md`

- [ ] **Step 1: Write the doc**

Create `docs/authoring/system_character.md`:

```markdown
# Authoring: System Character (Phase 3b)

This doc explains how new systems get their star, planets, features, and flavor
paragraph at activation time, and how to edit the data files without
breaking determinism for existing systems.

## What gets generated and when

When `/system enable` runs in a channel:

1. A `generator_seed` is rolled and stored in `systems.config["generator_seed"]`.
2. `engine.system_generator.generate(seed)` produces a `SystemCharacter`
   (star + planets + features) — pure function, no DB.
3. `persist_character` writes `system_planets` + `system_features` rows and
   sets `systems.star_type`/`star_color`/`star_age`.
4. `engine.lighthouse_engine.create_lighthouse` rolls a band (70/25/5 rim /
   middle / inner) and inserts the `Lighthouse` row.
5. `engine.system_narrative.generate_flavor` writes the 2–4 sentence flavor
   paragraph into `systems.flavor_text`.

## Determinism contract

Same `generator_seed` ⇒ identical structural data (star, planet count, names,
descriptors, feature placement). Editing the data files (`star_types.yaml`,
`planet_types.yaml`, `feature_types.yaml`) **breaks this for existing
systems** — the next call to `generate()` for an old seed will produce
different output. We accept this: the data files are author-tunable, not a
versioned interface. If you need stable systems across an edit, regenerate
their seeds (effectively "this system is being re-charted").

## Editing the data files

- `data/system/star_types.yaml` — type/color combo weights, age weights,
  per-color planet count ranges, planet-type bias by star color, feature-type
  bias by star age. Add new combos by extending `weights`.
- `data/system/planet_types.yaml` — name templates and descriptor pools per
  planet type. Each type needs ≥ 5 name templates and ≥ 3 descriptors —
  `tests/test_system_data_files.py` enforces this.
- `data/system/feature_types.yaml` — same shape, for the 5 feature types.
  ≥ 3 name templates and ≥ 3 descriptors required per type.
- `_pools` blocks at the bottom of the planet/feature files contain shared
  word lists used in name templates (`{prefix}`, `{noun}`, `{adj}`, etc.).

## The narrative paragraph

`engine/system_narrative.py::generate_flavor` is currently a deterministic
templated paragraph — no LLM call. The function signature and call site are
stable; a future Phase will swap in a real LLM call queued through the
Phase 2a scheduler with a fallback to this stub on failure. Keep template
phrasings in voice with `docs/lore/setting.md` (encyclopedic-yet-grounded,
captain-perspective, dry).

## How to test changes locally

```
pytest tests/test_system_data_files.py tests/test_engine_system_generator.py \
  tests/test_engine_system_narrative.py -v
```

For a manual smoke test, drop into a Python shell:

```python
from engine.system_generator import generate
from engine.system_narrative import generate_flavor

c = generate(seed=12345)
print(generate_flavor(c, sector_name="Marquee"))
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/authoring/system_character.md
git commit -m "docs(phase3b-1): authoring guide for system character data"
```

---

## Task 16: Final integration smoke

**Files:** none — verification only.

- [ ] **Step 1: Run the full suite**

Run: `pytest --no-cov -q`
Expected: All tests green.

- [ ] **Step 2: Round-trip the migration**

Run:
```
DATABASE_URL=postgresql://dare2drive:dare2drive@localhost:5432/dare2drive python -m alembic downgrade -1
DATABASE_URL=postgresql://dare2drive:dare2drive@localhost:5432/dare2drive python -m alembic upgrade head
```
Expected: both succeed; `pytest --no-cov -q` still green afterward.

- [ ] **Step 3: Local manual verification**

Bring up a dev bot and run, in a fresh channel:
- `/system enable` — confirm message includes "<color> <type>-class system, N planets, M features"
- `/system info` — confirm per-system band + star line render
- `/lighthouse` — confirm Status shows band, state=active, Warden=unclaimed, Pride=0
- `/dock <system>` — confirm "Docked at #<system>" message; verify in DB that a `citizenships` row was created
- Try `/dock <other_system>` immediately — confirm "Switch cooldown: ..." rejection

If anything renders wrong, fix it before moving on; type-checked and unit-tested code is not the same as feature-correct.

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin <branch>
gh pr create --title "Phase 3b-1: Lighthouses foundation (system character + citizenship)" --body "$(cat <<'EOF'
## Summary
- Adds the schema, deterministic procgen, citizenship table, and read-only `/lighthouse` view that 3b-2..5 depend on.
- `/system enable` now generates star + planets + features, writes a flavor paragraph, and creates an unclaimed `Lighthouse` row.
- `/dock <system>` lets a player become a citizen with a 24h switch cooldown.
- `/system info` and `/lighthouse [system]` render the new state read-only.
- LLM narrative seed is **stubbed** in this PR (deterministic templated paragraph) — see plan §Open Questions for context.

## Test plan
- [x] All previously-green tests stay green (`pytest --no-cov -q`)
- [x] Migration round-trips (`alembic downgrade -1 && alembic upgrade head`)
- [x] New scenario test: enable → procgen → dock → view flow
- [ ] Manual: dev bot, run /system enable + /system info + /lighthouse + /dock as described in plan Task 16

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Open Questions

1. **LLM seed pass — DECIDED.** 3b-1 ships a deterministic stub; the real LLM call lands in a dedicated follow-on plan **3b-6 (runtime LLM narrative)** scheduled to run *after* 3b-5. By that point we'll have flares, donations, and pride scoreboards using the system-character data, so we'll know exactly what the prompt needs to convey before we write it. 3b-6 will add the Anthropic SDK dep, the prompt template, queue-based dispatch via the Phase 2a scheduler, retry/timeout handling, and the fallback-to-stub path on failure. The stub stays in place after 3b-6 ships as the failure-mode default.

2. **Star type taxonomy.** Spec §4.1 says "≈ 60 total combos for MVP." 3b-1 ships ~30 (5 colors × 3 type prefixes minus "exotic-everything" weighting). Easy to grow by editing `star_types.yaml`. Worth tuning during playtest.

3. **`flavor_text` column type.** Migrated to `Text` from `String(500)` — paragraph length isn't artificially bounded. No callers downstream rely on the length cap.

4. **Existing `tests/conftest.py::sample_system` fixture.** This plan adds `sample_system_with_lighthouse` and `sample_system2` but does NOT change `sample_system`. If a downstream plan needs an "always populated" baseline fixture, add it there rather than retrofitting `sample_system` (would silently change behavior across many existing tests).

---

## Spec coverage check (self-review)

| Spec section | Covered by | Notes |
|---|---|---|
| §4.1 Star | Tasks 3, 4 | star_types.yaml + `_roll_star` |
| §4.2 Planets | Tasks 3, 4 | planet_types.yaml + `_build_planet` |
| §4.3 Features | Tasks 3, 4 | feature_types.yaml + `_build_feature` |
| §4.4 Narrative | Task 6 | Stub, see Open Question 1 |
| §4.5 Determinism | Task 4 | tests cover seed determinism |
| §4.6 Activation flow | Task 7 | Step 3 modifies `_system_enable_logic` |
| §4.7 Storage shape | Tasks 1, 2 | New tables + System extensions |
| §5.1 The dock verb | Task 8 | `/dock` cog + 24h cooldown |
| §5.2 Citizenship grants | DEFERRED | Buffs land in 3b-3, flare priority in 3b-4 |
| §5.3 Warden coupling | DEFERRED to 3b-2 | Auto-dock on claim is a 3b-2 task |
| §5.4 Forward-compat | Task 1 | Citizenship is a row, not a User column |
| §5.5 Citizenship NOT a gate | Task 12 | `/dock` is universe-wide |
| §6.1 Lighthouse one per system | Task 1 | UNIQUE on lighthouses.system_id |
| §6.2 State machine | Tasks 1, 2 | Enum + default `active`; 3b-1 only writes `active` |
| §6.3 Ownership/lapse | Tasks 1, 2 | Columns exist, lapse logic ships in 3b-5 |
| §6.4 Slot allocation | Task 1 | `lighthouse_upgrades` table is composite-key ready |
| §6.5 What depends on Lighthouse | DEFERRED | Buffs/flares/donations land in 3b-3..5 |
| §15 Data model (subset) | Task 1 | All tables touched in this plan are created |
| §16.1 `/dock`, read-only `/lighthouse`, `/system info` | Tasks 8, 9, 10 | |
| §19 Verification (subset) | Task 13 | Scenario covers §19.1, §19.2 partially |

Sections deferred to later sub-plans are listed in the plan header.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-02-phase-3b-1-foundation.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

- If Subagent-Driven: REQUIRED SUB-SKILL is `superpowers:subagent-driven-development`.
- If Inline: REQUIRED SUB-SKILL is `superpowers:executing-plans`.

---

## Next sub-plans (not in this file)

- `2026-05-02-phase-3b-2-claim.md` — Wardenship claim contract (§7)
- `2026-05-02-phase-3b-3-donations.md` — Upgrade goals + donations + citizen buffs + passive tribute (§8, §9, §10.1, §11)
- `2026-05-02-phase-3b-4-flares.md` — Beacon Flares + Pride + activity-cut tribute (§12, §13, §10.1)
- `2026-05-02-phase-3b-5-lapse.md` — Lapse, vacation, tribute spending, abdication (§10.3, §14)
- `2026-05-02-phase-3b-6-llm-narrative.md` — Replace the deterministic flavor stub with a real LLM call (Anthropic SDK + prompt template + Phase 2a scheduler dispatch + retry/timeout + fallback-to-stub on failure). Runs *after* 3b-5 so the prompt can be informed by what flares/donations/pride actually surface.
