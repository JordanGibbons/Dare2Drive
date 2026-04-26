# Phase 2b — Expeditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship multi-hour expeditions with mid-flight events on top of the Phase 2a scheduler. Players DM-reachable from anywhere, choices gated by archetype + stat-modified, asymmetric risk envelope (no permadeath), single-ship-per-expedition with per-user concurrency cap (default 2). Authorability of new templates by external developers and LLM sessions is a first-class deliverable.

**Architecture:** Two new tables (`expeditions`, `expedition_crew_assignments`) plus column extensions on `builds` (current_activity) and `crew_members` (injured_until). Engine resolves scenes via a single `resolve_scene` function shared between player-driven and auto-resolve paths. Four new `JobType`s (`EXPEDITION_EVENT`, `EXPEDITION_AUTO_RESOLVE`, `EXPEDITION_RESOLVE`, `EXPEDITION_COMPLETE`) plug into the Phase 2a scheduler-worker. Player responses flow through buttons (persistent view) OR `/expedition respond` slash command, both racing the auto-resolve scheduled job via the same atomic `WHERE state = PENDING` UPDATE that Phase 2a's `/training cancel` uses. Templates are YAML files validated by a JSON Schema + semantic checker run as a CI gate. v1 ships two templates (one scripted, one rolled) doubling as authoring exemplars. Crew display commands (`/crew`, `/crew_inspect`) are refreshed to surface the new states.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, redis-py 5.x async client, discord.py 2.x, PyYAML, jsonschema, pytest + pytest-asyncio, Prometheus client, OpenTelemetry. Two new top-level dependencies: `pyyaml` and `jsonschema` (added to `pyproject.toml` in Task 5).

**Spec:** [docs/superpowers/specs/2026-04-26-phase-2b-expeditions-design.md](../specs/2026-04-26-phase-2b-expeditions-design.md)

