# Phase 2a — Scheduler Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a durable, restart-safe scheduler-worker process plus three timer types (Training, Research, ShipBuild) and Station accrual, with Redis-stream-backed worker→bot notification delivery.

**Architecture:** A new `scheduler-worker` Railway service polls Postgres every 5s using `SELECT FOR UPDATE SKIP LOCKED`, dispatches due jobs to handlers in their own transactions, and emits notification requests to a Redis Stream. The bot consumes the stream, applies rate-limit + 30s batching, and sends DMs via discord.py. Postgres is the single source of truth; Redis is **not** in the scheduling path (documented as a future fast-path upgrade). Five new tables (`scheduled_jobs`, `timers`, `station_assignments`, `reward_ledger`, plus `notification_prefs` JSONB on `users` and `current_activity` columns on `crew_members`). One new cog (`bot/cogs/fleet.py`) exposes all timer + station + notification commands. Idempotency is enforced via `reward_ledger (source_type, source_id)` unique constraint with `ON CONFLICT DO NOTHING`.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, redis-py 5.x async client, discord.py 2.x, FastAPI (existing), Pillow (unused here), pytest + pytest-asyncio, Prometheus client, OpenTelemetry. No new top-level dependencies — `redis` is already in `pyproject.toml`.

**Spec:** [docs/superpowers/specs/2026-04-25-phase-2a-scheduler-foundation-design.md](../specs/2026-04-25-phase-2a-scheduler-foundation-design.md)

**Dev loop:** All tests run via `pytest` from the repo root. The `db_session` fixture in `tests/conftest.py` opens a per-test savepoint against the Docker Postgres (localhost:5432). `docker-compose up db redis` must be running for DB-backed and Redis-backed tests. Worker integration tests use a fresh process spawned via `subprocess` against the same Postgres.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0003_phase2a_scheduler.py` | Alembic migration: 4 new tables + 2 column extensions + 4 enums |
| `scripts/backfills/0003_crew_current_activity.py` | Backfill `crew_members.current_activity` from existing `crew_assignments` rows |
| `data/timers/training_routines.json` | 3 training recipe definitions |
| `data/timers/research_projects.json` | 3 research recipe definitions |
| `data/timers/ship_build_recipes.json` | 1 ship-build recipe ("Salvage Reconstruction") |
| `data/stations/station_types.json` | 3 station-type definitions |
| `engine/timer_recipes.py` | JSON loader + lookup for timer recipes |
| `engine/station_types.py` | JSON loader + lookup for station types |
| `engine/rewards.py` | `apply_reward` helper enforcing ledger idempotency |
| `scheduler/__init__.py` | Empty package marker |
| `scheduler/worker.py` | Worker process entry point: tracing, metrics, run_forever |
| `scheduler/engine.py` | `tick()` claim loop with `SELECT FOR UPDATE SKIP LOCKED` |
| `scheduler/dispatch.py` | Handler registry + per-job transaction wrapper |
| `scheduler/recovery.py` | `recovery_sweep()` for stuck claims + capped failures |
| `scheduler/jobs/__init__.py` | Empty package marker |
| `scheduler/jobs/timer_complete.py` | Handler for `timer_complete` job_type, dispatches by `timer_type` |
| `scheduler/jobs/accrual_tick.py` | Accrual handler + self-rescheduling |
| `scheduler/notifications.py` | `NotificationRequest` dataclass + Redis stream `xadd` helper |
| `scheduler/enqueue.py` | Cog-side helper: insert `Timer` + `ScheduledJob` atomically |
| `bot/cogs/fleet.py` | All Phase 2a slash commands: `/training`, `/research`, `/build`, `/stations`, `/claim`, `/notifications` |
| `bot/notifications.py` | Redis stream consumer + DM rate-limit/batching |
| `monitoring/grafana-stack/provisioning/dashboards/dare2drive-scheduler.json` | Scheduler health dashboard |
| `monitoring/grafana-stack/provisioning/alerting/scheduler-alerts.yaml` | Six scheduler/notification alerts |
| `tests/test_phase2a_models.py` | Schema-level tests for new models |
| `tests/test_phase2a_migration.py` | Migration round-trip + backfill correctness |
| `tests/test_timer_recipes.py` | Recipe loader tests |
| `tests/test_station_types.py` | Station-type loader tests |
| `tests/test_rewards.py` | Reward-ledger idempotency tests |
| `tests/test_scheduler_engine.py` | Tick + claim semantics tests (PG required) |
| `tests/test_scheduler_dispatch.py` | Dispatcher + handler-contract tests |
| `tests/test_scheduler_recovery.py` | Recovery sweep tests |
| `tests/test_handler_timer_complete.py` | timer_complete handler tests (per timer_type) |
| `tests/test_handler_accrual_tick.py` | accrual_tick handler tests |
| `tests/test_bot_notifications.py` | Bot consumer + rate-limit/batching tests |
| `tests/test_cog_fleet.py` | Cog command tests for `bot/cogs/fleet.py` |
| `tests/scenarios/test_timer_flow.py` | End-to-end timer scenario (start → fire → complete → DM) |
| `tests/scenarios/test_accrual_flow.py` | End-to-end accrual scenario |
| `tests/test_scheduler_chaos.py` | Worker mid-job kill + bot-offline drain |
| `tests/test_scheduler_load.py` | 1000 concurrent jobs perf test |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add 4 new enums, 4 new models, extend `CrewMember` (`current_activity`, `current_activity_id`) and `User` (`notification_prefs`) |
| `config/settings.py` | Add 11 scheduler + notification tunables |
| `api/metrics.py` | Add 11 new counters/gauges/histograms |
| `bot/main.py` | Load `FleetCog`, start `notification_consumer` task in `setup_hook`, cancel on close |
| `pyproject.toml` | Add `scheduler*` to `[tool.setuptools.packages.find].include`; add `scheduler` to coverage source |
| `railway.toml` | Add `scheduler-worker` service definition |
| `tests/conftest.py` | Add fixtures: `sample_user`, `sample_crew`, `sample_build`, `redis_client`, `clear_redis_streams` |

---

## Task 1: Settings tunables

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_settings.py` (create if missing)

- [ ] **Step 1: Write failing test**

Append to `tests/test_settings.py` (create the file if it doesn't exist with `from config.settings import settings`):

```python
def test_phase2a_scheduler_settings_defaults():
    from config.settings import settings
    assert settings.SCHEDULER_TICK_INTERVAL_SECONDS == 5
    assert settings.SCHEDULER_BATCH_SIZE == 100
    assert settings.SCHEDULER_MAX_ATTEMPTS == 3
    assert settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS == 300
    assert settings.SCHEDULER_RECOVERY_INTERVAL_SECS == 60
    assert settings.ACCRUAL_TICK_INTERVAL_MINUTES == 30
    assert settings.ACCRUAL_NOTIFICATION_THRESHOLD == 1000
    assert settings.TIMER_CANCEL_REFUND_PCT == 50
    assert settings.NOTIFICATION_RATE_LIMIT_PER_HOUR == 5
    assert settings.NOTIFICATION_BATCH_WINDOW_SECONDS == 30
    assert settings.NOTIFICATION_STREAM_MAXLEN == 10000
```

- [ ] **Step 2: Run test, confirm fails**

Run: `pytest tests/test_settings.py::test_phase2a_scheduler_settings_defaults -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'SCHEDULER_TICK_INTERVAL_SECONDS'`.

- [ ] **Step 3: Add tunables to `config/settings.py`**

Insert after the existing `LEGEND_CRATE_SIZE: int = 3` line (before `model_config = ...`):

```python
    # Phase 2a — Scheduler
    SCHEDULER_TICK_INTERVAL_SECONDS: int = 5
    SCHEDULER_BATCH_SIZE: int = 100
    SCHEDULER_MAX_ATTEMPTS: int = 3
    SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS: int = 300
    SCHEDULER_RECOVERY_INTERVAL_SECS: int = 60

    # Phase 2a — Accrual
    ACCRUAL_TICK_INTERVAL_MINUTES: int = 30
    ACCRUAL_NOTIFICATION_THRESHOLD: int = 1000

    # Phase 2a — Timers
    TIMER_CANCEL_REFUND_PCT: int = 50

    # Phase 2a — Notifications
    NOTIFICATION_RATE_LIMIT_PER_HOUR: int = 5
    NOTIFICATION_BATCH_WINDOW_SECONDS: int = 30
    NOTIFICATION_STREAM_MAXLEN: int = 10000
```

- [ ] **Step 4: Run test, confirm passes**

Run: `pytest tests/test_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_settings.py
git commit -m "feat(phase2a): add scheduler/notification tunables to settings"
```

---

## Task 2: Add Phase 2a enums to db/models.py

**Files:**
- Modify: `db/models.py`
- Create: `tests/test_phase2a_models.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_phase2a_models.py`:

```python
"""Phase 2a — schema-level tests for new enums and models."""

from __future__ import annotations


def test_job_type_enum_values():
    from db.models import JobType
    assert {j.value for j in JobType} == {"timer_complete", "accrual_tick"}


def test_job_state_enum_values():
    from db.models import JobState
    assert {s.value for s in JobState} == {
        "pending", "claimed", "completed", "failed", "cancelled",
    }


def test_timer_type_enum_values():
    from db.models import TimerType
    assert {t.value for t in TimerType} == {"training", "research", "ship_build"}


def test_timer_state_enum_values():
    from db.models import TimerState
    assert {s.value for s in TimerState} == {"active", "completed", "cancelled"}


def test_station_type_enum_values():
    from db.models import StationType
    assert {s.value for s in StationType} == {"cargo_run", "repair_bay", "watch_tower"}


def test_reward_source_type_enum_values():
    from db.models import RewardSourceType
    assert {s.value for s in RewardSourceType} == {
        "timer_complete", "accrual_tick", "accrual_claim", "timer_cancel_refund",
    }


def test_crew_activity_enum_values():
    from db.models import CrewActivity
    assert {a.value for a in CrewActivity} == {
        "idle", "on_build", "training", "researching", "on_station",
    }
```

- [ ] **Step 2: Run, confirm 7 fails**

Run: `pytest tests/test_phase2a_models.py -v`
Expected: 7 FAILs, `ImportError`.

- [ ] **Step 3: Add enums**

Insert after the existing `CrewArchetype` enum in `db/models.py`:

```python
class JobType(str, enum.Enum):
    TIMER_COMPLETE = "timer_complete"
    ACCRUAL_TICK = "accrual_tick"


class JobState(str, enum.Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TimerType(str, enum.Enum):
    TRAINING = "training"
    RESEARCH = "research"
    SHIP_BUILD = "ship_build"


class TimerState(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StationType(str, enum.Enum):
    CARGO_RUN = "cargo_run"
    REPAIR_BAY = "repair_bay"
    WATCH_TOWER = "watch_tower"


class RewardSourceType(str, enum.Enum):
    TIMER_COMPLETE = "timer_complete"
    ACCRUAL_TICK = "accrual_tick"
    ACCRUAL_CLAIM = "accrual_claim"
    TIMER_CANCEL_REFUND = "timer_cancel_refund"


class CrewActivity(str, enum.Enum):
    IDLE = "idle"
    ON_BUILD = "on_build"
    TRAINING = "training"
    RESEARCHING = "researching"
    ON_STATION = "on_station"
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_phase2a_models.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_phase2a_models.py
git commit -m "feat(phase2a): add scheduler/timer/station/reward/crew-activity enums"
```

---

## Task 3: Add Phase 2a models + extend CrewMember and User

**Files:**
- Modify: `db/models.py`
- Modify: `tests/test_phase2a_models.py`

- [ ] **Step 1: Append model-shape tests**

Append to `tests/test_phase2a_models.py`:

```python
def test_scheduled_job_columns():
    from db.models import ScheduledJob
    cols = {c.name for c in ScheduledJob.__table__.columns}
    assert cols >= {
        "id", "user_id", "job_type", "payload", "scheduled_for", "state",
        "claimed_at", "completed_at", "attempts", "last_error",
        "created_at", "updated_at",
    }


def test_timer_columns():
    from db.models import Timer
    cols = {c.name for c in Timer.__table__.columns}
    assert cols >= {
        "id", "user_id", "timer_type", "recipe_id", "payload",
        "started_at", "completes_at", "state", "linked_scheduled_job_id",
        "created_at", "updated_at",
    }


def test_station_assignment_columns():
    from db.models import StationAssignment
    cols = {c.name for c in StationAssignment.__table__.columns}
    assert cols >= {
        "id", "user_id", "station_type", "crew_id", "assigned_at",
        "last_yield_tick_at", "pending_credits", "pending_xp",
        "recalled_at", "created_at", "updated_at",
    }


def test_reward_ledger_columns():
    from db.models import RewardLedger
    cols = {c.name for c in RewardLedger.__table__.columns}
    assert cols >= {"id", "user_id", "source_type", "source_id", "delta", "applied_at"}


def test_crew_member_has_current_activity_columns():
    from db.models import CrewMember
    cols = {c.name for c in CrewMember.__table__.columns}
    assert {"current_activity", "current_activity_id"} <= cols


def test_user_has_notification_prefs():
    from db.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "notification_prefs" in cols
```

- [ ] **Step 2: Run, confirm 6 fails**

Run: `pytest tests/test_phase2a_models.py -v`
Expected: 6 new FAILs (`ImportError`).

- [ ] **Step 3: Update SQLAlchemy imports in `db/models.py`**

Update the existing `from sqlalchemy import (...)` block so it includes `BigInteger` and `Text`:

```python
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
```

- [ ] **Step 4: Append the four new models to `db/models.py`**

Append at the bottom of the file:

```python
# ──────────── Phase 2a: Scheduler / Timers / Accrual ────────────


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="pending",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_scheduled_jobs_pending_due",
            "state",
            "scheduled_for",
            postgresql_where="state IN ('pending', 'claimed')",
        ),
    )


class Timer(Base):
    __tablename__ = "timers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    timer_type: Mapped[TimerType] = mapped_column(
        Enum(TimerType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    recipe_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[TimerState] = mapped_column(
        Enum(TimerState, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="active",
    )
    linked_scheduled_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_jobs.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ux_timers_one_research_active",
            "user_id",
            unique=True,
            postgresql_where="timer_type = 'research' AND state = 'active'",
        ),
        Index(
            "ux_timers_one_ship_build_active",
            "user_id",
            unique=True,
            postgresql_where="timer_type = 'ship_build' AND state = 'active'",
        ),
    )


class StationAssignment(Base):
    __tablename__ = "station_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    station_type: Mapped[StationType] = mapped_column(
        Enum(StationType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    crew_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crew_members.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_yield_tick_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    pending_credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pending_xp: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    recalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ux_station_assignments_user_type_active",
            "user_id",
            "station_type",
            unique=True,
            postgresql_where="recalled_at IS NULL",
        ),
    )


class RewardLedger(Base):
    __tablename__ = "reward_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    source_type: Mapped[RewardSourceType] = mapped_column(
        Enum(RewardSourceType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    delta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="ux_reward_ledger_source"),
    )
```

- [ ] **Step 5: Extend `CrewMember` (existing class)**

Add these two columns inside the `CrewMember` class, immediately after `retired_at`:

```python
    current_activity: Mapped[CrewActivity] = mapped_column(
        Enum(CrewActivity, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="idle",
    )
    current_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
```

- [ ] **Step 6: Extend `User` (existing class)**

Add this column inside the `User` class, immediately after `last_daily`:

```python
    notification_prefs: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1}',
    )
```

- [ ] **Step 7: Run, confirm passes**

Run: `pytest tests/test_phase2a_models.py -v`
Expected: 13 PASS (7 enum tests from Task 2 + 6 new shape tests).

- [ ] **Step 8: Commit**

```bash
git add db/models.py tests/test_phase2a_models.py
git commit -m "feat(phase2a): add ScheduledJob/Timer/StationAssignment/RewardLedger + crew/user extensions"
```

---

## Task 4: Alembic migration `0003_phase2a_scheduler` + crew backfill

**Files:**
- Create: `db/migrations/versions/0003_phase2a_scheduler.py`
- Create: `scripts/backfills/0003_crew_current_activity.py`
- Create: `tests/test_phase2a_migration.py`

- [ ] **Step 1: Write failing migration round-trip tests**

Create `tests/test_phase2a_migration.py`:

```python
"""Round-trip + content tests for the 0003 phase 2a migration."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings


@pytest.mark.asyncio
async def test_phase2a_tables_exist_after_migration():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return set(insp.get_table_names())
        names = await conn.run_sync(_inspect)
    await engine.dispose()
    assert {"scheduled_jobs", "timers", "station_assignments", "reward_ledger"} <= names


@pytest.mark.asyncio
async def test_crew_members_has_current_activity_column():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [c["name"] for c in insp.get_columns("crew_members")]
        cols = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "current_activity" in cols
    assert "current_activity_id" in cols


@pytest.mark.asyncio
async def test_users_has_notification_prefs_column():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [c["name"] for c in insp.get_columns("users")]
        cols = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "notification_prefs" in cols


@pytest.mark.asyncio
async def test_reward_ledger_unique_source_constraint():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [uc["name"] for uc in insp.get_unique_constraints("reward_ledger")]
        uqs = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "ux_reward_ledger_source" in uqs


@pytest.mark.asyncio
async def test_timers_partial_unique_indexes():
    """Verify partial unique indexes for one-active-research / one-active-build per user."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [i["name"] for i in insp.get_indexes("timers")]
        idx_names = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "ux_timers_one_research_active" in idx_names
    assert "ux_timers_one_ship_build_active" in idx_names
```

- [ ] **Step 2: Run, confirm all fail**

Run: `pytest tests/test_phase2a_migration.py -v`
Expected: 5 FAILs (tables / columns / constraints don't exist).

- [ ] **Step 3: Create the migration**

Create `db/migrations/versions/0003_phase2a_scheduler.py`:

```python
"""phase 2a scheduler foundation

Revision ID: 0003_phase2a_scheduler
Revises: 0002_phase1_crew
Create Date: 2026-04-25

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_phase2a_scheduler"
down_revision = "0002_phase1_crew"
branch_labels = None
depends_on = None


JOB_TYPE = ("timer_complete", "accrual_tick")
JOB_STATE = ("pending", "claimed", "completed", "failed", "cancelled")
TIMER_TYPE = ("training", "research", "ship_build")
TIMER_STATE = ("active", "completed", "cancelled")
STATION_TYPE = ("cargo_run", "repair_bay", "watch_tower")
REWARD_SOURCE_TYPE = (
    "timer_complete", "accrual_tick", "accrual_claim", "timer_cancel_refund",
)
CREW_ACTIVITY = ("idle", "on_build", "training", "researching", "on_station")

DEFAULT_NOTIFICATION_PREFS = (
    '{"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1}'
)


def upgrade() -> None:
    bind = op.get_bind()

    # Create new enums.
    job_type = postgresql.ENUM(*JOB_TYPE, name="jobtype", create_type=False)
    job_state = postgresql.ENUM(*JOB_STATE, name="jobstate", create_type=False)
    timer_type = postgresql.ENUM(*TIMER_TYPE, name="timertype", create_type=False)
    timer_state = postgresql.ENUM(*TIMER_STATE, name="timerstate", create_type=False)
    station_type = postgresql.ENUM(*STATION_TYPE, name="stationtype", create_type=False)
    reward_source = postgresql.ENUM(
        *REWARD_SOURCE_TYPE, name="rewardsourcetype", create_type=False
    )
    crew_activity = postgresql.ENUM(*CREW_ACTIVITY, name="crewactivity", create_type=False)
    for e in (job_type, job_state, timer_type, timer_state, station_type, reward_source, crew_activity):
        e.create(bind, checkfirst=True)

    # scheduled_jobs
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", job_state, nullable=False, server_default="pending"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_scheduled_jobs_pending_due",
        "scheduled_jobs",
        ["state", "scheduled_for"],
        postgresql_where=sa.text("state IN ('pending', 'claimed')"),
    )

    # timers
    op.create_table(
        "timers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("timer_type", timer_type, nullable=False),
        sa.Column("recipe_id", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", timer_state, nullable=False, server_default="active"),
        sa.Column(
            "linked_scheduled_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_timers_one_research_active",
        "timers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("timer_type = 'research' AND state = 'active'"),
    )
    op.create_index(
        "ux_timers_one_ship_build_active",
        "timers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("timer_type = 'ship_build' AND state = 'active'"),
    )

    # station_assignments
    op.create_table(
        "station_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("station_type", station_type, nullable=False),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_yield_tick_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("pending_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_station_assignments_user_type_active",
        "station_assignments",
        ["user_id", "station_type"],
        unique=True,
        postgresql_where=sa.text("recalled_at IS NULL"),
    )

    # reward_ledger
    op.create_table(
        "reward_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", reward_source, nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("delta", postgresql.JSONB, nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source_type", "source_id", name="ux_reward_ledger_source"),
    )

    # Extend crew_members
    op.add_column(
        "crew_members",
        sa.Column("current_activity", crew_activity, nullable=False, server_default="idle"),
    )
    op.add_column(
        "crew_members",
        sa.Column("current_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Extend users
    op.add_column(
        "users",
        sa.Column(
            "notification_prefs",
            postgresql.JSONB,
            nullable=False,
            server_default=DEFAULT_NOTIFICATION_PREFS,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_prefs")
    op.drop_column("crew_members", "current_activity_id")
    op.drop_column("crew_members", "current_activity")
    op.drop_table("reward_ledger")
    op.drop_index(
        "ux_station_assignments_user_type_active", table_name="station_assignments"
    )
    op.drop_table("station_assignments")
    op.drop_index("ux_timers_one_ship_build_active", table_name="timers")
    op.drop_index("ux_timers_one_research_active", table_name="timers")
    op.drop_table("timers")
    op.drop_index("ix_scheduled_jobs_pending_due", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")

    bind = op.get_bind()
    for name in (
        "crewactivity",
        "rewardsourcetype",
        "stationtype",
        "timerstate",
        "timertype",
        "jobstate",
        "jobtype",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
```

- [ ] **Step 4: Apply migration**

Run: `alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade 0002_phase1_crew -> 0003_phase2a_scheduler`.

- [ ] **Step 5: Run round-trip tests, confirm pass**

Run: `pytest tests/test_phase2a_migration.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Confirm downgrade also works**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: clean down then up, no errors.

- [ ] **Step 7: Create the crew backfill script**

Create `scripts/backfills/0003_crew_current_activity.py`:

```python
"""Backfill crew_members.current_activity from existing crew_assignments.

Run this **after** alembic upgrade for 0003_phase2a_scheduler. Idempotent:
running multiple times is safe — the WHERE clause restricts to crew
that are still 'idle' (the default) and have a corresponding assignment row.

Usage:
    python -m scripts.backfills.0003_crew_current_activity
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from config.logging import get_logger, setup_logging
from db.session import async_session

log = get_logger(__name__)


BACKFILL_SQL = text(
    """
    UPDATE crew_members AS cm
    SET current_activity = 'on_build',
        current_activity_id = ca.build_id
    FROM crew_assignments AS ca
    WHERE ca.crew_id = cm.id
      AND cm.current_activity = 'idle'
    RETURNING cm.id;
    """
)


async def main() -> int:
    setup_logging()
    async with async_session() as session, session.begin():
        result = await session.execute(BACKFILL_SQL)
        rows = list(result)
    log.info("backfill_complete count=%d", len(rows))
    return len(rows)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 8: Add a backfill correctness test**

Append to `tests/test_phase2a_migration.py`:

```python
@pytest.mark.asyncio
async def test_crew_backfill_marks_assigned_crew_on_build(db_session):
    """Existing CrewAssignment rows produce current_activity='on_build' after backfill."""
    import uuid as _uuid

    from db.models import (
        Build,
        CrewArchetype,
        CrewActivity,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
        User,
    )

    user = User(
        discord_id="555111222",
        username="backfill_test",
        hull_class=HullClass.HAULER,
    )
    db_session.add(user)
    await db_session.flush()

    build = Build(id=_uuid.uuid4(), user_id=user.discord_id, name="bf_build", hull_class=HullClass.HAULER)
    db_session.add(build)
    await db_session.flush()

    crew = CrewMember(
        id=_uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Bee",
        last_name="Eff",
        callsign="Backfill",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    db_session.add(crew)
    await db_session.flush()

    db_session.add(
        CrewAssignment(
            id=_uuid.uuid4(),
            crew_id=crew.id,
            build_id=build.id,
            archetype=CrewArchetype.PILOT,
        )
    )
    # Ensure current_activity is still the default 'idle'.
    crew_after_insert = await db_session.get(CrewMember, crew.id)
    assert crew_after_insert.current_activity == CrewActivity.IDLE

    # Run the backfill SQL inline (the script's same statement).
    from scripts.backfills import _0003_crew_current_activity as bf  # noqa
    await db_session.execute(bf.BACKFILL_SQL)

    refreshed = await db_session.get(CrewMember, crew.id)
    assert refreshed.current_activity == CrewActivity.ON_BUILD
    assert refreshed.current_activity_id == build.id
```

The dotted import path `_0003_...` is the conventional Python alias since module names cannot start with a digit. **Add an alias module** at `scripts/backfills/_0003_crew_current_activity.py` that re-exports `BACKFILL_SQL` from the digit-prefixed file:

```python
from .__init__ import *  # noqa
from importlib import import_module

_real = import_module("scripts.backfills.0003_crew_current_activity")
BACKFILL_SQL = _real.BACKFILL_SQL
```

(Also create `scripts/backfills/__init__.py` if it doesn't exist — empty.)

- [ ] **Step 9: Run backfill test, confirm passes**

Run: `pytest tests/test_phase2a_migration.py::test_crew_backfill_marks_assigned_crew_on_build -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add db/migrations/versions/0003_phase2a_scheduler.py scripts/backfills/ tests/test_phase2a_migration.py
git commit -m "feat(phase2a): alembic migration 0003 + crew current_activity backfill"
```

---

## Task 5: Content JSON files

**Files:**
- Create: `data/timers/training_routines.json`
- Create: `data/timers/research_projects.json`
- Create: `data/timers/ship_build_recipes.json`
- Create: `data/stations/station_types.json`

- [ ] **Step 1: Create `data/timers/training_routines.json`**

```json
[
  {
    "id": "combat_drills",
    "name": "Combat Drills",
    "duration_minutes": 30,
    "cost_credits": 50,
    "min_crew_level": 1,
    "rewards": {"xp": 200, "archetype_perk": null},
    "flavor": "Standard sim runs in the gunnery pod. Reliable progress."
  },
  {
    "id": "specialty_course",
    "name": "Specialty Course",
    "duration_minutes": 90,
    "cost_credits": 150,
    "min_crew_level": 3,
    "rewards": {"xp": 800, "archetype_perk": null},
    "flavor": "Advanced curriculum tailored to your crew's archetype."
  },
  {
    "id": "field_exercise",
    "name": "Field Exercise",
    "duration_minutes": 120,
    "cost_credits": 80,
    "min_crew_level": 1,
    "rewards": {"xp": 500, "archetype_perk": null},
    "flavor": "Slow-burn live drills at the outer markers. Cheap, patient."
  }
]
```

- [ ] **Step 2: Create `data/timers/research_projects.json`**

```json
[
  {
    "id": "drive_tuning",
    "name": "Drive Tuning",
    "duration_minutes": 60,
    "cost_credits": 200,
    "rewards": {
      "fleet_buff": {"stat": "effective_acceleration", "pct": 2, "duration_hours": 48}
    },
    "flavor": "Bench testing on your drive coil. Wins you a small acceleration edge."
  },
  {
    "id": "shield_calibration",
    "name": "Shield Calibration",
    "duration_minutes": 75,
    "cost_credits": 250,
    "rewards": {
      "fleet_buff": {"stat": "effective_durability", "pct": 2, "duration_hours": 48}
    },
    "flavor": "Re-tuning hull shielding emitters. Marginal but compounding."
  },
  {
    "id": "nav_charting",
    "name": "Navigational Charting",
    "duration_minutes": 90,
    "cost_credits": 300,
    "rewards": {
      "fleet_buff": {"stat": "effective_weather_performance", "pct": 3, "duration_hours": 48}
    },
    "flavor": "Survey runs through the dust belts. Your nav crew loves it."
  }
]
```

- [ ] **Step 3: Create `data/timers/ship_build_recipes.json`**

```json
[
  {
    "id": "salvage_reconstruction",
    "name": "Salvage Reconstruction",
    "duration_minutes": 120,
    "cost_credits": 500,
    "input_scrapped_ship_count": 3,
    "rewards": {
      "new_ship": {"hull_class": "hauler", "title": "Reconstructed Hull"}
    },
    "flavor": "Three wrecks become one rough but functional hull. The slipway hums."
  }
]
```

- [ ] **Step 4: Create `data/stations/station_types.json`**

```json
[
  {
    "id": "cargo_run",
    "name": "Cargo Run",
    "yields_per_tick": {"credits": 50, "xp": 10},
    "preferred_archetype": "navigator",
    "archetype_bonus_pct": 25,
    "flavor": "Standard freight runs. Reliable, modest pay."
  },
  {
    "id": "repair_bay",
    "name": "Repair Bay",
    "yields_per_tick": {"credits": 30, "xp": 25},
    "preferred_archetype": "engineer",
    "archetype_bonus_pct": 25,
    "flavor": "Patching up other captains' wrecks. Bad coffee, decent XP."
  },
  {
    "id": "watch_tower",
    "name": "Watch Tower",
    "yields_per_tick": {"credits": 20, "xp": 35},
    "preferred_archetype": "gunner",
    "archetype_bonus_pct": 25,
    "flavor": "Long shifts staring at the void. The crew gets sharp."
  }
]
```

- [ ] **Step 5: Commit**

```bash
git add data/timers/ data/stations/
git commit -m "feat(phase2a): seed v1 timer recipes and station-type content"
```

---

## Task 6: Timer recipe loader (`engine/timer_recipes.py`)

**Files:**
- Create: `engine/timer_recipes.py`
- Create: `tests/test_timer_recipes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_timer_recipes.py`:

```python
"""Tests for engine/timer_recipes.py — JSON loader and lookup."""

from __future__ import annotations

import pytest

from db.models import TimerType


def test_get_recipe_returns_known_routine():
    from engine.timer_recipes import get_recipe

    r = get_recipe(TimerType.TRAINING, "combat_drills")
    assert r["id"] == "combat_drills"
    assert r["duration_minutes"] == 30
    assert r["cost_credits"] == 50
    assert r["rewards"]["xp"] == 200


def test_get_recipe_unknown_id_raises():
    from engine.timer_recipes import RecipeNotFound, get_recipe

    with pytest.raises(RecipeNotFound):
        get_recipe(TimerType.TRAINING, "no_such_routine")


def test_list_recipes_returns_all_for_type():
    from engine.timer_recipes import list_recipes

    training = list_recipes(TimerType.TRAINING)
    assert {r["id"] for r in training} == {
        "combat_drills",
        "specialty_course",
        "field_exercise",
    }
    research = list_recipes(TimerType.RESEARCH)
    assert {r["id"] for r in research} == {
        "drive_tuning",
        "shield_calibration",
        "nav_charting",
    }
    ship_build = list_recipes(TimerType.SHIP_BUILD)
    assert {r["id"] for r in ship_build} == {"salvage_reconstruction"}


def test_recipe_id_uniqueness_enforced_at_load():
    """If two recipes share an id within a type, loader raises."""
    from engine.timer_recipes import _build_registry

    bad_data = {
        TimerType.TRAINING: [
            {"id": "x", "name": "X", "duration_minutes": 1, "cost_credits": 1, "rewards": {}},
            {"id": "x", "name": "X2", "duration_minutes": 1, "cost_credits": 1, "rewards": {}},
        ]
    }
    with pytest.raises(ValueError, match="duplicate recipe id"):
        _build_registry(bad_data)
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_timer_recipes.py -v`
Expected: 4 FAILs (`ImportError`).

- [ ] **Step 3: Implement loader**

Create `engine/timer_recipes.py`:

```python
"""Timer recipe registry — JSON-backed, in-memory lookup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.models import TimerType

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "timers"

_FILES: dict[TimerType, str] = {
    TimerType.TRAINING: "training_routines.json",
    TimerType.RESEARCH: "research_projects.json",
    TimerType.SHIP_BUILD: "ship_build_recipes.json",
}


class RecipeNotFound(KeyError):
    """Raised when a recipe id is not present in the registry for a timer type."""


def _load_files() -> dict[TimerType, list[dict[str, Any]]]:
    out: dict[TimerType, list[dict[str, Any]]] = {}
    for ttype, fname in _FILES.items():
        with (_DATA_DIR / fname).open(encoding="utf-8") as f:
            out[ttype] = json.load(f)
    return out


def _build_registry(
    raw: dict[TimerType, list[dict[str, Any]]],
) -> dict[TimerType, dict[str, dict[str, Any]]]:
    """Return {timer_type: {recipe_id: recipe_dict}}, raising on duplicate ids."""
    registry: dict[TimerType, dict[str, dict[str, Any]]] = {}
    for ttype, recipes in raw.items():
        by_id: dict[str, dict[str, Any]] = {}
        for r in recipes:
            rid = r["id"]
            if rid in by_id:
                raise ValueError(f"duplicate recipe id {rid!r} in {ttype.value}")
            by_id[rid] = r
        registry[ttype] = by_id
    return registry


_REGISTRY: dict[TimerType, dict[str, dict[str, Any]]] = _build_registry(_load_files())


def get_recipe(timer_type: TimerType, recipe_id: str) -> dict[str, Any]:
    bucket = _REGISTRY.get(timer_type, {})
    if recipe_id not in bucket:
        raise RecipeNotFound(f"{timer_type.value}/{recipe_id}")
    return bucket[recipe_id]


def list_recipes(timer_type: TimerType) -> list[dict[str, Any]]:
    return list(_REGISTRY.get(timer_type, {}).values())
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_timer_recipes.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/timer_recipes.py tests/test_timer_recipes.py
git commit -m "feat(phase2a): timer recipe registry + lookup"
```

---

## Task 7: Station-type loader (`engine/station_types.py`)

**Files:**
- Create: `engine/station_types.py`
- Create: `tests/test_station_types.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_station_types.py`:

```python
"""Tests for engine/station_types.py."""

from __future__ import annotations

import pytest

from db.models import StationType


def test_get_station_returns_known():
    from engine.station_types import get_station

    s = get_station(StationType.CARGO_RUN)
    assert s["id"] == "cargo_run"
    assert s["yields_per_tick"]["credits"] == 50
    assert s["preferred_archetype"] == "navigator"


def test_get_station_unknown_raises():
    """Should never happen given enum constraint, but guarded anyway."""
    from engine.station_types import StationNotFound, get_station_by_id

    with pytest.raises(StationNotFound):
        get_station_by_id("no_such_station")


def test_list_stations_returns_all_three():
    from engine.station_types import list_stations

    ids = {s["id"] for s in list_stations()}
    assert ids == {"cargo_run", "repair_bay", "watch_tower"}
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_station_types.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement loader**

Create `engine/station_types.py`:

```python
"""Station-type registry — JSON-backed, in-memory lookup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.models import StationType

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "stations" / "station_types.json"


class StationNotFound(KeyError):
    """Raised when a station id is not present in the registry."""


def _load() -> dict[str, dict[str, Any]]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    by_id: dict[str, dict[str, Any]] = {}
    for s in raw:
        sid = s["id"]
        if sid in by_id:
            raise ValueError(f"duplicate station id {sid!r}")
        by_id[sid] = s
    return by_id


_REGISTRY: dict[str, dict[str, Any]] = _load()


def get_station(station_type: StationType) -> dict[str, Any]:
    return _REGISTRY[station_type.value]


def get_station_by_id(station_id: str) -> dict[str, Any]:
    if station_id not in _REGISTRY:
        raise StationNotFound(station_id)
    return _REGISTRY[station_id]


def list_stations() -> list[dict[str, Any]]:
    return list(_REGISTRY.values())
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_station_types.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/station_types.py tests/test_station_types.py
git commit -m "feat(phase2a): station-type registry + lookup"
```

---

## Task 8: Reward ledger helper (`engine/rewards.py`)

**Files:**
- Create: `engine/rewards.py`
- Create: `tests/test_rewards.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rewards.py`:

```python
"""Tests for engine/rewards.py — idempotent ledger writes."""

from __future__ import annotations

import pytest

from db.models import HullClass, RewardSourceType, User


@pytest.mark.asyncio
async def test_apply_reward_credits_user_on_first_call(db_session):
    from engine.rewards import apply_reward

    user = User(discord_id="700001", username="rewards_a", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    await db_session.flush()

    applied = await apply_reward(
        db_session,
        user_id=user.discord_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id="timer:abc-123",
        delta={"credits": 100, "xp": 50},
    )
    await db_session.flush()

    assert applied is True
    refreshed = await db_session.get(User, user.discord_id)
    assert refreshed.currency == 100
    assert refreshed.xp == 50


@pytest.mark.asyncio
async def test_apply_reward_is_idempotent_on_duplicate_source(db_session):
    from engine.rewards import apply_reward

    user = User(discord_id="700002", username="rewards_b", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    await db_session.flush()

    applied1 = await apply_reward(
        db_session,
        user_id=user.discord_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id="timer:dup-1",
        delta={"credits": 100},
    )
    await db_session.flush()
    applied2 = await apply_reward(
        db_session,
        user_id=user.discord_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id="timer:dup-1",
        delta={"credits": 100},
    )
    await db_session.flush()

    assert applied1 is True
    assert applied2 is False  # ON CONFLICT DO NOTHING — second call is a no-op.
    refreshed = await db_session.get(User, user.discord_id)
    assert refreshed.currency == 100  # only credited once.
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_rewards.py -v`
Expected: 2 FAILs (`ImportError`).

- [ ] **Step 3: Implement helper**

Create `engine/rewards.py`:

```python
"""Idempotent reward application via reward_ledger.

The (source_type, source_id) unique constraint on reward_ledger is the
load-bearing piece — INSERT ... ON CONFLICT DO NOTHING makes handlers
exactly-once-effective without a separate idempotency table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RewardLedger, RewardSourceType, User


async def apply_reward(
    session: AsyncSession,
    *,
    user_id: str,
    source_type: RewardSourceType,
    source_id: str,
    delta: dict[str, Any],
) -> bool:
    """Apply rewards atomically and idempotently.

    Returns True if rewards were applied (first time seeing this source),
    False if the (source_type, source_id) row already existed (no-op).

    Caller is responsible for the surrounding transaction. This function
    flushes after the ledger insert but does not commit.
    """
    stmt = (
        pg_insert(RewardLedger)
        .values(
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            delta=delta,
        )
        .on_conflict_do_nothing(index_elements=["source_type", "source_id"])
        .returning(RewardLedger.id)
    )
    result = await session.execute(stmt)
    inserted = result.scalar_one_or_none()
    if inserted is None:
        return False  # already applied — caller should treat as success.

    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise ValueError(f"unknown user_id={user_id!r} when applying reward")
    credits = int(delta.get("credits", 0))
    xp = int(delta.get("xp", 0))
    if credits:
        user.currency += credits
    if xp:
        user.xp += xp
    return True
```

Note: this helper handles user-scoped credits/XP. Crew-scoped XP (e.g., training reward XP applied to a specific crew member) is the handler's responsibility — it calls `apply_reward` for the audit + idempotency, then layers crew XP application on top using the `inserted` return value as the gate.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_rewards.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/rewards.py tests/test_rewards.py
git commit -m "feat(phase2a): reward_ledger idempotent apply helper"
```

---

## Task 9: Scheduler enqueue helper (`scheduler/enqueue.py`)

**Files:**
- Create: `scheduler/__init__.py` (empty)
- Create: `scheduler/enqueue.py`
- Create: `tests/test_scheduler_enqueue.py`

- [ ] **Step 1: Add empty package marker**

Create `scheduler/__init__.py` with a single line:

```python
"""Phase 2a — durable scheduler worker process."""
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_scheduler_enqueue.py`:

```python
"""Tests for scheduler.enqueue — cog-side helper to atomically insert Timer + ScheduledJob."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    HullClass,
    JobState,
    JobType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_enqueue_timer_creates_linked_rows(db_session):
    from scheduler.enqueue import enqueue_timer

    user = User(discord_id="800001", username="enq_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    completes_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    timer, job = await enqueue_timer(
        db_session,
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        completes_at=completes_at,
        payload={"crew_id": "11111111-1111-1111-1111-111111111111"},
    )
    await db_session.flush()

    assert timer.state == TimerState.ACTIVE
    assert timer.linked_scheduled_job_id == job.id
    assert job.state == JobState.PENDING
    assert job.job_type == JobType.TIMER_COMPLETE
    assert job.scheduled_for == completes_at
    assert job.payload == {"timer_id": str(timer.id)}


@pytest.mark.asyncio
async def test_enqueue_accrual_tick_creates_pending_job(db_session):
    from scheduler.enqueue import enqueue_accrual_tick

    user = User(discord_id="800002", username="enq_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    fires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    job = await enqueue_accrual_tick(db_session, user_id=user.discord_id, scheduled_for=fires_at)
    await db_session.flush()

    assert job.job_type == JobType.ACCRUAL_TICK
    assert job.state == JobState.PENDING
    assert job.scheduled_for == fires_at
    assert job.payload == {}
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_scheduler_enqueue.py -v`
Expected: 2 FAILs.

- [ ] **Step 4: Implement enqueue helpers**

Create `scheduler/enqueue.py`:

```python
"""Helpers cogs use to atomically enqueue jobs.

Cogs call these inside their own session.begin() block so the Timer + ScheduledJob
inserts (and any cost deductions, crew state updates, etc.) commit together.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    JobState,
    JobType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
)


async def enqueue_timer(
    session: AsyncSession,
    *,
    user_id: str,
    timer_type: TimerType,
    recipe_id: str,
    completes_at: datetime,
    payload: dict[str, Any] | None = None,
) -> tuple[Timer, ScheduledJob]:
    """Insert a Timer row and a paired ScheduledJob row.

    The ScheduledJob's payload references the timer id; the timer's
    linked_scheduled_job_id back-references the job. Both get UUIDs assigned
    here so we can wire the link before flush.
    """
    timer_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ScheduledJob(
        id=job_id,
        user_id=user_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={"timer_id": str(timer_id)},
        scheduled_for=completes_at,
        state=JobState.PENDING,
    )
    timer = Timer(
        id=timer_id,
        user_id=user_id,
        timer_type=timer_type,
        recipe_id=recipe_id,
        payload=payload or {},
        completes_at=completes_at,
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job_id,
    )
    session.add(job)
    session.add(timer)
    return timer, job


async def enqueue_accrual_tick(
    session: AsyncSession,
    *,
    user_id: str,
    scheduled_for: datetime,
) -> ScheduledJob:
    """Insert a pending accrual_tick ScheduledJob for the given user."""
    job = ScheduledJob(
        user_id=user_id,
        job_type=JobType.ACCRUAL_TICK,
        payload={},
        scheduled_for=scheduled_for,
        state=JobState.PENDING,
    )
    session.add(job)
    return job
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_scheduler_enqueue.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add scheduler/__init__.py scheduler/enqueue.py tests/test_scheduler_enqueue.py
git commit -m "feat(phase2a): scheduler enqueue helpers (Timer + ScheduledJob, accrual_tick)"
```

---

## Task 10: Tick claim loop (`scheduler/engine.py`)

**Files:**
- Create: `scheduler/engine.py`
- Create: `tests/test_scheduler_engine.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scheduler_engine.py`:

```python
"""Tests for scheduler.engine — claim semantics under SKIP LOCKED.

Requires a real Postgres (SKIP LOCKED is a PG feature; sqlite cannot exercise it).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import settings
from db.models import HullClass, JobState, JobType, ScheduledJob, User


@pytest.mark.asyncio
async def test_tick_claims_due_pending_jobs(db_session):
    from scheduler.engine import tick

    user = User(discord_id="900001", username="eng_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(
        ScheduledJob(
            user_id=user.discord_id,
            job_type=JobType.TIMER_COMPLETE,
            payload={"timer_id": "x"},
            scheduled_for=past,
            state=JobState.PENDING,
        )
    )
    await db_session.flush()

    # tick() requires its own session-maker — we run against the same engine binding.
    bind = db_session.bind
    sm = async_sessionmaker(bind=bind, expire_on_commit=False)

    claimed = await tick(sm, batch_size=10)
    assert len(claimed) == 1
    assert claimed[0].state == JobState.CLAIMED
    assert claimed[0].claimed_at is not None
    assert claimed[0].attempts == 1


@pytest.mark.asyncio
async def test_tick_skips_future_jobs(db_session):
    from scheduler.engine import tick

    user = User(discord_id="900002", username="eng_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.add(
        ScheduledJob(
            user_id=user.discord_id,
            job_type=JobType.TIMER_COMPLETE,
            payload={},
            scheduled_for=future,
            state=JobState.PENDING,
        )
    )
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    claimed = await tick(sm, batch_size=10)
    assert claimed == []


@pytest.mark.asyncio
async def test_concurrent_ticks_each_claim_disjoint_rows():
    """Two simultaneous tick() calls must claim disjoint rows under SKIP LOCKED.

    This test uses the shared docker PG (NOT db_session savepoint) because
    SKIP LOCKED requires real concurrent transactions.
    """
    from scheduler.engine import tick

    eng = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=4)
    sm = async_sessionmaker(bind=eng, expire_on_commit=False)

    async with sm() as s, s.begin():
        user = User(
            discord_id="900100",
            username="eng_concurrent",
            hull_class=HullClass.HAULER,
        )
        s.add(user)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with sm() as s, s.begin():
        for _ in range(20):
            s.add(
                ScheduledJob(
                    user_id="900100",
                    job_type=JobType.TIMER_COMPLETE,
                    payload={},
                    scheduled_for=past,
                    state=JobState.PENDING,
                )
            )

    a, b = await asyncio.gather(tick(sm, batch_size=10), tick(sm, batch_size=10))
    a_ids = {j.id for j in a}
    b_ids = {j.id for j in b}
    assert a_ids.isdisjoint(b_ids)
    assert len(a_ids) + len(b_ids) == 20

    # Cleanup so other tests aren't disturbed.
    async with sm() as s, s.begin():
        await s.execute(
            ScheduledJob.__table__.delete().where(ScheduledJob.user_id == "900100")
        )
        await s.execute(User.__table__.delete().where(User.discord_id == "900100"))
    await eng.dispose()
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_scheduler_engine.py -v`
Expected: 3 FAILs (`ImportError`).

- [ ] **Step 3: Implement engine**

Create `scheduler/engine.py`:

```python
"""Worker tick loop with SELECT FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import asyncio
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.logging import get_logger
from config.settings import settings
from db.models import JobState, ScheduledJob

log = get_logger(__name__)


async def tick(
    session_maker: async_sessionmaker,
    *,
    batch_size: int | None = None,
) -> Sequence[ScheduledJob]:
    """Claim up to `batch_size` due pending jobs and return them.

    Uses SELECT FOR UPDATE SKIP LOCKED so multiple concurrent tick() calls
    claim disjoint rows. Each claimed row is transitioned pending -> claimed
    in the same transaction; the dispatcher is then called outside the claim tx.
    """
    n = batch_size or settings.SCHEDULER_BATCH_SIZE
    async with session_maker() as session, session.begin():
        rows = (
            await session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.state == JobState.PENDING)
                .where(ScheduledJob.scheduled_for <= func.now())
                .order_by(ScheduledJob.scheduled_for)
                .limit(n)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for job in rows:
            job.state = JobState.CLAIMED
            job.claimed_at = func.now()
            job.attempts += 1
        # commit on session.begin() exit — claim is durable before any handler runs.
    return rows


async def run_forever(
    session_maker: async_sessionmaker,
    dispatcher,
    *,
    shutdown_event: asyncio.Event,
) -> None:
    """The worker's main loop: tick, dispatch, sleep.

    `dispatcher` is `scheduler.dispatch.dispatch` — passed in to avoid an
    import cycle and to make this loop testable with a fake dispatcher.
    """
    interval = settings.SCHEDULER_TICK_INTERVAL_SECONDS
    batch = settings.SCHEDULER_BATCH_SIZE
    while not shutdown_event.is_set():
        try:
            jobs = await tick(session_maker, batch_size=batch)
        except Exception:
            log.exception("scheduler tick failed")
            jobs = []
        for job in jobs:
            try:
                await dispatcher(job, session_maker)
            except Exception:
                log.exception("scheduler dispatch failed for job_id=%s", job.id)
        if len(jobs) < batch:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_scheduler_engine.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/engine.py tests/test_scheduler_engine.py
git commit -m "feat(phase2a): scheduler tick loop with SKIP LOCKED claim semantics"
```

---

## Task 11: Dispatcher + handler contract (`scheduler/dispatch.py`)

**Files:**
- Create: `scheduler/dispatch.py`
- Create: `scheduler/jobs/__init__.py` (empty package)
- Create: `tests/test_scheduler_dispatch.py`

- [ ] **Step 1: Empty package marker**

Create `scheduler/jobs/__init__.py`:

```python
"""Phase 2a — per-job-type handlers."""
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_scheduler_dispatch.py`:

```python
"""Tests for scheduler.dispatch — handler registry + per-job transactions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import HullClass, JobState, JobType, ScheduledJob, User


@pytest.mark.asyncio
async def test_dispatch_runs_handler_and_marks_completed(db_session, monkeypatch):
    from scheduler import dispatch as dispatch_mod
    from scheduler.dispatch import HandlerResult, dispatch

    calls: list[str] = []

    async def fake_timer_complete(session, job):
        calls.append(str(job.id))
        job.state = JobState.COMPLETED
        return HandlerResult()

    monkeypatch.setitem(dispatch_mod.HANDLERS, JobType.TIMER_COMPLETE, fake_timer_complete)

    user = User(discord_id="910001", username="d_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await dispatch(job, sm)

    assert calls == [str(job.id)]
    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_dispatch_marks_failed_on_handler_exception(db_session, monkeypatch):
    from scheduler import dispatch as dispatch_mod
    from scheduler.dispatch import dispatch

    async def boom(session, job):
        raise RuntimeError("handler exploded")

    monkeypatch.setitem(dispatch_mod.HANDLERS, JobType.TIMER_COMPLETE, boom)

    user = User(discord_id="910002", username="d_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await dispatch(job, sm)

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.FAILED
    assert refreshed.last_error and "handler exploded" in refreshed.last_error
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_scheduler_dispatch.py -v`
Expected: 2 FAILs.

- [ ] **Step 4: Implement dispatcher**

Create `scheduler/dispatch.py`:

```python
"""Job dispatcher: handler registry + per-job transaction wrapper."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from opentelemetry import trace
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.metrics import scheduler_jobs_total
from config.logging import get_logger
from db.models import JobState, JobType, ScheduledJob

log = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class NotificationRequest:
    user_id: str
    category: str
    title: str
    body: str
    correlation_id: str
    dedupe_key: str


@dataclass
class HandlerResult:
    notifications: list[NotificationRequest] = field(default_factory=list)


Handler = Callable[[AsyncSession, ScheduledJob], Awaitable[HandlerResult]]

# Handlers register themselves here. Imports below trigger registration.
HANDLERS: dict[JobType, Handler] = {}


def register(job_type: JobType, handler: Handler) -> None:
    HANDLERS[job_type] = handler


async def dispatch(job: ScheduledJob, session_maker: async_sessionmaker) -> None:
    """Execute one claimed job inside its own transaction."""
    handler = HANDLERS.get(job.job_type)
    if handler is None:
        log.error("no handler registered for job_type=%s", job.job_type)
        await _mark_failed(job, session_maker, error="no handler registered")
        scheduler_jobs_total.labels(job_type=job.job_type.value, result="failure").inc()
        return

    with tracer.start_as_current_span(f"scheduler.{job.job_type.value}") as span:
        span.set_attribute("d2d.job_id", str(job.id))
        span.set_attribute("d2d.job_type", job.job_type.value)
        span.set_attribute("d2d.user_id", job.user_id)
        span.set_attribute("d2d.attempts", job.attempts)

        notifications: list[NotificationRequest] = []
        try:
            async with session_maker() as session, session.begin():
                fresh = await session.get(ScheduledJob, job.id, with_for_update=True)
                if fresh is None or fresh.state != JobState.CLAIMED:
                    log.info("dispatch skipping job_id=%s state=%s", job.id, fresh.state if fresh else None)
                    return
                result = await handler(session, fresh)
                notifications = list(result.notifications)
            scheduler_jobs_total.labels(job_type=job.job_type.value, result="success").inc()
        except Exception as e:
            span.record_exception(e)
            await _mark_failed(job, session_maker, error=traceback.format_exc())
            scheduler_jobs_total.labels(job_type=job.job_type.value, result="failure").inc()
            log.exception("handler failed: job_id=%s", job.id)
            return

    # Emit notifications AFTER DB commit — accepted v1 trade if worker dies here.
    if notifications:
        from scheduler.notifications import emit_notification
        for n in notifications:
            try:
                await emit_notification(n)
            except Exception:
                log.exception("notification xadd failed for job_id=%s", job.id)


async def _mark_failed(
    job: ScheduledJob, session_maker: async_sessionmaker, *, error: str
) -> None:
    async with session_maker() as session, session.begin():
        fresh = await session.get(ScheduledJob, job.id, with_for_update=True)
        if fresh is None:
            return
        fresh.state = JobState.FAILED
        fresh.last_error = error[:8000]
        fresh.completed_at = func.now()
```

- [ ] **Step 5: Run, confirm tests pass**

Run: `pytest tests/test_scheduler_dispatch.py -v`
Expected: 2 PASS. (`emit_notification` import is lazy and not exercised by these tests.)

- [ ] **Step 6: Commit**

```bash
git add scheduler/dispatch.py scheduler/jobs/__init__.py tests/test_scheduler_dispatch.py
git commit -m "feat(phase2a): scheduler dispatcher with handler registry + per-job transactions"
```

---

## Task 12: Recovery sweep (`scheduler/recovery.py`)

**Files:**
- Create: `scheduler/recovery.py`
- Create: `tests/test_scheduler_recovery.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scheduler_recovery.py`:

```python
"""Tests for scheduler.recovery — stuck claims + capped failure retry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.settings import settings
from db.models import HullClass, JobState, JobType, ScheduledJob, User


@pytest.mark.asyncio
async def test_recovery_resets_stuck_claimed_to_pending(db_session):
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="920001", username="rec_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    stuck_for = datetime.now(timezone.utc) - timedelta(
        seconds=settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS + 60
    )
    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        claimed_at=stuck_for,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    n = await recovery_sweep(sm)
    assert n >= 1

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.PENDING


@pytest.mark.asyncio
async def test_recovery_retries_failed_under_attempt_cap(db_session):
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="920002", username="rec_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.FAILED,
        last_error="boom",
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await recovery_sweep(sm)

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.PENDING


@pytest.mark.asyncio
async def test_recovery_leaves_max_attempts_failures_alone(db_session):
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="920003", username="rec_c", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.FAILED,
        last_error="boom",
        attempts=settings.SCHEDULER_MAX_ATTEMPTS,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await recovery_sweep(sm)

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.FAILED  # left as terminal.
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_scheduler_recovery.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement recovery**

Create `scheduler/recovery.py`:

```python
"""Worker-internal periodic task: reset stuck claims, retry capped failures."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.logging import get_logger
from config.settings import settings
from db.models import JobState, ScheduledJob

log = get_logger(__name__)


async def recovery_sweep(session_maker: async_sessionmaker) -> int:
    """Reset stuck-claimed and retryable-failed jobs back to pending.

    Returns the total rows updated across both passes.
    """
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS
    )
    total = 0

    async with session_maker() as session, session.begin():
        # Stuck claims: claimed too long ago, push back to pending.
        result = await session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.state == JobState.CLAIMED)
            .where(ScheduledJob.claimed_at < stuck_cutoff)
            .values(state=JobState.PENDING, claimed_at=None)
        )
        total += result.rowcount or 0

        # Failed-but-retryable.
        result = await session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.state == JobState.FAILED)
            .where(ScheduledJob.attempts < settings.SCHEDULER_MAX_ATTEMPTS)
            .values(state=JobState.PENDING, last_error=None)
        )
        total += result.rowcount or 0

    if total:
        log.info("recovery_sweep_reset_count count=%d", total)
    return total