**Dev loop:** All tests run via `pytest` from the repo root. The `db_session` fixture in `tests/conftest.py` opens a per-test savepoint against the Docker Postgres (localhost:5432). `docker-compose up db redis` must be running for DB-backed and Redis-backed tests. Worker integration tests use a fresh process spawned via `subprocess` against the same Postgres.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0004_phase2b_expeditions.py` | Alembic migration: 2 new tables + 2 column extensions + 3 enum extensions + 1 new enum |
| `data/expeditions/schema.json` | JSON Schema for expedition templates (discriminated `oneOf` on `kind`) |
| `data/expeditions/marquee_run.yaml` | v1 scripted template — the marquee narrative |
| `data/expeditions/outer_marker_patrol.yaml` | v1 rolled template — generic patrol with 8-event pool |
| `engine/expedition_template.py` | Template loader, JSON Schema + semantic validator, CLI entry point |
| `engine/expedition_engine.py` | `resolve_scene`, stat lookup, outcome application, closing variant selection |
| `engine/expedition_concurrency.py` | `get_max_expeditions(user)` and per-user/per-build concurrency check helpers |
| `engine/effect_registry.py` | Closed-vocabulary effect-op registry consumed by the engine + validator + doc generator |
| `engine/stat_namespace.py` | Stat namespace registry consumed by the engine + validator + doc generator |
| `scheduler/jobs/expedition_event.py` | `EXPEDITION_EVENT` handler (scene fires → DM + queue auto-resolve) |
| `scheduler/jobs/expedition_auto_resolve.py` | `EXPEDITION_AUTO_RESOLVE` handler (timeout → enqueue resolve with default choice) |
| `scheduler/jobs/expedition_resolve.py` | `EXPEDITION_RESOLVE` handler (compute + apply outcome → DM resolution) |
| `scheduler/jobs/expedition_complete.py` | `EXPEDITION_COMPLETE` handler (closing variant → unlock build/crew) |
| `bot/cogs/expeditions.py` | `/expedition start/status/respond` slash commands + persistent button view |
| `docs/authoring/expeditions.md` | Self-contained authoring guide for human + LLM authors |
| `scripts/build_authoring_docs.py` | Regenerates the stat namespace + effect vocabulary tables in the authoring guide; CI-gated for drift |
| `tests/test_phase2b_models.py` | Schema-level tests for new models + enums |
| `tests/test_phase2b_migration.py` | Migration round-trip + column presence tests |
| `tests/test_expedition_template_schema.py` | JSON-Schema-level validator tests |
| `tests/test_expedition_template_semantic.py` | Semantic validator tests (default-choice rules, stat refs, archetype refs, etc.) |
| `tests/test_expedition_template_cli.py` | CLI entry point tests |
| `tests/test_expedition_template_files.py` | Loads every `data/expeditions/*.yaml` through the validator (CI gate) |
| `tests/test_stat_namespace.py` | Stat namespace registry + lookup tests |
| `tests/test_effect_registry.py` | Effect-op registry + apply tests |
| `tests/test_expedition_engine.py` | `resolve_scene`, `select_closing`, `_check_requires`, `_filter_visible_choices` tests |
| `tests/test_expedition_concurrency.py` | `get_max_expeditions` + per-user/per-build cap tests |
| `tests/test_handler_expedition_event.py` | EXPEDITION_EVENT handler tests |
| `tests/test_handler_expedition_auto_resolve.py` | EXPEDITION_AUTO_RESOLVE handler tests |
| `tests/test_handler_expedition_resolve.py` | EXPEDITION_RESOLVE handler tests (idempotency + roll determinism) |
| `tests/test_handler_expedition_complete.py` | EXPEDITION_COMPLETE handler tests (closing + unlocks) |
| `tests/test_cog_expedition_start.py` | `/expedition start` cog tests covering each validation path |
| `tests/test_cog_expedition_status.py` | `/expedition status` cog tests (no-arg + per-expedition forms) |
| `tests/test_cog_expedition_respond.py` | `/expedition respond` cog tests + button click handler tests |
| `tests/test_cog_hangar_build_lock.py` | Build-mutation refusal tests when `current_activity != IDLE` |
| `tests/test_cog_hiring_display.py` | `/crew` + `/crew_inspect` display refresh tests |
| `tests/test_authoring_docs_drift.py` | CI gate: regenerated docs must equal committed docs |
| `tests/scenarios/test_expedition_flow.py` | End-to-end scenario: start → event 1 → click → resolve → event 2 → no response → auto-resolve → complete |
| `tests/test_expedition_chaos.py` | Worker mid-job kill + persistent-view restart |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add `ExpeditionState`, `BuildActivity` enums; extend `CrewActivity`, `JobType`, `RewardSourceType`; add `Expedition`, `ExpeditionCrewAssignment` models; extend `Build` (current_activity, current_activity_id), `CrewMember` (injured_until) |
| `config/settings.py` | Add 4 Phase 2b tunables: `EXPEDITION_MAX_PER_USER_DEFAULT`, `EXPEDITION_RESPONSE_WINDOW_DEFAULT_MIN`, `EXPEDITION_EVENT_JITTER_PCT`, `EXPEDITIONS_ENABLED` |
| `pyproject.toml` | Add `pyyaml` and `jsonschema` to dependencies |
| `api/metrics.py` | Add 6 new counters/gauges/histograms |
| `engine/rewards.py` | Add `RewardSourceType.EXPEDITION_OUTCOME` accepted source |
| `scheduler/dispatch.py` | Register the 4 new EXPEDITION_* handlers |
| `bot/main.py` | Load `bot.cogs.expeditions` in `setup_hook`; register persistent `ExpeditionResponseView`; respect `EXPEDITIONS_ENABLED` flag |
| `bot/cogs/hangar.py` | `/equip` and any build-mutation path checks `Build.current_activity == IDLE` |
| `bot/cogs/hiring.py` | `/crew` and `/crew_inspect` render new activity states + injury status + "Qualified for" hints |
| `monitoring/grafana-stack/generate_scheduler_dashboard.py` | Add Phase 2b row (active count, throughput, response time, auto-resolve rate, outcome distribution) |
| `monitoring/grafana-stack/grafana/alerting/rules.yml` | Add 2 new alerts: `ExpeditionAutoResolveRate`, `ExpeditionFailureRate` |
| `docs/roadmap/2026-04-22-salvage-pulp-revamp.md` | Insert "Phase 2c — Tutorial v2" section between Phase 2b and Phase 3; mark Phase 3 as blocked on Phase 2c |
| `tests/conftest.py` | Add fixtures: `sample_build_idle`, `sample_expedition`, `sample_template_files` |

---

## Task 1: Settings tunables

**Files:**
- Modify: `config/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_settings.py` (the file already exists from Phase 2a):

```python
def test_phase2b_expedition_settings_defaults():
    from config.settings import settings
    assert settings.EXPEDITION_MAX_PER_USER_DEFAULT == 2
    assert settings.EXPEDITION_RESPONSE_WINDOW_DEFAULT_MIN == 30
    assert settings.EXPEDITION_EVENT_JITTER_PCT == 10
    assert settings.EXPEDITIONS_ENABLED is False
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_settings.py::test_phase2b_expedition_settings_defaults -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Add the four settings**

Append to the `Settings` class in `config/settings.py`, after the existing Phase 2a block:

```python
    # ---------------------------------------------------------------- #
    # Phase 2b — expedition tunables                                   #
    # ---------------------------------------------------------------- #
    # Default per-user concurrent expedition cap. Overridable per-user
    # later via engine/expedition_concurrency.get_max_expeditions().
    EXPEDITION_MAX_PER_USER_DEFAULT: int = 2

    # Default response window in minutes (templates can override per-template).
    EXPEDITION_RESPONSE_WINDOW_DEFAULT_MIN: int = 30

    # Jitter applied to inter-event spacing as a percentage of nominal spacing,
    # e.g. 10 = events fire ±10% around their nominal time. Avoids synchronized
    # cluster firing for templates with fixed schedules.
    EXPEDITION_EVENT_JITTER_PCT: int = 10

    # Rollout flag — when False, the expeditions cog does not register its
    # slash commands. Allows merging schema + engine + handlers without
    # exposing the surface to players. Removed after a stable rollout.
    EXPEDITIONS_ENABLED: bool = False
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_settings.py::test_phase2b_expedition_settings_defaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_settings.py
git commit -m "feat(phase2b): add expedition concurrency, response-window, jitter, rollout settings"
```

---

## Task 2: Phase 2b enums

**Files:**
- Modify: `db/models.py`
- Create: `tests/test_phase2b_models.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_phase2b_models.py`:

```python
"""Phase 2b — schema-level tests for new enums and models."""

from __future__ import annotations


def test_expedition_state_enum_values():
    from db.models import ExpeditionState
    assert {s.value for s in ExpeditionState} == {"active", "completed", "failed"}


def test_build_activity_enum_values():
    from db.models import BuildActivity
    assert {a.value for a in BuildActivity} == {"idle", "on_expedition"}


def test_crew_activity_enum_extended_with_on_expedition():
    from db.models import CrewActivity
    assert "on_expedition" in {a.value for a in CrewActivity}


def test_job_type_enum_extended_with_expedition_jobs():
    from db.models import JobType
    values = {j.value for j in JobType}
    assert {"expedition_event", "expedition_auto_resolve",
            "expedition_resolve", "expedition_complete"} <= values


def test_reward_source_type_extended_with_expedition_outcome():
    from db.models import RewardSourceType
    assert "expedition_outcome" in {s.value for s in RewardSourceType}
```

- [ ] **Step 2: Run, confirm 5 fails**

Run: `pytest tests/test_phase2b_models.py -v`
Expected: 5 FAILs (`ImportError` on the first two; `AssertionError` on the next three because the values aren't there yet).

- [ ] **Step 3: Add new enums and extend existing ones in `db/models.py`**

Add new enums after the existing `CrewActivity` enum (which Phase 2a added):

```python
class ExpeditionState(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class BuildActivity(str, enum.Enum):
    IDLE = "idle"
    ON_EXPEDITION = "on_expedition"
```

Extend the existing `CrewActivity` enum by adding the new value:

```python
class CrewActivity(str, enum.Enum):
    IDLE = "idle"
    ON_BUILD = "on_build"
    TRAINING = "training"
    RESEARCHING = "researching"
    ON_STATION = "on_station"
    ON_EXPEDITION = "on_expedition"   # Phase 2b
```

Extend `JobType`:

```python
class JobType(str, enum.Enum):
    TIMER_COMPLETE = "timer_complete"
    ACCRUAL_TICK = "accrual_tick"
    EXPEDITION_EVENT = "expedition_event"               # Phase 2b
    EXPEDITION_AUTO_RESOLVE = "expedition_auto_resolve" # Phase 2b
    EXPEDITION_RESOLVE = "expedition_resolve"           # Phase 2b
    EXPEDITION_COMPLETE = "expedition_complete"         # Phase 2b
```

Extend `RewardSourceType`:

```python
class RewardSourceType(str, enum.Enum):
    TIMER_COMPLETE = "timer_complete"
    ACCRUAL_TICK = "accrual_tick"
    ACCRUAL_CLAIM = "accrual_claim"
    TIMER_CANCEL_REFUND = "timer_cancel_refund"
    EXPEDITION_OUTCOME = "expedition_outcome"           # Phase 2b
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_phase2b_models.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_phase2b_models.py
git commit -m "feat(phase2b): add ExpeditionState, BuildActivity enums; extend CrewActivity, JobType, RewardSourceType"
```

---

## Task 3: Phase 2b models — Expedition, ExpeditionCrewAssignment, Build/CrewMember extensions

**Files:**
- Modify: `db/models.py`
- Modify: `tests/test_phase2b_models.py`

- [ ] **Step 1: Append model-shape tests**

Append to `tests/test_phase2b_models.py`:

```python
def test_expedition_columns():
    from db.models import Expedition
    cols = {c.name for c in Expedition.__table__.columns}
    assert cols >= {
        "id", "user_id", "build_id", "template_id", "state",
        "started_at", "completes_at", "correlation_id",
        "scene_log", "outcome_summary", "created_at",
    }


def test_expedition_crew_assignment_columns():
    from db.models import ExpeditionCrewAssignment
    cols = {c.name for c in ExpeditionCrewAssignment.__table__.columns}
    assert cols >= {"expedition_id", "crew_id", "archetype"}


def test_expedition_crew_assignment_unique_archetype_per_expedition():
    """Only one crew per archetype slot per expedition."""
    from db.models import ExpeditionCrewAssignment
    constraints = ExpeditionCrewAssignment.__table__.constraints
    unique_pairs = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("archetype", "expedition_id") in unique_pairs


def test_build_has_current_activity_columns():
    from db.models import Build
    cols = {c.name for c in Build.__table__.columns}
    assert {"current_activity", "current_activity_id"} <= cols


def test_crew_member_has_injured_until_column():
    from db.models import CrewMember
    cols = {c.name for c in CrewMember.__table__.columns}
    assert "injured_until" in cols


def test_expedition_active_per_build_partial_unique_index():
    """At most one ACTIVE expedition per build, enforced at DB level."""
    from db.models import Expedition
    # Find a partial unique index on build_id with the ACTIVE-state predicate.
    indexes = list(Expedition.__table__.indexes)
    matched = [
        ix for ix in indexes
        if ix.unique
        and {c.name for c in ix.columns} == {"build_id"}
        and "active" in (str(ix.dialect_options.get("postgresql", {}).get("where", "")).lower()
                         + str(ix.kwargs.get("postgresql_where", "")).lower())
    ]
    assert matched, "expected a partial unique index on Expedition(build_id) WHERE state = 'active'"
```

- [ ] **Step 2: Run, confirm 6 fails**

Run: `pytest tests/test_phase2b_models.py -v`
Expected: 6 new FAILs (mostly `ImportError`/`AttributeError`).

- [ ] **Step 3: Add the new models and column extensions in `db/models.py`**

Add the new models after the existing Phase 2a `RewardLedger` model. Adjust imports as needed (in particular ensure `JSONB`, `ForeignKey`, `Index`, `Boolean`, `text` are imported — they should already be from Phase 2a).

```python
class Expedition(Base):
    __tablename__ = "expeditions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.discord_id", ondelete="CASCADE"), nullable=False
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("builds.id"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[ExpeditionState] = mapped_column(
        Enum(ExpeditionState, name="expedition_state"),
        nullable=False, default=ExpeditionState.ACTIVE,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completes_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    scene_log: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    outcome_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_expeditions_user_state", "user_id", "state"),
        Index(
            "ix_expeditions_active_per_build",
            "build_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )


class ExpeditionCrewAssignment(Base):
    __tablename__ = "expedition_crew_assignments"

    expedition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expeditions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    crew_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crew_members.id"), primary_key=True
    )
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, name="crew_archetype"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("expedition_id", "archetype", name="uq_expedition_archetype_slot"),
    )
```

Extend `Build` with `current_activity` columns. Find the existing `Build` class definition and add inside it (right after the existing columns):

```python
    # Phase 2b — activity lock (mirrors crew pattern)
    current_activity: Mapped[BuildActivity] = mapped_column(
        Enum(BuildActivity, name="build_activity"),
        nullable=False, default=BuildActivity.IDLE,
        server_default=BuildActivity.IDLE.value,
    )
    current_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
```

Extend `CrewMember` with `injured_until`. Find the existing `CrewMember` class and add:

```python
    # Phase 2b — injury timestamp; blocks assignment while > now()
    injured_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Make sure `UniqueConstraint` and `text` are imported at the top of the file. The existing imports should already include `Index` and `ForeignKey` from Phase 2a.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_phase2b_models.py -v`
Expected: all 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_phase2b_models.py
git commit -m "feat(phase2b): add Expedition + ExpeditionCrewAssignment models, extend Build + CrewMember"
```

---

## Task 4: Alembic migration `0004_phase2b_expeditions`

**Files:**
- Create: `db/migrations/versions/0004_phase2b_expeditions.py`
- Create: `tests/test_phase2b_migration.py`

- [ ] **Step 1: Write migration round-trip tests**

Create `tests/test_phase2b_migration.py`:

```python
"""Phase 2b migration: tables exist, columns exist, partial unique index exists."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text


pytestmark = pytest.mark.asyncio


async def test_phase2b_tables_exist_after_migration(db_session):
    inspector = inspect((await db_session.connection()).engine.sync_engine)
    tables = inspector.get_table_names()
    assert "expeditions" in tables
    assert "expedition_crew_assignments" in tables


async def test_builds_has_current_activity_columns(db_session):
    inspector = inspect((await db_session.connection()).engine.sync_engine)
    cols = {c["name"] for c in inspector.get_columns("builds")}
    assert {"current_activity", "current_activity_id"} <= cols


async def test_crew_members_has_injured_until_column(db_session):
    inspector = inspect((await db_session.connection()).engine.sync_engine)
    cols = {c["name"] for c in inspector.get_columns("crew_members")}
    assert "injured_until" in cols


async def test_expedition_active_per_build_partial_unique_index_exists(db_session):
    """Postgres-side: the partial unique index is present."""
    result = await db_session.execute(text(
        "SELECT indexdef FROM pg_indexes "
        "WHERE tablename = 'expeditions' "
        "AND indexname = 'ix_expeditions_active_per_build'"
    ))
    indexdef = result.scalar_one_or_none()
    assert indexdef is not None
    assert "(state = 'active'" in indexdef.lower() or "where (state = 'active'" in indexdef.lower()


async def test_expedition_state_enum_in_postgres(db_session):
    result = await db_session.execute(text(
        "SELECT unnest(enum_range(NULL::expedition_state))::text"
    ))
    values = {row[0] for row in result}
    assert values == {"active", "completed", "failed"}


async def test_build_activity_enum_in_postgres(db_session):
    result = await db_session.execute(text(
        "SELECT unnest(enum_range(NULL::build_activity))::text"
    ))
    values = {row[0] for row in result}
    assert values == {"idle", "on_expedition"}


async def test_crew_activity_includes_on_expedition(db_session):
    result = await db_session.execute(text(
        "SELECT unnest(enum_range(NULL::crew_activity))::text"
    ))
    values = {row[0] for row in result}
    assert "on_expedition" in values


async def test_job_type_includes_expedition_jobs(db_session):
    result = await db_session.execute(text(
        "SELECT unnest(enum_range(NULL::job_type))::text"
    ))
    values = {row[0] for row in result}
    assert {"expedition_event", "expedition_auto_resolve",
            "expedition_resolve", "expedition_complete"} <= values


async def test_reward_source_type_includes_expedition_outcome(db_session):
    result = await db_session.execute(text(
        "SELECT unnest(enum_range(NULL::reward_source_type))::text"
    ))
    values = {row[0] for row in result}
    assert "expedition_outcome" in values
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase2b_migration.py -v`
Expected: 9 FAILs (tables/columns/indexes/enum values absent).

- [ ] **Step 3: Write the migration**

Create `db/migrations/versions/0004_phase2b_expeditions.py`. The down-revision must be the Phase 2a migration (`0003_phase2a_scheduler` — confirm via `alembic history`).

```python
"""Phase 2b — expeditions

Revision ID: 0004_phase2b_expeditions
Revises: 0003_phase2a_scheduler
Create Date: 2026-04-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_phase2b_expeditions"
down_revision = "0003_phase2a_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. New enums
    expedition_state = postgresql.ENUM(
        "active", "completed", "failed",
        name="expedition_state",
    )
    expedition_state.create(op.get_bind(), checkfirst=True)

    build_activity = postgresql.ENUM(
        "idle", "on_expedition",
        name="build_activity",
    )
    build_activity.create(op.get_bind(), checkfirst=True)

    # 2. Extend existing enums (Postgres ALTER TYPE ADD VALUE — non-transactional)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE crew_activity ADD VALUE IF NOT EXISTS 'on_expedition'")
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'expedition_event'")
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'expedition_auto_resolve'")
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'expedition_resolve'")
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'expedition_complete'")
        op.execute("ALTER TYPE reward_source_type ADD VALUE IF NOT EXISTS 'expedition_outcome'")

    # 3. Add columns to existing tables
    op.add_column(
        "builds",
        sa.Column(
            "current_activity",
            postgresql.ENUM(name="build_activity", create_type=False),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "builds",
        sa.Column("current_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "crew_members",
        sa.Column("injured_until", sa.DateTime(timezone=True), nullable=True),
    )

    # 4. expeditions table
    op.create_table(
        "expeditions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String,
            sa.ForeignKey("users.discord_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "build_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("builds.id"),
            nullable=False,
        ),
        sa.Column("template_id", sa.String, nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="expedition_state", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("completes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_log", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("outcome_summary", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_expeditions_user_state", "expeditions", ["user_id", "state"]
    )
    op.create_index(
        "ix_expeditions_active_per_build",
        "expeditions",
        ["build_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    # 5. expedition_crew_assignments table
    op.create_table(
        "expedition_crew_assignments",
        sa.Column(
            "expedition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expeditions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id"),
            primary_key=True,
        ),
        sa.Column(
            "archetype",
            postgresql.ENUM(name="crew_archetype", create_type=False),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "expedition_id", "archetype", name="uq_expedition_archetype_slot"
        ),
    )


def downgrade() -> None:
    op.drop_table("expedition_crew_assignments")
    op.drop_index("ix_expeditions_active_per_build", table_name="expeditions")
    op.drop_index("ix_expeditions_user_state", table_name="expeditions")
    op.drop_table("expeditions")

    op.drop_column("crew_members", "injured_until")
    op.drop_column("builds", "current_activity_id")
    op.drop_column("builds", "current_activity")

    # Note: Postgres does NOT support DROP VALUE on ENUM. The added enum
    # values for crew_activity, job_type, reward_source_type are NOT removed
    # on downgrade. This is a known Postgres limitation. The new enums
    # (expedition_state, build_activity) are dropped below since nothing
    # references them after the column drops above.
    op.execute("DROP TYPE IF EXISTS expedition_state")
    op.execute("DROP TYPE IF EXISTS build_activity")
```

- [ ] **Step 4: Apply the migration on the test database**

```bash
docker-compose up -d db
alembic upgrade head
```

Expected: migration applies cleanly. If you see "tuple index out of range" or similar, double-check that `down_revision` matches the actual Phase 2a revision name in `alembic history`.

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_phase2b_migration.py -v`
Expected: 9 PASS.

- [ ] **Step 6: Round-trip test**

```bash
alembic downgrade -1
alembic upgrade head
```

Both must succeed. Note the docstring caveat: enum values added by `ALTER TYPE ADD VALUE` are not removed on downgrade — this is documented inside the migration.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/versions/0004_phase2b_expeditions.py tests/test_phase2b_migration.py
git commit -m "feat(phase2b): alembic migration for expeditions tables + column extensions"
```

---

## Task 5: JSON Schema for expedition templates + dependency wiring

**Files:**
- Modify: `pyproject.toml`
- Create: `data/expeditions/schema.json`
- Create: `tests/test_expedition_template_schema.py`

- [ ] **Step 1: Add `pyyaml` and `jsonschema` to dependencies**

Edit `pyproject.toml`. Find the `[project] dependencies = [` block and add:

```toml
"pyyaml>=6.0",
"jsonschema>=4.21",
```

Reinstall:

```bash
pip install -e .
```

- [ ] **Step 2: Write schema-conformance tests**

Create `tests/test_expedition_template_schema.py`:

```python
"""JSON-Schema-level validator tests for expedition templates."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "expeditions" / "schema.json"


@pytest.fixture(scope="module")
def schema():
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _scripted_min():
    """Minimal valid scripted template body."""
    return {
        "id": "scripted_min",
        "kind": "scripted",
        "duration_minutes": 360,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "opening",
                "narration": "You depart.",
            },
            {
                "id": "closing",
                "is_closing": True,
                "closings": [
                    {"when": {"default": True}, "body": "You return.", "effects": []},
                ],
            },
        ],
    }


def _rolled_min():
    return {
        "id": "rolled_min",
        "kind": "rolled",
        "duration_minutes": 360,
        "response_window_minutes": 30,
        "event_count": 1,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "opening": {"id": "opening", "narration": "You depart."},
        "events": [
            {
                "id": "evt_a",
                "narration": "Something happens.",
                "choices": [
                    {
                        "id": "safe",
                        "text": "Play it safe.",
                        "default": True,
                        "outcomes": {"result": {"narrative": "ok", "effects": []}},
                    },
                ],
            },
        ],
        "closings": [
            {"when": {"default": True}, "body": "You return.", "effects": []},
        ],
    }


def test_scripted_minimum_validates(schema):
    jsonschema.validate(_scripted_min(), schema)


def test_rolled_minimum_validates(schema):
    jsonschema.validate(_rolled_min(), schema)


def test_kind_enum_enforced(schema):
    bad = _scripted_min()
    bad["kind"] = "novel"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_id_pattern_enforced(schema):
    bad = _scripted_min()
    bad["id"] = "BadID-WithDash"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_rolled_requires_event_count(schema):
    bad = _rolled_min()
    del bad["event_count"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_scripted_requires_scenes(schema):
    bad = _scripted_min()
    del bad["scenes"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_choice_with_roll_requires_success_and_failure(schema):
    bad = _rolled_min()
    bad["events"][0]["choices"][0] = {
        "id": "rolled_choice",
        "text": "Try it.",
        "default": True,
        "roll": {"stat": "pilot.acceleration", "base_p": 0.5, "base_stat": 50, "per_point": 0.005},
        "outcomes": {"result": {"narrative": "ok", "effects": []}},  # missing success/failure
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_expedition_template_schema.py -v`
Expected: 7 FAILs (FileNotFoundError on `schema.json`).

- [ ] **Step 4: Write `data/expeditions/schema.json`**

Create `data/expeditions/schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://dare2drive/schemas/expeditions/v1.json",
  "title": "Expedition Template",
  "type": "object",
  "required": ["id", "kind", "duration_minutes", "response_window_minutes", "cost_credits", "crew_required"],
  "properties": {
    "id": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9_]*$"
    },
    "kind": {
      "type": "string",
      "enum": ["scripted", "rolled"]
    },
    "duration_minutes": {"type": "integer", "minimum": 60, "maximum": 1440},
    "response_window_minutes": {"type": "integer", "minimum": 5, "maximum": 240},
    "cost_credits": {"type": "integer", "minimum": 0},
    "crew_required": {
      "type": "object",
      "required": ["min"],
      "properties": {
        "min": {"type": "integer", "minimum": 0, "maximum": 4},
        "archetypes_any": {
          "type": "array",
          "items": {"type": "string", "enum": ["PILOT", "GUNNER", "ENGINEER", "NAVIGATOR"]}
        },
        "archetypes_all": {
          "type": "array",
          "items": {"type": "string", "enum": ["PILOT", "GUNNER", "ENGINEER", "NAVIGATOR"]}
        }
      },
      "additionalProperties": false
    }
  },
  "oneOf": [
    {"$ref": "#/$defs/scriptedTemplate"},
    {"$ref": "#/$defs/rolledTemplate"}
  ],
  "$defs": {
    "scriptedTemplate": {
      "type": "object",
      "properties": {
        "kind": {"const": "scripted"},
        "scenes": {
          "type": "array",
          "minItems": 2,
          "items": {"$ref": "#/$defs/scene"}
        }
      },
      "required": ["scenes"]
    },
    "rolledTemplate": {
      "type": "object",
      "properties": {
        "kind": {"const": "rolled"},
        "event_count": {"type": "integer", "minimum": 1, "maximum": 10},
        "opening": {"$ref": "#/$defs/scene"},
        "events": {
          "type": "array",
          "minItems": 1,
          "items": {"$ref": "#/$defs/scene"}
        },
        "closings": {
          "type": "array",
          "minItems": 1,
          "items": {"$ref": "#/$defs/closingVariant"}
        }
      },
      "required": ["event_count", "opening", "events", "closings"]
    },
    "scene": {
      "type": "object",
      "required": ["id"],
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "narration": {"type": "string"},
        "is_closing": {"type": "boolean"},
        "closings": {
          "type": "array",
          "items": {"$ref": "#/$defs/closingVariant"}
        },
        "choices": {
          "type": "array",
          "minItems": 1,
          "items": {"$ref": "#/$defs/choice"}
        }
      }
    },
    "choice": {
      "type": "object",
      "required": ["id", "text", "outcomes"],
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "text": {"type": "string", "minLength": 1},
        "default": {"type": "boolean"},
        "requires": {"$ref": "#/$defs/requires"},
        "roll": {"$ref": "#/$defs/roll"},
        "outcomes": {
          "type": "object",
          "properties": {
            "result": {"$ref": "#/$defs/outcome"},
            "success": {"$ref": "#/$defs/outcome"},
            "failure": {"$ref": "#/$defs/outcome"}
          },
          "additionalProperties": false
        }
      },
      "allOf": [
        {
          "if": {"required": ["roll"]},
          "then": {
            "properties": {
              "outcomes": {"required": ["success", "failure"]}
            }
          },
          "else": {
            "properties": {
              "outcomes": {"required": ["result"]}
            }
          }
        }
      ]
    },
    "roll": {
      "type": "object",
      "required": ["stat", "base_p", "base_stat", "per_point"],
      "properties": {
        "stat": {"type": "string"},
        "base_p": {"type": "number", "minimum": 0, "maximum": 1},
        "base_stat": {"type": "number"},
        "per_point": {"type": "number"},
        "clamp_min": {"type": "number", "minimum": 0, "maximum": 1},
        "clamp_max": {"type": "number", "minimum": 0, "maximum": 1}
      }
    },
    "requires": {
      "type": "object",
      "properties": {
        "archetype": {"type": "string", "enum": ["PILOT", "GUNNER", "ENGINEER", "NAVIGATOR"]},
        "min_level": {"type": "integer", "minimum": 1},
        "hull_class": {"type": "string"}
      },
      "additionalProperties": false
    },
    "outcome": {
      "type": "object",
      "required": ["narrative", "effects"],
      "properties": {
        "narrative": {"type": "string"},
        "effects": {
          "type": "array",
          "items": {"$ref": "#/$defs/effect"}
        }
      }
    },
    "effect": {
      "type": "object",
      "minProperties": 1,
      "maxProperties": 1
    },
    "closingVariant": {
      "type": "object",
      "required": ["when", "body", "effects"],
      "properties": {
        "when": {
          "type": "object",
          "properties": {
            "min_successes": {"type": "integer", "minimum": 0},
            "max_failures": {"type": "integer", "minimum": 0},
            "has_flag": {"type": "string"},
            "not_flag": {"type": "string"},
            "default": {"type": "boolean"}
          },
          "additionalProperties": false
        },
        "body": {"type": "string"},
        "effects": {
          "type": "array",
          "items": {"$ref": "#/$defs/effect"}
        }
      }
    }
  }
}
```

The schema deliberately keeps `effect` as a single-property generic object so the JSON Schema doesn't constrain the closed effect vocabulary — that's the semantic validator's job (Task 8). Same for `roll.stat` (free-form string at this level; Task 7 enforces real namespace entries).

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_expedition_template_schema.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml data/expeditions/schema.json tests/test_expedition_template_schema.py
git commit -m "feat(phase2b): JSON Schema for expedition templates + add pyyaml + jsonschema deps"
```

---

## Task 6: Stat namespace registry

Authors reference stats via dotted keys (`pilot.acceleration`, `ship.durability`, etc.). The registry is the **single source of truth** for what's legal — consumed by the engine (when reading a stat at resolution time), the semantic validator (Task 8 — fails if a template references an unknown stat), and the doc generator (Task 13 — auto-builds the reference table in the authoring guide).

**Files:**
- Create: `engine/stat_namespace.py`
- Create: `tests/test_stat_namespace.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_stat_namespace.py`:

```python
"""Stat namespace registry — what authors can reference in roll.stat / requires.stat."""

from __future__ import annotations

import pytest


def test_known_namespaces_present():
    from engine.stat_namespace import KNOWN_STAT_KEYS
    # Crew archetype stats
    for arche in ("pilot", "gunner", "engineer", "navigator"):
        for stat in ("acceleration", "combat", "repair", "luck"):
            # Not every archetype has every stat — see archetype-specific stat
            # mapping in engine/crew_xp.py. For the namespace registry we
            # publish ALL crew-stat keys generically: each archetype has its own
            # subset, and the validator cross-checks per-archetype below.
            pass
    # Ship namespace
    for stat in ("acceleration", "durability", "power"):
        assert f"ship.{stat}" in KNOWN_STAT_KEYS
    # Aggregate keys
    assert "crew.avg_level" in KNOWN_STAT_KEYS
    assert "crew.count" in KNOWN_STAT_KEYS


def test_is_known_stat():
    from engine.stat_namespace import is_known_stat
    assert is_known_stat("ship.durability")
    assert is_known_stat("crew.avg_level")
    assert is_known_stat("pilot.acceleration")
    assert not is_known_stat("ship.nonsense")
    assert not is_known_stat("randomthing")
    assert not is_known_stat("pilot.notarealstat")


def test_archetype_for_stat():
    """Returns the implicit archetype gate for a crew-specific stat key."""
    from engine.stat_namespace import archetype_for_stat
    assert archetype_for_stat("pilot.acceleration") == "PILOT"
    assert archetype_for_stat("gunner.combat") == "GUNNER"
    assert archetype_for_stat("engineer.repair") == "ENGINEER"
    assert archetype_for_stat("navigator.luck") == "NAVIGATOR"
    assert archetype_for_stat("ship.durability") is None
    assert archetype_for_stat("crew.avg_level") is None


@pytest.mark.asyncio
async def test_read_stat_reads_pilot_acceleration(db_session, sample_expedition_with_pilot):
    """`read_stat` returns the assigned PILOT crew's acceleration."""
    from engine.stat_namespace import read_stat
    expedition, pilot = sample_expedition_with_pilot
    val = await read_stat(db_session, expedition, "pilot.acceleration")
    # Fixture sets pilot.acceleration = 70 (see conftest below).
    assert val == 70


@pytest.mark.asyncio
async def test_read_stat_returns_none_when_archetype_unassigned(
    db_session, sample_expedition_pilot_only
):
    """`read_stat` returns None for a crew slot the player didn't assign."""
    from engine.stat_namespace import read_stat
    expedition, _ = sample_expedition_pilot_only
    val = await read_stat(db_session, expedition, "gunner.combat")
    assert val is None


@pytest.mark.asyncio
async def test_read_stat_ship_durability(db_session, sample_expedition_with_pilot):
    """`read_stat` reads ship.durability via engine/stat_resolver from the locked build."""
    from engine.stat_namespace import read_stat
    expedition, _ = sample_expedition_with_pilot
    val = await read_stat(db_session, expedition, "ship.durability")
    # Fixture sets up build with durability >= 0 — just assert it returns a number.
    assert val is not None
    assert isinstance(val, (int, float))
```

- [ ] **Step 2: Add fixtures to `tests/conftest.py`**

Add to `tests/conftest.py` (after the existing Phase 2a fixtures):

```python
@pytest_asyncio.fixture
async def sample_expedition_with_pilot(db_session, sample_system):
    """An ACTIVE expedition with a PILOT crew member assigned (acceleration=70)."""
    from db.models import (
        Build, BuildActivity, CrewActivity, CrewArchetype, CrewMember,
        Expedition, ExpeditionCrewAssignment, ExpeditionState,
        HullClass, Rarity, User,
    )
    import uuid
    from datetime import datetime, timezone, timedelta

    user = User(
        discord_id="exp_test_user_1", username="exp1",
        hull_class=HullClass.SKIRMISHER, currency=1000,
    )
    db_session.add(user)
    await db_session.flush()

    build = Build(
        id=uuid.uuid4(), user_id=user.discord_id,
        name="Flagstaff", hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()

    pilot = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="Mira", last_name="Voss", callsign="Sixgun",
        archetype=CrewArchetype.PILOT, rarity=Rarity.RARE,
        level=4,
        # Stats are stored on CrewMember per Phase 1; field name varies — adjust
        # to match the actual model. Below assumes a JSON `stats` column.
        stats={"acceleration": 70, "luck": 40},
        current_activity=CrewActivity.ON_EXPEDITION,
    )
    db_session.add(pilot)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    expedition = Expedition(
        id=uuid.uuid4(), user_id=user.discord_id, build_id=build.id,
        template_id="outer_marker_patrol",
        state=ExpeditionState.ACTIVE,
        started_at=now,
        completes_at=now + timedelta(hours=6),
        correlation_id=uuid.uuid4(),
        scene_log=[],
    )
    db_session.add(expedition)
    await db_session.flush()
    db_session.add(ExpeditionCrewAssignment(
        expedition_id=expedition.id, crew_id=pilot.id,
        archetype=CrewArchetype.PILOT,
    ))
    await db_session.flush()
    build.current_activity_id = expedition.id
    pilot.current_activity_id = expedition.id
    await db_session.flush()
    return expedition, pilot


@pytest_asyncio.fixture
async def sample_expedition_pilot_only(sample_expedition_with_pilot):
    """Alias — fixture above already has only a PILOT, no GUNNER."""
    return sample_expedition_with_pilot
```

If the `CrewMember.stats` column doesn't exist or has a different shape (e.g., separate columns per stat), adapt the fixture to populate the actual model. Inspect `db/models.py:CrewMember` and `engine/crew_xp.py` to confirm.

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_stat_namespace.py -v`
Expected: 6 FAILs (`ImportError` on `engine.stat_namespace`).

- [ ] **Step 4: Implement `engine/stat_namespace.py`**

Create `engine/stat_namespace.py`:

```python
"""Stat namespace registry for expedition templates.

Single source of truth for what `roll.stat` and `requires.stat` may reference.
Consumed by:
  - engine/expedition_engine.py — at resolution time, to read the value
  - engine/expedition_template.py — at validation time, to reject unknown keys
  - scripts/build_authoring_docs.py — to regenerate the docs reference table
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CrewArchetype, CrewMember, ExpeditionCrewAssignment

if TYPE_CHECKING:
    from db.models import Expedition

# Per-archetype stat namespaces. Each archetype's stat list is the union
# of stats meaningful to that archetype's events. Adding a new stat here
# is a one-line change; the doc generator picks it up automatically.
_CREW_STATS: dict[str, tuple[str, ...]] = {
    "pilot": ("acceleration", "handling", "luck"),
    "gunner": ("combat", "luck"),
    "engineer": ("repair", "luck"),
    "navigator": ("luck", "perception"),
}

# Ship-resolved stats. These flow through engine/stat_resolver.py.
_SHIP_STATS: tuple[str, ...] = (
    "acceleration", "durability", "power", "weather_performance",
)

# Aggregate / derived crew keys.
_CREW_AGGREGATE: tuple[str, ...] = ("avg_level", "count")


def _build_known_stat_keys() -> frozenset[str]:
    keys: set[str] = set()
    for archetype, stats in _CREW_STATS.items():
        for stat in stats:
            keys.add(f"{archetype}.{stat}")
    for stat in _SHIP_STATS:
        keys.add(f"ship.{stat}")
    for stat in _CREW_AGGREGATE:
        keys.add(f"crew.{stat}")
    return frozenset(keys)


KNOWN_STAT_KEYS: frozenset[str] = _build_known_stat_keys()


_ARCHETYPE_BY_PREFIX: dict[str, str] = {
    "pilot": "PILOT",
    "gunner": "GUNNER",
    "engineer": "ENGINEER",
    "navigator": "NAVIGATOR",
}


def is_known_stat(key: str) -> bool:
    """True iff `key` is a published stat namespace entry."""
    return key in KNOWN_STAT_KEYS


def archetype_for_stat(key: str) -> str | None:
    """Return the implicit archetype gate for a crew-specific stat key.

    e.g. 'pilot.acceleration' → 'PILOT'.
    Non-crew keys (ship.*, crew.*) return None.
    """
    if "." not in key:
        return None
    prefix, _ = key.split(".", 1)
    return _ARCHETYPE_BY_PREFIX.get(prefix)


async def read_stat(
    session: AsyncSession,
    expedition: "Expedition",
    key: str,
) -> float | int | None:
    """Read the live value of a stat namespace key for an expedition.

    Returns None if the key is unassigned (e.g., 'gunner.combat' when no
    GUNNER is on this expedition). Callers should treat None as
    'this choice is hidden / not applicable.'
    """
    if not is_known_stat(key):
        raise ValueError(f"unknown stat key: {key}")

    if "." not in key:
        return None
    prefix, stat = key.split(".", 1)

    if prefix == "ship":
        # Resolve ship stats via the existing stat_resolver.
        from engine.stat_resolver import resolve_ship_stats
        resolved = await resolve_ship_stats(session, expedition.build_id)
        return resolved.get(stat)

    if prefix == "crew":
        if stat == "count":
            return await _crew_count(session, expedition.id)
        if stat == "avg_level":
            return await _crew_avg_level(session, expedition.id)
        return None

    # Per-archetype crew stat: load the assigned crew of that archetype.
    archetype = _ARCHETYPE_BY_PREFIX[prefix]
    crew = await _assigned_crew(session, expedition.id, archetype)
    if crew is None:
        return None
    return _crew_stat_value(crew, stat)


async def _assigned_crew(
    session: AsyncSession, expedition_id, archetype_str: str
) -> CrewMember | None:
    """Return the assigned crew of the given archetype, or None."""
    archetype = CrewArchetype(archetype_str)
    result = await session.execute(
        select(CrewMember)
        .join(ExpeditionCrewAssignment, ExpeditionCrewAssignment.crew_id == CrewMember.id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
        .where(ExpeditionCrewAssignment.archetype == archetype)
    )
    return result.scalar_one_or_none()


def _crew_stat_value(crew: CrewMember, stat: str) -> float | int | None:
    """Read a stat off a crew row. Adjust to the actual stat-storage shape."""
    # If CrewMember stores stats as a JSON dict in `stats`:
    stats = getattr(crew, "stats", None) or {}
    return stats.get(stat)


async def _crew_count(session: AsyncSession, expedition_id) -> int:
    from sqlalchemy import func
    result = await session.execute(
        select(func.count())
        .select_from(ExpeditionCrewAssignment)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
    )
    return int(result.scalar_one() or 0)


async def _crew_avg_level(session: AsyncSession, expedition_id) -> float:
    from sqlalchemy import func
    result = await session.execute(
        select(func.avg(CrewMember.level))
        .select_from(ExpeditionCrewAssignment)
        .join(CrewMember, CrewMember.id == ExpeditionCrewAssignment.crew_id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
    )
    val = result.scalar_one()
    return float(val) if val is not None else 0.0
```

If `engine.stat_resolver.resolve_ship_stats` doesn't exist with that exact signature, locate the existing API in `engine/stat_resolver.py` and adapt the call. The function signature for `resolve_ship_stats(session, build_id)` is conventional — implement a small adapter at the top of `stat_namespace.py` if the upstream function has a different shape.

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_stat_namespace.py -v`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/stat_namespace.py tests/test_stat_namespace.py tests/conftest.py
git commit -m "feat(phase2b): stat namespace registry with read_stat for expeditions"
```

---

## Task 7: Outcome effect-op registry

The closed vocabulary of effect operations (`reward_credits`, `injure_crew`, `damage_part`, etc.). Like the stat namespace, this is a single source of truth shared by the engine (applies effects), the validator (rejects unknown ops), and the doc generator.

**Files:**
- Create: `engine/effect_registry.py`
- Create: `tests/test_effect_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_effect_registry.py`:

```python
"""Effect-op registry — closed vocabulary of expedition outcome operations."""

from __future__ import annotations

import pytest


def test_known_effect_ops_present():
    from engine.effect_registry import KNOWN_OPS
    expected = {
        "reward_credits", "reward_wreck", "reward_card", "reward_xp",
        "injure_crew", "damage_part", "set_flag",
    }
    assert expected <= set(KNOWN_OPS.keys())


def test_each_op_declares_required_params():
    """Every op has a parameter schema used by the validator."""
    from engine.effect_registry import KNOWN_OPS
    for name, spec in KNOWN_OPS.items():
        assert "params" in spec, f"{name} missing 'params'"
        assert "summary" in spec, f"{name} missing 'summary'"


def test_validate_effect_accepts_known_op():
    from engine.effect_registry import validate_effect
    errors = validate_effect({"reward_credits": 250})
    assert errors == []


def test_validate_effect_rejects_unknown_op():
    from engine.effect_registry import validate_effect
    errors = validate_effect({"reward_telepathy": True})
    assert len(errors) == 1
    assert "unknown effect op" in errors[0].lower()


def test_validate_effect_rejects_multi_op():
    """An effect must be exactly one op."""
    from engine.effect_registry import validate_effect
    errors = validate_effect({"reward_credits": 100, "set_flag": {"name": "x"}})
    assert any("exactly one" in e.lower() for e in errors)


def test_validate_effect_param_shape_injure_crew():
    from engine.effect_registry import validate_effect
    assert validate_effect({"injure_crew": {"archetype": "GUNNER", "duration_hours": 24}}) == []
    errs = validate_effect({"injure_crew": {"archetype": "GUNNER"}})
    assert any("duration_hours" in e for e in errs)


@pytest.mark.asyncio
async def test_apply_reward_credits_writes_ledger(db_session, sample_expedition_with_pilot):
    from engine.effect_registry import apply_effect
    expedition, _ = sample_expedition_with_pilot
    await apply_effect(
        db_session, expedition,
        scene_id="test_scene",
        effect={"reward_credits": 250},
    )
    from db.models import RewardLedger, RewardSourceType
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(RewardLedger)
        .where(RewardLedger.user_id == expedition.user_id)
        .where(RewardLedger.source_type == RewardSourceType.EXPEDITION_OUTCOME)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].delta.get("credits") == 250


@pytest.mark.asyncio
async def test_apply_effect_idempotent_on_double_call(
    db_session, sample_expedition_with_pilot
):
    from engine.effect_registry import apply_effect
    expedition, _ = sample_expedition_with_pilot
    await apply_effect(
        db_session, expedition, scene_id="test_scene_idem",
        effect={"reward_credits": 100},
    )
    await apply_effect(
        db_session, expedition, scene_id="test_scene_idem",
        effect={"reward_credits": 100},
    )
    from db.models import RewardLedger
    from sqlalchemy import select, func
    count = (await db_session.execute(
        select(func.count()).select_from(RewardLedger)
        .where(RewardLedger.user_id == expedition.user_id)
    )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_apply_effect_injure_crew_sets_injured_until(
    db_session, sample_expedition_with_pilot
):
    from datetime import datetime, timezone
    from engine.effect_registry import apply_effect
    from db.models import CrewMember
    expedition, pilot = sample_expedition_with_pilot
    await apply_effect(
        db_session, expedition, scene_id="injury_test",
        effect={"injure_crew": {"archetype": "PILOT", "duration_hours": 24}},
    )
    refreshed = await db_session.get(CrewMember, pilot.id)
    assert refreshed.injured_until is not None
    delta = refreshed.injured_until - datetime.now(timezone.utc)
    assert 23 < delta.total_seconds() / 3600 < 25
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_effect_registry.py -v`
Expected: 8 FAILs (`ImportError`).

- [ ] **Step 3: Implement `engine/effect_registry.py`**

Create `engine/effect_registry.py`:

```python
"""Effect-op registry for expedition outcomes.

Closed vocabulary. Adding a new op requires updating KNOWN_OPS plus an
apply_<op_name> handler. Both the validator and the doc generator read
from KNOWN_OPS, so the schema, the docs, and the engine never drift.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    CrewActivity, CrewArchetype, CrewMember, ExpeditionCrewAssignment,
    RewardSourceType,
)
from engine.rewards import apply_reward

if TYPE_CHECKING:
    from db.models import Expedition

# Each entry: {params: list[str] required keys, summary: docs blurb}.
KNOWN_OPS: dict[str, dict[str, Any]] = {
    "reward_credits": {
        "params": [],  # value is a plain int
        "param_kind": "scalar_int",
        "summary": "Adds (or subtracts, if negative) credits to the player.",
    },
    "reward_wreck": {
        "params": ["hull_class", "quality"],
        "param_kind": "object",
        "summary": "Generates a wreck row of the named hull_class + quality.",
    },
    "reward_card": {
        "params": ["slot", "rarity"],
        "param_kind": "object",
        "summary": "Mints a card of the given slot + rarity for the player.",
    },
    "reward_xp": {
        "params": ["archetype", "amount"],
        "param_kind": "object",
        "summary": "Grants XP to the assigned crew of the named archetype. "
                   "No-op if no crew of that archetype is assigned.",
    },
    "injure_crew": {
        "params": ["archetype", "duration_hours"],
        "param_kind": "object",
        "summary": "Sets the assigned crew's `injured_until` to now + duration_hours. "
                   "No-op if no crew of that archetype is assigned.",
    },
    "damage_part": {
        "params": ["slot", "amount"],
        "param_kind": "object",
        "summary": "Reduces durability on the equipped card in the given slot by `amount` "
                   "(0..1, fractional).",
    },
    "set_flag": {
        "params": ["name"],
        "param_kind": "object",
        "summary": "Records a named flag in the expedition's accumulated state. "
                   "Readable by `when` clauses on later scenes / closings.",
    },
}


def validate_effect(effect: dict[str, Any]) -> list[str]:
    """Return a list of error messages, [] if valid."""
    errors: list[str] = []
    if not isinstance(effect, dict) or len(effect) != 1:
        errors.append("each effect must be a dict with exactly one op key")
        return errors
    op_name, value = next(iter(effect.items()))
    spec = KNOWN_OPS.get(op_name)
    if spec is None:
        errors.append(f"unknown effect op: {op_name}")
        return errors
    if spec["param_kind"] == "scalar_int":
        if not isinstance(value, int):
            errors.append(f"{op_name} expects an integer, got {type(value).__name__}")
    elif spec["param_kind"] == "object":
        if not isinstance(value, dict):
            errors.append(f"{op_name} expects an object")
            return errors
        for required in spec["params"]:
            if required not in value:
                errors.append(f"{op_name} missing required param: {required}")
    return errors


async def apply_effect(
    session: AsyncSession,
    expedition: "Expedition",
    scene_id: str,
    effect: dict[str, Any],
) -> None:
    """Apply a single effect inside the caller's transaction.

    Idempotent: every reward write goes through `apply_reward()` with
    `source_id = f"expedition:{expedition.id}:{scene_id}"`, so a retry of the
    same scene short-circuits via the (source_type, source_id) unique constraint.

    `set_flag` mutates `expedition.scene_log` (caller is responsible for
    flushing). All other ops are reward-ledger-backed and atomic.
    """
    errors = validate_effect(effect)
    if errors:
        raise ValueError(f"invalid effect: {effect} → {errors}")
    op_name, value = next(iter(effect.items()))
    source_id = f"expedition:{expedition.id}:{scene_id}"

    if op_name == "reward_credits":
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + ":credits",
            delta={"credits": int(value)},
        )

    elif op_name == "reward_xp":
        crew = await _assigned_crew(session, expedition.id, value["archetype"])
        if crew is None:
            return  # no-op when archetype not assigned
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":xp:{value['archetype']}",
            delta={"xp": {value["archetype"]: int(value["amount"])}},
        )

    elif op_name == "reward_wreck":
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":wreck:{value['hull_class']}",
            delta={"wreck": {
                "hull_class": value["hull_class"],
                "quality": value["quality"],
            }},
        )

    elif op_name == "reward_card":
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":card:{value['slot']}:{value['rarity']}",
            delta={"card": {
                "slot": value["slot"],
                "rarity": value["rarity"],
            }},
        )

    elif op_name == "injure_crew":
        crew = await _assigned_crew(session, expedition.id, value["archetype"])
        if crew is None:
            return  # no-op
        crew.injured_until = (
            datetime.now(timezone.utc) + timedelta(hours=int(value["duration_hours"]))
        )
        # The `apply_reward` ledger entry is the idempotency token — re-applying
        # the same scene's injure_crew should not extend the timer twice.
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":injure:{value['archetype']}",
            delta={"injury": {
                "crew_id": str(crew.id),
                "duration_hours": int(value["duration_hours"]),
            }},
        )

    elif op_name == "damage_part":
        # Apply via existing engine/durability if available; fallback to ledger record.
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":damage:{value['slot']}",
            delta={"damage": {
                "build_id": str(expedition.build_id),
                "slot": value["slot"],
                "amount": float(value["amount"]),
            }},
        )
        # Also reduce durability on the equipped card. The exact path depends
        # on engine/durability.py — call its public reducer:
        try:
            from engine.durability import damage_equipped_part
            await damage_equipped_part(
                session, build_id=expedition.build_id,
                slot=value["slot"], amount=float(value["amount"]),
            )
        except ImportError:
            pass  # durability engine not available; ledger record is the truth

    elif op_name == "set_flag":
        # Append to scene_log under a synthetic flag entry for later when-clause
        # matching. The resolver consolidates flags via _accumulated_flags().
        scene_log = list(expedition.scene_log or [])
        scene_log.append({
            "kind": "flag",
            "scene_id": scene_id,
            "name": value["name"],
        })
        expedition.scene_log = scene_log

    else:
        # validate_effect should have caught this; defensive raise.
        raise RuntimeError(f"unhandled effect op: {op_name}")


async def _assigned_crew(
    session: AsyncSession, expedition_id, archetype_str: str
) -> CrewMember | None:
    archetype = CrewArchetype(archetype_str)
    result = await session.execute(
        select(CrewMember)
        .join(ExpeditionCrewAssignment, ExpeditionCrewAssignment.crew_id == CrewMember.id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
        .where(ExpeditionCrewAssignment.archetype == archetype)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 4: Extend `engine/rewards.py` to accept the new `RewardSourceType`**

In `engine/rewards.py`, find the function signature for `apply_reward` and confirm `RewardSourceType.EXPEDITION_OUTCOME` is accepted (no source-type filter). If there's a per-source-type dispatch, add an EXPEDITION_OUTCOME branch that simply credits whatever's in `delta` (credits, xp, etc.) the same way `TIMER_COMPLETE` does.

If `apply_reward` is type-agnostic (it just writes to the ledger and applies the delta), no change needed. Verify by reading `engine/rewards.py`.

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_effect_registry.py -v`
Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/effect_registry.py tests/test_effect_registry.py engine/rewards.py
git commit -m "feat(phase2b): effect-op registry + apply_effect with idempotent ledger writes"
```

---

## Task 8: Template loader + semantic validator + CLI

The validator does three jobs: parse YAML → validate against the JSON Schema (Task 5) → run semantic checks beyond what the schema can express. Exposes both an in-process API and a CLI for use inside an LLM author's edit loop.

**Files:**
- Create: `engine/expedition_template.py`
- Create: `tests/test_expedition_template_semantic.py`
- Create: `tests/test_expedition_template_cli.py`

- [ ] **Step 1: Write semantic-validator failing tests**

Create `tests/test_expedition_template_semantic.py`:

```python
"""Semantic validator tests — invariants the JSON Schema can't express."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


SCRIPTED_YAML = textwrap.dedent("""\
    id: scripted_test
    kind: scripted
    duration_minutes: 360
    response_window_minutes: 30
    cost_credits: 0
    crew_required: { min: 1, archetypes_any: [PILOT] }
    scenes:
      - id: opening
        narration: "You depart."
      - id: midscene
        narration: "Pirates!"
        choices:
          - id: comply
            text: "Pay them."
            default: true
            outcomes:
              result:
                narrative: "Paid."
                effects:
                  - reward_credits: -100
      - id: closing
        is_closing: true
        closings:
          - when: { default: true }
            body: "You return."
            effects: []
    """)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_valid_scripted_template(tmp_path):
    from engine.expedition_template import load_template_file
    p = _write(tmp_path, "scripted_test", SCRIPTED_YAML)
    tmpl = load_template_file(p)
    assert tmpl["id"] == "scripted_test"
    assert tmpl["kind"] == "scripted"


def test_filename_must_match_id(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace("id: scripted_test", "id: different_name")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="filename must match id"):
        load_template_file(p)


def test_default_choice_required_per_scene_with_choices(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace("default: true\n            outcomes:", "outcomes:")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="default"):
        load_template_file(p)


def test_default_choice_must_have_no_requires(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace(
        "default: true",
        "default: true\n            requires: { archetype: PILOT }",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="default.*requires"):
        load_template_file(p)


def test_default_closing_required(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace("when: { default: true }", "when: { min_successes: 99 }")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="default closing"):
        load_template_file(p)


def test_unknown_stat_in_roll_rejected(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace(
        "outcomes:\n              result:",
        "roll: { stat: pilot.bogus, base_p: 0.5, base_stat: 50, per_point: 0.005 }\n"
        "            outcomes:\n"
        "              success: { narrative: ok, effects: [] }\n"
        "              failure: { narrative: bad, effects: [] }\n"
        "              result:",
    )
    body = body.replace("              result:\n                narrative: \"Paid.\"\n                effects:\n                  - reward_credits: -100\n", "")
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="unknown stat"):
        load_template_file(p)


def test_unknown_archetype_in_outcome_rejected(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace(
        "- reward_credits: -100",
        "- reward_xp: { archetype: WIZARD, amount: 50 }",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="archetype"):
        load_template_file(p)


def test_unknown_effect_op_rejected(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace(
        "- reward_credits: -100",
        "- reward_telepathy: true",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="unknown effect op"):
        load_template_file(p)


def test_rolled_pool_must_be_at_least_event_count(tmp_path):
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = textwrap.dedent("""\
        id: rolled_test
        kind: rolled
        duration_minutes: 360
        response_window_minutes: 30
        cost_credits: 0
        event_count: 5
        crew_required: { min: 1, archetypes_any: [PILOT] }
        opening: { id: opening, narration: "Off you go." }
        events:
          - id: a
            narration: x
            choices:
              - id: ok
                text: ok
                default: true
                outcomes: { result: { narrative: ok, effects: [] } }
        closings:
          - when: { default: true }
            body: ok
            effects: []
        """)
    p = _write(tmp_path, "rolled_test", body)
    with pytest.raises(TemplateValidationError, match="event_count"):
        load_template_file(p)


def test_set_flag_referenced_by_when_clause_no_typo(tmp_path):
    """A `has_flag: foo` without any `set_flag: { name: foo }` is a typo."""
    from engine.expedition_template import load_template_file, TemplateValidationError
    body = SCRIPTED_YAML.replace(
        "when: { default: true }",
        "when: { has_flag: never_set_flag }\n            body: \"closing a\"\n            effects: []\n          - when: { default: true }",
    )
    p = _write(tmp_path, "scripted_test", body)
    with pytest.raises(TemplateValidationError, match="never_set_flag"):
        load_template_file(p)
```

- [ ] **Step 2: Write CLI tests**

Create `tests/test_expedition_template_cli.py`:

```python
"""CLI entry point tests for the template validator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import textwrap


def _write_valid(tmp_path: Path) -> Path:
    body = textwrap.dedent("""\
        id: cli_valid
        kind: scripted
        duration_minutes: 360
        response_window_minutes: 30
        cost_credits: 0
        crew_required: { min: 1, archetypes_any: [PILOT] }
        scenes:
          - id: opening
            narration: "Hi."
          - id: closing
            is_closing: true
            closings:
              - when: { default: true }
                body: "Bye."
                effects: []
        """)
    p = tmp_path / "cli_valid.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_cli_validate_returns_zero_for_valid(tmp_path):
    p = _write_valid(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "engine.expedition_template", "validate", str(p)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_cli_validate_returns_nonzero_for_invalid(tmp_path):
    body = "id: bad\nkind: nonsense\n"
    p = tmp_path / "bad.yaml"
    p.write_text(body)
    result = subprocess.run(
        [sys.executable, "-m", "engine.expedition_template", "validate", str(p)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "kind" in (result.stderr + result.stdout).lower()
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_expedition_template_semantic.py tests/test_expedition_template_cli.py -v`
Expected: many FAILs (`ImportError`).

- [ ] **Step 4: Implement `engine/expedition_template.py`**

Create `engine/expedition_template.py`:

```python
"""Expedition template loader, JSON Schema + semantic validator, CLI entry point.

Public API:
    load_template_file(path) -> dict   # validate + parse one file
    load_template(template_id) -> dict # by id from data/expeditions/
    validate_all() -> None             # iterate data/expeditions/*.yaml
    main()                             # CLI: python -m engine.expedition_template

Validator runs four passes:
    1. JSON Schema conformance (data/expeditions/schema.json)
    2. Filename matches id
    3. Choice / closing / pool semantic invariants
    4. Stat namespace + effect vocabulary + archetype + flag cross-refs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml

from db.models import CrewArchetype
from engine.effect_registry import KNOWN_OPS, validate_effect
from engine.stat_namespace import is_known_stat


_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "expeditions"
_SCHEMA_PATH = _DATA_DIR / "schema.json"


class TemplateValidationError(ValueError):
    """Raised when a template fails any validation pass."""


def _load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


_SCHEMA = _load_schema()


def load_template_file(path: Path | str) -> dict[str, Any]:
    """Load + validate a single template file. Raises TemplateValidationError on issues."""
    p = Path(path)
    if not p.exists():
        raise TemplateValidationError(f"file not found: {p}")
    with p.open(encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise TemplateValidationError(f"YAML parse error in {p}: {e}") from e

    if not isinstance(doc, dict):
        raise TemplateValidationError(f"top-level YAML must be a mapping in {p}")

    # 1. JSON Schema
    try:
        jsonschema.validate(doc, _SCHEMA)
    except jsonschema.ValidationError as e:
        raise TemplateValidationError(f"schema error in {p}: {e.message}") from e

    # 2. Filename matches id
    if doc["id"] != p.stem:
        raise TemplateValidationError(
            f"filename must match id in {p}: file says {p.stem}, doc says {doc['id']}"
        )

    # 3 + 4. Semantic checks
    errors = list(_semantic_errors(doc))
    if errors:
        raise TemplateValidationError(
            f"semantic errors in {p}:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return doc


def load_template(template_id: str) -> dict[str, Any]:
    """Load + validate a template by id from data/expeditions/."""
    return load_template_file(_DATA_DIR / f"{template_id}.yaml")


def validate_all() -> None:
    """Iterate every data/expeditions/*.yaml and validate. Raises on first failure."""
    for path in sorted(_DATA_DIR.glob("*.yaml")):
        load_template_file(path)


def _semantic_errors(doc: dict[str, Any]) -> Iterable[str]:
    """Yield semantic-validation error strings."""
    kind = doc["kind"]

    # Walk all scenes (kind-specific) — emit generic checks per scene with choices.
    scenes = list(_iter_scenes(doc))
    for scene in scenes:
        if "choices" in scene:
            yield from _check_scene_choices(scene)

    # Closing check (both kinds): exactly one default.
    closings = _all_closings(doc)
    defaults = [c for c in closings if c.get("when", {}).get("default") is True]
    if len(defaults) != 1:
        yield (
            f"every template must have exactly one closing with `when: {{default: true}}` — "
            f"found {len(defaults)}"
        )

    # Rolled-template-specific
    if kind == "rolled":
        ec = doc.get("event_count", 0)
        ev = doc.get("events", [])
        if len(ev) < ec:
            yield (
                f"rolled template event_count={ec} but pool has only {len(ev)} events; "
                "increase pool or lower event_count"
            )

    # Stat / effect / archetype / flag cross-refs
    set_flag_names: set[str] = set()
    yield from _walk_effects(doc, set_flag_names)
    yield from _check_flag_references(doc, set_flag_names)
    yield from _check_stat_references(doc)
    yield from _check_archetype_references(doc)


def _iter_scenes(doc: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if doc["kind"] == "scripted":
        yield from doc.get("scenes", [])
    else:
        yield doc.get("opening", {})
        yield from doc.get("events", [])


def _all_closings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if doc["kind"] == "scripted":
        out: list[dict[str, Any]] = []
        for scene in doc.get("scenes", []):
            if scene.get("is_closing"):
                out.extend(scene.get("closings", []))
        return out
    return list(doc.get("closings", []))


def _check_scene_choices(scene: dict[str, Any]) -> Iterable[str]:
    choices = scene.get("choices", [])
    defaults = [c for c in choices if c.get("default")]
    if len(defaults) != 1:
        yield (
            f"scene `{scene.get('id')}` must have exactly one default choice — "
            f"found {len(defaults)}"
        )
    for c in defaults:
        if "requires" in c:
            yield (
                f"scene `{scene.get('id')}` default choice `{c.get('id')}` "
                "must NOT have `requires` (default must always be available)"
            )


def _walk_effects(doc: dict[str, Any], set_flag_names: set[str]) -> Iterable[str]:
    """Validate every effect op + collect set_flag names."""
    for source, effects in _iter_all_effects(doc):
        for eff in effects:
            errors = validate_effect(eff)
            for e in errors:
                yield f"{source}: {e}"
            if isinstance(eff, dict) and "set_flag" in eff:
                v = eff["set_flag"]
                if isinstance(v, dict) and "name" in v:
                    set_flag_names.add(v["name"])


def _iter_all_effects(doc: dict[str, Any]) -> Iterable[tuple[str, list[dict]]]:
    for scene in _iter_scenes(doc):
        sid = scene.get("id", "?")
        for choice in scene.get("choices", []):
            cid = choice.get("id", "?")
            for outcome_key, outcome in (choice.get("outcomes") or {}).items():
                if outcome and "effects" in outcome:
                    yield (f"scene {sid}/choice {cid}/{outcome_key}", outcome["effects"])
    for closing in _all_closings(doc):
        yield ("closing", closing.get("effects", []))


def _check_flag_references(doc: dict[str, Any], set_flag_names: set[str]) -> Iterable[str]:
    for closing in _all_closings(doc):
        when = closing.get("when") or {}
        for key in ("has_flag", "not_flag"):
            ref = when.get(key)
            if ref and ref not in set_flag_names:
                yield (
                    f"closing references {key}={ref!r} but no scene sets that flag — "
                    "typo or unreachable variant"
                )


def _check_stat_references(doc: dict[str, Any]) -> Iterable[str]:
    for scene in _iter_scenes(doc):
        for choice in scene.get("choices", []):
            roll = choice.get("roll")
            if roll and not is_known_stat(roll["stat"]):
                yield f"scene {scene.get('id')}/choice {choice.get('id')}: unknown stat {roll['stat']!r}"


def _check_archetype_references(doc: dict[str, Any]) -> Iterable[str]:
    valid = {a.value for a in CrewArchetype} | {a.value.upper() for a in CrewArchetype}
    valid |= {"PILOT", "GUNNER", "ENGINEER", "NAVIGATOR"}
    crew_req = doc.get("crew_required") or {}
    for key in ("archetypes_any", "archetypes_all"):
        for a in crew_req.get(key, []) or []:
            if a not in valid:
                yield f"crew_required.{key}: unknown archetype {a!r}"
    for scene in _iter_scenes(doc):
        for choice in scene.get("choices", []):
            req = choice.get("requires") or {}
            if "archetype" in req and req["archetype"] not in valid:
                yield f"choice {choice.get('id')}: unknown archetype {req['archetype']!r}"
            for outcome_key, outcome in (choice.get("outcomes") or {}).items():
                for eff in (outcome or {}).get("effects", []) or []:
                    if not isinstance(eff, dict):
                        continue
                    for op in ("reward_xp", "injure_crew"):
                        if op in eff and isinstance(eff[op], dict):
                            a = eff[op].get("archetype")
                            if a is not None and a not in valid:
                                yield (
                                    f"choice {choice.get('id')}/{outcome_key}/{op}: "
                                    f"unknown archetype {a!r}"
                                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.expedition_template")
    sub = parser.add_subparsers(dest="cmd", required=True)
    val = sub.add_parser("validate", help="Validate one or more template files")
    val.add_argument("paths", nargs="+", help="Paths to YAML files (or directory)")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        rc = 0
        for raw in args.paths:
            p = Path(raw)
            targets = list(p.glob("*.yaml")) if p.is_dir() else [p]
            for t in targets:
                try:
                    load_template_file(t)
                    print(f"OK  {t}")
                except TemplateValidationError as e:
                    print(f"FAIL {t}: {e}", file=sys.stderr)
                    rc = 1
        return rc
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_expedition_template_semantic.py tests/test_expedition_template_cli.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/expedition_template.py tests/test_expedition_template_semantic.py tests/test_expedition_template_cli.py
git commit -m "feat(phase2b): expedition template loader + semantic validator + CLI"
```

---

## Task 9: v1 templates + CI gate that loads every template

The v1 content: one scripted (marquee) template and one rolled (utility) template. Both serve as authoring exemplars and as positive cases for the validator.

**Files:**
- Create: `data/expeditions/marquee_run.yaml`
- Create: `data/expeditions/outer_marker_patrol.yaml`
- Create: `tests/test_expedition_template_files.py`

- [ ] **Step 1: Write CI-gate test**

Create `tests/test_expedition_template_files.py`:

```python
"""CI gate: every committed template must validate."""

from __future__ import annotations

from pathlib import Path

import pytest


_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "expeditions"


def test_at_least_two_templates_committed():
    yamls = list(_DATA_DIR.glob("*.yaml"))
    assert len(yamls) >= 2, f"v1 ships with at least 2 templates; found {len(yamls)}"


@pytest.mark.parametrize("path", sorted(_DATA_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_template_validates(path):
    from engine.expedition_template import load_template_file
    load_template_file(path)
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_expedition_template_files.py -v`
Expected: FAIL on `test_at_least_two_templates_committed` (no .yaml files yet).

- [ ] **Step 3: Author the marquee scripted template**

Create `data/expeditions/marquee_run.yaml`:

```yaml
id: marquee_run
kind: scripted
duration_minutes: 360
response_window_minutes: 30
cost_credits: 250
crew_required: { min: 2, archetypes_any: [PILOT, GUNNER] }
scenes:
  - id: opening
    narration: |
      The contract came through dirty channels — a courier with a half-eaten
      manifest, a name you almost recognized, a number too large for a clean
      job. You took it anyway. Six hours of black space between you and a
      payday. Your crew settles into their stations as the dock's running
      lights fall away.

  - id: distress_beacon
    narration: |
      Two hours out, your nav console lights up with a beacon — old code,
      civilian frequency. A merchant ship dead in the lane, hull cracked
      down the spine. The crew on board is alive but bleeding atmosphere
      fast.
    choices:
      - id: investigate
        text: "Decelerate and bring them aboard."
        roll: { stat: navigator.luck, base_p: 0.55, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: |
              You match velocities clean. The merchant captain — a graying
              woman with smoke in her hair — promises a favor in lieu of
              payment. She means it.
            effects:
              - reward_credits: 150
              - reward_xp: { archetype: NAVIGATOR, amount: 40 }
              - set_flag: { name: rescued_merchant }
          failure:
            narrative: |
              The maneuver costs you fuel and momentum. You get them aboard,
              but you've burned an hour and the merchant's gratitude doesn't
              pay rent.
            effects:
              - damage_part: { slot: drive, amount: 0.10 }
              - set_flag: { name: rescued_merchant }
      - id: ignore
        text: "Mark the beacon and keep moving."
        default: true
        outcomes:
          result:
            narrative: |
              You log the position for someone else's conscience and slide
              past. Mira is quiet at the helm.
            effects:
              - reward_xp: { archetype: PILOT, amount: 20 }

  - id: pirate_skiff
    narration: |
      Four hours out, your scope catches a contact running dark off your
      starboard quarter. A scarred skiff, the kind that scavenges merchant
      lanes. Their gun ports are open. You have seconds.
    choices:
      - id: outrun
        text: "Throttle up and outrun them."
        roll: { stat: pilot.acceleration, base_p: 0.55, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: |
              Mira pins the throttle. The skiff falls behind, screaming
              threats on open channels.
            effects:
              - reward_credits: 200
              - reward_xp: { archetype: PILOT, amount: 50 }
          failure:
            narrative: |
              The skiff matches your burn. They open fire before you can
              clear the field.
            effects:
              - damage_part: { slot: hull, amount: 0.15 }
              - reward_xp: { archetype: PILOT, amount: 20 }
      - id: board_them
        text: "Bring them in close. Take their cargo."
        requires: { archetype: GUNNER }
        roll: { stat: gunner.combat, base_p: 0.45, base_stat: 50, per_point: 0.006 }
        outcomes:
          success:
            narrative: |
              Jax leads the boarding party. Three pirates surrender; the hold
              yields a reactor in surprisingly good condition.
            effects:
              - reward_credits: 350
              - reward_card: { slot: reactor, rarity: rare }
              - reward_xp: { archetype: GUNNER, amount: 80 }
          failure:
            narrative: |
              The boarding goes sideways. Jax takes a round to the leg
              getting back. The skiff bolts before you can pursue.
            effects:
              - injure_crew: { archetype: GUNNER, duration_hours: 24 }
              - reward_xp: { archetype: GUNNER, amount: 30 }
      - id: comply
        text: "Cut your engines. Pay the toll."
        default: true
        outcomes:
          result:
            narrative: |
              You hand over a hundred credits and a salute. They wave you
              through, laughing.
            effects:
              - reward_credits: -100

  - id: closing
    is_closing: true
    closings:
      - when: { has_flag: rescued_merchant, min_successes: 2 }
        body: |
          The dock comes up out of the dark like a halo. Your contract pays
          out. Two days later, a coded message arrives — the merchant
          captain has filed your signature in places that matter. Whatever
          else happens this run, you have a friend now.
        effects:
          - reward_credits: 500
          - set_flag: { name: merchant_friend }
      - when: { min_successes: 2 }
        body: |
          The dock comes up out of the dark like a halo. Contract paid.
          Crew alive. Ship intact. A clean run.
        effects:
          - reward_credits: 400
      - when: { max_failures: 2 }
        body: |
          The dock comes up out of the dark, but the run cost you. Repairs
          will eat half the take. You sit at the helm a long time after
          docking, watching the lights and thinking about what you'd do
          differently.
        effects:
          - reward_credits: 200
      - when: { default: true }
        body: |
          You make port. Just barely. Tomorrow's another contract.
        effects:
          - reward_credits: 100
```

- [ ] **Step 4: Author the rolled patrol template**

Create `data/expeditions/outer_marker_patrol.yaml`:

```yaml
id: outer_marker_patrol
kind: rolled
duration_minutes: 240
response_window_minutes: 30
cost_credits: 100
event_count: 2
crew_required: { min: 1, archetypes_any: [PILOT, GUNNER] }
opening:
  id: opening
  narration: |
    Outer-marker patrol — the slow loop that sector security pays for and
    everyone hates. Four hours of scanning empty space for things that
    almost never show up. You log the start of your run and settle in.

events:
  - id: drifting_wreck
    narration: |
      The scope picks up something cold and tumbling — a dead corvette,
      the running lights long out. Could be salvage. Could be bait.
    choices:
      - id: salvage
        text: "Match velocities and crack it open."
        roll: { stat: engineer.repair, base_p: 0.50, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: "The hold yields a clean drive and a half-charged reactor."
            effects:
              - reward_card: { slot: drive, rarity: uncommon }
              - reward_xp: { archetype: ENGINEER, amount: 40 }
          failure:
            narrative: "The wreck shifts under your tow rig and bites back. Hull damage."
            effects:
              - damage_part: { slot: hull, amount: 0.08 }
      - id: leave_it
        text: "Mark the position and move on."
        default: true
        outcomes:
          result:
            narrative: "Probably someone else's problem. You log it and keep flying."
            effects:
              - reward_xp: { archetype: PILOT, amount: 10 }

  - id: distress_call
    narration: |
      Civilian distress call — a private yacht with engine trouble in the
      asteroid debris. Their captain is panicking on open channels.
    choices:
      - id: assist
        text: "Pull alongside and help with repairs."
        requires: { archetype: ENGINEER }
        outcomes:
          result:
            narrative: |
              An hour of tedious work. The yacht's owner tips you for the
              trouble — and remembers your callsign.
            effects:
              - reward_credits: 200
              - reward_xp: { archetype: ENGINEER, amount: 30 }
      - id: relay_only
        text: "Relay the distress to a closer ship and continue patrol."
        default: true
        outcomes:
          result:
            narrative: "Procedure says relay-and-continue, and procedure pays."
            effects:
              - reward_credits: 50

  - id: customs_check
    narration: |
      A customs cutter pulls alongside and demands your patrol logs.
      Their officer looks bored. The logs are clean.
    choices:
      - id: comply_check
        text: "Hand over the logs and answer their questions."
        default: true
        outcomes:
          result:
            narrative: "Twenty minutes of bureaucracy. They wave you on."
            effects:
              - reward_xp: { archetype: PILOT, amount: 10 }
      - id: stall
        text: "Stall. You don't have time for this."
        roll: { stat: navigator.luck, base_p: 0.40, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: "They lose interest. You're back on patrol in five minutes."
            effects:
              - reward_xp: { archetype: NAVIGATOR, amount: 30 }
          failure:
            narrative: |
              The customs officer wakes up. The fine is steep and the lecture
              is longer.
            effects:
              - reward_credits: -150

  - id: scope_ghost
    narration: |
      A contact appears at the edge of your scope — fast, hot, gone before
      you can lock on. Could be nothing. Could be a courier running silent.
    choices:
      - id: pursue
        text: "Pursue the contact."
        roll: { stat: pilot.acceleration, base_p: 0.45, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: |
              You overhaul a courier dropping cargo as you close. A canister
              tumbles into the dark — recovered, it's worth something.
            effects:
              - reward_credits: 250
              - reward_xp: { archetype: PILOT, amount: 50 }
          failure:
            narrative: "You burn fuel chasing a ghost. Nothing on scope."
            effects:
              - reward_xp: { archetype: PILOT, amount: 15 }
      - id: log_only
        text: "Log the contact and keep your patrol heading."
        default: true
        outcomes:
          result:
            narrative: "Whoever it was, they're gone. The scope is empty again."
            effects: []

  - id: corp_courier
    narration: |
      A small corporate courier hails on patrol channel — they need an
      escort through a stretch of unmarked debris. They'll pay for it.
    choices:
      - id: escort
        text: "Take the escort. Money is money."
        outcomes:
          result:
            narrative: "Forty minutes flying close formation. The courier pays in clean credits."
            effects:
              - reward_credits: 175
              - reward_xp: { archetype: NAVIGATOR, amount: 25 }
      - id: refuse
        text: "Patrol comes first. Decline."
        default: true
        outcomes:
          result:
            narrative: "By the book. The courier huffs and finds someone else."
            effects: []

  - id: sensor_anomaly
    narration: |
      Your sensors throw an anomaly — a brief, impossible reading from
      empty space. Probably noise. Probably.
    choices:
      - id: investigate_anomaly
        text: "Run a scan sweep on the bearing."
        roll: { stat: navigator.perception, base_p: 0.50, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: |
              You catch a faint encrypted ping — looks like a stash beacon.
              Coordinates logged for later. Could be valuable.
            effects:
              - reward_credits: 150
              - reward_xp: { archetype: NAVIGATOR, amount: 50 }
              - set_flag: { name: stash_logged }
          failure:
            narrative: "Nothing on the scan. Probably was noise after all."
            effects: []
      - id: ignore_anomaly
        text: "Log it and move on."
        default: true
        outcomes:
          result:
            narrative: "Anomalies happen. You file the readings for the analysts."
            effects: []

  - id: pirate_pair
    narration: |
      Two skiffs slide out of the asteroids ahead — coordinated, professional.
      They want your cargo or your fuel.
    choices:
      - id: fight
        text: "Hold position. Open fire."
        requires: { archetype: GUNNER }
        roll: { stat: gunner.combat, base_p: 0.50, base_stat: 50, per_point: 0.006 }
        outcomes:
          success:
            narrative: "One skiff burns. The other runs. You collect a bounty."
            effects:
              - reward_credits: 300
              - reward_xp: { archetype: GUNNER, amount: 60 }
          failure:
            narrative: "They got a hit in before they ran. Crew is shaken."
            effects:
              - injure_crew: { archetype: GUNNER, duration_hours: 12 }
              - damage_part: { slot: hull, amount: 0.10 }
      - id: outrun_pirates
        text: "Don't engage. Burn for clear space."
        roll: { stat: pilot.acceleration, base_p: 0.55, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: "You leave them eating exhaust."
            effects:
              - reward_xp: { archetype: PILOT, amount: 40 }
          failure:
            narrative: "They chase, fire a few warning shots, then break off."
            effects:
              - damage_part: { slot: hull, amount: 0.05 }
      - id: pay_pirates
        text: "Pay them. Live to patrol another day."
        default: true
        outcomes:
          result:
            narrative: "You hand over 200 credits. They wave you through."
            effects:
              - reward_credits: -200

  - id: dead_buoy
    narration: |
      A navigation buoy is dark — out of position, batteries fried.
      Sector security pays a small bonus for replacements logged in-flight.
    choices:
      - id: replace_buoy
        text: "Pull alongside and reset it."
        outcomes:
          result:
            narrative: "Ten minutes of work. You file the report and collect."
            effects:
              - reward_credits: 75
              - reward_xp: { archetype: ENGINEER, amount: 20 }
      - id: report_only
        text: "Log it for a maintenance crew."
        default: true
        outcomes:
          result:
            narrative: "Not your problem today."
            effects: []

closings:
  - when: { min_successes: 2 }
    body: |
      The patrol clock runs out clean. You file your logs and dock.
      Sector security pays the standard fee — and the run paid more
      than that. Good day.
    effects:
      - reward_credits: 200

  - when: { max_failures: 2 }
    body: |
      The patrol ends and you limp into dock. The mandatory fee barely
      covers the repairs. Tomorrow's run.
    effects:
      - reward_credits: 100

  - when: { has_flag: stash_logged }
    body: |
      You file the logs. The stash beacon is in your private records now.
      Something to come back to.
    effects:
      - reward_credits: 150

  - when: { default: true }
    body: |
      Patrol completed. Standard pay. The dock lights welcome you back.
    effects:
      - reward_credits: 150
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_expedition_template_files.py -v`
Expected: 3 PASS (the ≥2 count test + parametrized for both files).

```bash
python -m engine.expedition_template validate data/expeditions/
```
Expected: `OK data/expeditions/marquee_run.yaml` + `OK data/expeditions/outer_marker_patrol.yaml`.

- [ ] **Step 6: Commit**

```bash
git add data/expeditions/marquee_run.yaml data/expeditions/outer_marker_patrol.yaml tests/test_expedition_template_files.py
git commit -m "feat(phase2b): v1 expedition templates (marquee scripted + outer-marker rolled)"
```

---

## Task 10: Authoring guide + auto-regenerated reference tables

**Files:**
- Create: `docs/authoring/expeditions.md`
- Create: `scripts/build_authoring_docs.py`
- Create: `tests/test_authoring_docs_drift.py`

The authoring guide is **self-contained** — a fresh Claude session reading just this file should produce a valid template. Two reference tables (stat namespace + effect vocabulary) are auto-regenerated from the engine registries; the CI gate fails if the committed guide drifts from what the script produces.

- [ ] **Step 1: Write the auto-regenerator script**

Create `scripts/build_authoring_docs.py`:

```python
"""Regenerate the auto-managed reference tables in docs/authoring/expeditions.md.

The guide has two markers:

    <!-- BEGIN: STAT_NAMESPACE_TABLE -->
    ...auto-generated table...
    <!-- END: STAT_NAMESPACE_TABLE -->

    <!-- BEGIN: EFFECT_VOCABULARY_TABLE -->
    ...auto-generated table...
    <!-- END: EFFECT_VOCABULARY_TABLE -->

This script reads engine.stat_namespace.KNOWN_STAT_KEYS + archetype_for_stat
and engine.effect_registry.KNOWN_OPS, formats them as Markdown tables, and
rewrites the regions in-place.

CI runs this and fails if `git diff` is non-empty (i.e., the committed guide
is stale). Authors who change the engine registries must re-run this script
and commit the regenerated guide as part of the same PR.

Usage:
    python -m scripts.build_authoring_docs           # rewrites in place
    python -m scripts.build_authoring_docs --check   # exit 1 if dirty
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from engine.effect_registry import KNOWN_OPS
from engine.stat_namespace import KNOWN_STAT_KEYS, archetype_for_stat


_GUIDE = Path(__file__).resolve().parents[1] / "docs" / "authoring" / "expeditions.md"


def _stat_table() -> str:
    rows = ["| Key | Implicit archetype gate | Source |", "|---|---|---|"]
    for key in sorted(KNOWN_STAT_KEYS):
        gate = archetype_for_stat(key) or "—"
        if key.startswith("ship."):
            source = "resolved live from the locked build (engine/stat_resolver)"
        elif key.startswith("crew."):
            source = "aggregate across all assigned crew"
        else:
            source = f"the assigned {gate} crew member's stats"
        rows.append(f"| `{key}` | {gate} | {source} |")
    return "\n".join(rows)


def _effect_table() -> str:
    rows = ["| Op | Required params | Summary |", "|---|---|---|"]
    for name in sorted(KNOWN_OPS):
        spec = KNOWN_OPS[name]
        if spec["param_kind"] == "scalar_int":
            params = "(int value)"
        else:
            params = ", ".join(f"`{p}`" for p in spec["params"]) or "—"
        rows.append(f"| `{name}` | {params} | {spec['summary']} |")
    return "\n".join(rows)


_REGIONS = [
    ("STAT_NAMESPACE_TABLE", _stat_table),
    ("EFFECT_VOCABULARY_TABLE", _effect_table),
]


def regenerate(text: str) -> str:
    out = text
    for marker, builder in _REGIONS:
        pattern = re.compile(
            rf"(<!-- BEGIN: {marker} -->\n).*?(\n<!-- END: {marker} -->)",
            re.DOTALL,
        )
        replacement = rf"\g<1>{builder()}\g<2>"
        new_out, n = pattern.subn(replacement, out)
        if n != 1:
            raise RuntimeError(
                f"Marker {marker} not found exactly once in {_GUIDE}"
            )
        out = new_out
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if the file is out of date")
    args = parser.parse_args(argv)

    original = _GUIDE.read_text(encoding="utf-8")
    new_content = regenerate(original)

    if args.check:
        if new_content != original:
            print("docs/authoring/expeditions.md is out of date.", file=sys.stderr)
            print("Run `python -m scripts.build_authoring_docs` and commit.", file=sys.stderr)
            return 1
        return 0

    if new_content != original:
        _GUIDE.write_text(new_content, encoding="utf-8")
        print(f"Regenerated {_GUIDE}")
    else:
        print(f"{_GUIDE} already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write drift-detection test**

Create `tests/test_authoring_docs_drift.py`:

```python
"""CI gate: docs/authoring/expeditions.md must match the auto-generated tables."""

from __future__ import annotations

import subprocess
import sys


def test_authoring_docs_in_sync_with_engine():
    """Fail if the committed guide doesn't match what build_authoring_docs.py produces."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.build_authoring_docs", "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "docs/authoring/expeditions.md is out of date relative to the engine "
        "registries (engine/stat_namespace.py, engine/effect_registry.py).\n"
        "Run `python -m scripts.build_authoring_docs` and commit the result.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
```

- [ ] **Step 3: Author the guide skeleton with markers**

Create `docs/authoring/expeditions.md`:

````markdown
# Authoring Expedition Templates

> **If you are a Claude/LLM session helping a human author an expedition:** follow this loop:
>
> 1. Read this entire guide.
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
      30–80 for choice text and outcome narratives.

  - id: distress_beacon                    # a scene with choices
    narration: |
      Set the stakes here. The player is reading this in a Discord DM.
    choices:
      - id: investigate
        text: "Decelerate and bring them aboard."
        roll:                              # optional: gives this choice a stat-modified probability roll
          stat: navigator.luck             # one of the published stat namespace keys (see table below)
          base_p: 0.55                     # base probability of success (0..1)
          base_stat: 50                    # stat value at which p == base_p
          per_point: 0.005                 # +0.5pp for each stat point above base_stat
        outcomes:
          success:
            narrative: "What happens on success."
            effects:
              - reward_credits: 150
              - reward_xp: { archetype: NAVIGATOR, amount: 40 }
              - set_flag: { name: rescued_merchant }   # readable later by `has_flag` in closings
          failure:
            narrative: "What happens on failure."
            effects:
              - damage_part: { slot: drive, amount: 0.10 }
      - id: ignore
        text: "Mark the beacon and keep moving."
        default: true                      # exactly one choice per scene must be marked default
                                           # — the default fires on auto-resolve and must be ungated
        outcomes:                          # no `roll` → outcomes uses `result` (deterministic)
          result:
            narrative: "Default-branch narrative."
            effects:
              - reward_xp: { archetype: PILOT, amount: 20 }

  - id: closing                            # mark the closing scene
    is_closing: true
    closings:                              # closing variants — first match wins
      - when: { has_flag: rescued_merchant, min_successes: 2 }
        body: "Best-case ending."
        effects:
          - reward_credits: 500
      - when: { default: true }            # exactly one closing must be `default: true`
        body: "Fallback ending."
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
<!-- END: STAT_NAMESPACE_TABLE -->

## Outcome effect vocabulary

These are the closed-vocabulary operations an `outcome.effects` list may contain. Each effect is a dict with exactly one key (the op name).

<!-- BEGIN: EFFECT_VOCABULARY_TABLE -->
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
````

- [ ] **Step 4: Run the regenerator to populate the tables**

```bash
python -m scripts.build_authoring_docs
```

Expected: `Regenerated docs/authoring/expeditions.md`. The two `<!-- BEGIN ... -->` regions now contain populated markdown tables.

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_authoring_docs_drift.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/authoring/expeditions.md scripts/build_authoring_docs.py tests/test_authoring_docs_drift.py
git commit -m "feat(phase2b): authoring guide + auto-regenerator + CI drift gate"
```

---

## Task 11: Concurrency helper — `get_max_expeditions` + per-build / per-user checks

**Files:**
- Create: `engine/expedition_concurrency.py`
- Create: `tests/test_expedition_concurrency.py`

The cap function is intentionally a function call (not a column) so future raises (player level, premium tier) are a one-line implementation change with no schema migration.

- [ ] **Step 1: Write failing tests**

Create `tests/test_expedition_concurrency.py`:

```python
"""Per-user / per-build expedition concurrency cap."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_max_expeditions_default(db_session, sample_user):
    from engine.expedition_concurrency import get_max_expeditions
    assert await get_max_expeditions(db_session, sample_user) == 2


@pytest.mark.asyncio
async def test_count_active_expeditions_for_user_zero_when_none(
    db_session, sample_user
):
    from engine.expedition_concurrency import count_active_expeditions_for_user
    assert await count_active_expeditions_for_user(db_session, sample_user.discord_id) == 0


@pytest.mark.asyncio
async def test_count_active_expeditions_for_user_increments(
    db_session, sample_expedition_with_pilot
):
    from engine.expedition_concurrency import count_active_expeditions_for_user
    expedition, _ = sample_expedition_with_pilot
    assert await count_active_expeditions_for_user(
        db_session, expedition.user_id
    ) == 1


@pytest.mark.asyncio
async def test_build_has_active_expedition_true_when_locked(
    db_session, sample_expedition_with_pilot
):
    from engine.expedition_concurrency import build_has_active_expedition
    expedition, _ = sample_expedition_with_pilot
    assert await build_has_active_expedition(db_session, expedition.build_id) is True


@pytest.mark.asyncio
async def test_build_has_active_expedition_false_for_idle_build(
    db_session, sample_user
):
    from engine.expedition_concurrency import build_has_active_expedition
    from db.models import Build, BuildActivity, HullClass
    import uuid
    b = Build(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        name="Spinward", hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(b)
    await db_session.flush()
    assert await build_has_active_expedition(db_session, b.id) is False
```

- [ ] **Step 2: Add `sample_user` fixture if missing**

Verify `tests/conftest.py` has a `sample_user` fixture. Phase 2a's plan defined one. If absent:

```python
@pytest_asyncio.fixture
async def sample_user(db_session):
    from db.models import HullClass, User
    u = User(
        discord_id="testuser_1", username="testuser1",
        hull_class=HullClass.SKIRMISHER, currency=1000,
    )
    db_session.add(u)
    await db_session.flush()
    return u
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_expedition_concurrency.py -v`
Expected: 5 FAILs.

- [ ] **Step 4: Implement `engine/expedition_concurrency.py`**

Create `engine/expedition_concurrency.py`:

```python
"""Per-user / per-build expedition concurrency caps."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models import Expedition, ExpeditionState, User


async def get_max_expeditions(session: AsyncSession, user: User) -> int:
    """Return how many concurrent active expeditions this user is allowed.

    v1: returns the global default. Future: scale by user level, premium tier,
    or whatever raise mechanic we add. Always called via this function so the
    raise-path is a single-file change.
    """
    return settings.EXPEDITION_MAX_PER_USER_DEFAULT


async def count_active_expeditions_for_user(
    session: AsyncSession, user_id: str
) -> int:
    """Count ACTIVE expeditions for a user."""
    result = await session.execute(
        select(func.count())
        .select_from(Expedition)
        .where(Expedition.user_id == user_id)
        .where(Expedition.state == ExpeditionState.ACTIVE)
    )
    return int(result.scalar_one() or 0)


async def build_has_active_expedition(
    session: AsyncSession, build_id: uuid.UUID
) -> bool:
    """True iff there's an ACTIVE expedition on this build."""
    result = await session.execute(
        select(Expedition.id)
        .where(Expedition.build_id == build_id)
        .where(Expedition.state == ExpeditionState.ACTIVE)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_expedition_concurrency.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/expedition_concurrency.py tests/test_expedition_concurrency.py tests/conftest.py
git commit -m "feat(phase2b): per-user/per-build expedition concurrency helpers"
```

---

## Task 12: Engine — `resolve_scene`, `select_closing`, `_filter_visible_choices`

**Files:**
- Create: `engine/expedition_engine.py`
- Create: `tests/test_expedition_engine.py`

The single resolver shared by player-driven and auto-resolve paths. Picks visible choices, resolves a scene with stat-modified rolls, applies outcome effects, picks closing variants from accumulated state.

- [ ] **Step 1: Write failing tests**

Create `tests/test_expedition_engine.py`:

```python
"""Engine tests for resolve_scene, select_closing, _filter_visible_choices."""

from __future__ import annotations

import pytest


def test_filter_visible_choices_hides_archetype_gated(monkeypatch):
    from engine.expedition_engine import _filter_visible_choices

    scene = {
        "id": "test",
        "choices": [
            {"id": "always", "text": "ok", "default": True,
             "outcomes": {"result": {"narrative": "x", "effects": []}}},
            {"id": "engineer_only", "text": "ok",
             "requires": {"archetype": "ENGINEER"},
             "outcomes": {"result": {"narrative": "x", "effects": []}}},
        ],
    }
    visible = _filter_visible_choices(
        scene, assigned_archetypes={"PILOT"}, ship_hull_class="SKIRMISHER"
    )
    assert {c["id"] for c in visible} == {"always"}


def test_filter_visible_choices_hides_implicit_archetype_gate(monkeypatch):
    """A choice with `roll.stat: pilot.X` is hidden when no PILOT is assigned."""
    from engine.expedition_engine import _filter_visible_choices

    scene = {
        "id": "test",
        "choices": [
            {"id": "always", "text": "ok", "default": True,
             "outcomes": {"result": {"narrative": "x", "effects": []}}},
            {"id": "pilot_roll", "text": "ok",
             "roll": {"stat": "pilot.acceleration", "base_p": 0.5, "base_stat": 50, "per_point": 0.005},
             "outcomes": {
                 "success": {"narrative": "yes", "effects": []},
                 "failure": {"narrative": "no", "effects": []},
             }},
        ],
    }
    visible = _filter_visible_choices(
        scene, assigned_archetypes={"GUNNER"}, ship_hull_class="HAULER"
    )
    assert {c["id"] for c in visible} == {"always"}


def test_filter_visible_choices_keeps_default_always():
    """Default choice is always visible (validator enforces no requires)."""
    from engine.expedition_engine import _filter_visible_choices
    scene = {
        "id": "test",
        "choices": [
            {"id": "default_choice", "text": "ok", "default": True,
             "outcomes": {"result": {"narrative": "x", "effects": []}}},
        ],
    }
    visible = _filter_visible_choices(
        scene, assigned_archetypes=set(), ship_hull_class="SKIRMISHER"
    )
    assert {c["id"] for c in visible} == {"default_choice"}


def test_select_closing_first_match_wins():
    from engine.expedition_engine import select_closing
    closings = [
        {"when": {"min_successes": 99}, "body": "unreachable", "effects": []},
        {"when": {"min_successes": 1}, "body": "matched", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    state = {"successes": 2, "failures": 0, "flags": set()}
    selected = select_closing(closings, state)
    assert selected["body"] == "matched"


def test_select_closing_default_when_no_match():
    from engine.expedition_engine import select_closing
    closings = [
        {"when": {"min_successes": 99}, "body": "unreachable", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    state = {"successes": 0, "failures": 0, "flags": set()}
    selected = select_closing(closings, state)
    assert selected["body"] == "fallback"


def test_select_closing_has_flag_match():
    from engine.expedition_engine import select_closing
    closings = [
        {"when": {"has_flag": "rescued"}, "body": "good", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    selected = select_closing(closings, {
        "successes": 0, "failures": 0, "flags": {"rescued"},
    })
    assert selected["body"] == "good"


def test_select_closing_not_flag_match():
    from engine.expedition_engine import select_closing
    closings = [
        {"when": {"not_flag": "rescued"}, "body": "alone", "effects": []},
        {"when": {"default": True}, "body": "fallback", "effects": []},
    ]
    selected = select_closing(closings, {
        "successes": 0, "failures": 0, "flags": set(),
    })
    assert selected["body"] == "alone"


@pytest.mark.asyncio
async def test_resolve_scene_with_roll_records_outcome(
    db_session, sample_expedition_with_pilot
):
    """Successful roll should produce success branch + correct ledger write."""
    from engine.expedition_engine import resolve_scene
    expedition, _ = sample_expedition_with_pilot
    scene = {
        "id": "roll_test",
        "narration": "test",
        "choices": [
            {"id": "go", "text": "Go.", "default": True,
             "roll": {"stat": "pilot.acceleration", "base_p": 0.99,
                      "base_stat": 50, "per_point": 0.005},
             "outcomes": {
                 "success": {
                     "narrative": "yay",
                     "effects": [{"reward_credits": 100}],
                 },
                 "failure": {
                     "narrative": "boo",
                     "effects": [{"reward_credits": -50}],
                 },
             }},
        ],
    }
    resolution = await resolve_scene(
        db_session, expedition, scene, picked_choice_id="go",
    )
    assert resolution["choice_id"] == "go"
    assert resolution["outcome"]["narrative"] == "yay"
    assert resolution["roll"] is not None


@pytest.mark.asyncio
async def test_resolve_scene_seeded_rng_is_stable(
    db_session, sample_expedition_with_pilot
):
    """Re-resolving the same (expedition_id, scene_id) must produce the same rolled value."""
    from engine.expedition_engine import _seeded_random
    expedition, _ = sample_expedition_with_pilot
    a = _seeded_random(expedition.id, "scene_a")
    b = _seeded_random(expedition.id, "scene_a")
    assert a == b
    c = _seeded_random(expedition.id, "scene_b")
    assert a != c


@pytest.mark.asyncio
async def test_resolve_scene_default_when_no_pick(
    db_session, sample_expedition_with_pilot
):
    """auto_resolved=True when picked_choice_id is None."""
    from engine.expedition_engine import resolve_scene
    expedition, _ = sample_expedition_with_pilot
    scene = {
        "id": "auto_test",
        "narration": "test",
        "choices": [
            {"id": "comply", "text": "ok", "default": True,
             "outcomes": {"result": {
                 "narrative": "default",
                 "effects": [{"reward_credits": -10}],
             }}},
        ],
    }
    resolution = await resolve_scene(
        db_session, expedition, scene, picked_choice_id=None,
    )
    assert resolution["auto_resolved"] is True
    assert resolution["choice_id"] == "comply"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_expedition_engine.py -v`
Expected: 10 FAILs (`ImportError`).

- [ ] **Step 3: Implement `engine/expedition_engine.py`**

Create `engine/expedition_engine.py`:

```python
"""Expedition event resolver: shared by player-driven and auto-resolve paths.

Public API:
    resolve_scene(session, expedition, scene, picked_choice_id) -> SceneResolution
    select_closing(closings, accumulated_state) -> closing dict
    accumulated_state(expedition) -> {successes, failures, flags}
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Build, CrewArchetype, ExpeditionCrewAssignment,
)
from engine.effect_registry import apply_effect
from engine.stat_namespace import archetype_for_stat, read_stat


class SceneResolution(TypedDict):
    scene_id: str
    choice_id: str | None
    roll: dict | None
    outcome: dict
    auto_resolved: bool


async def _assigned_archetypes(
    session: AsyncSession, expedition_id: uuid.UUID
) -> set[str]:
    """The set of archetype names assigned on this expedition."""
    result = await session.execute(
        select(ExpeditionCrewAssignment.archetype)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
    )
    return {row[0].value if hasattr(row[0], "value") else str(row[0]) for row in result}


async def _ship_hull_class(session: AsyncSession, build_id: uuid.UUID) -> str:
    build = await session.get(Build, build_id)
    if build is None:
        return ""
    return build.hull_class.value if hasattr(build.hull_class, "value") else str(build.hull_class)


def _filter_visible_choices(
    scene: dict[str, Any],
    assigned_archetypes: set[str],
    ship_hull_class: str,
) -> list[dict[str, Any]]:
    """Drop choices whose `requires` or implicit archetype gate fails."""
    visible: list[dict[str, Any]] = []
    for c in scene.get("choices", []) or []:
        # Default is always visible (validator enforces no requires on default).
        if c.get("default"):
            visible.append(c)
            continue
        req = c.get("requires") or {}
        # Explicit archetype gate
        archetype_required = req.get("archetype")
        if archetype_required and archetype_required not in assigned_archetypes:
            continue
        # Hull class gate
        if "hull_class" in req and req["hull_class"] != ship_hull_class:
            continue
        # Implicit archetype gate from `roll.stat` (pilot.* / gunner.* / engineer.* / navigator.*)
        roll = c.get("roll") or {}
        implicit = archetype_for_stat(roll.get("stat", "")) if roll else None
        if implicit and implicit not in assigned_archetypes:
            continue
        visible.append(c)
    return visible


def _seeded_random(expedition_id: uuid.UUID, scene_id: str) -> float:
    """Deterministic PRNG: same (expedition_id, scene_id) → same float in [0,1)."""
    payload = f"{expedition_id}:{scene_id}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    # Take first 8 bytes as unsigned int, normalize to [0,1).
    return int.from_bytes(digest[:8], "big") / (2**64)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


async def resolve_scene(
    session: AsyncSession,
    expedition,
    scene: dict[str, Any],
    picked_choice_id: str | None,
) -> SceneResolution:
    """Resolve one scene.

    If the scene has no choices, applies the scene's outcome and returns.
    If the scene has choices, finds the chosen one (or falls back to default),
    optionally rolls a stat-modified probability, applies the outcome.
    Effect application is idempotent via apply_reward's source_id.
    """
    auto_resolved = picked_choice_id is None
    assigned_archetypes = await _assigned_archetypes(session, expedition.id)
    hull_class = await _ship_hull_class(session, expedition.build_id)

    # Narration-only scene (no choices)
    if not scene.get("choices"):
        outcome = scene.get("outcome", {"narrative": scene.get("narration", ""), "effects": []})
        for eff in outcome.get("effects", []) or []:
            await apply_effect(session, expedition, scene["id"], eff)
        return SceneResolution(
            scene_id=scene["id"], choice_id=None, roll=None,
            outcome=outcome, auto_resolved=auto_resolved,
        )

    visible = _filter_visible_choices(scene, assigned_archetypes, hull_class)
    visible_by_id = {c["id"]: c for c in visible}
    default = next((c for c in visible if c.get("default")), None)
    if default is None:
        # Validator should prevent this, but be defensive.
        raise RuntimeError(f"scene {scene['id']!r} has no default choice")

    if picked_choice_id and picked_choice_id in visible_by_id:
        choice = visible_by_id[picked_choice_id]
    else:
        choice = default

    roll_info: dict[str, Any] | None = None
    if "roll" in choice:
        spec = choice["roll"]
        stat_value = await read_stat(session, expedition, spec["stat"])
        if stat_value is None:
            # Implicit-archetype gate failed — fall back to default.
            choice = default
        else:
            base_p = spec["base_p"]
            base_stat = spec["base_stat"]
            per_point = spec["per_point"]
            p = base_p + (stat_value - base_stat) * per_point
            p = _clamp(
                p,
                spec.get("clamp_min", 0.05),
                spec.get("clamp_max", 0.95),
            )
            rolled = _seeded_random(expedition.id, scene["id"])
            success = rolled < p
            outcome = choice["outcomes"]["success" if success else "failure"]
            roll_info = {"stat": spec["stat"], "value": stat_value, "p": p, "rolled": rolled, "success": success}
            for eff in outcome.get("effects", []) or []:
                await apply_effect(session, expedition, scene["id"], eff)
            return SceneResolution(
                scene_id=scene["id"], choice_id=choice["id"], roll=roll_info,
                outcome=outcome, auto_resolved=auto_resolved,
            )

    # Deterministic / no-roll outcome path.
    outcome = choice["outcomes"]["result"]
    for eff in outcome.get("effects", []) or []:
        await apply_effect(session, expedition, scene["id"], eff)
    return SceneResolution(
        scene_id=scene["id"], choice_id=choice["id"], roll=None,
        outcome=outcome, auto_resolved=auto_resolved,
    )


def select_closing(
    closings: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Pick the first matching closing variant. `state` has keys: successes, failures, flags."""
    for c in closings:
        when = c.get("when") or {}
        if when.get("default"):
            return c  # if default appears earlier than any real match, that's a config bug
        if "min_successes" in when and state["successes"] < when["min_successes"]:
            continue
        if "max_failures" in when and state["failures"] > when["max_failures"]:
            continue
        if "has_flag" in when and when["has_flag"] not in state["flags"]:
            continue
        if "not_flag" in when and when["not_flag"] in state["flags"]:
            continue
        return c
    # Fallback: find the explicit default. Validator guarantees one exists.
    for c in closings:
        if (c.get("when") or {}).get("default"):
            return c
    raise RuntimeError("no closing matched and no default closing present")


def accumulated_state(expedition) -> dict[str, Any]:
    """Walk expedition.scene_log and compute {successes, failures, flags}."""
    successes = 0
    failures = 0
    flags: set[str] = set()
    for entry in expedition.scene_log or []:
        if entry.get("kind") == "flag":
            flags.add(entry.get("name"))
            continue
        # Status entries from scene resolutions:
        if entry.get("status") == "resolved":
            roll = entry.get("roll") or {}
            if roll:
                if roll.get("success"):
                    successes += 1
                else:
                    failures += 1
            else:
                # Deterministic outcome — count as success unless explicitly marked.
                # Authors can use `set_flag: failure_X` to influence closings instead.
                successes += 1
    return {"successes": successes, "failures": failures, "flags": flags}
```

The `_filter_visible_choices` correctly walks:
- Default → always visible.
- Explicit `requires.archetype` / `requires.hull_class` → checked against the player's loadout.
- Implicit archetype from `roll.stat` (per `engine.stat_namespace.archetype_for_stat`).

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_expedition_engine.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/expedition_engine.py tests/test_expedition_engine.py
git commit -m "feat(phase2b): expedition engine — resolve_scene, select_closing, choice filtering"
```

---

## Task 13: `EXPEDITION_EVENT` handler

When this job fires: load the scene, render the DM payload (text + button labels), enqueue the auto-resolve job, append a `pending` entry to `scene_log`. Return a `NotificationRequest` for the bot consumer.

**Files:**
- Create: `scheduler/jobs/expedition_event.py`
- Create: `tests/test_handler_expedition_event.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler_expedition_event.py`:

```python
"""EXPEDITION_EVENT handler — DM payload + auto-resolve enqueue + scene_log update."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_expedition_event_handler_enqueues_auto_resolve(
    db_session, sample_expedition_with_pilot
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event
    from sqlalchemy import select
    expedition, _ = sample_expedition_with_pilot

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    await db_session.flush()

    auto = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.job_type == JobType.EXPEDITION_AUTO_RESOLVE)
        .where(ScheduledJob.user_id == expedition.user_id)
    )).scalar_one_or_none()
    assert auto is not None
    assert auto.payload["scene_id"] == "pirate_skiff"
    assert auto.payload["expedition_id"] == str(expedition.id)


@pytest.mark.asyncio
async def test_expedition_event_handler_appends_pending_scene_log(
    db_session, sample_expedition_with_pilot
):
    from db.models import Expedition, JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event
    expedition, _ = sample_expedition_with_pilot

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_event(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    pending = [e for e in (refreshed.scene_log or [])
               if e.get("status") == "pending"
               and e.get("scene_id") == "pirate_skiff"]
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_expedition_event_handler_returns_notification(
    db_session, sample_expedition_with_pilot
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event
    expedition, _ = sample_expedition_with_pilot
    job = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    assert len(result.notifications) == 1
    notif = result.notifications[0]
    assert notif.user_id == expedition.user_id
    assert notif.category == "expedition_event"
    # Body should be a JSON-serializable payload that the bot consumer
    # can render into an embed + button view.
    assert "scene_id" in notif.body or "pirate_skiff" in notif.body


@pytest.mark.asyncio
async def test_expedition_event_handler_idempotent_skip_for_completed_expedition(
    db_session, sample_expedition_with_pilot
):
    """If the expedition is already COMPLETED/FAILED, the handler is a no-op."""
    from db.models import ExpeditionState, JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event
    expedition, _ = sample_expedition_with_pilot
    expedition.state = ExpeditionState.COMPLETED
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    assert result.notifications == []
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_event.py -v`
Expected: 4 FAILs (`ImportError`).

- [ ] **Step 3: Implement `scheduler/jobs/expedition_event.py`**

Create `scheduler/jobs/expedition_event.py`:

```python
"""EXPEDITION_EVENT handler.

Fires when a scheduled scene is due. Loads the scene from the template,
filters visible choices for the player's loadout, builds the DM payload,
enqueues the auto-resolve timeout job, appends a `pending` scene_log entry.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from config.settings import settings
from db.models import (
    Expedition, ExpeditionState, JobState, JobType, ScheduledJob,
)
from engine.expedition_engine import _filter_visible_choices, _assigned_archetypes, _ship_hull_class
from engine.expedition_template import load_template
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_expedition_event(
    session: AsyncSession, job: ScheduledJob
) -> HandlerResult:
    expedition_id = uuid.UUID(job.payload["expedition_id"])
    scene_id = job.payload["scene_id"]
    template_id = job.payload["template_id"]

    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        log.warning("expedition_event_handler: expedition not found id=%s", expedition_id)
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        # Idempotent skip — expedition already wrapped up.
        log.info("expedition_event_handler: skipping non-active state=%s id=%s",
                 expedition.state, expedition_id)
        return HandlerResult()

    template = load_template(template_id)
    scene = _find_scene(template, scene_id)
    if scene is None:
        log.error("expedition_event_handler: scene %s not found in template %s",
                  scene_id, template_id)
        return HandlerResult()

    # Filter visible choices for this player's loadout.
    archetypes = await _assigned_archetypes(session, expedition.id)
    hull_class = await _ship_hull_class(session, expedition.build_id)
    visible = _filter_visible_choices(scene, archetypes, hull_class)

    # Append `pending` log entry.
    scene_log = list(expedition.scene_log or [])
    scene_log.append({
        "scene_id": scene_id,
        "status": "pending",
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "visible_choice_ids": [c["id"] for c in visible],
    })
    expedition.scene_log = scene_log

    # Enqueue auto-resolve.
    response_window = template.get(
        "response_window_minutes",
        settings.EXPEDITION_RESPONSE_WINDOW_DEFAULT_MIN,
    )
    auto_resolve_at = datetime.now(timezone.utc) + timedelta(minutes=int(response_window))
    auto_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": scene_id,
            "template_id": template_id,
        },
        scheduled_for=auto_resolve_at,
        state=JobState.PENDING,
    )
    session.add(auto_job)
    await session.flush()

    # Build the bot-consumer payload. The bot consumer parses this JSON
    # and renders an embed + button view (Task 17).
    body = json.dumps({
        "type": "expedition_event",
        "expedition_id": str(expedition.id),
        "scene_id": scene_id,
        "narration": scene.get("narration", ""),
        "choices": [{"id": c["id"], "text": c["text"]} for c in visible],
        "auto_resolve_job_id": str(auto_job.id),
        "response_window_minutes": int(response_window),
    })

    return HandlerResult(notifications=[NotificationRequest(
        user_id=expedition.user_id,
        category="expedition_event",
        title=f"Expedition event — {scene_id}",
        body=body,
        correlation_id=str(expedition.correlation_id),
        dedupe_key=f"expedition:{expedition.id}:scene:{scene_id}",
    )])


def _find_scene(template: dict, scene_id: str) -> dict | None:
    if template["kind"] == "scripted":
        for s in template.get("scenes", []):
            if s.get("id") == scene_id:
                return s
        return None
    # rolled
    if template.get("opening", {}).get("id") == scene_id:
        return template["opening"]
    for s in template.get("events", []):
        if s.get("id") == scene_id:
            return s
    return None


register(JobType.EXPEDITION_EVENT, handle_expedition_event)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_event.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_event.py tests/test_handler_expedition_event.py
git commit -m "feat(phase2b): EXPEDITION_EVENT handler — DM payload + auto-resolve enqueue"
```

---

## Task 14: `EXPEDITION_AUTO_RESOLVE` handler

The "no response in window" path. Enqueues an `EXPEDITION_RESOLVE` with `picked_choice_id=None` so the resolver falls back to the scene's default choice.

**Files:**
- Create: `scheduler/jobs/expedition_auto_resolve.py`
- Create: `tests/test_handler_expedition_auto_resolve.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler_expedition_auto_resolve.py`:

```python
"""EXPEDITION_AUTO_RESOLVE — enqueue RESOLVE with no picked choice."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_auto_resolve_enqueues_resolve_job(
    db_session, sample_expedition_with_pilot
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_auto_resolve import handle_expedition_auto_resolve
    from sqlalchemy import select
    expedition, _ = sample_expedition_with_pilot

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_auto_resolve(db_session, job)
    await db_session.flush()

    resolves = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
        .where(ScheduledJob.user_id == expedition.user_id)
    )).scalars().all()
    assert len(resolves) == 1
    assert resolves[0].payload["picked_choice_id"] is None
    assert resolves[0].payload["auto_resolved"] is True
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_auto_resolve.py -v`
Expected: 1 FAIL.

- [ ] **Step 3: Implement `scheduler/jobs/expedition_auto_resolve.py`**

```python
"""EXPEDITION_AUTO_RESOLVE handler — fires when the response window elapses.

Enqueues an EXPEDITION_RESOLVE job with `picked_choice_id=None` so the
resolver uses the scene's default choice.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import JobState, JobType, ScheduledJob
from scheduler.dispatch import HandlerResult, register

log = get_logger(__name__)


async def handle_expedition_auto_resolve(
    session: AsyncSession, job: ScheduledJob
) -> HandlerResult:
    resolve = ScheduledJob(
        id=uuid.uuid4(),
        user_id=job.user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": job.payload["expedition_id"],
            "scene_id": job.payload["scene_id"],
            "template_id": job.payload["template_id"],
            "picked_choice_id": None,
            "auto_resolved": True,
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.PENDING,
    )
    session.add(resolve)
    await session.flush()
    return HandlerResult()


register(JobType.EXPEDITION_AUTO_RESOLVE, handle_expedition_auto_resolve)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_auto_resolve.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_auto_resolve.py tests/test_handler_expedition_auto_resolve.py
git commit -m "feat(phase2b): EXPEDITION_AUTO_RESOLVE handler — enqueue RESOLVE with default choice"
```

---

## Task 15: `EXPEDITION_RESOLVE` handler

The handler that calls `resolve_scene`, applies effects, updates `scene_log`, and emits the resolution narrative DM.

**Files:**
- Create: `scheduler/jobs/expedition_resolve.py`
- Create: `tests/test_handler_expedition_resolve.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler_expedition_resolve.py`:

```python
"""EXPEDITION_RESOLVE — invoke resolve_scene + update scene_log + emit DM."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


def _make_resolve_job(user_id, expedition_id, scene_id, picked, template_id="marquee_run"):
    from db.models import JobState, JobType, ScheduledJob
    return ScheduledJob(
        id=uuid.uuid4(), user_id=user_id, job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": str(expedition_id),
            "scene_id": scene_id,
            "template_id": template_id,
            "picked_choice_id": picked,
            "auto_resolved": picked is None,
        },
        scheduled_for=datetime.now(timezone.utc), state=JobState.CLAIMED,
    )


@pytest.mark.asyncio
async def test_resolve_handler_updates_scene_log_to_resolved(
    db_session, sample_expedition_with_pilot
):
    from db.models import Expedition
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve
    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z", "visible_choice_ids": ["outrun", "comply"]},
    ]
    await db_session.flush()

    job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
    db_session.add(job)
    await db_session.flush()
    await handle_expedition_resolve(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    assert refreshed.scene_log[0]["status"] == "resolved"
    assert refreshed.scene_log[0]["choice_id"] == "comply"


@pytest.mark.asyncio
async def test_resolve_handler_returns_notification(
    db_session, sample_expedition_with_pilot
):
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve
    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z", "visible_choice_ids": ["outrun", "comply"]},
    ]
    await db_session.flush()

    job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
    db_session.add(job)
    await db_session.flush()
    result = await handle_expedition_resolve(db_session, job)
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "expedition_resolution"


@pytest.mark.asyncio
async def test_resolve_handler_idempotent_on_re_fire(
    db_session, sample_expedition_with_pilot
):
    """Re-running RESOLVE for the same scene must not double-write rewards."""
    from db.models import RewardLedger
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve
    from sqlalchemy import func, select
    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z", "visible_choice_ids": ["outrun", "comply"]},
    ]
    await db_session.flush()

    for _ in range(2):
        job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
        db_session.add(job)
        await db_session.flush()
        await handle_expedition_resolve(db_session, job)
        await db_session.flush()

    cnt = (await db_session.execute(
        select(func.count()).select_from(RewardLedger)
        .where(RewardLedger.user_id == expedition.user_id)
    )).scalar_one()
    assert cnt == 1   # only one ledger row for the (expedition_id, scene_id) idempotency key
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_resolve.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement `scheduler/jobs/expedition_resolve.py`**

```python
"""EXPEDITION_RESOLVE handler — apply scene outcome + emit DM."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import Expedition, ExpeditionState, JobType, ScheduledJob
from engine.expedition_engine import resolve_scene
from engine.expedition_template import load_template
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_expedition_resolve(
    session: AsyncSession, job: ScheduledJob
) -> HandlerResult:
    expedition_id = uuid.UUID(job.payload["expedition_id"])
    scene_id = job.payload["scene_id"]
    template_id = job.payload["template_id"]
    picked = job.payload.get("picked_choice_id")
    auto_resolved = bool(job.payload.get("auto_resolved", False))

    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        log.warning("expedition_resolve: expedition %s not found", expedition_id)
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        log.info("expedition_resolve: skipping non-active state=%s id=%s",
                 expedition.state, expedition_id)
        return HandlerResult()

    template = load_template(template_id)
    scene = _find_scene(template, scene_id)
    if scene is None:
        log.error("expedition_resolve: scene %s not found in %s", scene_id, template_id)
        return HandlerResult()

    resolution = await resolve_scene(session, expedition, scene, picked)

    # Update scene_log: find the latest pending entry with this scene_id and resolve it.
    scene_log = list(expedition.scene_log or [])
    for entry in reversed(scene_log):
        if entry.get("scene_id") == scene_id and entry.get("status") == "pending":
            entry["status"] = "resolved"
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
            entry["choice_id"] = resolution["choice_id"]
            entry["roll"] = resolution["roll"]
            entry["narrative"] = resolution["outcome"].get("narrative")
            entry["auto_resolved"] = resolution["auto_resolved"]
            break
    expedition.scene_log = scene_log
    await session.flush()

    body = json.dumps({
        "type": "expedition_resolution",
        "expedition_id": str(expedition.id),
        "scene_id": scene_id,
        "narrative": resolution["outcome"].get("narrative", ""),
        "auto_resolved": auto_resolved,
        "roll": resolution["roll"],
    })
    return HandlerResult(notifications=[NotificationRequest(
        user_id=expedition.user_id,
        category="expedition_resolution",
        title=f"Expedition update — {scene_id}",
        body=body,
        correlation_id=str(expedition.correlation_id),
        dedupe_key=f"expedition:{expedition.id}:scene:{scene_id}:resolved",
    )])


def _find_scene(template: dict, scene_id: str) -> dict | None:
    if template["kind"] == "scripted":
        for s in template.get("scenes", []):
            if s.get("id") == scene_id:
                return s
        return None
    if template.get("opening", {}).get("id") == scene_id:
        return template["opening"]
    for s in template.get("events", []):
        if s.get("id") == scene_id:
            return s
    return None


register(JobType.EXPEDITION_RESOLVE, handle_expedition_resolve)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_resolve.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_resolve.py tests/test_handler_expedition_resolve.py
git commit -m "feat(phase2b): EXPEDITION_RESOLVE handler — apply outcome + emit narrative DM"
```

---

## Task 16: `EXPEDITION_COMPLETE` handler

The closing job. Picks the closing variant from accumulated state, applies its effects, sets `expedition.state = COMPLETED`, unlocks the build (`current_activity = IDLE`) and crew (`current_activity = IDLE`, preserving any `injured_until` set by mid-flight events).

**Files:**
- Create: `scheduler/jobs/expedition_complete.py`
- Create: `tests/test_handler_expedition_complete.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler_expedition_complete.py`:

```python
"""EXPEDITION_COMPLETE handler — closing variant + unlocks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


def _make_complete_job(user_id, expedition_id, template_id="marquee_run"):
    from db.models import JobState, JobType, ScheduledJob
    return ScheduledJob(
        id=uuid.uuid4(), user_id=user_id, job_type=JobType.EXPEDITION_COMPLETE,
        payload={"expedition_id": str(expedition_id), "template_id": template_id},
        scheduled_for=datetime.now(timezone.utc), state=JobState.CLAIMED,
    )


@pytest.mark.asyncio
async def test_complete_handler_sets_state_completed(
    db_session, sample_expedition_with_pilot
):
    from db.models import Build, BuildActivity, CrewActivity, CrewMember, Expedition, ExpeditionState
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    expedition, pilot = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "x", "status": "resolved", "roll": {"success": True}},
    ]
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job); await db_session.flush()
    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    assert refreshed.state == ExpeditionState.COMPLETED
    assert refreshed.outcome_summary is not None

    build = await db_session.get(Build, expedition.build_id)
    assert build.current_activity == BuildActivity.IDLE
    assert build.current_activity_id is None

    crew = await db_session.get(CrewMember, pilot.id)
    assert crew.current_activity == CrewActivity.IDLE
    assert crew.current_activity_id is None


@pytest.mark.asyncio
async def test_complete_handler_preserves_injured_until(
    db_session, sample_expedition_with_pilot
):
    from datetime import timedelta
    from db.models import CrewMember
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    expedition, pilot = sample_expedition_with_pilot
    pilot.injured_until = datetime.now(timezone.utc) + timedelta(hours=24)
    expedition.scene_log = []
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job); await db_session.flush()
    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(CrewMember, pilot.id)
    assert refreshed.injured_until is not None  # preserved


@pytest.mark.asyncio
async def test_complete_handler_emits_closing_dm(
    db_session, sample_expedition_with_pilot
):
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = []
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job); await db_session.flush()
    result = await handle_expedition_complete(db_session, job)
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "expedition_complete"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_expedition_complete.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement `scheduler/jobs/expedition_complete.py`**

```python
"""EXPEDITION_COMPLETE handler — closing variant + unlocks."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import (
    Build, BuildActivity, CrewActivity, CrewMember, Expedition,
    ExpeditionCrewAssignment, ExpeditionState, JobType, ScheduledJob,
)
from engine.effect_registry import apply_effect
from engine.expedition_engine import accumulated_state, select_closing
from engine.expedition_template import load_template
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_expedition_complete(
    session: AsyncSession, job: ScheduledJob
) -> HandlerResult:
    expedition_id = uuid.UUID(job.payload["expedition_id"])
    template_id = job.payload["template_id"]

    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        log.warning("expedition_complete: %s not found", expedition_id)
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        log.info("expedition_complete: already %s", expedition.state)
        return HandlerResult()

    template = load_template(template_id)
    closings = _all_closings(template)
    state = accumulated_state(expedition)
    closing = select_closing(closings, state)

    # Apply closing effects (idempotent via apply_reward source_id).
    for eff in closing.get("effects", []) or []:
        await apply_effect(session, expedition, scene_id="closing", effect=eff)

    # Build outcome summary.
    expedition.state = ExpeditionState.COMPLETED
    expedition.outcome_summary = {
        "closing_body": closing.get("body", ""),
        "successes": state["successes"],
        "failures": state["failures"],
        "flags": sorted(state["flags"]),
    }

    # Unlock build.
    build = await session.get(Build, expedition.build_id, with_for_update=True)
    if build is not None:
        build.current_activity = BuildActivity.IDLE
        build.current_activity_id = None

    # Unlock crew (preserve `injured_until` — that's a separate timestamp).
    assignments = (await session.execute(
        select(ExpeditionCrewAssignment.crew_id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition.id)
    )).scalars().all()
    if assignments:
        await session.execute(
            update(CrewMember)
            .where(CrewMember.id.in_(assignments))
            .values(current_activity=CrewActivity.IDLE, current_activity_id=None)
        )

    body = json.dumps({
        "type": "expedition_complete",
        "expedition_id": str(expedition.id),
        "narrative": closing.get("body", ""),
        "summary": expedition.outcome_summary,
    })
    return HandlerResult(notifications=[NotificationRequest(
        user_id=expedition.user_id,
        category="expedition_complete",
        title="Expedition complete",
        body=body,
        correlation_id=str(expedition.correlation_id),
        dedupe_key=f"expedition:{expedition.id}:complete",
    )])


def _all_closings(template: dict) -> list[dict]:
    if template["kind"] == "scripted":
        out: list[dict] = []
        for scene in template.get("scenes", []):
            if scene.get("is_closing"):
                out.extend(scene.get("closings", []))
        return out
    return list(template.get("closings", []))


register(JobType.EXPEDITION_COMPLETE, handle_expedition_complete)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_complete.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_complete.py tests/test_handler_expedition_complete.py
git commit -m "feat(phase2b): EXPEDITION_COMPLETE handler — closing variant + unlock build/crew"
```

---

## Task 17: Persistent button view + shared response method

The button view + its response handler. The handler is **shared** by buttons and the `/expedition respond` slash command (Task 20).

**Files:**
- Create: `bot/cogs/expeditions.py` (initial — view + response handler only; commands added in subsequent tasks)
- Create: `tests/test_cog_expedition_view.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_expedition_view.py`:

```python
"""Persistent expedition button view + atomic auto-resolve cancellation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_custom_id_format_parses():
    from bot.cogs.expeditions import parse_custom_id, build_custom_id
    eid = uuid.uuid4()
    cid = build_custom_id(eid, "scene_a", "outrun")
    parsed = parse_custom_id(cid)
    assert parsed == (eid, "scene_a", "outrun")


def test_parse_custom_id_rejects_non_expedition_prefix():
    from bot.cogs.expeditions import parse_custom_id
    assert parse_custom_id("training:abc:run") is None


@pytest.mark.asyncio
async def test_handle_response_cancels_auto_resolve_and_enqueues_resolve(
    db_session, sample_expedition_with_pilot
):
    from bot.cogs.expeditions import handle_expedition_response
    from db.models import JobState, JobType, ScheduledJob
    from sqlalchemy import select

    expedition, _ = sample_expedition_with_pilot
    auto = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id), "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc) + timedelta(minutes=30),
        state=JobState.PENDING,
    )
    db_session.add(auto)
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z",
         "visible_choice_ids": ["outrun", "comply"],
         "auto_resolve_job_id": str(auto.id)},
    ]
    await db_session.flush()

    outcome = await handle_expedition_response(
        db_session, expedition_id=expedition.id,
        scene_id="pirate_skiff", choice_id="outrun",
        invoking_user_id=expedition.user_id,
    )
    await db_session.flush()
    assert outcome["status"] == "accepted"

    refreshed_auto = await db_session.get(ScheduledJob, auto.id)
    assert refreshed_auto.state == JobState.CANCELLED

    resolves = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
        .where(ScheduledJob.user_id == expedition.user_id)
    )).scalars().all()
    assert len(resolves) == 1
    assert resolves[0].payload["picked_choice_id"] == "outrun"


@pytest.mark.asyncio
async def test_handle_response_too_late_when_auto_already_fired(
    db_session, sample_expedition_with_pilot
):
    from bot.cogs.expeditions import handle_expedition_response
    from db.models import JobState, JobType, ScheduledJob

    expedition, _ = sample_expedition_with_pilot
    auto = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id), "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.COMPLETED,  # already fired
    )
    db_session.add(auto)
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z",
         "visible_choice_ids": ["outrun", "comply"],
         "auto_resolve_job_id": str(auto.id)},
    ]
    await db_session.flush()

    outcome = await handle_expedition_response(
        db_session, expedition_id=expedition.id,
        scene_id="pirate_skiff", choice_id="outrun",
        invoking_user_id=expedition.user_id,
    )
    assert outcome["status"] == "too_late"


@pytest.mark.asyncio
async def test_handle_response_rejects_other_user(
    db_session, sample_expedition_with_pilot
):
    from bot.cogs.expeditions import handle_expedition_response
    expedition, _ = sample_expedition_with_pilot
    outcome = await handle_expedition_response(
        db_session, expedition_id=expedition.id,
        scene_id="pirate_skiff", choice_id="outrun",
        invoking_user_id="some_other_user",
    )
    assert outcome["status"] == "not_owner"


@pytest.mark.asyncio
async def test_handle_response_rejects_invalid_choice(
    db_session, sample_expedition_with_pilot
):
    from bot.cogs.expeditions import handle_expedition_response
    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z",
         "visible_choice_ids": ["outrun", "comply"],
         "auto_resolve_job_id": str(uuid.uuid4())},
    ]
    await db_session.flush()
    outcome = await handle_expedition_response(
        db_session, expedition_id=expedition.id,
        scene_id="pirate_skiff", choice_id="board_them",  # not visible to this loadout
        invoking_user_id=expedition.user_id,
    )
    assert outcome["status"] == "invalid_choice"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_expedition_view.py -v`
Expected: 6 FAILs (`ImportError`).

- [ ] **Step 3: Write `bot/cogs/expeditions.py` (view + response handler portion)**

Create `bot/cogs/expeditions.py`:

```python
"""Expeditions cog — persistent button view, response handler, slash commands.

This file is built up across Tasks 17-20:
  - Task 17 (now): persistent view + handle_expedition_response (shared)
  - Task 18: /expedition start
  - Task 19: /expedition status
  - Task 20: /expedition respond
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import (
    Expedition, ExpeditionState, JobState, JobType, ScheduledJob,
)
from db.session import async_session

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom ID parsing — buttons identify themselves with stable, parseable IDs
# so the persistent view works across bot restarts.
# ---------------------------------------------------------------------------

CUSTOM_ID_PREFIX = "expedition"


def build_custom_id(expedition_id: uuid.UUID, scene_id: str, choice_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{expedition_id}:{scene_id}:{choice_id}"


def parse_custom_id(custom_id: str) -> tuple[uuid.UUID, str, str] | None:
    parts = custom_id.split(":", 3)
    if len(parts) != 4 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    try:
        eid = uuid.UUID(parts[1])
    except ValueError:
        return None
    return (eid, parts[2], parts[3])


class ResponseOutcome(TypedDict):
    status: str   # one of: accepted, too_late, not_owner, invalid_choice, not_found, not_pending
    detail: str


# ---------------------------------------------------------------------------
# Shared response handler — called by both button clicks and /expedition respond.
# ---------------------------------------------------------------------------


async def handle_expedition_response(
    session: AsyncSession,
    *,
    expedition_id: uuid.UUID,
    scene_id: str,
    choice_id: str,
    invoking_user_id: str,
) -> ResponseOutcome:
    """Atomic: cancel auto-resolve PENDING → CANCELLED, enqueue RESOLVE with picked choice.

    Symmetric with Phase 2a's /training cancel. Exactly one of (this method,
    the auto-resolve worker) wins the race via the WHERE state = PENDING guard.
    """
    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        return {"status": "not_found", "detail": "expedition not found"}
    if expedition.user_id != invoking_user_id:
        return {"status": "not_owner", "detail": "this expedition belongs to another player"}
    if expedition.state != ExpeditionState.ACTIVE:
        return {"status": "not_pending", "detail": f"expedition is {expedition.state.value}"}

    # Find the most recent pending entry for this scene_id.
    pending_entry = None
    for entry in reversed(expedition.scene_log or []):
        if entry.get("scene_id") == scene_id and entry.get("status") == "pending":
            pending_entry = entry
            break
    if pending_entry is None:
        return {"status": "not_pending", "detail": f"no pending response on scene {scene_id}"}

    # Validate choice_id is in the scene's visible_choice_ids.
    visible_ids = pending_entry.get("visible_choice_ids", []) or []
    if choice_id not in visible_ids:
        return {"status": "invalid_choice", "detail": f"choice {choice_id} not available"}

    auto_job_id_str = pending_entry.get("auto_resolve_job_id")
    if not auto_job_id_str:
        return {"status": "not_pending", "detail": "scene_log missing auto_resolve_job_id"}
    auto_job_id = uuid.UUID(auto_job_id_str)

    # Atomic CAS: cancel auto-resolve only if still PENDING.
    result = await session.execute(
        update(ScheduledJob)
        .where(ScheduledJob.id == auto_job_id)
        .where(ScheduledJob.state == JobState.PENDING)
        .values(state=JobState.CANCELLED)
    )
    if (result.rowcount or 0) == 0:
        return {"status": "too_late", "detail": "auto-resolve already fired"}

    # Enqueue an immediate RESOLVE with the picked choice.
    resolve = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": scene_id,
            "template_id": pending_entry.get("template_id") or _infer_template_id(expedition),
            "picked_choice_id": choice_id,
            "auto_resolved": False,
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.PENDING,
    )
    session.add(resolve)
    return {"status": "accepted", "detail": f"choice {choice_id} committed"}


def _infer_template_id(expedition: Expedition) -> str:
    """Fallback if the pending entry doesn't include the template_id explicitly."""
    return expedition.template_id


# ---------------------------------------------------------------------------
# Persistent button view — registered globally in setup_hook.
# ---------------------------------------------------------------------------


class ExpeditionResponseView(discord.ui.View):
    """A persistent View that handles all expedition button clicks.

    Registered once at bot startup via `bot.add_view(ExpeditionResponseView())`.
    Doesn't pre-declare buttons — discord.py routes by custom_id when the View
    is registered as persistent. We use a single dynamic dispatcher on
    `interaction_check` to handle any custom_id starting with `expedition:`.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Buttons send their custom_id in interaction.data["custom_id"].
        custom_id = (interaction.data or {}).get("custom_id", "") if interaction.data else ""
        parsed = parse_custom_id(custom_id)
        if parsed is None:
            return False
        expedition_id, scene_id, choice_id = parsed

        async with async_session() as session, session.begin():
            outcome = await handle_expedition_response(
                session,
                expedition_id=expedition_id,
                scene_id=scene_id,
                choice_id=choice_id,
                invoking_user_id=str(interaction.user.id),
            )

        msg = _user_facing_message(outcome, choice_id)
        await interaction.response.send_message(msg, ephemeral=True)
        return False  # we've already responded; don't run a default callback


def _user_facing_message(outcome: ResponseOutcome, choice_id: str) -> str:
    s = outcome["status"]
    if s == "accepted":
        return f"Choice committed: **{choice_id}**. Standby for the result."
    if s == "too_late":
        return "Too late — that scene already auto-resolved."
    if s == "not_owner":
        return "This expedition belongs to another player."
    if s == "invalid_choice":
        return "That choice isn't available on your loadout."
    if s == "not_found":
        return "Expedition not found."
    return f"Couldn't process your response: {outcome.get('detail', s)}"


def build_button_components(
    expedition_id: uuid.UUID, scene_id: str,
    choices: list[dict[str, str]],
) -> list[discord.ui.Button]:
    """Build a list of Buttons for an event DM. Bot consumer attaches these to the embed."""
    out: list[discord.ui.Button] = []
    for c in choices[:5]:  # Discord caps at 5 buttons per row
        btn = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label=c["text"][:80],  # Discord caps at 80 chars
            custom_id=build_custom_id(expedition_id, scene_id, c["id"]),
        )
        out.append(btn)
    return out
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_expedition_view.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/expeditions.py tests/test_cog_expedition_view.py
git commit -m "feat(phase2b): persistent button view + shared expedition response handler"
```

---

## Task 18: `/expedition start` slash command

The cog command. Validates per the spec's order, atomically creates the Expedition row + assignments, queues all `EXPEDITION_EVENT` + `EXPEDITION_COMPLETE` jobs.

**Files:**
- Modify: `bot/cogs/expeditions.py`
- Create: `tests/test_cog_expedition_start.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_expedition_start.py`:

```python
"""/expedition start cog tests — each validation path + happy path."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest


def _make_interaction(user_id: str, channel_id: int = 222222222) -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id) if user_id.isdigit() else user_id
    inter.channel_id = channel_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_start_happy_path(db_session, sample_user, monkeypatch):
    """Happy path: build IDLE, crew IDLE, no existing expedition → starts."""
    from bot.cogs import expeditions as exp_mod
    from bot.system_gating import get_active_system
    from db.models import (
        Build, BuildActivity, CrewActivity, CrewArchetype, CrewMember,
        Expedition, HullClass, Rarity,
    )
    from sqlalchemy import select
    from tests.conftest import SessionWrapper

    build = Build(id=uuid.uuid4(), user_id=sample_user.discord_id,
                  name="Flagstaff", hull_class=HullClass.SKIRMISHER,
                  current_activity=BuildActivity.IDLE)
    db_session.add(build)
    pilot = CrewMember(id=uuid.uuid4(), user_id=sample_user.discord_id,
                       first_name="Mira", last_name="Voss", callsign="Sixgun",
                       archetype=CrewArchetype.PILOT, rarity=Rarity.RARE,
                       level=4, stats={"acceleration": 70},
                       current_activity=CrewActivity.IDLE)
    db_session.add(pilot)
    await db_session.flush()
    sample_user.currency = 1000
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(
        exp_mod, "get_active_system",
        create_autospec(get_active_system, return_value=MagicMock()),
    )

    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog, inter,
        template="marquee_run",
        build=str(build.id),
        pilot=f"{pilot.first_name} \"{pilot.callsign}\" {pilot.last_name}",
        gunner=None, engineer=None, navigator=None,
    )

    expeditions = (await db_session.execute(
        select(Expedition).where(Expedition.user_id == sample_user.discord_id)
    )).scalars().all()
    assert len(expeditions) == 1


@pytest.mark.asyncio
async def test_start_blocked_when_max_concurrent_reached(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    """User already has max active expeditions → refuses."""
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper

    expedition_a, _ = sample_expedition_with_pilot
    # Manufacture a second active expedition to hit the cap of 2.
    from db.models import (
        Build, BuildActivity, Expedition, ExpeditionState, HullClass,
    )
    b2 = Build(id=uuid.uuid4(), user_id=expedition_a.user_id,
               name="B2", hull_class=HullClass.SKIRMISHER,
               current_activity=BuildActivity.ON_EXPEDITION)
    db_session.add(b2)
    await db_session.flush()
    e2 = Expedition(id=uuid.uuid4(), user_id=expedition_a.user_id,
                    build_id=b2.id, template_id="outer_marker_patrol",
                    state=ExpeditionState.ACTIVE,
                    started_at=datetime.now(timezone.utc),
                    completes_at=datetime.now(timezone.utc) + timedelta(hours=4),
                    correlation_id=uuid.uuid4(), scene_log=[])
    db_session.add(e2); await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition_a.user_id)
    await cog.expedition_start.callback(
        cog, inter,
        template="outer_marker_patrol",
        build=str(uuid.uuid4()),
        pilot=None, gunner=None, engineer=None, navigator=None,
    )
    inter.response.send_message.assert_called_once()
    msg = inter.response.send_message.call_args.args[0]
    assert "limit" in msg.lower() or "max" in msg.lower() or "slot" in msg.lower()


@pytest.mark.asyncio
async def test_start_blocked_when_build_locked(db_session, sample_user, monkeypatch):
    from bot.cogs import expeditions as exp_mod
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    build = Build(id=uuid.uuid4(), user_id=sample_user.discord_id,
                  name="Locked", hull_class=HullClass.SKIRMISHER,
                  current_activity=BuildActivity.ON_EXPEDITION)
    db_session.add(build); await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog, inter, template="marquee_run", build=str(build.id),
        pilot=None, gunner=None, engineer=None, navigator=None,
    )
    msg = inter.response.send_message.call_args.args[0]
    assert "expedition" in msg.lower()


@pytest.mark.asyncio
async def test_start_blocked_when_insufficient_credits(
    db_session, sample_user, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    build = Build(id=uuid.uuid4(), user_id=sample_user.discord_id,
                  name="X", hull_class=HullClass.SKIRMISHER,
                  current_activity=BuildActivity.IDLE)
    db_session.add(build); await db_session.flush()
    sample_user.currency = 50  # marquee_run costs 250
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_start.callback(
        cog, inter, template="marquee_run", build=str(build.id),
        pilot=None, gunner=None, engineer=None, navigator=None,
    )
    msg = inter.response.send_message.call_args.args[0]
    assert "credit" in msg.lower()
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_expedition_start.py -v`
Expected: 4 FAILs.

- [ ] **Step 3: Append the cog class + `expedition_start` to `bot/cogs/expeditions.py`**

Append to `bot/cogs/expeditions.py`:

```python
# ---------------------------------------------------------------------------
# Cog with /expedition slash commands.
# ---------------------------------------------------------------------------

from datetime import timedelta
from random import Random

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from bot.system_gating import get_active_system, system_required_message
from config.settings import settings
from db.models import (
    Build, BuildActivity, CrewActivity, CrewArchetype, CrewMember,
    ExpeditionCrewAssignment, User,
)
from engine.expedition_concurrency import (
    build_has_active_expedition, count_active_expeditions_for_user,
    get_max_expeditions,
)
from engine.expedition_template import (
    TemplateValidationError, load_template,
)


class ExpeditionsCog(commands.Cog):
    """Phase 2b — /expedition start, status, respond."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    expedition = app_commands.Group(name="expedition", description="Multi-hour expeditions")

    @expedition.command(name="start", description="Launch a new expedition.")
    @app_commands.describe(
        template="Expedition template id",
        build="Which build (ship) to deploy",
        pilot="Optional: assigned PILOT (display name)",
        gunner="Optional: assigned GUNNER",
        engineer="Optional: assigned ENGINEER",
        navigator="Optional: assigned NAVIGATOR",
    )
    async def expedition_start(
        self,
        interaction: discord.Interaction,
        template: str,
        build: str,
        pilot: str | None = None,
        gunner: str | None = None,
        engineer: str | None = None,
        navigator: str | None = None,
    ) -> None:
        # 1. Template exists?
        try:
            tmpl = load_template(template)
        except (TemplateValidationError, FileNotFoundError):
            await interaction.response.send_message(
                f"Unknown template: `{template}`.", ephemeral=True
            )
            return

        async with async_session() as session, session.begin():
            sys = await get_active_system(interaction, session)
            if sys is None:
                await interaction.response.send_message(
                    system_required_message(), ephemeral=True,
                )
                return

            user = await session.get(
                User, str(interaction.user.id), with_for_update=True
            )
            if user is None:
                await interaction.response.send_message(
                    "You don't have a profile yet — run `/start` first.",
                    ephemeral=True,
                )
                return

            # 2. Concurrency cap
            max_active = await get_max_expeditions(session, user)
            current = await count_active_expeditions_for_user(session, user.discord_id)
            if current >= max_active:
                await interaction.response.send_message(
                    f"You're at the max active expedition limit ({current}/{max_active}). "
                    "Wait for one to complete.",
                    ephemeral=True,
                )
                return

            # 3. Cost
            cost = int(tmpl.get("cost_credits", 0))
            if user.currency < cost:
                await interaction.response.send_message(
                    f"You need {cost} credits — you have {user.currency}.",
                    ephemeral=True,
                )
                return

            # 4. Build owned, IDLE
            try:
                build_uuid = uuid.UUID(build)
            except ValueError:
                await interaction.response.send_message(
                    "Pick a valid build from the autocomplete list.", ephemeral=True,
                )
                return
            build_row = await session.get(Build, build_uuid, with_for_update=True)
            if build_row is None or build_row.user_id != user.discord_id:
                await interaction.response.send_message(
                    "Build not found in your fleet.", ephemeral=True,
                )
                return
            if build_row.current_activity != BuildActivity.IDLE:
                await interaction.response.send_message(
                    f"Build `{build_row.name}` is already on expedition.",
                    ephemeral=True,
                )
                return
            if await build_has_active_expedition(session, build_row.id):
                # Belt-and-suspenders against current_activity drift.
                await interaction.response.send_message(
                    f"Build `{build_row.name}` already has an active expedition.",
                    ephemeral=True,
                )
                return

            # 5. Resolve crew picks
            crew_picks: list[tuple[CrewArchetype, CrewMember]] = []
            for arche, display in (
                (CrewArchetype.PILOT, pilot),
                (CrewArchetype.GUNNER, gunner),
                (CrewArchetype.ENGINEER, engineer),
                (CrewArchetype.NAVIGATOR, navigator),
            ):
                if display is None:
                    continue
                row = await _lookup_crew_by_display(session, user.discord_id, display)
                if row is None:
                    await interaction.response.send_message(
                        f"Crew member `{display}` not found.", ephemeral=True,
                    )
                    return
                if row.archetype != arche:
                    await interaction.response.send_message(
                        f"`{display}` is a {row.archetype.value}, "
                        f"not a {arche.value}.", ephemeral=True,
                    )
                    return
                if row.current_activity != CrewActivity.IDLE:
                    await interaction.response.send_message(
                        f"`{display}` is currently {row.current_activity.value}.",
                        ephemeral=True,
                    )
                    return
                if row.injured_until and row.injured_until > datetime.now(timezone.utc):
                    await interaction.response.send_message(
                        f"`{display}` is recovering — back later.",
                        ephemeral=True,
                    )
                    return
                crew_picks.append((arche, row))

            # 6. crew_required minimums
            req = tmpl.get("crew_required", {}) or {}
            if len(crew_picks) < req.get("min", 0):
                await interaction.response.send_message(
                    f"Template `{template}` requires at least {req['min']} crew. "
                    f"You assigned {len(crew_picks)}.", ephemeral=True,
                )
                return
            picked_archetypes = {a.value for a, _ in crew_picks}
            if "archetypes_any" in req:
                if not (set(req["archetypes_any"]) & picked_archetypes):
                    await interaction.response.send_message(
                        f"Template `{template}` requires at least one of "
                        f"{req['archetypes_any']}. You assigned {sorted(picked_archetypes)}.",
                        ephemeral=True,
                    )
                    return
            if "archetypes_all" in req:
                missing = set(req["archetypes_all"]) - picked_archetypes
                if missing:
                    await interaction.response.send_message(
                        f"Template `{template}` requires all of "
                        f"{req['archetypes_all']}. Missing: {sorted(missing)}.",
                        ephemeral=True,
                    )
                    return

            # 7. Atomic creation
            now = datetime.now(timezone.utc)
            duration = int(tmpl["duration_minutes"])
            completes_at = now + timedelta(minutes=duration)
            expedition = Expedition(
                id=uuid.uuid4(), user_id=user.discord_id,
                build_id=build_row.id, template_id=template,
                state=ExpeditionState.ACTIVE,
                started_at=now, completes_at=completes_at,
                correlation_id=uuid.uuid4(), scene_log=[],
            )
            session.add(expedition)
            await session.flush()

            for arche, row in crew_picks:
                session.add(ExpeditionCrewAssignment(
                    expedition_id=expedition.id, crew_id=row.id, archetype=arche,
                ))
                row.current_activity = CrewActivity.ON_EXPEDITION
                row.current_activity_id = expedition.id
            build_row.current_activity = BuildActivity.ON_EXPEDITION
            build_row.current_activity_id = expedition.id
            user.currency -= cost
            await session.flush()

            # 8. Schedule events + completion
            scheduled_scenes = _select_scheduled_scenes(tmpl, expedition.id)
            spacing = duration / max(len(scheduled_scenes) + 1, 2)
            jitter_pct = settings.EXPEDITION_EVENT_JITTER_PCT / 100.0
            rng = Random(str(expedition.id))
            for i, scene_id in enumerate(scheduled_scenes, start=1):
                offset_min = spacing * i
                jitter_min = offset_min * jitter_pct * (rng.random() * 2 - 1)
                fire_at = now + timedelta(minutes=offset_min + jitter_min)
                session.add(ScheduledJob(
                    id=uuid.uuid4(), user_id=user.discord_id,
                    job_type=JobType.EXPEDITION_EVENT,
                    payload={
                        "expedition_id": str(expedition.id),
                        "scene_id": scene_id,
                        "template_id": template,
                    },
                    scheduled_for=fire_at, state=JobState.PENDING,
                ))
            session.add(ScheduledJob(
                id=uuid.uuid4(), user_id=user.discord_id,
                job_type=JobType.EXPEDITION_COMPLETE,
                payload={
                    "expedition_id": str(expedition.id),
                    "template_id": template,
                },
                scheduled_for=completes_at, state=JobState.PENDING,
            ))
            await session.flush()

        await interaction.response.send_message(
            f"**{tmpl.get('id', template)}** launched. ETA "
            f"{discord.utils.format_dt(completes_at, 'R')}.",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Helpers shared with /expedition status + respond.
# ---------------------------------------------------------------------------


def _select_scheduled_scenes(tmpl: dict, expedition_id: uuid.UUID) -> list[str]:
    """Return the ordered list of scene_ids that get EXPEDITION_EVENT jobs."""
    if tmpl["kind"] == "scripted":
        return [
            s["id"] for s in tmpl.get("scenes", [])
            if s.get("choices") and not s.get("is_closing")
        ]
    # rolled — sample event_count from pool with seeded RNG
    pool = tmpl.get("events", [])
    n = int(tmpl.get("event_count", 1))
    rng = Random(str(expedition_id))
    sampled = rng.sample(pool, k=min(n, len(pool)))
    return [s["id"] for s in sampled]


async def _lookup_crew_by_display(
    session: AsyncSession, user_id: str, display: str
) -> CrewMember | None:
    """Match a 'First "Callsign" Last' display string to a crew row."""
    result = await session.execute(
        select(CrewMember).where(CrewMember.user_id == user_id)
    )
    for row in result.scalars().all():
        if _format_display(row) == display:
            return row
    return None


def _format_display(crew: CrewMember) -> str:
    return f'{crew.first_name} "{crew.callsign}" {crew.last_name}'
```

Note: this references `Expedition`, `ExpeditionState`, `JobType`, `JobState`, `ScheduledJob` already in scope from the file's earlier imports — adjust to ensure they're imported.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_expedition_start.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/expeditions.py tests/test_cog_expedition_start.py
git commit -m "feat(phase2b): /expedition start cog command — full validation + atomic launch"
```

---

## Task 19: `/expedition status` slash command

Two render modes: no-arg (list active expeditions) and per-expedition (timeline from `scene_log`).

**Files:**
- Modify: `bot/cogs/expeditions.py`
- Create: `tests/test_cog_expedition_status.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_expedition_status.py`:

```python
"""/expedition status cog tests — list mode + per-expedition timeline mode."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_status_no_arg_shows_no_active_message(
    db_session, sample_user, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper
    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))

    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_status.callback(cog, inter, expedition=None)
    msg = inter.response.send_message.call_args.args[0]
    assert "no active" in msg.lower() or "none" in msg.lower()


@pytest.mark.asyncio
async def test_status_no_arg_lists_active(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper
    expedition, _ = sample_expedition_with_pilot

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.expedition_status.callback(cog, inter, expedition=None)
    msg = inter.response.send_message.call_args.args[0]
    assert "active" in msg.lower()
    assert expedition.template_id in msg or "marquee" in msg.lower() or "outer" in msg.lower()


@pytest.mark.asyncio
async def test_status_per_expedition_renders_timeline(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper
    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "resolved",
         "fired_at": "2026-04-26T12:00:00Z", "resolved_at": "2026-04-26T12:18:00Z",
         "choice_id": "outrun", "narrative": "Mira pins the throttle.",
         "auto_resolved": False, "roll": {"success": True}},
        {"scene_id": "scope_ghost", "status": "pending",
         "fired_at": "2026-04-26T14:00:00Z",
         "visible_choice_ids": ["pursue", "log_only"],
         "auto_resolve_job_id": str(uuid.uuid4())},
    ]
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.expedition_status.callback(cog, inter, expedition=str(expedition.id))
    msg = inter.response.send_message.call_args.args[0]
    assert "pirate_skiff" in msg or "outrun" in msg.lower()
    assert "scope_ghost" in msg or "pending" in msg.lower()
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_expedition_status.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Append `/expedition status` to `bot/cogs/expeditions.py`**

Append inside the `ExpeditionsCog` class (just after `expedition_start`):

```python
    @expedition.command(name="status", description="Status of your active expeditions.")
    @app_commands.describe(expedition="Optional: a specific expedition id for the timeline view.")
    async def expedition_status(
        self,
        interaction: discord.Interaction,
        expedition: str | None = None,
    ) -> None:
        async with async_session() as session:
            user_id = str(interaction.user.id)
            if expedition is None:
                # List mode: all ACTIVE expeditions for this user.
                rows = (await session.execute(
                    select(Expedition)
                    .where(Expedition.user_id == user_id)
                    .where(Expedition.state == ExpeditionState.ACTIVE)
                    .order_by(Expedition.completes_at)
                )).scalars().all()
                if not rows:
                    await interaction.response.send_message(
                        "No active expeditions.", ephemeral=True,
                    )
                    return
                max_active = await get_max_expeditions(session, await session.get(User, user_id))
                lines = [f"**Active expeditions** ({len(rows)} / {max_active} slots used)\n"]
                for ex in rows:
                    pending_count = sum(
                        1 for e in (ex.scene_log or []) if e.get("status") == "pending"
                    )
                    suffix = f" — {pending_count} event pending response now" if pending_count else ""
                    lines.append(
                        f"• `{ex.template_id}` — ETA "
                        f"{discord.utils.format_dt(ex.completes_at, 'R')}{suffix}"
                    )
                await interaction.response.send_message(
                    "\n".join(lines), ephemeral=True,
                )
                return

            # Timeline mode
            try:
                exp_uuid = uuid.UUID(expedition)
            except ValueError:
                await interaction.response.send_message(
                    "Pick an expedition from the autocomplete list.", ephemeral=True,
                )
                return
            ex = await session.get(Expedition, exp_uuid)
            if ex is None or ex.user_id != user_id:
                await interaction.response.send_message(
                    "Expedition not found.", ephemeral=True,
                )
                return
            await interaction.response.send_message(
                _render_timeline(ex), ephemeral=True,
            )


def _render_timeline(ex: Expedition) -> str:
    lines: list[str] = [
        f"**{ex.template_id}**",
        f"State: {ex.state.value}  ·  "
        f"ETA: {discord.utils.format_dt(ex.completes_at, 'R')}",
        "",
        "**Timeline**",
    ]
    if not ex.scene_log:
        lines.append("_(no scenes resolved yet)_")
    for entry in ex.scene_log or []:
        status = entry.get("status", "?")
        sid = entry.get("scene_id", "?")
        if status == "pending":
            lines.append(f"○ `{sid}` — pending response")
        elif status == "resolved":
            choice = entry.get("choice_id") or "default"
            outcome = "auto-resolved" if entry.get("auto_resolved") else f"chose {choice}"
            roll = entry.get("roll") or {}
            roll_note = ""
            if roll:
                roll_note = " (success)" if roll.get("success") else " (failure)"
            narr = entry.get("narrative", "")
            short = narr[:70] + "..." if len(narr) > 70 else narr
            lines.append(f"✓ `{sid}` — {outcome}{roll_note} — {short}")
        elif entry.get("kind") == "flag":
            lines.append(f"  · flag set: {entry.get('name')}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_expedition_status.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/expeditions.py tests/test_cog_expedition_status.py
git commit -m "feat(phase2b): /expedition status — list + timeline modes"
```

---

## Task 20: `/expedition respond` slash command

Slash-command fallback that reaches the same `handle_expedition_response` as the button view.

**Files:**
- Modify: `bot/cogs/expeditions.py`
- Create: `tests/test_cog_expedition_respond.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_expedition_respond.py`:

```python
"""/expedition respond — slash-command path through handle_expedition_response."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_respond_routes_through_handle_expedition_response(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from db.models import JobState, JobType, ScheduledJob
    from sqlalchemy import select
    from tests.conftest import SessionWrapper

    expedition, _ = sample_expedition_with_pilot
    auto = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={"expedition_id": str(expedition.id), "scene_id": "pirate_skiff",
                 "template_id": "marquee_run"},
        scheduled_for=datetime.now(timezone.utc) + timedelta(minutes=30),
        state=JobState.PENDING,
    )
    db_session.add(auto)
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z",
         "visible_choice_ids": ["outrun", "comply"],
         "auto_resolve_job_id": str(auto.id)},
    ]
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.expedition_respond.callback(
        cog, inter, expedition=str(expedition.id),
        scene="pirate_skiff", choice="outrun",
    )

    refreshed_auto = await db_session.get(ScheduledJob, auto.id)
    assert refreshed_auto.state == JobState.CANCELLED
    resolves = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
        .where(ScheduledJob.user_id == expedition.user_id)
    )).scalars().all()
    assert len(resolves) == 1
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_expedition_respond.py -v`
Expected: 1 FAIL.

- [ ] **Step 3: Append `/expedition respond` to `bot/cogs/expeditions.py`**

Append inside the `ExpeditionsCog` class:

```python
    @expedition.command(name="respond", description="Respond to a pending expedition event.")
    @app_commands.describe(
        expedition="Which expedition (defaults from autocomplete)",
        scene="Scene id with the pending event",
        choice="Choice id to commit",
    )
    async def expedition_respond(
        self,
        interaction: discord.Interaction,
        expedition: str,
        scene: str,
        choice: str,
    ) -> None:
        try:
            exp_uuid = uuid.UUID(expedition)
        except ValueError:
            await interaction.response.send_message(
                "Pick an expedition from the autocomplete list.", ephemeral=True,
            )
            return

        async with async_session() as session, session.begin():
            outcome = await handle_expedition_response(
                session,
                expedition_id=exp_uuid,
                scene_id=scene,
                choice_id=choice,
                invoking_user_id=str(interaction.user.id),
            )

        await interaction.response.send_message(
            _user_facing_message(outcome, choice), ephemeral=True,
        )


# Cog-level setup hook for `await bot.load_extension("bot.cogs.expeditions")`
async def setup(bot: commands.Bot) -> None:
    if not settings.EXPEDITIONS_ENABLED:
        log.info("expeditions cog skipped — EXPEDITIONS_ENABLED is False")
        return
    await bot.add_cog(ExpeditionsCog(bot))
    bot.add_view(ExpeditionResponseView())
    log.info("expeditions cog loaded + persistent view registered")
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_expedition_respond.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/expeditions.py tests/test_cog_expedition_respond.py
git commit -m "feat(phase2b): /expedition respond slash-command fallback + cog setup hook"
```

---

## Task 21: Wire the expeditions cog + scheduler handlers + persistent view into bot startup

**Files:**
- Modify: `bot/main.py`
- Modify: `scheduler/dispatch.py` (ensure handler imports)
- Modify: `scheduler/worker.py` (ensure handler imports)

The `register()` calls in `scheduler/jobs/expedition_*.py` happen at module import. Ensure those modules are imported when the worker starts and when the bot starts (the bot also dispatches some jobs at start time during recovery sweeps).

- [ ] **Step 1: Add expedition handler imports to `scheduler/worker.py`**

Find the worker entry point (`scheduler/worker.py`) and confirm there's an import block that loads the Phase 2a handlers (`scheduler.jobs.timer_complete`, `scheduler.jobs.accrual_tick`). Append the four expedition handlers:

```python
# Phase 2b expedition handlers (registers via side-effect import)
import scheduler.jobs.expedition_event  # noqa: F401
import scheduler.jobs.expedition_auto_resolve  # noqa: F401
import scheduler.jobs.expedition_resolve  # noqa: F401
import scheduler.jobs.expedition_complete  # noqa: F401
```

- [ ] **Step 2: Add expedition handler imports to bot startup**

In `bot/main.py`, find `setup_hook` where Phase 2a's `notification_consumer` is set up. Append the same imports there (so the cog tests don't break with missing handlers if they import bot.main):

```python
# Phase 2b expedition handlers (registered for side-effect; the bot doesn't dispatch
# them, but imports keep the dispatch registry consistent across processes)
import scheduler.jobs.expedition_event  # noqa: F401
import scheduler.jobs.expedition_auto_resolve  # noqa: F401
import scheduler.jobs.expedition_resolve  # noqa: F401
import scheduler.jobs.expedition_complete  # noqa: F401
```

- [ ] **Step 3: Add `bot.cogs.expeditions` to the cog load list in `bot/main.py`**

Find the existing cog list in `setup_hook`:

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
]
```

Append:

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
    "bot.cogs.expeditions",  # Phase 2b — gated by settings.EXPEDITIONS_ENABLED inside the cog's setup()
]
```

The cog's `setup()` (Task 20 step 3) already short-circuits when `settings.EXPEDITIONS_ENABLED is False`, so loading is safe in either state.

- [ ] **Step 4: Sanity test**

Run: `pytest tests/test_phase2b_models.py tests/test_handler_expedition_event.py tests/test_handler_expedition_resolve.py tests/test_handler_expedition_complete.py -v`
Expected: all PASS (the imports don't crash).

Run: `python -c "from scheduler.dispatch import HANDLERS; from db.models import JobType; assert JobType.EXPEDITION_EVENT in HANDLERS; print('all 4 expedition handlers registered')"`
Expected: prints success message.

- [ ] **Step 5: Commit**

```bash
git add scheduler/worker.py bot/main.py
git commit -m "feat(phase2b): wire expedition handlers + cog into bot + worker startup"
```

---

## Task 22: Build-mutation refusal in hangar cog

While a build is `current_activity = ON_EXPEDITION`, `/equip` and any other build-mutating cog must refuse with a clear "this ship is on expedition" message.

**Files:**
- Modify: `bot/cogs/hangar.py`
- Create: `tests/test_cog_hangar_build_lock.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_hangar_build_lock.py`:

```python
"""Hangar cog refuses build-mutation commands while build is ON_EXPEDITION."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.channel_id = 222222222
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_equip_refuses_when_build_on_expedition(
    db_session, sample_user, monkeypatch
):
    from bot.cogs import hangar as hangar_mod
    from bot.system_gating import get_active_system
    from db.models import (
        Build, BuildActivity, Card, HullClass, UserCard,
    )
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        name="Locked", hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()
    sample_user.active_build_id = build.id  # if hangar uses default-build pattern
    await db_session.flush()

    monkeypatch.setattr(hangar_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(
        hangar_mod, "get_active_system",
        create_autospec(get_active_system, return_value=MagicMock()),
    )

    cog = hangar_mod.HangarCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    # The exact equip command signature varies — read bot/cogs/hangar.py and
    # adjust this call to match (e.g., positional args, named args).
    await cog.equip.callback(cog, inter, card_id="any_card", slot="reactor")

    msg = inter.response.send_message.call_args.args[0]
    assert "expedition" in msg.lower()
```

This test assumes `/equip` exists with `card_id` + `slot` parameters. Inspect `bot/cogs/hangar.py` — adjust the call to match the actual signature.

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_hangar_build_lock.py -v`
Expected: FAIL — `/equip` doesn't currently check `current_activity`.

- [ ] **Step 3: Add the refusal check to `/equip` (and any build-mutation paths)**

Find every place in `bot/cogs/hangar.py` that mutates a `Build` row (equip, unequip, autoequip, set_default, mint, build new, build delete, etc.). Add this check immediately after looking up the build:

```python
from db.models import BuildActivity

# Inside the relevant command, after `build = await session.get(Build, build_id, ...)`:
if build.current_activity != BuildActivity.IDLE:
    eta_note = ""
    if build.current_activity == BuildActivity.ON_EXPEDITION:
        # Optional: look up the expedition for ETA. For v1 a simple message is enough.
        eta_note = " until it returns from expedition"
    await interaction.response.send_message(
        f"Build `{build.name}` is busy{eta_note} — can't modify it right now.",
        ephemeral=True,
    )
    return
```

Apply to:
- `/equip`
- `/unequip` (if exists)
- `/autoequip`
- `/build mint`
- `/build new` — only the build being mutated; new build creation is fine even if other builds are busy
- `/build set-default` — refuse only if SETTING a busy build as default? Or always allow? For v1, always allow (default-build switch doesn't mutate the build's content). Skip this one.
- `/build delete` — refuse with the same message.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_hangar_build_lock.py -v`
Expected: PASS.

Re-run the existing hangar test suite to verify no regressions:

```bash
pytest tests/test_cog_hangar.py tests/test_cog_hangar_build_lock.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/hangar.py tests/test_cog_hangar_build_lock.py
git commit -m "feat(phase2b): hangar refuses build-mutation while build is on expedition"
```

---

## Task 23: `/crew` + `/crew_inspect` display refresh

Surface the new `ON_EXPEDITION`, `INJURED` (via `injured_until`) states + a "Qualified for" section on `/crew_inspect`.

**Files:**
- Modify: `bot/cogs/hiring.py`
- Create: `tests/test_cog_hiring_display.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_hiring_display.py`:

```python
"""/crew + /crew_inspect display refresh tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_crew_roster_shows_on_expedition(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import hiring as hiring_mod
    from tests.conftest import SessionWrapper

    expedition, pilot = sample_expedition_with_pilot

    monkeypatch.setattr(
        hiring_mod, "async_session", lambda: SessionWrapper(db_session)
    )
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.crew.callback(cog, inter, filter=None)

    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    embed = kwargs.get("embed")
    assert embed is not None
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "ON_EXP" in flat or "expedition" in flat.lower()


@pytest.mark.asyncio
async def test_crew_roster_shows_injured(
    db_session, sample_user, monkeypatch
):
    from bot.cogs import hiring as hiring_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        first_name="Hurt", last_name="Body", callsign="Bandage",
        archetype=CrewArchetype.GUNNER, rarity=Rarity.COMMON, level=2,
        current_activity=CrewActivity.IDLE,
        injured_until=datetime.now(timezone.utc) + timedelta(hours=14),
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(
        hiring_mod, "async_session", lambda: SessionWrapper(db_session)
    )
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.crew.callback(cog, inter, filter=None)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "INJURED" in flat or "🩹" in flat or "recover" in flat.lower()


@pytest.mark.asyncio
async def test_crew_roster_idle_recovered_when_past_injured_until(
    db_session, sample_user, monkeypatch
):
    """A crew member with `injured_until` in the past is shown as IDLE."""
    from bot.cogs import hiring as hiring_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        first_name="Healed", last_name="Up", callsign="Up",
        archetype=CrewArchetype.GUNNER, rarity=Rarity.COMMON, level=2,
        current_activity=CrewActivity.IDLE,
        injured_until=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(crew); await db_session.flush()

    monkeypatch.setattr(
        hiring_mod, "async_session", lambda: SessionWrapper(db_session)
    )
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.crew.callback(cog, inter, filter=None)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "IDLE" in flat or "🟢" in flat
    # Must NOT show as INJURED
    assert "🩹" not in flat or "INJURED" not in flat


@pytest.mark.asyncio
async def test_crew_inspect_shows_qualified_for(
    db_session, sample_user, monkeypatch
):
    from bot.cogs import hiring as hiring_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    crew = CrewMember(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        first_name="Qual", last_name="Test", callsign="Q",
        archetype=CrewArchetype.PILOT, rarity=Rarity.RARE, level=3,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew); await db_session.flush()

    monkeypatch.setattr(
        hiring_mod, "async_session", lambda: SessionWrapper(db_session)
    )
    cog = hiring_mod.HiringCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.crew_inspect.callback(cog, inter, crew='Qual "Q" Test')
    embed = inter.response.send_message.call_args.kwargs["embed"]
    flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
    assert "Qualified for" in flat
    assert "PILOT" in flat
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_hiring_display.py -v`
Expected: 4 FAILs.

- [ ] **Step 3: Update `bot/cogs/hiring.py`**

Add the activity-icon helper near the top of the file (after imports):

```python
from datetime import datetime, timezone
from db.models import BuildActivity, CrewActivity


_ACTIVITY_ICON = {
    "IDLE": "🟢 IDLE",
    "TRAIN": "⚙️  TRAIN",
    "RESEARCH": "🔬 RESEARCH",
    "ON_STATION": "🛰️ ON_STATION",
    "ON_EXP": "🚀 ON_EXP",
    "INJURED": "🩹 INJURED",
}


def _crew_display_state(crew) -> str:
    """Compute the display label for a crew member's effective activity state."""
    now = datetime.now(timezone.utc)
    if crew.injured_until and crew.injured_until > now:
        return _ACTIVITY_ICON["INJURED"]
    if crew.current_activity == CrewActivity.ON_EXPEDITION:
        return _ACTIVITY_ICON["ON_EXP"]
    if crew.current_activity == CrewActivity.TRAINING:
        return _ACTIVITY_ICON["TRAIN"]
    if crew.current_activity == CrewActivity.RESEARCHING:
        return _ACTIVITY_ICON["RESEARCH"]
    if crew.current_activity == CrewActivity.ON_STATION:
        return _ACTIVITY_ICON["ON_STATION"]
    return _ACTIVITY_ICON["IDLE"]


def _crew_state_suffix(crew) -> str:
    """ETA / recovery hint shown next to the activity label."""
    now = datetime.now(timezone.utc)
    if crew.injured_until and crew.injured_until > now:
        delta = crew.injured_until - now
        hours = int(delta.total_seconds() / 3600)
        return f" (recovers in ~{hours}h)"
    return ""


def _qualified_for(crew) -> list[str]:
    """Return human-readable lines naming what activities/archetypes this crew suits."""
    lines: list[str] = []
    # Training routines: read engine.timer_recipes for level thresholds
    try:
        from engine.timer_recipes import list_recipes
        from db.models import TimerType
        for r in list_recipes(TimerType.TRAINING):
            min_lvl = r.get("min_crew_level", 1)
            mark = "✓" if crew.level >= min_lvl else "✗"
            lines.append(f"  • Training: {r['name']} (level ≥ {min_lvl} {mark})")
    except Exception:
        pass
    # Expeditions: any with the matching archetype slot
    lines.append(f"  • Expeditions: any with {crew.archetype.value} slot")
    # Stations: read station types
    try:
        from engine.station_types import list_station_types
        suitable = [s for s in list_station_types()
                    if crew.archetype.value in s.get("archetype_any", [])]
        if suitable:
            names = ", ".join(s["id"] for s in suitable)
            lines.append(f"  • Stations: {names}")
    except Exception:
        pass
    return lines
```

In the existing `/crew` command body, find the place that builds the embed roster and update each crew row to include the activity label:

```python
# When constructing each line of the roster embed:
state = _crew_display_state(row) + _crew_state_suffix(row)
line = f"{state}  {_format_display(row)}  {row.archetype.value}  Lvl {row.level}"
```

In the existing `/crew_inspect` command body, after the existing stats block, append:

```python
state_label = _crew_display_state(crew_row) + _crew_state_suffix(crew_row)
embed.add_field(
    name="Status",
    value=state_label,
    inline=False,
)
qualified_lines = "\n".join(_qualified_for(crew_row))
embed.add_field(
    name="Qualified for (derived from archetype + level)",
    value=qualified_lines or "—",
    inline=False,
)
```

If `_format_display` doesn't exist in `bot/cogs/hiring.py`, copy the helper from `bot/cogs/expeditions.py` (Task 18).

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_hiring_display.py tests/test_hiring_cog.py -v`
Expected: 4 new PASS + existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/hiring.py tests/test_cog_hiring_display.py
git commit -m "feat(phase2b): /crew + /crew_inspect surface ON_EXPEDITION + INJURED + qualified-for"
```

---

## Task 24: Phase 2b metrics

**Files:**
- Modify: `api/metrics.py`
- Modify: `tests/test_metrics.py` (or create if missing)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_metrics.py` (create if missing):

```python
def test_phase2b_metrics_exist():
    from api.metrics import (
        expeditions_started_total,
        expeditions_completed_total,
        expedition_events_fired_total,
        expedition_events_resolved_total,
        expedition_active,
        expedition_event_response_seconds,
    )
    # Touch one labelset on each to confirm they're real Prometheus metrics.
    expeditions_started_total.labels(template_id="x", kind="rolled").inc(0)
    expeditions_completed_total.labels(template_id="x", outcome="success").inc(0)
    expedition_events_fired_total.labels(template_id="x", scene_id="y").inc(0)
    expedition_events_resolved_total.labels(template_id="x", scene_id="y", source="auto").inc(0)
    expedition_active.set(0)
    expedition_event_response_seconds.labels(template_id="x").observe(0.0)
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_metrics.py::test_phase2b_metrics_exist -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Define the metrics in `api/metrics.py`**

Append to `api/metrics.py` (after the existing Phase 2a metrics):

```python
# ----------------------------------------------------------------- #
# Phase 2b — expedition metrics                                     #
# ----------------------------------------------------------------- #
expeditions_started_total = Counter(
    "dare2drive_expeditions_started_total",
    "Total expeditions started, labeled by template + kind",
    ["template_id", "kind"],
)
expeditions_completed_total = Counter(
    "dare2drive_expeditions_completed_total",
    "Total expeditions completed, labeled by template + outcome",
    ["template_id", "outcome"],
)
expedition_events_fired_total = Counter(
    "dare2drive_expedition_events_fired_total",
    "Mid-flight events fired, labeled by template + scene_id",
    ["template_id", "scene_id"],
)
expedition_events_resolved_total = Counter(
    "dare2drive_expedition_events_resolved_total",
    "Events resolved, labeled by template + scene_id + source (button|slash|auto)",
    ["template_id", "scene_id", "source"],
)
expedition_active = Gauge(
    "dare2drive_expedition_active",
    "Currently active expeditions across all users",
)
expedition_event_response_seconds = Histogram(
    "dare2drive_expedition_event_response_seconds",
    "How long players take to respond to a mid-flight event",
    ["template_id"],
    buckets=(5, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400),
)
```

The bucket choice (5s..4h) reflects the realistic distribution: most responses are within a minute or two, but some players check DMs hours after they're sent.

- [ ] **Step 4: Wire metrics into the handlers / cog**

The metrics need to be incremented at the right callsites. Make the following inserts:

In `bot/cogs/expeditions.py` `expedition_start` (just before `await interaction.response.send_message(...)` final):

```python
from api.metrics import expedition_active, expeditions_started_total
expeditions_started_total.labels(template_id=template, kind=tmpl["kind"]).inc()
expedition_active.inc()
```

In `scheduler/jobs/expedition_event.py` `handle_expedition_event` (just before `return HandlerResult(...)`):

```python
from api.metrics import expedition_events_fired_total
expedition_events_fired_total.labels(
    template_id=template_id, scene_id=scene_id,
).inc()
```

In `scheduler/jobs/expedition_resolve.py` `handle_expedition_resolve` (right after the scene_log update):

```python
from api.metrics import expedition_event_response_seconds, expedition_events_resolved_total

source = "auto" if auto_resolved else "player"   # cog-level can pass "button" vs "slash" via payload
expedition_events_resolved_total.labels(
    template_id=template_id, scene_id=scene_id, source=source,
).inc()

# Compute response time from pending entry's fired_at if present
fired_at_iso = next(
    (e.get("fired_at") for e in scene_log
     if e.get("scene_id") == scene_id and e.get("status") == "resolved"),
    None,
)
if fired_at_iso:
    fired_at = datetime.fromisoformat(fired_at_iso.replace("Z", "+00:00"))
    delta = (datetime.now(timezone.utc) - fired_at).total_seconds()
    expedition_event_response_seconds.labels(template_id=template_id).observe(delta)
```

In `scheduler/jobs/expedition_complete.py` `handle_expedition_complete` (just before `return HandlerResult(...)`):

```python
from api.metrics import expedition_active, expeditions_completed_total

# Outcome label: success if no failures, partial if mixed, failure if all failures
if state["failures"] == 0:
    outcome_label = "success"
elif state["successes"] == 0:
    outcome_label = "failure"
else:
    outcome_label = "partial"
expeditions_completed_total.labels(
    template_id=template_id, outcome=outcome_label,
).inc()
expedition_active.dec()
```

- [ ] **Step 5: Add a handler-side button/slash distinction (optional follow-up)**

The cog button handler and `/expedition respond` both end up at `handle_expedition_response`, which enqueues the RESOLVE job. The `source` label in `expedition_events_resolved_total` is currently `"auto"` or `"player"`. To distinguish button vs slash, plumb a `source` field into the RESOLVE payload:

In `bot/cogs/expeditions.py`'s `handle_expedition_response`, when enqueuing the RESOLVE job, set `payload["response_source"] = "button"` (from the view) or `"slash"` (from `/expedition respond`). Then the resolve handler reads this label.

Pass `response_source` from the View `interaction_check` and the `expedition_respond` callback distinctly. Update the RESOLVE handler to use it.

- [ ] **Step 6: Run, confirm passes**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS.

Run: `pytest tests/test_handler_expedition_event.py tests/test_handler_expedition_resolve.py tests/test_handler_expedition_complete.py tests/test_cog_expedition_start.py -v`
Expected: all still PASS (metrics inc shouldn't break anything).

- [ ] **Step 7: Commit**

```bash
git add api/metrics.py tests/test_metrics.py scheduler/jobs/expedition_event.py scheduler/jobs/expedition_resolve.py scheduler/jobs/expedition_complete.py bot/cogs/expeditions.py
git commit -m "feat(phase2b): expedition Prometheus metrics + handler/cog instrumentation"
```

---

## Task 25: End-to-end integration scenario

Full lifecycle test: start → event 1 → click → resolve → event 2 → no response → auto-resolve → complete. Mocked clock to fast-forward time.

**Files:**
- Create: `tests/scenarios/__init__.py` (if missing)
- Create: `tests/scenarios/test_expedition_flow.py`

- [ ] **Step 1: Write integration test**

Create `tests/scenarios/test_expedition_flow.py`:

```python
"""End-to-end expedition lifecycle: launch → 2 events → close → unlocks."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_full_expedition_lifecycle(db_session, sample_user):
    """Drive an expedition through every JobType in order, verify final state."""
    from bot.cogs.expeditions import handle_expedition_response
    from db.models import (
        Build, BuildActivity, CrewActivity, CrewArchetype, CrewMember,
        Expedition, ExpeditionState, HullClass, JobState, JobType,
        Rarity, RewardLedger, ScheduledJob,
    )
    from scheduler.jobs.expedition_auto_resolve import handle_expedition_auto_resolve
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    from scheduler.jobs.expedition_event import handle_expedition_event
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve
    from sqlalchemy import select

    # --- Set up: user, build, crew (PILOT + GUNNER) ---
    sample_user.currency = 1000
    build = Build(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        name="Flagstaff", hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)
    pilot = CrewMember(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        first_name="Mira", last_name="Voss", callsign="Sixgun",
        archetype=CrewArchetype.PILOT, rarity=Rarity.RARE, level=4,
        stats={"acceleration": 70, "luck": 40, "handling": 50},
        current_activity=CrewActivity.IDLE,
    )
    gunner = CrewMember(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        first_name="Jax", last_name="Krell", callsign="Blackjack",
        archetype=CrewArchetype.GUNNER, rarity=Rarity.RARE, level=3,
        stats={"combat": 65, "luck": 30},
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(pilot); db_session.add(gunner)
    await db_session.flush()

    # --- Manually launch the expedition (skipping the cog for test isolation) ---
    from db.models import ExpeditionCrewAssignment
    now = datetime.now(timezone.utc)
    expedition = Expedition(
        id=uuid.uuid4(), user_id=sample_user.discord_id,
        build_id=build.id, template_id="outer_marker_patrol",
        state=ExpeditionState.ACTIVE,
        started_at=now,
        completes_at=now + timedelta(hours=4),
        correlation_id=uuid.uuid4(), scene_log=[],
    )
    db_session.add(expedition)
    await db_session.flush()
    db_session.add(ExpeditionCrewAssignment(
        expedition_id=expedition.id, crew_id=pilot.id, archetype=CrewArchetype.PILOT,
    ))
    db_session.add(ExpeditionCrewAssignment(
        expedition_id=expedition.id, crew_id=gunner.id, archetype=CrewArchetype.GUNNER,
    ))
    build.current_activity = BuildActivity.ON_EXPEDITION
    build.current_activity_id = expedition.id
    pilot.current_activity = CrewActivity.ON_EXPEDITION
    gunner.current_activity = CrewActivity.ON_EXPEDITION
    pilot.current_activity_id = expedition.id
    gunner.current_activity_id = expedition.id
    await db_session.flush()

    # --- Phase 1: EVENT fires ---
    # Pick a real scene from outer_marker_patrol — drifting_wreck has both visible options
    event_job = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={"expedition_id": str(expedition.id),
                 "scene_id": "drifting_wreck",
                 "template_id": "outer_marker_patrol"},
        scheduled_for=now, state=JobState.CLAIMED,
    )
    db_session.add(event_job); await db_session.flush()
    result = await handle_expedition_event(db_session, event_job)
    await db_session.flush()
    assert len(result.notifications) == 1
    auto_job = (await db_session.execute(
        select(ScheduledJob).where(ScheduledJob.job_type == JobType.EXPEDITION_AUTO_RESOLVE)
    )).scalar_one()
    assert auto_job.state == JobState.PENDING

    # --- Phase 2: Player responds via button (handle_expedition_response) ---
    outcome = await handle_expedition_response(
        db_session, expedition_id=expedition.id,
        scene_id="drifting_wreck", choice_id="leave_it",
        invoking_user_id=expedition.user_id,
    )
    assert outcome["status"] == "accepted"
    await db_session.flush()
    refreshed_auto = await db_session.get(ScheduledJob, auto_job.id)
    assert refreshed_auto.state == JobState.CANCELLED

    # --- Phase 3: RESOLVE fires (auto-enqueued by handle_expedition_response) ---
    resolve = (await db_session.execute(
        select(ScheduledJob).where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
    )).scalar_one()
    resolve.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_resolve(db_session, resolve)
    await db_session.flush()

    # Now there should be a resolved entry in scene_log.
    refreshed = await db_session.get(Expedition, expedition.id)
    resolved = [e for e in refreshed.scene_log if e.get("status") == "resolved"]
    assert len(resolved) == 1

    # --- Phase 4: Second event fires, NO player response → auto-resolve fires ---
    event2 = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={"expedition_id": str(expedition.id),
                 "scene_id": "scope_ghost",
                 "template_id": "outer_marker_patrol"},
        scheduled_for=now + timedelta(hours=2), state=JobState.CLAIMED,
    )
    db_session.add(event2); await db_session.flush()
    await handle_expedition_event(db_session, event2)
    await db_session.flush()
    auto2 = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.job_type == JobType.EXPEDITION_AUTO_RESOLVE)
        .where(ScheduledJob.state == JobState.PENDING)
    )).scalar_one()
    auto2.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_auto_resolve(db_session, auto2)
    await db_session.flush()
    auto_resolve_resolve = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
        .where(ScheduledJob.state == JobState.PENDING)
    )).scalar_one()
    auto_resolve_resolve.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_resolve(db_session, auto_resolve_resolve)
    await db_session.flush()

    # --- Phase 5: COMPLETE fires ---
    complete = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_COMPLETE,
        payload={"expedition_id": str(expedition.id),
                 "template_id": "outer_marker_patrol"},
        scheduled_for=now + timedelta(hours=4), state=JobState.CLAIMED,
    )
    db_session.add(complete); await db_session.flush()
    result = await handle_expedition_complete(db_session, complete)
    await db_session.flush()

    # --- Verifications ---
    refreshed = await db_session.get(Expedition, expedition.id)
    assert refreshed.state == ExpeditionState.COMPLETED
    assert refreshed.outcome_summary is not None

    refreshed_build = await db_session.get(Build, build.id)
    assert refreshed_build.current_activity == BuildActivity.IDLE

    refreshed_pilot = await db_session.get(CrewMember, pilot.id)
    refreshed_gunner = await db_session.get(CrewMember, gunner.id)
    assert refreshed_pilot.current_activity == CrewActivity.IDLE
    assert refreshed_gunner.current_activity == CrewActivity.IDLE

    # At least one ledger row was written across the lifecycle.
    ledger_count = (await db_session.execute(
        select(RewardLedger).where(RewardLedger.user_id == expedition.user_id)
    )).scalars().all()
    assert len(ledger_count) >= 1
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/scenarios/test_expedition_flow.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_expedition_flow.py
git commit -m "test(phase2b): end-to-end expedition lifecycle scenario test"
```

---

## Task 26: Idempotency + race-resolution tests

Two adversarial properties:

1. **Idempotency:** double-fire of an `EXPEDITION_RESOLVE` job must not double-credit rewards.
2. **Race resolution:** simultaneous button-click + auto-resolve fire — exactly one wins via the `WHERE state = PENDING` guard.

**Files:**
- Modify: `tests/test_handler_expedition_resolve.py` (extend) or create `tests/test_expedition_idempotency.py`

- [ ] **Step 1: Add race test**

Append to `tests/test_handler_expedition_resolve.py` (or create a new file):

```python
@pytest.mark.asyncio
async def test_button_click_vs_auto_resolve_race_only_one_wins(
    db_session, sample_expedition_with_pilot
):
    """Simulate the race: both paths attempt the WHERE state=PENDING update."""
    from bot.cogs.expeditions import handle_expedition_response
    from db.models import JobState, JobType, ScheduledJob
    from sqlalchemy import select, update

    expedition, _ = sample_expedition_with_pilot
    auto = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.PENDING,
    )
    db_session.add(auto)
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z",
         "visible_choice_ids": ["outrun", "comply"],
         "auto_resolve_job_id": str(auto.id)},
    ]
    await db_session.flush()

    # Path A — button click:
    outcome_a = await handle_expedition_response(
        db_session, expedition_id=expedition.id,
        scene_id="pirate_skiff", choice_id="comply",
        invoking_user_id=expedition.user_id,
    )
    assert outcome_a["status"] == "accepted"

    # Path B (worker tick, post-A) — same `WHERE state = PENDING` flip:
    result = await db_session.execute(
        update(ScheduledJob)
        .where(ScheduledJob.id == auto.id)
        .where(ScheduledJob.state == JobState.PENDING)
        .values(state=JobState.CANCELLED)
    )
    # Should be 0 rowcount because A already flipped it.
    assert (result.rowcount or 0) == 0
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_resolve.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_handler_expedition_resolve.py
git commit -m "test(phase2b): button-vs-auto-resolve race resolution test"
```

---

## Task 27: Chaos test — worker mid-job kill + persistent-view restart

Validates the durability properties Phase 2a established carry over: kill the worker between event firing and resolution, restart, the resolution job is re-claimed and runs once. Persistent view re-binds across bot restart.

**Files:**
- Create: `tests/test_expedition_chaos.py`

- [ ] **Step 1: Write the chaos test**

Create `tests/test_expedition_chaos.py`:

```python
"""Chaos tests — worker kill mid-event recovery + persistent view restart."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_resolve_job_re_claim_runs_exactly_once(
    db_session, sample_expedition_with_pilot
):
    """Simulate: RESOLVE job is CLAIMED → worker dies → recovery sweep flips back to PENDING → re-fires.

    Idempotency from the (source_type, source_id) constraint means the
    second fire writes nothing new.
    """
    from db.models import JobState, JobType, RewardLedger, ScheduledJob
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve
    from sqlalchemy import func, select

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "pirate_skiff", "status": "pending",
         "fired_at": "2026-04-26T12:00:00Z",
         "visible_choice_ids": ["outrun", "comply"]},
    ]
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
            "picked_choice_id": "comply",
            "auto_resolved": False,
        },
        scheduled_for=datetime.now(timezone.utc), state=JobState.CLAIMED,
    )
    db_session.add(job); await db_session.flush()

    await handle_expedition_resolve(db_session, job)
    await db_session.flush()

    cnt_after_first = (await db_session.execute(
        select(func.count()).select_from(RewardLedger)
        .where(RewardLedger.user_id == expedition.user_id)
    )).scalar_one()

    # Now simulate recovery sweep: flip job back to PENDING and re-fire.
    job.state = JobState.PENDING
    await db_session.flush()
    job.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_resolve(db_session, job)
    await db_session.flush()

    cnt_after_second = (await db_session.execute(
        select(func.count()).select_from(RewardLedger)
        .where(RewardLedger.user_id == expedition.user_id)
    )).scalar_one()
    assert cnt_after_second == cnt_after_first
```

The persistent-view restart property is hard to test in-process (it requires real Discord state). It's covered manually:

> Manual smoke test on dev: launch a real expedition, wait for an event DM, restart the bot service via `railway service restart`, click the button on the DM. The click must succeed (the persistent view re-binds in `setup_hook`).

Document this in the test file's docstring.

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_expedition_chaos.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_expedition_chaos.py
git commit -m "test(phase2b): chaos — resolve-job re-claim is idempotent + persistent-view restart manual gate"
```

---

## Task 28: Roadmap update — insert Phase 2c (Tutorial v2)

Insert the Phase 2c stub before Phase 3 in the roadmap, mark Phase 3 as blocked on Phase 2c.

**Files:**
- Modify: `docs/roadmap/2026-04-22-salvage-pulp-revamp.md`

- [ ] **Step 1: Edit the roadmap**

Find the line `## Phase 3 — Job Board + Channel Events + Villain Takeovers + System Control` (it's around line 353 of the roadmap as of this writing). Insert this section **immediately before** that heading:

```markdown
## Phase 2c — Tutorial v2

**Status:** Blocked on Phase 2b. **Phase 3 is blocked on Phase 2c.**

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
```

- [ ] **Step 2: Update Phase 3's "Status:" line**

Find `## Phase 3 — Job Board ...` and update its Status line:

```markdown
**Status:** Blocked on Phase 2c.
```

(Was previously "Blocked on Phase 2b.")

- [ ] **Step 3: Commit**

```bash
git add docs/roadmap/2026-04-22-salvage-pulp-revamp.md
git commit -m "docs(roadmap): insert Phase 2c Tutorial v2; Phase 3 now blocked on 2c"
```

---

## Task 29: Grafana dashboard row + alerts

**Files:**
- Modify: `monitoring/grafana-stack/generate_scheduler_dashboard.py`
- Modify: `monitoring/grafana-stack/grafana/alerting/rules.yml`
- Modify: `monitoring/grafana-stack/dashboards/dare2drive-scheduler.json` (regenerated)

This is the monitoring submodule. Phase 2a's instructions used a separate PR for monitoring; do the same here. The submodule is at `monitoring/grafana-stack` pointing at the `dare2drive-monitoring` repo.

- [ ] **Step 1: Branch the submodule**

```bash
cd monitoring/grafana-stack
git fetch origin main
git checkout -b feat/phase-2b-expeditions-monitoring origin/main
```

- [ ] **Step 2: Add the new row to the dashboard generator**

Edit `monitoring/grafana-stack/generate_scheduler_dashboard.py`. Find the `elements = { ... }` block — append new panels (panel-8 through panel-12), and add a new `Expeditions` row to `layout`:

```python
elements["panel-8"] = stat_panel(
    8, "Active expeditions",
    "dare2drive_expedition_active",
    [{"color": "green", "value": None}, {"color": "yellow", "value": 100}],
)
elements["panel-9"] = timeseries_panel(
    9, "Expeditions started by template + kind",
    [query("A",
           "sum by (template_id, kind) (rate(dare2drive_expeditions_started_total[15m]))",
           "{{template_id}} {{kind}}")],
)
elements["panel-10"] = timeseries_panel(
    10, "Expedition event response time p50/p95/p99",
    [
        query("A", "histogram_quantile(0.5, sum by (le, template_id) (rate(dare2drive_expedition_event_response_seconds_bucket[15m])))", "p50 {{template_id}}"),
        query("B", "histogram_quantile(0.95, sum by (le, template_id) (rate(dare2drive_expedition_event_response_seconds_bucket[15m])))", "p95 {{template_id}}"),
        query("C", "histogram_quantile(0.99, sum by (le, template_id) (rate(dare2drive_expedition_event_response_seconds_bucket[15m])))", "p99 {{template_id}}"),
    ],
    unit="s",
)
elements["panel-11"] = timeseries_panel(
    11, "Auto-resolve rate per template",
    [query("A",
           "sum by (template_id) (rate(dare2drive_expedition_events_resolved_total{source=\"auto\"}[15m])) "
           "/ clamp_min(sum by (template_id) (rate(dare2drive_expedition_events_resolved_total[15m])), 0.001)",
           "{{template_id}}")],
    unit="percentunit",
)
elements["panel-12"] = timeseries_panel(
    12, "Expedition outcome distribution",
    [query("A",
           "sum by (template_id, outcome) (rate(dare2drive_expeditions_completed_total[1h]))",
           "{{template_id}} {{outcome}}")],
)
```

Append a new row to `layout["spec"]["rows"]`:

```python
row(
    "Expeditions",
    [
        grid_item("panel-8", 0, 0, 6, 6),
        grid_item("panel-9", 6, 0, 18, 6),
        grid_item("panel-10", 0, 6, 12, 8),
        grid_item("panel-11", 12, 6, 12, 8),
        grid_item("panel-12", 0, 14, 24, 8),
    ],
),
```

- [ ] **Step 3: Regenerate the JSON**

```bash
cd monitoring/grafana-stack
python generate_scheduler_dashboard.py
```

Expected: `Wrote dashboards/dare2drive-scheduler.json with 12 panels.`

- [ ] **Step 4: Add the two alerts**

Edit `monitoring/grafana-stack/grafana/alerting/rules.yml`. Append after the existing scheduler alerts:

```yaml
      # ------------------------------------------------------------------ #
      # Expedition Auto-Resolve Rate — UX issue if too many auto-resolve   #
      # ------------------------------------------------------------------ #
      - uid: expedition-auto-resolve-rate
        title: "ExpeditionAutoResolveRate"
        condition: B
        data:
          - refId: A
            relativeTimeRange: { from: 3600, to: 0 }
            datasourceUid: grafana_prometheus
            model:
              datasource: { type: prometheus, uid: grafana_prometheus }
              expr: >
                (sum by (template_id) (rate(dare2drive_expedition_events_resolved_total{source="auto"}[1h]))
                 / clamp_min(sum by (template_id) (rate(dare2drive_expedition_events_resolved_total[1h])), 0.001))
                * 100
              instant: true
              intervalMs: 1000
              maxDataPoints: 43200
              refId: A
          - refId: B
            relativeTimeRange: { from: 3600, to: 0 }
            datasourceUid: "-100"
            model:
              conditions:
                - evaluator: { params: [50], type: gt }
                  operator: { type: and }
                  query: { params: [A] }
                  reducer: { params: [], type: last }
                  type: query
              datasource: { type: __expr__, uid: "-100" }
              expression: A
              intervalMs: 1000
              maxDataPoints: 43200
              refId: B
              type: classic_conditions
        noDataState: OK
        execErrState: OK
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Expedition auto-resolve rate above 50% sustained 1h"
          description: "More than half of expedition events on a single template are auto-resolving. UX issue (DMs not landing, response window too short, or content disengaging)."
        isPaused: false

      # ------------------------------------------------------------------ #
      # Expedition Failure Rate — broken template / bad balance            #
      # ------------------------------------------------------------------ #
      - uid: expedition-failure-rate
        title: "ExpeditionFailureRate"
        condition: B
        data:
          - refId: A
            relativeTimeRange: { from: 3600, to: 0 }
            datasourceUid: grafana_prometheus
            model:
              datasource: { type: prometheus, uid: grafana_prometheus }
              expr: >
                (sum by (template_id) (rate(dare2drive_expeditions_completed_total{outcome="failure"}[1h]))
                 / clamp_min(sum by (template_id) (rate(dare2drive_expeditions_completed_total[1h])), 0.001))
                * 100
              instant: true
              intervalMs: 1000
              maxDataPoints: 43200
              refId: A
          - refId: B
            relativeTimeRange: { from: 3600, to: 0 }
            datasourceUid: "-100"
            model:
              conditions:
                - evaluator: { params: [95], type: gt }
                  operator: { type: and }
                  query: { params: [A] }
                  reducer: { params: [], type: last }
                  type: query
              datasource: { type: __expr__, uid: "-100" }
              expression: A
              intervalMs: 1000
              maxDataPoints: 43200
              refId: B
              type: classic_conditions
        noDataState: OK
        execErrState: OK
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Expedition failure rate above 95% on a template, sustained 1h"
          description: "A specific expedition template is producing >95% failure outcomes — broken template (validator missed something) or grossly unbalanced choice math."
        isPaused: false
```

- [ ] **Step 5: Commit, push, PR on the monitoring repo**

```bash
cd monitoring/grafana-stack
git add generate_scheduler_dashboard.py dashboards/dare2drive-scheduler.json grafana/alerting/rules.yml
git commit -m "feat(phase-2b): expedition dashboard row + 2 alerts"
git push -u origin feat/phase-2b-expeditions-monitoring
gh pr create --repo JordanGibbons/dare2drive-monitoring --base main \
  --head feat/phase-2b-expeditions-monitoring \
  --title "feat(phase-2b): expedition dashboard row + 2 alerts"
```

After the monitoring PR merges, bump the parent's submodule pointer in a small follow-up PR (same pattern as Phase 2a's monitoring follow-ups).

---

## Task 30: Rollout — railway config + flag flip plan

The cog's `setup()` is gated on `settings.EXPEDITIONS_ENABLED`. Schema + handlers + cog can merge while the flag is `False`. Once the migration is applied on prod and dev smoke-tests pass, flip the flag to `True`.

**Files:**
- No code changes in the parent repo for this task.
- Operational steps documented here as runbook.

- [ ] **Step 1: After all prior tasks are merged, apply the migration on dev**

```bash
railway environment dev
railway service api
railway run alembic upgrade head
```

Verify in Postgres:

```sql
SELECT 1 FROM expeditions LIMIT 0;
SELECT 1 FROM expedition_crew_assignments LIMIT 0;
\d builds
\d crew_members
```

- [ ] **Step 2: Flip the dev flag**

In Railway dashboard for the `dare2drive` (bot) service in dev, set:

```
EXPEDITIONS_ENABLED=true
```

Restart the service. Confirm the cog loads (Loki query: `{app="dare2drive"} |= "expeditions cog loaded"`).

Confirm the four expedition handlers are registered on the worker:

```bash
railway environment dev
railway service scheduler-worker
railway logs | grep "registered handler"
```

Expected: lines containing `expedition_event`, `expedition_auto_resolve`, `expedition_resolve`, `expedition_complete`.

- [ ] **Step 3: Smoke test the dev environment**

In a Discord channel with `/system enable`d:

1. `/expedition start template:outer_marker_patrol build:<your-build> pilot:<your-pilot>`
2. Wait for the first event DM (or use `/admin force_complete_expedition` to fast-forward — admin-only). For real-time testing, can also tweak template `duration_minutes` to something short locally.
3. Click a button. Confirm DM resolution arrives.
4. Wait for the second event. Don't respond. Confirm auto-resolve fires after the response window.
5. Wait for completion. Confirm the closing DM arrives. Confirm `/crew` shows the crew back to IDLE (with `injured_until` if injured) and the build IDLE.

If anything is off, add Loki queries with `correlation_id={{...}}` to trace the lifecycle.

- [ ] **Step 4: Apply the migration on prod**

Once dev is stable for at least 24 hours and the dashboard shows the new metrics flowing:

```bash
railway environment production
railway service api
railway run alembic upgrade head
```

- [ ] **Step 5: Flip the prod flag**

In Railway dashboard for the `dare2drive` service in prod, set:

```
EXPEDITIONS_ENABLED=true
```

Restart the service. Watch the dashboard's "Active expeditions" gauge — should start at 0 and tick up as players launch.

- [ ] **Step 6: After ~1 stable week, remove the flag**

Open a small PR that:

- Removes `EXPEDITIONS_ENABLED` from `config/settings.py`.
- Removes the `if not settings.EXPEDITIONS_ENABLED: return` guard from `bot/cogs/expeditions.py`'s `setup()`.

```bash
git checkout -b chore/remove-expeditions-enabled-flag
# edit config/settings.py + bot/cogs/expeditions.py
git commit -m "chore(phase2b): drop EXPEDITIONS_ENABLED feature flag — stable in prod"
git push -u origin chore/remove-expeditions-enabled-flag
gh pr create --base demo --title "chore(phase2b): drop EXPEDITIONS_ENABLED feature flag"
```

Also remove the env var from Railway dashboards (dev + prod) after the PR merges.

---

## Plan complete

This plan has 30 tasks. Every task includes failing-test → implementation → passing-test → commit. All file paths, code blocks, and commands are concrete.

The plan respects:

- **Spec coverage:** all 6 spec sections (data model, engine, cog UX, adjacent crew display, authoring format + validator, observability) map to tasks.
- **Spec invariants:** asymmetric risk + no permadeath (Task 7's effect registry has no permadeath ops); single-ship single-build (Task 3's schema; Task 18's per-build cap check); LLM-authorability (Tasks 5, 8, 9, 10 — schema, validator, templates, guide with auto-regen); per-user concurrency cap as a function (Task 11); build lock with no stat snapshot (Tasks 3, 18, 22).
- **Dev practices:** TDD throughout, frequent commits, exact code in every step.

Execution choice — pick one:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses superpowers:subagent-driven-development.

**2. Inline Execution** — Execute tasks in this session using superpowers:executing-plans, batch execution with checkpoints.

Which approach?