async def run_forever(
    session_maker: async_sessionmaker,
    *,
    shutdown_event: asyncio.Event,
) -> None:
    interval = settings.SCHEDULER_RECOVERY_INTERVAL_SECS
    while not shutdown_event.is_set():
        try:
            await recovery_sweep(session_maker)
        except Exception:
            log.exception("recovery_sweep failed")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_scheduler_recovery.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/recovery.py tests/test_scheduler_recovery.py
git commit -m "feat(phase2a): scheduler recovery sweep for stuck claims and retryable failures"
```

---

## Task 13: NotificationRequest + Redis stream emit (`scheduler/notifications.py`)

**Files:**
- Create: `scheduler/notifications.py`
- Modify: `tests/conftest.py` (add `redis_client` fixture)
- Create: `tests/test_scheduler_notifications.py`

- [ ] **Step 1: Add `redis_client` fixture to `tests/conftest.py`**

Append to `tests/conftest.py`:

```python
import os as _os

import redis.asyncio as _redis_async


_TEST_REDIS_URL = _os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture
async def redis_client():
    """Async Redis client pointed at db 15 (test isolation)."""
    client = _redis_async.from_url(_TEST_REDIS_URL, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_scheduler_notifications.py`:

```python
"""Tests for scheduler.notifications — Redis Streams XADD."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_emit_notification_xadds_to_stream(redis_client):
    from scheduler.notifications import NotificationRequest, emit_notification

    n = NotificationRequest(
        user_id="555",
        category="timer_completion",
        title="Training complete",
        body="Alice gained 200 XP",
        correlation_id="11111111-1111-1111-1111-111111111111",
        dedupe_key="timer:abc",
    )
    await emit_notification(n, client=redis_client, stream_key="d2d:notifications:test")

    entries = await redis_client.xrange("d2d:notifications:test", count=10)
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["user_id"] == "555"
    assert fields["category"] == "timer_completion"
    assert fields["title"] == "Training complete"
    assert fields["correlation_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_emit_notification_respects_maxlen(redis_client):
    from scheduler.notifications import NotificationRequest, emit_notification

    for i in range(20):
        await emit_notification(
            NotificationRequest(
                user_id="x",
                category="timer_completion",
                title=str(i),
                body="b",
                correlation_id="c",
                dedupe_key=str(i),
            ),
            client=redis_client,
            stream_key="d2d:notifications:cap",
            maxlen=5,
        )

    length = await redis_client.xlen("d2d:notifications:cap")
    assert length <= 10  # approximate trim — Redis may keep slightly more.
```

- [ ] **Step 3: Run, confirm fails**

Run: `pytest tests/test_scheduler_notifications.py -v`
Expected: 2 FAILs (`ImportError`).

- [ ] **Step 4: Implement helper**

Create `scheduler/notifications.py`. `NotificationRequest` is the canonical dataclass already defined in `scheduler/dispatch.py` (Task 11) — this module imports it rather than redefining, so there's only one type and handlers/dispatcher/notifications all agree on it:

```python
"""Notification emission to Redis Streams."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import redis.asyncio as redis_async

from config.logging import get_logger
from config.settings import settings
from scheduler.dispatch import NotificationRequest

log = get_logger(__name__)

DEFAULT_STREAM_KEY = "d2d:notifications"

_client: redis_async.Redis | None = None


def get_redis_client() -> redis_async.Redis:
    """Return the process-local async Redis client (lazy-init)."""
    global _client
    if _client is None:
        _client = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def _to_stream_fields(n: NotificationRequest) -> dict[str, str]:
    d = asdict(n)
    d["created_at"] = datetime.now(timezone.utc).isoformat()
    return d


async def emit_notification(
    n: NotificationRequest,
    *,
    client: redis_async.Redis | None = None,
    stream_key: str | None = None,
    maxlen: int | None = None,
) -> str:
    """XADD a NotificationRequest to the Redis stream. Returns the entry id."""
    c = client or get_redis_client()
    key = stream_key or DEFAULT_STREAM_KEY
    cap = maxlen if maxlen is not None else settings.NOTIFICATION_STREAM_MAXLEN
    entry_id = await c.xadd(key, _to_stream_fields(n), maxlen=cap, approximate=True)
    log.info(
        "notification_emitted user_id=%s category=%s correlation_id=%s entry_id=%s",
        n.user_id, n.category, n.correlation_id, entry_id,
    )
    return entry_id
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_scheduler_notifications.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add scheduler/notifications.py tests/test_scheduler_notifications.py tests/conftest.py
git commit -m "feat(phase2a): NotificationRequest dataclass + Redis stream emit helper"
```

---

## Task 14: timer_complete handler

**Files:**
- Create: `scheduler/jobs/timer_complete.py`
- Create: `tests/test_handler_timer_complete.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler_timer_complete.py`:

```python
"""Tests for the timer_complete handler — per timer_type sub-handlers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    RewardLedger,
    RewardSourceType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_training_handler_credits_xp_and_frees_crew(db_session):
    from scheduler.jobs.timer_complete import handle_timer_complete

    user = User(discord_id="700101", username="t_a", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Train",
        last_name="Ee",
        callsign="Drill",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        xp=0,
        current_activity=CrewActivity.TRAINING,
    )
    db_session.add(crew)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    timer = Timer(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        payload={"crew_id": str(crew.id)},
        completes_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job.id,
    )
    db_session.add(timer)
    job.payload = {"timer_id": str(timer.id)}
    await db_session.flush()

    result = await handle_timer_complete(db_session, job)

    refreshed_crew = await db_session.get(CrewMember, crew.id)
    refreshed_timer = await db_session.get(Timer, timer.id)
    refreshed_job = await db_session.get(ScheduledJob, job.id)
    assert refreshed_crew.xp >= 200
    assert refreshed_crew.current_activity == CrewActivity.IDLE
    assert refreshed_crew.current_activity_id is None
    assert refreshed_timer.state == TimerState.COMPLETED
    assert refreshed_job.state == JobState.COMPLETED
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "timer_completion"


@pytest.mark.asyncio
async def test_training_handler_idempotent_on_re_dispatch(db_session):
    """Re-dispatching the same timer_complete job must not double-credit XP."""
    from scheduler.jobs.timer_complete import handle_timer_complete

    user = User(discord_id="700102", username="t_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="X", last_name="Y", callsign="Z",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        xp=0,
        current_activity=CrewActivity.TRAINING,
    )
    db_session.add(crew)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=2,
    )
    db_session.add(job)
    await db_session.flush()

    timer = Timer(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        payload={"crew_id": str(crew.id)},
        completes_at=datetime.now(timezone.utc),
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job.id,
    )
    db_session.add(timer)
    job.payload = {"timer_id": str(timer.id)}
    await db_session.flush()

    await handle_timer_complete(db_session, job)
    xp_after_first = (await db_session.get(CrewMember, crew.id)).xp

    # Reset state to simulate re-claim and re-fire.
    job.state = JobState.CLAIMED
    timer.state = TimerState.ACTIVE
    await db_session.flush()
    await handle_timer_complete(db_session, job)
    xp_after_second = (await db_session.get(CrewMember, crew.id)).xp

    assert xp_after_first == xp_after_second  # ledger blocked second credit.
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_timer_complete.py -v`
Expected: 2 FAILs.

- [ ] **Step 3: Implement handler**

Create `scheduler/jobs/timer_complete.py`:

```python
"""timer_complete handler — dispatches by timer.timer_type."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import (
    CrewActivity,
    CrewMember,
    JobState,
    JobType,
    RewardSourceType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
)
from engine.crew_xp import award_xp
from engine.rewards import apply_reward
from engine.timer_recipes import get_recipe
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_timer_complete(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    timer_id_str = job.payload.get("timer_id")
    if not timer_id_str:
        raise ValueError(f"timer_complete job {job.id} missing timer_id in payload")
    timer = await session.get(Timer, uuid.UUID(timer_id_str), with_for_update=True)
    if timer is None:
        raise ValueError(f"Timer {timer_id_str} not found for job {job.id}")
    if timer.state != TimerState.ACTIVE:
        # Idempotent skip: timer already cancelled or completed in a parallel path.
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    recipe = get_recipe(timer.timer_type, timer.recipe_id)

    if timer.timer_type == TimerType.TRAINING:
        notif = await _resolve_training(session, timer, recipe)
    elif timer.timer_type == TimerType.RESEARCH:
        notif = await _resolve_research(session, timer, recipe)
    elif timer.timer_type == TimerType.SHIP_BUILD:
        notif = await _resolve_ship_build(session, timer, recipe)
    else:
        raise ValueError(f"unhandled timer_type {timer.timer_type}")

    timer.state = TimerState.COMPLETED
    job.state = JobState.COMPLETED
    job.completed_at = func.now()

    return HandlerResult(notifications=[notif])


async def _resolve_training(
    session: AsyncSession, timer: Timer, recipe: dict[str, Any]
) -> NotificationRequest:
    crew_id = uuid.UUID(timer.payload["crew_id"])
    crew = await session.get(CrewMember, crew_id, with_for_update=True)
    if crew is None:
        raise ValueError(f"crew {crew_id} not found for timer {timer.id}")

    xp_amount = int(recipe["rewards"]["xp"])
    applied = await apply_reward(
        session,
        user_id=timer.user_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id=f"timer:{timer.id}",
        delta={"xp": 0, "credits": 0},  # User-scoped fields are zero — XP goes to crew.
    )
    if applied:
        await award_xp(session, crew, xp_amount)

    crew.current_activity = CrewActivity.IDLE
    crew.current_activity_id = None

    return NotificationRequest(
        user_id=timer.user_id,
        category="timer_completion",
        title="Training complete",
        body=f'{crew.first_name} "{crew.callsign}" {crew.last_name} '
             f"gained {xp_amount} XP from {recipe['name']}.",
        correlation_id=str(timer.linked_scheduled_job_id),
        dedupe_key=f"timer:{timer.id}",
    )


async def _resolve_research(
    session: AsyncSession, timer: Timer, recipe: dict[str, Any]
) -> NotificationRequest:
    # v1 research output is a fleet buff; we record it in the ledger but
    # actual buff application lives in stat_resolver in a follow-on task.
    # Here we just close out the timer + notify.
    await apply_reward(
        session,
        user_id=timer.user_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id=f"timer:{timer.id}",
        delta={"fleet_buff": recipe["rewards"]["fleet_buff"]},
    )
    return NotificationRequest(
        user_id=timer.user_id,
        category="timer_completion",
        title="Research complete",
        body=f"{recipe['name']} finished.",
        correlation_id=str(timer.linked_scheduled_job_id),
        dedupe_key=f"timer:{timer.id}",
    )


async def _resolve_ship_build(
    session: AsyncSession, timer: Timer, recipe: dict[str, Any]
) -> NotificationRequest:
    # v1 ship build: ledger entry + notification. Actual hull-creation lives
    # in a separate follow-on (Phase 2a stub — see spec).
    await apply_reward(
        session,
        user_id=timer.user_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id=f"timer:{timer.id}",
        delta={"new_ship": recipe["rewards"]["new_ship"]},
    )
    return NotificationRequest(
        user_id=timer.user_id,
        category="timer_completion",
        title="Ship build complete",
        body=f"{recipe['name']} delivered to your hangar.",
        correlation_id=str(timer.linked_scheduled_job_id),
        dedupe_key=f"timer:{timer.id}",
    )


# Self-register so the dispatcher picks us up.
register(JobType.TIMER_COMPLETE, handle_timer_complete)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_timer_complete.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/timer_complete.py tests/test_handler_timer_complete.py
git commit -m "feat(phase2a): timer_complete handler with training/research/ship_build sub-resolvers"
```

---

## Task 15: accrual_tick handler

**Files:**
- Create: `scheduler/jobs/accrual_tick.py`
- Create: `tests/test_handler_accrual_tick.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_handler_accrual_tick.py`:

```python
"""Tests for accrual_tick handler — pending yield accumulation + self-reschedule."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    ScheduledJob,
    StationAssignment,
    StationType,
    User,
)


@pytest.mark.asyncio
async def test_accrual_tick_accumulates_pending_yield(db_session):
    from scheduler.jobs.accrual_tick import handle_accrual_tick

    user = User(discord_id="710001", username="acc_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="N", last_name="V", callsign="Nav",
        archetype=CrewArchetype.NAVIGATOR, rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    await db_session.flush()

    sa = StationAssignment(
        id=uuid.uuid4(), user_id=user.discord_id,
        station_type=StationType.CARGO_RUN, crew_id=crew.id,
        last_yield_tick_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db_session.add(sa)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=user.discord_id,
        job_type=JobType.ACCRUAL_TICK,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED, attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_accrual_tick(db_session, job)

    refreshed = await db_session.get(StationAssignment, sa.id)
    assert refreshed.pending_credits > 0
    assert refreshed.pending_xp > 0


@pytest.mark.asyncio
async def test_accrual_tick_self_reschedules_next_tick(db_session):
    from scheduler.jobs.accrual_tick import handle_accrual_tick

    user = User(discord_id="710002", username="acc_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="X", last_name="Y", callsign="Z",
        archetype=CrewArchetype.GUNNER, rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    await db_session.flush()

    sa = StationAssignment(
        id=uuid.uuid4(), user_id=user.discord_id,
        station_type=StationType.WATCH_TOWER, crew_id=crew.id,
    )
    db_session.add(sa)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=user.discord_id,
        job_type=JobType.ACCRUAL_TICK, payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED, attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_accrual_tick(db_session, job)
    await db_session.flush()

    next_tick = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.user_id == user.discord_id)
        .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
        .where(ScheduledJob.state == JobState.PENDING)
    )).scalar_one_or_none()
    assert next_tick is not None


@pytest.mark.asyncio
async def test_accrual_tick_no_assignments_does_not_reschedule(db_session):
    """If user has zero active assignments, the cycle stops."""
    from scheduler.jobs.accrual_tick import handle_accrual_tick

    user = User(discord_id="710003", username="acc_c", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(), user_id=user.discord_id,
        job_type=JobType.ACCRUAL_TICK, payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED, attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_accrual_tick(db_session, job)
    await db_session.flush()

    pending = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.user_id == user.discord_id)
        .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
        .where(ScheduledJob.state == JobState.PENDING)
    )).all()
    assert pending == []
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_handler_accrual_tick.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement handler**

Create `scheduler/jobs/accrual_tick.py`:

```python
"""accrual_tick handler — yield computation + self-rescheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from config.settings import settings
from db.models import (
    CrewMember,
    JobState,
    JobType,
    RewardSourceType,
    ScheduledJob,
    StationAssignment,
)
from engine.rewards import apply_reward
from engine.station_types import get_station
from scheduler.dispatch import HandlerResult, NotificationRequest, register
from scheduler.enqueue import enqueue_accrual_tick

log = get_logger(__name__)


async def handle_accrual_tick(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    # Idempotency: ledger row keyed off the job id ensures double-fire is a no-op.
    applied = await apply_reward(
        session,
        user_id=job.user_id,
        source_type=RewardSourceType.ACCRUAL_TICK,
        source_id=f"accrual_tick:{job.id}",
        delta={},  # bookkeeping; pending_* increments are below.
    )
    if not applied:
        # Already processed — close out the job without re-incrementing.
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    rows = (await session.execute(
        select(StationAssignment)
        .where(StationAssignment.user_id == job.user_id)
        .where(StationAssignment.recalled_at.is_(None))
    )).scalars().all()

    notifications: list[NotificationRequest] = []
    if not rows:
        # No active assignments — terminate the cycle.
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    now = datetime.now(timezone.utc)
    threshold_user_total = 0
    for sa in rows:
        elapsed = (now - sa.last_yield_tick_at).total_seconds()
        ticks_eq = elapsed / (settings.ACCRUAL_TICK_INTERVAL_MINUTES * 60)
        station = get_station(sa.station_type)

        crew = await session.get(CrewMember, sa.crew_id)
        bonus = 0.0
        if crew and station["preferred_archetype"] == crew.archetype.value:
            bonus = station["archetype_bonus_pct"] / 100.0
        mult = ticks_eq * (1.0 + bonus)

        sa.pending_credits += int(station["yields_per_tick"]["credits"] * mult)
        sa.pending_xp += int(station["yields_per_tick"]["xp"] * mult)
        sa.last_yield_tick_at = now
        threshold_user_total += sa.pending_credits

    # Threshold notification (one per user per tick if it crosses the bar).
    if threshold_user_total >= settings.ACCRUAL_NOTIFICATION_THRESHOLD:
        notifications.append(
            NotificationRequest(
                user_id=job.user_id,
                category="accrual_threshold",
                title="Stations have unclaimed yield",
                body=f"Your stations have {threshold_user_total} pending credits — `/claim` to collect.",
                correlation_id=str(job.id),
                dedupe_key=f"accrual_threshold:{job.user_id}:{now.date().isoformat()}",
            )
        )

    # Mark this tick complete.
    job.state = JobState.COMPLETED
    job.completed_at = func.now()

    # Schedule the next tick.
    next_for = now + timedelta(minutes=settings.ACCRUAL_TICK_INTERVAL_MINUTES)
    await enqueue_accrual_tick(session, user_id=job.user_id, scheduled_for=next_for)

    return HandlerResult(notifications=notifications)


# Self-register.
register(JobType.ACCRUAL_TICK, handle_accrual_tick)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_accrual_tick.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/accrual_tick.py tests/test_handler_accrual_tick.py
git commit -m "feat(phase2a): accrual_tick handler with self-rescheduling and threshold notifications"
```

---

## Task 16: Worker entry point (`scheduler/worker.py`)

**Files:**
- Create: `scheduler/worker.py`
- Create: `tests/test_worker_smoke.py`

- [ ] **Step 1: Write smoke test**

Create `tests/test_worker_smoke.py`:

```python
"""Smoke test for scheduler.worker — start, run a tick, shut down cleanly."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_worker_starts_and_stops_within_timeout():
    from scheduler.worker import run

    shutdown = asyncio.Event()

    async def _stop_after():
        await asyncio.sleep(0.5)
        shutdown.set()

    runner = asyncio.create_task(run(shutdown_event=shutdown))
    stopper = asyncio.create_task(_stop_after())

    await asyncio.wait_for(runner, timeout=5.0)
    await stopper
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_worker_smoke.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement worker**

Create `scheduler/worker.py`:

```python
"""Worker process entry point: tracing, metrics, run_forever loop."""

from __future__ import annotations

import asyncio
import signal

from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import start_http_server
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.logging import get_logger, setup_logging
from config.settings import settings
from config.tracing import init_tracing
from db.session import async_session, engine
from scheduler import dispatch as _dispatch_module  # noqa: F401 — registers handlers
from scheduler.engine import run_forever as run_engine_forever
from scheduler.jobs import accrual_tick as _accrual_module  # noqa: F401
from scheduler.jobs import timer_complete as _timer_complete_module  # noqa: F401
from scheduler.recovery import run_forever as run_recovery_forever

log = get_logger(__name__)


async def run(*, shutdown_event: asyncio.Event | None = None) -> None:
    """Run the worker: start engine and recovery loops concurrently until shutdown."""
    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    sm = async_sessionmaker(bind=engine, expire_on_commit=False)

    engine_task = asyncio.create_task(
        run_engine_forever(sm, _dispatch_module.dispatch, shutdown_event=shutdown_event),
        name="scheduler.engine",
    )
    recovery_task = asyncio.create_task(
        run_recovery_forever(sm, shutdown_event=shutdown_event),
        name="scheduler.recovery",
    )
    log.info("worker_started tick_interval_s=%d", settings.SCHEDULER_TICK_INTERVAL_SECONDS)

    try:
        await asyncio.gather(engine_task, recovery_task)
    finally:
        log.info("worker_stopped")


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _trigger():
        log.info("shutdown_signal_received")
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _trigger)
        except NotImplementedError:
            # Windows may not support signal handlers on the event loop.
            signal.signal(sig, lambda *a: _trigger())


async def _main() -> None:
    setup_logging()
    init_tracing("Dare2Drive-Worker")
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    start_http_server(8002)
    log.info("worker_metrics_server_started port=8002")

    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)

    await run(shutdown_event=shutdown)


def cli() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_worker_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/worker.py tests/test_worker_smoke.py
git commit -m "feat(phase2a): scheduler-worker entry point with tracing + metrics + signal handling"
```

---

## Task 17: Bot notification consumer (`bot/notifications.py`)

**Files:**
- Create: `bot/notifications.py`
- Create: `tests/test_bot_notifications.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bot_notifications.py`:

```python
"""Tests for bot.notifications — Redis-stream consumer + rate-limit + batching."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from db.models import HullClass, User


@pytest.mark.asyncio
async def test_consumer_sends_dm_for_in_band_message(db_session, redis_client, monkeypatch):
    from bot import notifications as notifs

    user = User(
        discord_id="600101", username="cn_a", hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    sent: list[dict[str, Any]] = []

    class FakeUser:
        async def send(self, content: str | None = None, embed=None):
            sent.append({"content": content, "embed": embed})

    class FakeBot:
        async def fetch_user(self, _id: int):
            return FakeUser()

    await redis_client.xadd(
        "d2d:notifications:test",
        {
            "user_id": "600101",
            "category": "timer_completion",
            "title": "T",
            "body": "B",
            "correlation_id": "c",
            "dedupe_key": "k",
            "created_at": "now",
        },
    )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(),
        redis=redis_client,
        stream_key="d2d:notifications:test",
        consumer_group="d2d-bot-test",
        consumer_id="bot-test-1",
        batch_window_seconds=0,  # immediate flush.
    )
    await consumer.ensure_group()
    await consumer.process_once(block_ms=200)
    await asyncio.sleep(0.05)
    await consumer.flush_pending()

    assert len(sent) == 1
    assert "T" in (sent[0]["content"] or "") or sent[0]["embed"] is not None


@pytest.mark.asyncio
async def test_consumer_skips_opted_out_user(db_session, redis_client):
    from bot import notifications as notifs

    user = User(
        discord_id="600102", username="cn_b", hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "off", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    sent: list[Any] = []

    class FakeBot:
        async def fetch_user(self, _id: int):
            class FU:
                async def send(self, *a, **kw):
                    sent.append((a, kw))
            return FU()

    await redis_client.xadd(
        "d2d:notifications:test_optout",
        {
            "user_id": "600102", "category": "timer_completion",
            "title": "T", "body": "B", "correlation_id": "c",
            "dedupe_key": "k", "created_at": "now",
        },
    )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(), redis=redis_client,
        stream_key="d2d:notifications:test_optout",
        consumer_group="g", consumer_id="c1",
        batch_window_seconds=0,
    )
    await consumer.ensure_group()
    await consumer.process_once(block_ms=200)
    await consumer.flush_pending()

    assert sent == []  # opted out — silent drop.


@pytest.mark.asyncio
async def test_consumer_rate_limit_drops_excess(db_session, redis_client):
    from bot import notifications as notifs

    user = User(
        discord_id="600103", username="cn_c", hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    sent: list[str] = []

    class FakeBot:
        async def fetch_user(self, _id: int):
            class FU:
                async def send(self, content=None, embed=None):
                    sent.append(content or "")
            return FU()

    for i in range(10):
        await redis_client.xadd(
            "d2d:notifications:test_rate",
            {
                "user_id": "600103", "category": "timer_completion",
                "title": f"T{i}", "body": "B", "correlation_id": "c",
                "dedupe_key": f"k{i}", "created_at": "now",
            },
        )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(), redis=redis_client,
        stream_key="d2d:notifications:test_rate",
        consumer_group="g", consumer_id="c1",
        batch_window_seconds=0,
        rate_limit_per_hour=3,
    )
    await consumer.ensure_group()
    for _ in range(10):
        await consumer.process_once(block_ms=200)
    await consumer.flush_pending()

    assert len(sent) <= 3
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_bot_notifications.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement consumer**

Create `bot/notifications.py`:

```python
"""Bot-side Redis-stream consumer with rate-limit + batching for DM delivery."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass

import discord
import redis.asyncio as redis_async

from api.metrics import notifications_total
from config.logging import get_logger
from config.settings import settings
from db.models import User
from db.session import async_session

log = get_logger(__name__)

DEFAULT_STREAM_KEY = "d2d:notifications"
DEFAULT_CONSUMER_GROUP = "d2d-bot"


@dataclass
class _PendingItem:
    user_id: str
    category: str
    title: str
    body: str
    entry_id: str
    received_at: float


class NotificationConsumer:
    """Reads notifications from a Redis stream, applies rate-limit + batching, sends DMs."""

    def __init__(
        self,
        *,
        bot: discord.Client,
        redis: redis_async.Redis,
        stream_key: str = DEFAULT_STREAM_KEY,
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        consumer_id: str = "bot-1",
        batch_window_seconds: float | None = None,
        rate_limit_per_hour: int | None = None,
    ) -> None:
        self.bot = bot
        self.redis = redis
        self.stream_key = stream_key
        self.consumer_group = consumer_group
        self.consumer_id = consumer_id
        self.batch_window_seconds = (
            batch_window_seconds
            if batch_window_seconds is not None
            else settings.NOTIFICATION_BATCH_WINDOW_SECONDS
        )
        self.rate_limit_per_hour = (
            rate_limit_per_hour
            if rate_limit_per_hour is not None
            else settings.NOTIFICATION_RATE_LIMIT_PER_HOUR
        )
        self._buffer: dict[str, list[_PendingItem]] = defaultdict(list)
        self._rate_buckets: dict[tuple[str, int], int] = defaultdict(int)
        self._stop = asyncio.Event()

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream_key, self.consumer_group, id="$", mkstream=True)
        except redis_async.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run(self) -> None:
        """Run forever, until stop() is called."""
        await self.ensure_group()
        while not self._stop.is_set():
            try:
                await self.process_once(block_ms=2000)
                await self.flush_pending()
            except Exception:
                log.exception("notification consumer loop error")
                await asyncio.sleep(1)

    def stop(self) -> None:
        self._stop.set()

    async def process_once(self, *, block_ms: int = 2000) -> None:
        msgs = await self.redis.xreadgroup(
            self.consumer_group,
            self.consumer_id,
            {self.stream_key: ">"},
            count=50,
            block=block_ms,
        )
        if not msgs:
            return
        for _stream, entries in msgs:
            for entry_id, fields in entries:
                user_id = fields.get("user_id")
                if not user_id:
                    await self.redis.xack(self.stream_key, self.consumer_group, entry_id)
                    continue
                self._buffer[user_id].append(
                    _PendingItem(
                        user_id=user_id,
                        category=fields.get("category", "timer_completion"),
                        title=fields.get("title", ""),
                        body=fields.get("body", ""),
                        entry_id=entry_id,
                        received_at=time.monotonic(),
                    )
                )

    async def flush_pending(self) -> None:
        now = time.monotonic()
        for user_id, items in list(self._buffer.items()):
            ready = [it for it in items if (now - it.received_at) >= self.batch_window_seconds]
            if not ready:
                continue
            await self._deliver_batch(user_id, ready)
            self._buffer[user_id] = [it for it in items if it not in ready]
            if not self._buffer[user_id]:
                del self._buffer[user_id]

    async def _deliver_batch(self, user_id: str, items: list[_PendingItem]) -> None:
        async with async_session() as session:
            user = await session.get(User, user_id)
        if user is None:
            for it in items:
                await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
                notifications_total.labels(category=it.category, result="user_missing").inc()
            return

        prefs = dict(user.notification_prefs or {})
        # Filter out opted-out categories.
        deliver, drop = [], []
        for it in items:
            if prefs.get(it.category, "dm") == "off":
                drop.append(it)
            else:
                deliver.append(it)
        for it in drop:
            await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
            notifications_total.labels(category=it.category, result="opted_out").inc()

        if not deliver:
            return

        # Rate limit (per-user, per hour bucket).
        hour_bucket = int(time.time() // 3600)
        sent_this_hour = self._rate_buckets[(user_id, hour_bucket)]
        room = max(0, self.rate_limit_per_hour - sent_this_hour)
        to_send = deliver[:room] if room < len(deliver) else deliver
        rate_dropped = deliver[room:] if room < len(deliver) else []
        for it in rate_dropped:
            await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
            notifications_total.labels(category=it.category, result="rate_limited").inc()

        if not to_send:
            return

        try:
            discord_user = await self.bot.fetch_user(int(user_id))
        except Exception:
            log.exception("fetch_user failed user_id=%s", user_id)
            return

        # Merge titles/bodies into one DM.
        merged = "\n\n".join(f"**{it.title}**\n{it.body}" for it in to_send)
        try:
            await discord_user.send(merged)
            for it in to_send:
                await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
                notifications_total.labels(category=it.category, result="delivered").inc()
            self._rate_buckets[(user_id, hour_bucket)] += len(to_send)
        except discord.Forbidden:
            for it in to_send:
                await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
                notifications_total.labels(category=it.category, result="dm_closed").inc()
        except Exception:
            log.exception("DM send failed user_id=%s", user_id)
            for it in to_send:
                notifications_total.labels(category=it.category, result="failed").inc()
            # don't XACK transient failures — let XPENDING reclaim later.
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_bot_notifications.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/notifications.py tests/test_bot_notifications.py
git commit -m "feat(phase2a): bot notification consumer with rate-limit + batching"
```

---

## Task 18: Phase 2a metrics

**Files:**
- Modify: `api/metrics.py`

This task has no separate test file — metrics are exercised indirectly by the handler/dispatcher/notification tests (which import these names).

- [ ] **Step 1: Append the new metrics**

Append to `api/metrics.py`:

```python
# ---------------------------------------------------------------------------
# Phase 2a — Scheduler / Timers / Accrual / Notifications
# ---------------------------------------------------------------------------

scheduler_jobs_total = Counter(
    "dare2drive_scheduler_jobs_total",
    "Scheduler job dispatch outcomes.",
    ["job_type", "result"],  # result: success | failure
)

scheduler_job_duration_seconds = Histogram(
    "dare2drive_scheduler_job_duration_seconds",
    "Scheduler job dispatch duration.",
    ["job_type"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

scheduler_jobs_in_flight = Gauge(
    "dare2drive_scheduler_jobs_in_flight",
    "Jobs currently in state='claimed' (snapshot).",
)

scheduler_jobs_pending = Gauge(
    "dare2drive_scheduler_jobs_pending",
    "Jobs currently in state='pending' (snapshot).",
)

scheduler_tick_duration_seconds = Histogram(
    "dare2drive_scheduler_tick_duration_seconds",
    "Scheduler tick duration.",
    buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

notifications_total = Counter(
    "dare2drive_notifications_total",
    "Notification delivery outcomes.",
    ["category", "result"],
    # result: delivered | rate_limited | opted_out | dm_closed | failed | user_missing
)

notification_stream_lag = Gauge(
    "dare2drive_notification_stream_lag",
    "Approx XLEN of d2d:notifications stream.",
)

timers_started_total = Counter(
    "dare2drive_timers_started_total",
    "Timers started, by type.",
    ["timer_type"],
)

timers_completed_total = Counter(
    "dare2drive_timers_completed_total",
    "Timers completed, by type and outcome.",
    ["timer_type", "outcome"],  # success | cancelled
)

station_yield_credits_total = Counter(
    "dare2drive_station_yield_credits_total",
    "Total credits yielded by station accrual (pre-claim).",
)

claim_total = Counter(
    "dare2drive_claim_total",
    "/claim invocations.",
    ["result"],  # success | empty
)
```

- [ ] **Step 2: Smoke test the imports work**

Run: `python -c "from api.metrics import scheduler_jobs_total, notifications_total, timers_started_total, claim_total; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add api/metrics.py
git commit -m "feat(phase2a): scheduler/timer/notification/claim Prometheus metrics"
```

---

## Task 19: `/training` slash commands in `bot/cogs/fleet.py`

**Files:**
- Create: `bot/cogs/fleet.py`
- Create: `tests/test_cog_fleet_training.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_fleet_training.py`:

```python
"""Tests for /training start, /training status, /training cancel."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    Rarity,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


def _make_interaction(user_id: str, system_id: str = "222222222") -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id)
    inter.channel_id = int(system_id)
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_training_start_validates_credits_and_schedules_timer(
    db_session, sample_system, monkeypatch
):
    """A successful /training start deducts credits, sets crew busy, inserts timer + job."""
    from bot.cogs import fleet as fleet_mod

    user = User(
        discord_id="600301", username="cog_a",
        hull_class=HullClass.HAULER, currency=200,
    )
    db_session.add(user)
    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="A", last_name="B", callsign="C",
        archetype=CrewArchetype.PILOT, rarity=Rarity.COMMON,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    monkeypatch.setattr(
        fleet_mod, "async_session",
        lambda: _SessionWrapper(db_session),
    )
    monkeypatch.setattr(
        fleet_mod, "get_active_system",
        AsyncMock(return_value=sample_system),
    )

    inter = _make_interaction(user.discord_id)
    cog = fleet_mod.FleetCog(MagicMock())
    await cog.training_start.callback(
        cog, inter, crew=f'A "C" B', routine="combat_drills",
    )

    refreshed_user = await db_session.get(User, user.discord_id)
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert refreshed_user.currency == 150  # 200 - 50.
    assert refreshed_crew.current_activity == CrewActivity.TRAINING


class _SessionWrapper:
    """Make async_session() returns a context manager wrapping the test session."""
    def __init__(self, session):
        self._session = session
    async def __aenter__(self):
        return self._session
    async def __aexit__(self, *a):
        return False
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_fleet_training.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the cog (training portion)**

Create `bot/cogs/fleet.py` (this file will grow across Tasks 20–22; start with the training surface here):

```python
"""Fleet cog — Phase 2a slash commands for timers, stations, claims, notifications."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import currency_spent, timers_completed_total, timers_started_total
from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.settings import settings
from db.models import (
    CrewActivity,
    CrewMember,
    JobState,
    JobType,
    RewardSourceType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)
from db.session import async_session
from engine.rewards import apply_reward
from engine.timer_recipes import RecipeNotFound, get_recipe, list_recipes
from scheduler.enqueue import enqueue_timer

log = get_logger(__name__)


# ──────────── helpers ────────────


async def _lookup_crew_by_display(
    session: AsyncSession, user_id: str, display_name: str
) -> CrewMember | None:
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


async def _crew_idle_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete listing only idle crew."""
    async with async_session() as session:
        rows = (await session.execute(
            select(CrewMember).where(
                CrewMember.user_id == str(interaction.user.id),
                CrewMember.current_activity == CrewActivity.IDLE,
            )
        )).scalars().all()
    q = current.lower()
    out: list[app_commands.Choice[str]] = []
    for m in rows:
        name = f'{m.first_name} "{m.callsign}" {m.last_name}'
        if q in name.lower():
            out.append(app_commands.Choice(name=name[:100], value=name[:100]))
        if len(out) >= 25:
            break
    return out


def _routine_choices() -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=f"{r['name']} ({r['cost_credits']} Creds, {r['duration_minutes']}m)", value=r["id"])
        for r in list_recipes(TimerType.TRAINING)
    ]


# ──────────── cog ────────────


class FleetCog(commands.Cog):
    """All Phase 2a fleet/training/research/build/stations/claim commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    training = app_commands.Group(name="training", description="Crew training routines")

    @training.command(name="start", description="Start a training routine on a crew member.")
    @app_commands.describe(crew="Which crew member to train", routine="Training routine to run")
    @app_commands.autocomplete(crew=_crew_idle_autocomplete)
    @app_commands.choices(routine=_routine_choices())
    async def training_start(
        self,
        interaction: discord.Interaction,
        crew: str,
        routine: str,
    ) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return

        try:
            recipe = get_recipe(TimerType.TRAINING, routine)
        except RecipeNotFound:
            await interaction.response.send_message("Unknown routine.", ephemeral=True)
            return

        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None or user.currency < recipe["cost_credits"]:
                await interaction.response.send_message(
                    f"You need {recipe['cost_credits']} credits.", ephemeral=True,
                )
                return
            crew_row = await _lookup_crew_by_display(session, user.discord_id, crew)
            if crew_row is None:
                await interaction.response.send_message("Crew member not found.", ephemeral=True)
                return
            if crew_row.current_activity != CrewActivity.IDLE:
                await interaction.response.send_message(
                    f"{crew_row.first_name} is currently {crew_row.current_activity.value}. "
                    "Free them first.", ephemeral=True,
                )
                return

            now = datetime.now(timezone.utc)
            completes_at = now + timedelta(minutes=recipe["duration_minutes"])
            timer, _job = await enqueue_timer(
                session, user_id=user.discord_id,
                timer_type=TimerType.TRAINING, recipe_id=routine,
                completes_at=completes_at,
                payload={"crew_id": str(crew_row.id)},
            )
            user.currency -= recipe["cost_credits"]
            crew_row.current_activity = CrewActivity.TRAINING
            crew_row.current_activity_id = timer.id

        currency_spent.labels(reason="training").inc(recipe["cost_credits"])
        timers_started_total.labels(timer_type="training").inc()

        await interaction.response.send_message(
            f"**{recipe['name']}** started for {crew}. Returns in {recipe['duration_minutes']} minutes.",
            ephemeral=True,
        )

    @training.command(name="status", description="List your active and recent training timers.")
    async def training_status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            active = (await session.execute(
                select(Timer)
                .where(Timer.user_id == str(interaction.user.id))
                .where(Timer.timer_type == TimerType.TRAINING)
                .where(Timer.state == TimerState.ACTIVE)
                .order_by(Timer.completes_at)
            )).scalars().all()
        if not active:
            await interaction.response.send_message("No active training.", ephemeral=True)
            return
        lines = []
        for t in active:
            lines.append(
                f"• `{t.recipe_id}` — completes {discord.utils.format_dt(t.completes_at, 'R')}"
            )
        await interaction.response.send_message(
            "**Active training:**\n" + "\n".join(lines), ephemeral=True,
        )

    @training.command(name="cancel", description="Cancel an active training (50% credit refund, no XP).")
    @app_commands.describe(crew="Which crew member's training to cancel")
    async def training_cancel(self, interaction: discord.Interaction, crew: str) -> None:
        async with async_session() as session, session.begin():
            crew_row = await _lookup_crew_by_display(session, str(interaction.user.id), crew)
            if crew_row is None or crew_row.current_activity != CrewActivity.TRAINING:
                await interaction.response.send_message(
                    "That crew member is not currently training.", ephemeral=True,
                )
                return
            timer = await session.get(Timer, crew_row.current_activity_id, with_for_update=True)
            if timer is None or timer.state != TimerState.ACTIVE:
                await interaction.response.send_message("Training already completed.", ephemeral=True)
                return
            recipe = get_recipe(TimerType.TRAINING, timer.recipe_id)

            # Cancel the linked job atomically — only succeeds if still pending.
            from sqlalchemy import update as _upd
            result = await session.execute(
                _upd(ScheduledJob)
                .where(ScheduledJob.id == timer.linked_scheduled_job_id)
                .where(ScheduledJob.state == JobState.PENDING)
                .values(state=JobState.CANCELLED)
            )
            if (result.rowcount or 0) == 0:
                await interaction.response.send_message(
                    "Training is already firing — too late to cancel.", ephemeral=True,
                )
                return

            refund = (recipe["cost_credits"] * settings.TIMER_CANCEL_REFUND_PCT) // 100
            await apply_reward(
                session,
                user_id=crew_row.user_id,
                source_type=RewardSourceType.TIMER_CANCEL_REFUND,
                source_id=f"timer_cancel_refund:{timer.id}",
                delta={"credits": refund},
            )
            timer.state = TimerState.CANCELLED
            crew_row.current_activity = CrewActivity.IDLE
            crew_row.current_activity_id = None

        timers_completed_total.labels(timer_type="training", outcome="cancelled").inc()
        await interaction.response.send_message(
            f"Training cancelled. Refunded {refund} credits.", ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FleetCog(bot))
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_fleet_training.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/fleet.py tests/test_cog_fleet_training.py
git commit -m "feat(phase2a): /training start/status/cancel slash commands"
```

---

## Task 20: `/research` and `/build` slash commands

**Files:**
- Modify: `bot/cogs/fleet.py`
- Create: `tests/test_cog_fleet_research_build.py`

These commands follow the same pattern as `/training`, but are user-scoped (one active per user) rather than crew-scoped. The partial unique indexes from Task 4 enforce concurrency at the DB layer.

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_fleet_research_build.py`:

```python
"""Tests for /research and /build commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import HullClass, TimerType, User


def _make_interaction(user_id: str) -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id)
    inter.channel_id = 222222222
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_research_start_inserts_active_research_timer(
    db_session, sample_system, monkeypatch
):
    from bot.cogs import fleet as fleet_mod
    from sqlalchemy import select
    from db.models import Timer

    user = User(discord_id="600401", username="r_a", hull_class=HullClass.HAULER, currency=500)
    db_session.add(user)
    await db_session.flush()

    class _SW:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(fleet_mod, "async_session", lambda: _SW(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    inter = _make_interaction(user.discord_id)
    cog = fleet_mod.FleetCog(MagicMock())
    await cog.research_start.callback(cog, inter, project="drive_tuning")

    timer = (await db_session.execute(
        select(Timer).where(Timer.user_id == user.discord_id, Timer.timer_type == TimerType.RESEARCH)
    )).scalar_one_or_none()
    assert timer is not None
    assert timer.recipe_id == "drive_tuning"


@pytest.mark.asyncio
async def test_research_start_blocked_by_partial_unique_index(
    db_session, sample_system, monkeypatch
):
    """A second concurrent research timer must be rejected by the DB."""
    from bot.cogs import fleet as fleet_mod

    user = User(discord_id="600402", username="r_b", hull_class=HullClass.HAULER, currency=2000)
    db_session.add(user)
    await db_session.flush()

    class _SW:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(fleet_mod, "async_session", lambda: _SW(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    cog = fleet_mod.FleetCog(MagicMock())
    inter1 = _make_interaction(user.discord_id)
    await cog.research_start.callback(cog, inter1, project="drive_tuning")

    inter2 = _make_interaction(user.discord_id)
    with pytest.raises(IntegrityError):
        await cog.research_start.callback(cog, inter2, project="shield_calibration")


@pytest.mark.asyncio
async def test_build_construct_inserts_active_ship_build_timer(
    db_session, sample_system, monkeypatch
):
    from bot.cogs import fleet as fleet_mod
    from sqlalchemy import select
    from db.models import Timer

    user = User(discord_id="600403", username="r_c", hull_class=HullClass.HAULER, currency=1000)
    db_session.add(user)
    await db_session.flush()

    class _SW:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(fleet_mod, "async_session", lambda: _SW(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.build_construct.callback(cog, inter, recipe="salvage_reconstruction")

    timer = (await db_session.execute(
        select(Timer).where(Timer.user_id == user.discord_id, Timer.timer_type == TimerType.SHIP_BUILD)
    )).scalar_one_or_none()
    assert timer is not None
    assert timer.recipe_id == "salvage_reconstruction"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_fleet_research_build.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Add `/research` group to `bot/cogs/fleet.py`**

Append inside the `FleetCog` class (after the existing `training` group definitions) — preserves the `class` declaration; do not duplicate it:

```python
    research = app_commands.Group(name="research", description="Fleet-wide research projects")

    @research.command(name="start", description="Start a research project (one active per pilot).")
    @app_commands.choices(
        project=[
            app_commands.Choice(name="Drive Tuning (200 Creds, 60m, +2% acceleration 48h)", value="drive_tuning"),
            app_commands.Choice(name="Shield Calibration (250 Creds, 75m, +2% durability 48h)", value="shield_calibration"),
            app_commands.Choice(name="Navigational Charting (300 Creds, 90m, +3% weather 48h)", value="nav_charting"),
        ]
    )
    async def research_start(self, interaction: discord.Interaction, project: str) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return
        try:
            recipe = get_recipe(TimerType.RESEARCH, project)
        except RecipeNotFound:
            await interaction.response.send_message("Unknown project.", ephemeral=True)
            return
        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None or user.currency < recipe["cost_credits"]:
                await interaction.response.send_message(
                    f"You need {recipe['cost_credits']} credits.", ephemeral=True,
                )
                return
            now = datetime.now(timezone.utc)
            completes_at = now + timedelta(minutes=recipe["duration_minutes"])
            await enqueue_timer(
                session, user_id=user.discord_id,
                timer_type=TimerType.RESEARCH, recipe_id=project,
                completes_at=completes_at, payload={},
            )
            user.currency -= recipe["cost_credits"]
        currency_spent.labels(reason="research").inc(recipe["cost_credits"])
        timers_started_total.labels(timer_type="research").inc()
        await interaction.response.send_message(
            f"**{recipe['name']}** started. Completes in {recipe['duration_minutes']} minutes.",
            ephemeral=True,
        )

    @research.command(name="status", description="Status of your active research project.")
    async def research_status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            t = (await session.execute(
                select(Timer)
                .where(Timer.user_id == str(interaction.user.id))
                .where(Timer.timer_type == TimerType.RESEARCH)
                .where(Timer.state == TimerState.ACTIVE)
            )).scalar_one_or_none()
        if t is None:
            await interaction.response.send_message("No active research.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**Active research:** `{t.recipe_id}` — "
            f"completes {discord.utils.format_dt(t.completes_at, 'R')}",
            ephemeral=True,
        )

    @research.command(name="cancel", description="Cancel your active research (50% credit refund).")
    async def research_cancel(self, interaction: discord.Interaction) -> None:
        await self._cancel_user_scoped_timer(interaction, TimerType.RESEARCH, "research")

    build = app_commands.Group(name="build", description="Ship construction recipes")

    @build.command(name="construct", description="Start a ship-build recipe (one active per pilot).")
    @app_commands.choices(
        recipe=[
            app_commands.Choice(
                name="Salvage Reconstruction (500 Creds, 120m, 1 hauler hull)",
                value="salvage_reconstruction",
            ),
        ]
    )
    async def build_construct(self, interaction: discord.Interaction, recipe: str) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return
        try:
            r = get_recipe(TimerType.SHIP_BUILD, recipe)
        except RecipeNotFound:
            await interaction.response.send_message("Unknown recipe.", ephemeral=True)
            return
        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None or user.currency < r["cost_credits"]:
                await interaction.response.send_message(
                    f"You need {r['cost_credits']} credits.", ephemeral=True,
                )
                return
            now = datetime.now(timezone.utc)
            await enqueue_timer(
                session, user_id=user.discord_id,
                timer_type=TimerType.SHIP_BUILD, recipe_id=recipe,
                completes_at=now + timedelta(minutes=r["duration_minutes"]),
                payload={},
            )
            user.currency -= r["cost_credits"]
        currency_spent.labels(reason="ship_build").inc(r["cost_credits"])
        timers_started_total.labels(timer_type="ship_build").inc()
        await interaction.response.send_message(
            f"**{r['name']}** started. Slipway hum-time: {r['duration_minutes']} minutes.",
            ephemeral=True,
        )

    @build.command(name="status", description="Status of your active ship-build.")
    async def build_status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            t = (await session.execute(
                select(Timer)
                .where(Timer.user_id == str(interaction.user.id))
                .where(Timer.timer_type == TimerType.SHIP_BUILD)
                .where(Timer.state == TimerState.ACTIVE)
            )).scalar_one_or_none()
        if t is None:
            await interaction.response.send_message("No active ship-build.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**Active ship-build:** `{t.recipe_id}` — "
            f"completes {discord.utils.format_dt(t.completes_at, 'R')}",
            ephemeral=True,
        )

    @build.command(name="cancel", description="Cancel your active ship-build (50% credit refund).")
    async def build_cancel(self, interaction: discord.Interaction) -> None:
        await self._cancel_user_scoped_timer(interaction, TimerType.SHIP_BUILD, "ship_build")

    async def _cancel_user_scoped_timer(
        self, interaction: discord.Interaction, ttype: TimerType, label: str
    ) -> None:
        async with async_session() as session, session.begin():
            t = (await session.execute(
                select(Timer)
                .where(Timer.user_id == str(interaction.user.id))
                .where(Timer.timer_type == ttype)
                .where(Timer.state == TimerState.ACTIVE)
                .with_for_update()
            )).scalar_one_or_none()
            if t is None:
                await interaction.response.send_message(
                    f"No active {label} to cancel.", ephemeral=True,
                )
                return
            recipe = get_recipe(ttype, t.recipe_id)
            from sqlalchemy import update as _upd
            result = await session.execute(
                _upd(ScheduledJob)
                .where(ScheduledJob.id == t.linked_scheduled_job_id)
                .where(ScheduledJob.state == JobState.PENDING)
                .values(state=JobState.CANCELLED)
            )
            if (result.rowcount or 0) == 0:
                await interaction.response.send_message(
                    f"{label.title()} is already firing — too late to cancel.", ephemeral=True,
                )
                return
            refund = (recipe["cost_credits"] * settings.TIMER_CANCEL_REFUND_PCT) // 100
            await apply_reward(
                session, user_id=t.user_id,
                source_type=RewardSourceType.TIMER_CANCEL_REFUND,
                source_id=f"timer_cancel_refund:{t.id}",
                delta={"credits": refund},
            )
            t.state = TimerState.CANCELLED
        timers_completed_total.labels(timer_type=ttype.value, outcome="cancelled").inc()
        await interaction.response.send_message(
            f"{label.title()} cancelled. Refunded {refund} credits.", ephemeral=True,
        )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_fleet_research_build.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/fleet.py tests/test_cog_fleet_research_build.py
git commit -m "feat(phase2a): /research and /build slash command groups"
```

---

## Task 21: `/stations` and `/claim` slash commands

**Files:**
- Modify: `bot/cogs/fleet.py`
- Create: `tests/test_cog_fleet_stations_claim.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cog_fleet_stations_claim.py`:

```python
"""Tests for /stations assign/list/recall and /claim."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    Rarity,
    StationAssignment,
    StationType,
    User,
)


def _make_interaction(user_id: str) -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id)
    inter.channel_id = 222222222
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_stations_assign_creates_row_and_marks_crew_busy(
    db_session, sample_system, monkeypatch
):
    from bot.cogs import fleet as fleet_mod

    user = User(discord_id="600501", username="s_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="Cee", last_name="Are", callsign="Crow",
        archetype=CrewArchetype.NAVIGATOR, rarity=Rarity.COMMON,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    class _SW:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(fleet_mod, "async_session", lambda: _SW(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.stations_assign.callback(
        cog, inter, crew='Cee "Crow" Are', station="cargo_run",
    )

    sa = (await db_session.execute(
        select(StationAssignment).where(StationAssignment.user_id == user.discord_id)
    )).scalar_one_or_none()
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert sa is not None
    assert sa.station_type == StationType.CARGO_RUN
    assert refreshed_crew.current_activity == CrewActivity.ON_STATION


@pytest.mark.asyncio
async def test_claim_zeroes_pending_and_credits_user(db_session, sample_system, monkeypatch):
    from bot.cogs import fleet as fleet_mod

    user = User(discord_id="600502", username="s_b", hull_class=HullClass.HAULER, currency=10)
    db_session.add(user)
    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="X", last_name="Y", callsign="Z",
        archetype=CrewArchetype.GUNNER, rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    sa = StationAssignment(
        id=uuid.uuid4(), user_id=user.discord_id,
        station_type=StationType.WATCH_TOWER, crew_id=crew.id,
        pending_credits=300, pending_xp=80,
    )
    db_session.add(sa)
    await db_session.flush()

    class _SW:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(fleet_mod, "async_session", lambda: _SW(db_session))
    monkeypatch.setattr(fleet_mod, "get_active_system", AsyncMock(return_value=sample_system))

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.claim.callback(cog, inter)

    refreshed_user = await db_session.get(User, user.discord_id)
    refreshed_sa = await db_session.get(StationAssignment, sa.id)
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert refreshed_user.currency == 310  # 10 + 300.
    assert refreshed_sa.pending_credits == 0
    assert refreshed_sa.pending_xp == 0
    assert refreshed_crew.xp == 80
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_fleet_stations_claim.py -v`
Expected: 2 FAILs.

- [ ] **Step 3: Add stations + claim commands to `bot/cogs/fleet.py`**

Append inside the `FleetCog` class:

```python
    stations = app_commands.Group(name="stations", description="Station accrual roster")

    @stations.command(name="list", description="See your station roster + pending yield.")
    async def stations_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = (await session.execute(
                select(StationAssignment)
                .where(StationAssignment.user_id == str(interaction.user.id))
                .where(StationAssignment.recalled_at.is_(None))
            )).scalars().all()
        if not rows:
            await interaction.response.send_message("No active station assignments.", ephemeral=True)
            return
        lines = [
            f"• **{r.station_type.value}** — {r.pending_credits} cred / {r.pending_xp} xp pending"
            for r in rows
        ]
        await interaction.response.send_message(
            "**Stations:**\n" + "\n".join(lines), ephemeral=True,
        )

    @stations.command(name="assign", description="Assign a crew member to a station type.")
    @app_commands.describe(crew="Idle crew member to assign", station="Station type")
    @app_commands.autocomplete(crew=_crew_idle_autocomplete)
    @app_commands.choices(
        station=[
            app_commands.Choice(name="Cargo Run", value="cargo_run"),
            app_commands.Choice(name="Repair Bay", value="repair_bay"),
            app_commands.Choice(name="Watch Tower", value="watch_tower"),
        ]
    )
    async def stations_assign(
        self, interaction: discord.Interaction, crew: str, station: str
    ) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return
        from db.models import StationType as _ST
        st = _ST(station)
        async with async_session() as session, session.begin():
            crew_row = await _lookup_crew_by_display(session, str(interaction.user.id), crew)
            if crew_row is None:
                await interaction.response.send_message("Crew member not found.", ephemeral=True)
                return
            if crew_row.current_activity != CrewActivity.IDLE:
                await interaction.response.send_message(
                    f"{crew_row.first_name} is currently {crew_row.current_activity.value}.",
                    ephemeral=True,
                )
                return
            sa = StationAssignment(
                id=uuid.uuid4(),
                user_id=str(interaction.user.id),
                station_type=st,
                crew_id=crew_row.id,
            )
            session.add(sa)
            crew_row.current_activity = CrewActivity.ON_STATION
            crew_row.current_activity_id = sa.id
            # Bootstrap an accrual_tick if none pending for this user.
            from scheduler.enqueue import enqueue_accrual_tick
            existing = (await session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.user_id == str(interaction.user.id))
                .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
                .where(ScheduledJob.state == JobState.PENDING)
            )).scalar_one_or_none()
            if existing is None:
                fires = datetime.now(timezone.utc) + timedelta(
                    minutes=settings.ACCRUAL_TICK_INTERVAL_MINUTES
                )
                await enqueue_accrual_tick(
                    session, user_id=str(interaction.user.id), scheduled_for=fires,
                )
        await interaction.response.send_message(
            f"{crew} assigned to **{station.replace('_', ' ').title()}**.", ephemeral=True,
        )

    @stations.command(name="recall", description="Recall a crew from station (yield stays claimable).")
    async def stations_recall(self, interaction: discord.Interaction, crew: str) -> None:
        async with async_session() as session, session.begin():
            crew_row = await _lookup_crew_by_display(session, str(interaction.user.id), crew)
            if crew_row is None or crew_row.current_activity != CrewActivity.ON_STATION:
                await interaction.response.send_message(
                    "That crew member is not on a station.", ephemeral=True,
                )
                return
            sa = await session.get(
                StationAssignment, crew_row.current_activity_id, with_for_update=True,
            )
            if sa is not None:
                sa.recalled_at = datetime.now(timezone.utc)
            crew_row.current_activity = CrewActivity.IDLE
            crew_row.current_activity_id = None
        await interaction.response.send_message(f"{crew} recalled. Yield remains claimable.", ephemeral=True)

    @app_commands.command(name="claim", description="Claim all pending station yield.")
    async def claim(self, interaction: discord.Interaction) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return
        from api.metrics import claim_total
        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None:
                claim_total.labels(result="empty").inc()
                await interaction.response.send_message("No account.", ephemeral=True)
                return
            rows = (await session.execute(
                select(StationAssignment)
                .where(StationAssignment.user_id == user.discord_id)
                .with_for_update()
            )).scalars().all()
            total_credits = 0
            total_xp_per_crew: dict[uuid.UUID, int] = {}
            for r in rows:
                total_credits += r.pending_credits
                if r.pending_xp:
                    total_xp_per_crew[r.crew_id] = total_xp_per_crew.get(r.crew_id, 0) + r.pending_xp
                r.pending_credits = 0
                r.pending_xp = 0
            if total_credits == 0 and not total_xp_per_crew:
                claim_total.labels(result="empty").inc()
                await interaction.response.send_message("Nothing to claim.", ephemeral=True)
                return
            await apply_reward(
                session, user_id=user.discord_id,
                source_type=RewardSourceType.ACCRUAL_CLAIM,
                source_id=f"accrual_claim:{uuid.uuid4()}",
                delta={"credits": total_credits},
            )
            for crew_id, xp in total_xp_per_crew.items():
                crew_row = await session.get(CrewMember, crew_id)
                if crew_row is not None:
                    crew_row.xp += xp
            # Cleanup recalled rows that are now empty.
            for r in rows:
                if r.recalled_at is not None:
                    await session.delete(r)
        claim_total.labels(result="success").inc()
        await interaction.response.send_message(
            f"Claimed **{total_credits}** credits and XP across stations.", ephemeral=True,
        )
```

Note: the `import uuid` at the top of the file already covers the inline `uuid.uuid4()` use in `claim` and `stations_assign`. The `from datetime import ...` import is also already present.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_fleet_stations_claim.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/fleet.py tests/test_cog_fleet_stations_claim.py
git commit -m "feat(phase2a): /stations list/assign/recall and /claim slash commands"
```

---

## Task 22: `/notifications` slash command

**Files:**
- Modify: `bot/cogs/fleet.py`
- Create: `tests/test_cog_fleet_notifications.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_cog_fleet_notifications.py`:

```python
"""Tests for /notifications view + edit."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import HullClass, User


def _make_interaction(user_id: str) -> MagicMock:
    inter = MagicMock()
    inter.user.id = int(user_id)
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_notifications_set_updates_prefs(db_session, monkeypatch):
    from bot.cogs import fleet as fleet_mod

    user = User(
        discord_id="600601", username="n_a", hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    class _SW:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(fleet_mod, "async_session", lambda: _SW(db_session))

    cog = fleet_mod.FleetCog(MagicMock())
    inter = _make_interaction(user.discord_id)
    await cog.notifications.callback(cog, inter, category="timer_completion", value="off")

    refreshed = await db_session.get(User, user.discord_id)
    assert refreshed.notification_prefs["timer_completion"] == "off"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_fleet_notifications.py -v`
Expected: FAIL.

- [ ] **Step 3: Add `/notifications` command**

Append inside the `FleetCog` class:

```python
    @app_commands.command(
        name="notifications",
        description="View or edit your notification preferences.",
    )
    @app_commands.describe(
        category="Which notification category to edit (omit to view).",
        value="dm = receive as DM, off = silenced.",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Timer completion", value="timer_completion"),
            app_commands.Choice(name="Accrual threshold", value="accrual_threshold"),
        ],
        value=[
            app_commands.Choice(name="DM", value="dm"),
            app_commands.Choice(name="Off", value="off"),
        ],
    )
    async def notifications(
        self,
        interaction: discord.Interaction,
        category: str | None = None,
        value: str | None = None,
    ) -> None:
        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None:
                await interaction.response.send_message("No account.", ephemeral=True)
                return
            prefs = dict(user.notification_prefs or {})
            if category and value:
                prefs[category] = value
                prefs["_version"] = 1
                user.notification_prefs = prefs
                await interaction.response.send_message(
                    f"`{category}` set to **{value}**.", ephemeral=True,
                )
                return
        # View mode.
        lines = [
            f"• **{k}**: `{v}`" for k, v in user.notification_prefs.items() if not k.startswith("_")
        ]
        await interaction.response.send_message(
            "**Your notification preferences:**\n" + "\n".join(lines), ephemeral=True,
        )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_cog_fleet_notifications.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/fleet.py tests/test_cog_fleet_notifications.py
git commit -m "feat(phase2a): /notifications view/edit slash command"
```

---

## Task 23: Wire the FleetCog and notification consumer into the bot

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1: Manual smoke test (no automated test)**

Cog/consumer wiring is exercised by the integration scenarios in Tasks 24–25. This task is a focused edit to `bot/main.py` only.

- [ ] **Step 2: Modify `bot/main.py`**

Find the `cog_modules` list and append `"bot.cogs.fleet"` so it reads:

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

In the same `Dare2DriveBot` class, extend `setup_hook` to start the notification consumer. After the existing cog-loading loop and before the `if settings.DISCORD_GUILD_ID:` block, insert:

```python
        # Phase 2a — start the notification consumer.
        import redis.asyncio as _redis_async

        from bot.notifications import NotificationConsumer

        self._notif_redis = _redis_async.from_url(settings.REDIS_URL, decode_responses=True)
        self._notif_consumer = NotificationConsumer(
            bot=self, redis=self._notif_redis,
        )
        self._notif_task = asyncio.create_task(
            self._notif_consumer.run(), name="notification_consumer",
        )
        log.info("notification_consumer_started")
```

Override `close` on the same class (add this method to `Dare2DriveBot`):

```python
    async def close(self) -> None:
        # Stop notification consumer cleanly.
        consumer = getattr(self, "_notif_consumer", None)
        task = getattr(self, "_notif_task", None)
        if consumer is not None:
            consumer.stop()
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        redis_client = getattr(self, "_notif_redis", None)
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        await super().close()
```

- [ ] **Step 3: Smoke check the bot still imports**

Run: `python -c "from bot.main import Dare2DriveBot; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "feat(phase2a): wire FleetCog + start NotificationConsumer in bot setup_hook"
```

---

## Task 24: Integration scenario — full timer flow

**Files:**
- Create: `tests/scenarios/__init__.py` (empty if missing)
- Create: `tests/scenarios/test_timer_flow.py`

This scenario exercises the full pipeline: cog → enqueue → worker tick → handler → reward → stream emit. It uses an in-process worker tick (not the real `worker.py` process) but otherwise fires every code path.

- [ ] **Step 1: Create the scenario**

Create `tests/scenarios/test_timer_flow.py`:

```python
"""End-to-end timer flow: start → fire → complete → reward → notification.

Drives the worker tick + dispatch in-process against the test session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    Rarity,
    RewardLedger,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_training_timer_full_lifecycle(db_session, redis_client, monkeypatch):
    """End-to-end: enqueue → fire → complete → ledger row → notification on stream."""
    from scheduler import dispatch as dispatch_mod
    from scheduler.engine import tick
    from scheduler.enqueue import enqueue_timer
    from scheduler.jobs import timer_complete  # noqa — registers handler.

    # Direct Redis stream emit at the helper level.
    monkeypatch.setattr(
        "scheduler.notifications.get_redis_client", lambda: redis_client,
    )
    monkeypatch.setattr(
        "scheduler.notifications.DEFAULT_STREAM_KEY", "d2d:notifications:scenario",
    )

    user = User(
        discord_id="800001", username="scenario_timer",
        hull_class=HullClass.HAULER, currency=200, xp=0,
    )
    db_session.add(user)
    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="Scen", last_name="Test", callsign="One",
        archetype=CrewArchetype.PILOT, rarity=Rarity.COMMON,
        level=1, xp=0, current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    # Enqueue with a past completes_at so the tick fires immediately.
    completes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    timer, job = await enqueue_timer(
        db_session, user_id=user.discord_id,
        timer_type=TimerType.TRAINING, recipe_id="combat_drills",
        completes_at=completes_at, payload={"crew_id": str(crew.id)},
    )
    crew.current_activity = CrewActivity.TRAINING
    crew.current_activity_id = timer.id
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    claimed = await tick(sm, batch_size=10)
    assert any(j.id == job.id for j in claimed)
    for j in claimed:
        await dispatch_mod.dispatch(j, sm)

    # Refresh from a fresh transaction — dispatch runs in its own session.
    refreshed_timer = await db_session.get(Timer, timer.id)
    refreshed_job = await db_session.get(ScheduledJob, job.id)
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    assert refreshed_timer.state == TimerState.COMPLETED
    assert refreshed_job.state == JobState.COMPLETED
    assert refreshed_crew.current_activity == CrewActivity.IDLE
    assert refreshed_crew.xp >= 200

    entries = await redis_client.xrange("d2d:notifications:scenario", count=10)
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["user_id"] == user.discord_id
    assert fields["category"] == "timer_completion"
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/scenarios/test_timer_flow.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/__init__.py tests/scenarios/test_timer_flow.py
git commit -m "test(phase2a): end-to-end training timer lifecycle scenario"
```

---

## Task 25: Integration scenario — accrual flow

**Files:**
- Create: `tests/scenarios/test_accrual_flow.py`

- [ ] **Step 1: Create the scenario**

Create `tests/scenarios/test_accrual_flow.py`:

```python
"""End-to-end accrual flow: assign → tick → /claim → balances applied."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    ScheduledJob,
    StationAssignment,
    StationType,
    User,
)


@pytest.mark.asyncio
async def test_accrual_tick_then_claim(db_session, monkeypatch):
    from scheduler import dispatch as dispatch_mod
    from scheduler.engine import tick
    from scheduler.enqueue import enqueue_accrual_tick
    from scheduler.jobs import accrual_tick  # noqa — registers.

    user = User(
        discord_id="800002", username="scenario_acc",
        hull_class=HullClass.HAULER, currency=0,
    )
    db_session.add(user)
    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="A", last_name="C", callsign="Crew",
        archetype=CrewArchetype.NAVIGATOR, rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    sa = StationAssignment(
        id=uuid.uuid4(), user_id=user.discord_id,
        station_type=StationType.CARGO_RUN, crew_id=crew.id,
        last_yield_tick_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db_session.add(sa)
    crew.current_activity_id = sa.id

    job = await enqueue_accrual_tick(
        db_session, user_id=user.discord_id,
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    claimed = await tick(sm, batch_size=10)
    assert any(j.id == job.id for j in claimed)
    for j in claimed:
        await dispatch_mod.dispatch(j, sm)

    refreshed_sa = await db_session.get(StationAssignment, sa.id)
    assert refreshed_sa.pending_credits > 0

    # /claim flow — replicated inline (bypasses cog plumbing).
    from engine.rewards import apply_reward
    from db.models import RewardSourceType
    async with sm() as session, session.begin():
        u = await session.get(User, user.discord_id, with_for_update=True)
        sas = await session.get(StationAssignment, sa.id, with_for_update=True)
        total = sas.pending_credits
        await apply_reward(
            session, user_id=u.discord_id,
            source_type=RewardSourceType.ACCRUAL_CLAIM,
            source_id=f"accrual_claim:{uuid.uuid4()}",
            delta={"credits": total},
        )
        sas.pending_credits = 0
        sas.pending_xp = 0

    final_user = await db_session.get(User, user.discord_id)
    assert final_user.currency >= refreshed_sa.pending_credits  # credited.
    final_sa = await db_session.get(StationAssignment, sa.id)
    assert final_sa.pending_credits == 0

    # Self-rescheduling: a fresh accrual_tick is now pending for this user.
    from sqlalchemy import select
    next_tick = (await db_session.execute(
        select(ScheduledJob)
        .where(ScheduledJob.user_id == user.discord_id)
        .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
        .where(ScheduledJob.state == JobState.PENDING)
    )).scalar_one_or_none()
    assert next_tick is not None
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/scenarios/test_accrual_flow.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_accrual_flow.py
git commit -m "test(phase2a): end-to-end accrual flow scenario"
```

---

## Task 26: Chaos test — worker mid-job kill + recovery

**Files:**
- Create: `tests/test_scheduler_chaos.py`

- [ ] **Step 1: Create the test**

Create `tests/test_scheduler_chaos.py`:

```python
"""Chaos: simulate worker dying mid-job, verify recovery + no double-credit."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.settings import settings
from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    RewardLedger,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_stuck_claim_recovered_and_handler_idempotent(db_session, monkeypatch):
    """Simulate: handler partially executed, worker died, recovery resets, retry runs cleanly."""
    from scheduler import dispatch as dispatch_mod
    from scheduler.jobs import timer_complete  # noqa — registers.
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="800101", username="chaos_a", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    crew = CrewMember(
        id=uuid.uuid4(), user_id=user.discord_id,
        first_name="C", last_name="H", callsign="Aos",
        archetype=CrewArchetype.PILOT, rarity=Rarity.COMMON,
        level=1, xp=0, current_activity=CrewActivity.TRAINING,
    )
    db_session.add(crew)
    job = ScheduledJob(
        id=uuid.uuid4(), user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE, payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        # claimed_at well past stuck-timeout — the recovery sweep should reset it.
        claimed_at=datetime.now(timezone.utc) - timedelta(
            seconds=settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS + 60
        ),
        attempts=1,
    )
    db_session.add(job)
    timer = Timer(
        id=uuid.uuid4(), user_id=user.discord_id,
        timer_type=TimerType.TRAINING, recipe_id="combat_drills",
        payload={"crew_id": str(crew.id)},
        completes_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job.id,
    )
    db_session.add(timer)
    job.payload = {"timer_id": str(timer.id)}
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    n = await recovery_sweep(sm)
    assert n >= 1
    refreshed_job = await db_session.get(ScheduledJob, job.id)
    assert refreshed_job.state == JobState.PENDING

    # Now claim and dispatch — should run handler exactly once.
    from scheduler.engine import tick
    claimed = await tick(sm, batch_size=10)
    assert any(j.id == job.id for j in claimed)
    for j in claimed:
        await dispatch_mod.dispatch(j, sm)

    # Re-running dispatch on the same job-id (simulating a redelivery) must not double-credit.
    await dispatch_mod.dispatch(job, sm)

    final_crew = await db_session.get(CrewMember, crew.id)
    assert final_crew.xp == 200  # exactly once.
    from sqlalchemy import select
    ledger_rows = (await db_session.execute(
        select(RewardLedger)
        .where(RewardLedger.source_id == f"timer:{timer.id}")
    )).scalars().all()
    assert len(ledger_rows) == 1
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_scheduler_chaos.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scheduler_chaos.py
git commit -m "test(phase2a): chaos test — stuck-claim recovery + handler idempotency"
```

---

## Task 27: Load test — 1000 concurrent jobs

**Files:**
- Create: `tests/test_scheduler_load.py`

- [ ] **Step 1: Create the test**

Create `tests/test_scheduler_load.py`:

```python
"""Load: 1000 concurrent jobs fire within 60s, no deadlocks, p99 latency under SLO."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import settings
from db.models import (
    HullClass,
    JobState,
    JobType,
    ScheduledJob,
    User,
)


@pytest.mark.perf
@pytest.mark.asyncio
async def test_thousand_jobs_drain_under_minute():
    """Fire 1000 jobs that all complete within 60s of wall-clock; no rows left pending."""
    from scheduler import dispatch as dispatch_mod
    from scheduler.dispatch import HandlerResult, register
    from scheduler.engine import tick

    eng = create_async_engine(
        settings.DATABASE_URL, echo=False, pool_size=8, max_overflow=4,
    )
    sm = async_sessionmaker(bind=eng, expire_on_commit=False)

    # Replace handler with a near-noop that just marks completed.
    async def noop_handler(session, job):
        from sqlalchemy import func
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()
    register(JobType.TIMER_COMPLETE, noop_handler)

    async with sm() as s, s.begin():
        s.add(User(discord_id="800201", username="load_a", hull_class=HullClass.HAULER))
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with sm() as s, s.begin():
        for _ in range(1000):
            s.add(
                ScheduledJob(
                    user_id="800201",
                    job_type=JobType.TIMER_COMPLETE,
                    payload={},
                    scheduled_for=past,
                    state=JobState.PENDING,
                )
            )

    started = time.monotonic()
    deadline = started + 60.0
    drained = 0
    while time.monotonic() < deadline:
        claimed = await tick(sm, batch_size=settings.SCHEDULER_BATCH_SIZE)
        if not claimed:
            break
        for j in claimed:
            await dispatch_mod.dispatch(j, sm)
        drained += len(claimed)
    elapsed = time.monotonic() - started

    assert drained == 1000
    assert elapsed < 60.0

    async with sm() as s:
        from sqlalchemy import select, func as _f
        remaining = (await s.execute(
            select(_f.count(ScheduledJob.id))
            .where(ScheduledJob.user_id == "800201")
            .where(ScheduledJob.state == JobState.PENDING)
        )).scalar_one()
        assert remaining == 0

    # Cleanup.
    async with sm() as s, s.begin():
        await s.execute(
            ScheduledJob.__table__.delete().where(ScheduledJob.user_id == "800201")
        )
        await s.execute(User.__table__.delete().where(User.discord_id == "800201"))
    await eng.dispose()
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_scheduler_load.py -v -m perf`
Expected: PASS within 60s.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scheduler_load.py
git commit -m "test(phase2a): load test — 1000 concurrent jobs drain under 60s"
```

---

## Task 28: Deployment configs (`railway.toml` + `pyproject.toml`)

**Files:**
- Modify: `railway.toml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `scheduler-worker` Railway service**

Append to `railway.toml`:

```toml
[[services]]
name = "scheduler-worker"
buildCommand = "docker build -f docker/Dockerfile.prod --target runtime -t dare2drive-scheduler ."
startCommand = "python -m scheduler.worker"

[services.variables]
DATABASE_URL = "${{Postgres.DATABASE_URL}}"
REDIS_URL = "${{Redis.REDIS_URL}}"
TEMPO_URL = "${{tempo.RAILWAY_PRIVATE_DOMAIN}}:4318"
```

- [ ] **Step 2: Update `pyproject.toml`**

In `[tool.setuptools.packages.find]`, change the `include` line to include `scheduler*`:

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["api*", "bot*", "config*", "db*", "engine*", "scheduler*", "scripts*"]
```

In `[tool.coverage.run]`, add `scheduler` to the source list:

```toml
[tool.coverage.run]
source = ["bot", "engine", "api", "db", "config", "scheduler"]
omit = ["*/migrations/*", "*/tests/*", "bot/cogs/*", "bot/main.py", "scheduler/worker.py"]
```

In `[tool.pytest.ini_options]`, expand `--cov` flags to include scheduler:

```toml
addopts = "--cov=bot --cov=engine --cov=api --cov=db --cov=config --cov=scheduler --cov-report=term-missing --cov-report=xml"
```

- [ ] **Step 3: Verify the package is discoverable**

Run: `python -c "import scheduler.worker; import scheduler.engine; import scheduler.dispatch; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add railway.toml pyproject.toml
git commit -m "feat(phase2a): scheduler-worker Railway service + pyproject packaging"
```

---

## Task 29: Grafana dashboard + alerts

**Files:**
- Create: `monitoring/grafana-stack/provisioning/dashboards/dare2drive-scheduler.json`
- Create: `monitoring/grafana-stack/provisioning/alerting/scheduler-alerts.yaml`

The `monitoring/grafana-stack` directory is a git submodule. Phases 0/1 followed the convention of modifying it and bumping the submodule pointer.

- [ ] **Step 1: Create the dashboard JSON**

Create `monitoring/grafana-stack/provisioning/dashboards/dare2drive-scheduler.json`:

```json
{
  "title": "Dare2Drive — Scheduler",
  "uid": "dare2drive-scheduler",
  "schemaVersion": 39,
  "version": 1,
  "timezone": "browser",
  "panels": [
    {
      "type": "stat",
      "title": "Pending jobs",
      "targets": [{"expr": "dare2drive_scheduler_jobs_pending"}],
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0}
    },
    {
      "type": "stat",
      "title": "In-flight (claimed)",
      "targets": [{"expr": "dare2drive_scheduler_jobs_in_flight"}],
      "gridPos": {"h": 4, "w": 6, "x": 6, "y": 0}
    },
    {
      "type": "stat",
      "title": "Notification stream lag",
      "targets": [{"expr": "dare2drive_notification_stream_lag"}],
      "gridPos": {"h": 4, "w": 6, "x": 12, "y": 0}
    },
    {
      "type": "timeseries",
      "title": "Job throughput by type",
      "targets": [
        {"expr": "sum by (job_type, result) (rate(dare2drive_scheduler_jobs_total[5m]))"}
      ],
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4}
    },
    {
      "type": "timeseries",
      "title": "Tick duration p50/p95/p99",
      "targets": [
        {"expr": "histogram_quantile(0.5, sum by (le) (rate(dare2drive_scheduler_tick_duration_seconds_bucket[5m])))", "legendFormat": "p50"},
        {"expr": "histogram_quantile(0.95, sum by (le) (rate(dare2drive_scheduler_tick_duration_seconds_bucket[5m])))", "legendFormat": "p95"},
        {"expr": "histogram_quantile(0.99, sum by (le) (rate(dare2drive_scheduler_tick_duration_seconds_bucket[5m])))", "legendFormat": "p99"}
      ],
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4}
    },
    {
      "type": "timeseries",
      "title": "Timers started by type",
      "targets": [
        {"expr": "sum by (timer_type) (rate(dare2drive_timers_started_total[15m]))"}
      ],
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12}
    },
    {
      "type": "timeseries",
      "title": "Notification delivery outcomes",
      "targets": [
        {"expr": "sum by (result) (rate(dare2drive_notifications_total[5m]))"}
      ],
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12}
    }
  ]
}
```

- [ ] **Step 2: Create the alerts YAML**

Create `monitoring/grafana-stack/provisioning/alerting/scheduler-alerts.yaml`:

```yaml
apiVersion: 1
groups:
  - orgId: 1
    name: scheduler
    folder: dare2drive
    interval: 1m
    rules:
      - uid: scheduler_jobs_backlog_warn
        title: SchedulerJobsBacklog (warning)
        condition: A
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: dare2drive_scheduler_jobs_pending > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: Scheduler pending backlog above 1000 for 10m

      - uid: scheduler_jobs_backlog_crit
        title: SchedulerJobsBacklog (critical)
        condition: A
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: dare2drive_scheduler_jobs_pending > 5000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: Scheduler pending backlog above 5000 for 5m

      - uid: scheduler_jobs_failure_rate
        title: SchedulerJobsFailureRate
        condition: A
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: |
                (sum(rate(dare2drive_scheduler_jobs_total{result="failure"}[5m]))
                 / clamp_min(sum(rate(dare2drive_scheduler_jobs_total[5m])), 1)) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: Scheduler failure rate above 5% for 10m

      - uid: notification_stream_buildup
        title: NotificationStreamBuildup
        condition: A
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: dare2drive_notification_stream_lag > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: Notification stream backlog above 1000 entries for 10m

      - uid: notification_failure_rate
        title: NotificationFailureRate
        condition: A
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: sum(rate(dare2drive_notifications_total{result="failed"}[15m])) > 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: Notification delivery failures above 0.1/sec sustained 15m

      - uid: worker_down
        title: WorkerDown
        condition: A
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: up{job="scheduler-worker"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: scheduler-worker process down for 2m
```

- [ ] **Step 3: Commit inside the submodule**

```bash
cd monitoring/grafana-stack
git add provisioning/dashboards/dare2drive-scheduler.json provisioning/alerting/scheduler-alerts.yaml
git commit -m "feat: phase 2a scheduler dashboard + alerts"
git push  # if your submodule is pushable; otherwise skip and bump in the parent.
cd ../..
```

- [ ] **Step 4: Bump the submodule pointer in the parent repo**

```bash
git add monitoring/grafana-stack
git commit -m "feat(phase2a): bump grafana-stack to include scheduler dashboard + alerts"
```

---

## Definition of Done

All tasks complete, all tests pass, and:

- [ ] `pytest -v` from the repo root passes (existing Phase 0/1 tests + all Phase 2a tests).
- [ ] `pytest -v -m perf` passes (load test).
- [ ] `alembic upgrade head` and `alembic downgrade -1 && alembic upgrade head` are clean.
- [ ] `python -m scheduler.worker` starts, exposes `:8002/metrics`, and logs `worker_started`.
- [ ] Manual: launch the bot in a test guild, register a system, run `/training start`, wait, observe DM.
- [ ] Manual: `/stations assign`, wait for an accrual_tick to fire, run `/claim`, see credits applied.
- [ ] Grafana dashboard `dare2drive-scheduler` renders all panels post-deploy with synthetic load.
- [ ] All six alerts visible in Grafana Alerting, none firing under normal conditions.
