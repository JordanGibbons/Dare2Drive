# Phase 3b-4 — Beacon Flares + System Pride + Activity-Cut Tribute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Light up the live-channel layer of Phase 3b. Beacon Flares fire on a cadence (passive on every active Lighthouse, Warden-called via tribute), citizens see them with 0s delay, same-Sector neighbors with 30-60s delay, and the click race resolves into prizes (Salvage Drift = single winner; Signal Pulse = multi-winner coalesce). Pride accrues from donations (already wired in 3b-3) plus the new flare-win and goal-completion sources, decays 1% daily. Activity-cut tribute (3% of citizen credit-equivalent rewards) flows to the Warden's ledger. **Lapse, vacation, tribute spending — except flare-call cost — and Pride cosmetic unlocks do not ship in this plan.** They land in 3b-5 (lapse/vacation/general spending) and Phase 4+ (cosmetics).

**Architecture:**
- Two new tables: `flares` and `flare_clicks` (latter is the race-resolution surface — Postgres transaction order is the tiebreaker). Migration `0009_phase3b_4_flares`.
- One new column on `systems`: `last_human_message_at` (timestamp), updated by a new `on_message` listener in `bot/main.py`. Drives the silence auto-throttle (>12h extends, >24h pauses passive cadence).
- `engine/flare_engine.py` owns the lifecycle: `spawn_passive(session, system_id)`, `spawn_called(session, system_id, warden_id, archetype, prize_tier)`, `register_click(session, flare_id, player_id)`, `finalize(session, flare_id)`. The two archetypes share the spawn/click path; finalize branches on archetype.
- Audience-tier delay is a **server-side check**: a single channel post goes out at `spawned_at`, and the click handler rejects neighbor clicks until `spawned_at + neighbor_delay`. Neighbor_delay is rolled per-flare (`roll(30, 60)s`) and stored on the row. Citizens of the firing system bypass the check; same-Sector neighbors honor it; cross-Sector players can't click at all in 3b-4 (universe-wide tier is 3e).
- Spawn cadence is driven by `scheduler/jobs/flare_spawner.py` running roughly every 5 minutes. Per-Lighthouse, it computes the next-flare interval from the Fog Clearance tier, applies the auto-throttle multiplier based on `last_human_message_at`, jitters, and either spawns or schedules its own next tick. **One active passive flare per system at a time** (spec §12.6); if one is open, the spawner skips that system this tick.
- `engine/pride_engine.py` is the central writer for `lighthouses.pride_score`. Every event (donation, flare win, goal completion, etc.) calls `apply_pride(session, lighthouse_id, delta, reason)`. A new `pride_events` table records the deltas for the `/system info` recent-activity panel and post-hoc analytics.
- `scheduler/jobs/pride_decay.py` runs daily and applies `pride_score *= 0.99` (with floor 0).
- Activity-cut tribute hooks into `engine/rewards.py::apply_reward`. When the reward is a `reward_credits` to a citizen acting *in* a system, 3% of the credit amount is auto-credited to that system's Warden's `tribute_ledger`. Donations are NOT counted (spec §10.1). A small `_is_eligible_for_activity_cut(reward_kind, source_type)` switch in `apply_reward` keeps the rule legible.
- Flare embed view is a persistent `DynamicItem` matching the 3b-3 goal-embed pattern. `bot/views/flare_view.py` ships `FlareView` and `ClaimButton`. Custom_id format: `flare:claim:<flare_id>`.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, discord.py 2.x (DynamicItem persistent View, on_message listener), pytest + pytest-asyncio. No new top-level dependencies.

**Spec:** [docs/roadmap/2026-05-02-phase-3b-lighthouses-design.md](../../roadmap/2026-05-02-phase-3b-lighthouses-design.md) — sections covered: §12 (Beacon Flares — both archetypes, audience tiers, cadence, auto-throttle, prize tiers, reward delivery, Warden-called), §13 (System Pride — sources, decay, visibility, storage), §10.1 last paragraph (activity-cut tribute), parts of §15 (`flares`, `flare_clicks`, `pride_events`), §16.1 (`/lighthouse flare call`), §16.4 (flare embed).

**Depends on:** 3b-1 (Lighthouse + citizenship), 3b-2 (Warden seats — Warden-called flares require a Warden), 3b-3 (donation/install Pride hooks; tribute_ledger).

**Sections deferred:** Lapse / vacation / general tribute spending → 3b-5; LLM seed → 3b-6; universe-wide flare tier and cross-Sector stealing → 3e; Pride cosmetic unlocks → Phase 4+.

**Dev loop:** Same as prior sub-plans. Plus: dev-bot manual verification of the flare embed click race needs at least two test Discord accounts.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0009_phase3b_4_flares.py` | `flares` + `flare_clicks` + `pride_events` tables; `flare_archetype` / `flare_prize_tier` / `flare_state` enums; `systems.last_human_message_at` column |
| `engine/flare_engine.py` | Lifecycle: spawn passive/called, register_click, finalize per-archetype, prize delivery |
| `engine/pride_engine.py` | `apply_pride(session, lighthouse_id, delta, reason)` + write `pride_events` |
| `scheduler/jobs/flare_spawner.py` | Periodic spawn handler (cadence per Lighthouse) |
| `scheduler/jobs/flare_resolve.py` | Fires when a flare's window closes (Salvage Drift outer expiry, Signal Pulse coalesce close) |
| `scheduler/jobs/pride_decay.py` | Daily 1% decay handler |
| `bot/views/flare_view.py` | `FlareView` + `ClaimButton` DynamicItem + custom_id helpers + audience-tier check |
| `tests/test_phase3b_4_migration.py` | Schema round-trip |
| `tests/test_phase3b_4_models.py` | ORM invariants |
| `tests/test_engine_flare_spawn.py` | spawn_passive/spawn_called paths |
| `tests/test_engine_flare_click.py` | Click-race tiebreaker via DB tx order |
| `tests/test_engine_flare_finalize.py` | Salvage Drift single winner + Signal Pulse multi-winner coalesce |
| `tests/test_engine_flare_audience_tier.py` | Citizen 0s, neighbor delay, cross-Sector denied |
| `tests/test_engine_pride.py` | Each Pride source delta; decay floor at 0 |
| `tests/test_engine_activity_cut.py` | 3% cut from expedition rewards; donations not counted |
| `tests/test_handler_flare_spawner.py` | Cadence + auto-throttle + one-flare-per-system |
| `tests/test_handler_flare_resolve.py` | Outer-window expiry path |
| `tests/test_handler_pride_decay.py` | 1% daily decay applied to all Lighthouses |
| `tests/test_view_flare.py` | ClaimButton interaction routing + audience check |
| `tests/test_cog_lighthouse_flare.py` | `/lighthouse flare call` happy + tribute insufficient |
| `tests/test_scenarios/test_flare_race.py` | End-to-end: spawn → citizen clicks first → wins → Pride moves |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add enums (`FlareArchetype`, `FlarePrizeTier`, `FlareState`); models `Flare`, `FlareClick`, `PrideEvent`; extend `System` with `last_human_message_at`; extend `JobType` with `FLARE_SPAWNER`, `FLARE_RESOLVE`, `PRIDE_DECAY` |
| `bot/main.py` | Add `on_message` listener that updates `last_human_message_at`; register `flare_spawner`/`flare_resolve`/`pride_decay` handlers; register `ClaimButton` DynamicItem |
| `bot/cogs/lighthouse.py` | Add `flare` subgroup with `call` subcommand |
| `engine/upgrade_engine.py` | `donate` calls `apply_pride`; `install_goal` (+20) and `cancel_goal` (-10) call `apply_pride` |
| `engine/rewards.py` | `apply_reward` calls `_credit_activity_cut_tribute` when reward is a citizen-side credit |
| `bot/system_gating.py` | New subcommand qualified names added |

---

## Task 1: Migration 0009 — `flares`, `flare_clicks`, `pride_events`, `systems.last_human_message_at`

**Files:**
- Create: `db/migrations/versions/0009_phase3b_4_flares.py`
- Create: `tests/test_phase3b_4_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3b_4_migration.py`:

```python
"""Phase 3b-4 migration: flares + flare_clicks + pride_events + systems.last_human_message_at."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def test_three_new_tables(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    names = set(insp.get_table_names())
    for table in ("flares", "flare_clicks", "pride_events"):
        assert table in names, table


async def test_systems_last_human_message_at_column(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {c["name"] for c in insp.get_columns("systems")}
    assert "last_human_message_at" in cols


async def test_flare_archetype_enum(db_session):
    rows = (
        await db_session.execute(
            text("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                 "WHERE t.typname = 'flare_archetype' ORDER BY enumlabel")
        )
    ).scalars().all()
    assert set(rows) == {"salvage_drift", "signal_pulse"}


async def test_flare_state_enum(db_session):
    rows = (
        await db_session.execute(
            text("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                 "WHERE t.typname = 'flare_state' ORDER BY enumlabel")
        )
    ).scalars().all()
    assert set(rows) == {"open", "won", "expired"}


async def test_flare_clicks_composite_primary_key(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    pk = insp.get_pk_constraint("flare_clicks")
    assert set(pk["constrained_columns"]) == {"flare_id", "player_id"}
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase3b_4_migration.py -v --no-cov`
Expected: 5 FAIL.

- [ ] **Step 3: Write the migration**

Create `db/migrations/versions/0009_phase3b_4_flares.py`:

```python
"""Phase 3b-4 — Beacon flares, Pride events, channel-silence tracking.

Revision ID: 0009_phase3b_4_flares
Revises: 0008_phase3b_3_donations
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_phase3b_4_flares"
down_revision = "0008_phase3b_3_donations"
branch_labels = None
depends_on = None


FLARE_ARCHETYPE = postgresql.ENUM("salvage_drift", "signal_pulse", name="flare_archetype")
FLARE_PRIZE_TIER = postgresql.ENUM("small", "standard", "premium", name="flare_prize_tier")
FLARE_STATE = postgresql.ENUM("open", "won", "expired", name="flare_state")


def upgrade() -> None:
    bind = op.get_bind()
    FLARE_ARCHETYPE.create(bind, checkfirst=True)
    FLARE_PRIZE_TIER.create(bind, checkfirst=True)
    FLARE_STATE.create(bind, checkfirst=True)

    op.add_column(
        "systems",
        sa.Column("last_human_message_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "flares",
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
            index=True,
        ),
        sa.Column(
            "archetype",
            postgresql.ENUM(name="flare_archetype", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "prize_tier",
            postgresql.ENUM(name="flare_prize_tier", create_type=False),
            nullable=False,
        ),
        sa.Column("prize_pool", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "triggered_by",
            sa.String(20),
            sa.ForeignKey("users.discord_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("neighbor_delay_seconds", sa.Integer(), nullable=False, server_default="45"),
        sa.Column(
            "spawned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coalesce_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name="flare_state", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("winners", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("channel_message_id", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_flares_open_per_system",
        "flares",
        ["system_id", "state"],
        postgresql_where=sa.text("state = 'open'"),
    )

    op.create_table(
        "flare_clicks",
        sa.Column(
            "flare_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flares.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "player_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "clicked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "pride_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "lighthouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lighthouses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Extend jobtype enum with the three new job types.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'flare_spawner'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'flare_resolve'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'pride_decay'")


def downgrade() -> None:
    op.drop_table("pride_events")
    op.drop_table("flare_clicks")
    op.drop_index("ix_flares_open_per_system", table_name="flares")
    op.drop_table("flares")
    op.drop_column("systems", "last_human_message_at")
    bind = op.get_bind()
    FLARE_STATE.drop(bind, checkfirst=True)
    FLARE_PRIZE_TIER.drop(bind, checkfirst=True)
    FLARE_ARCHETYPE.drop(bind, checkfirst=True)
```

- [ ] **Step 4: Run, confirm passes**

Run: `alembic upgrade head` → `pytest tests/test_phase3b_4_migration.py -v --no-cov`
Expected: 5 PASS.

- [ ] **Step 5: Round-trip**

Run: `alembic downgrade -1 && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add db/migrations/versions/0009_phase3b_4_flares.py tests/test_phase3b_4_migration.py
git commit -m "feat(phase3b-4): schema for flares + flare_clicks + pride_events"
```

---

## Task 2: ORM models — `Flare`, `FlareClick`, `PrideEvent`, System extension

**Files:**
- Modify: `db/models.py`
- Create: `tests/test_phase3b_4_models.py`

- [ ] **Step 1: Write the failing test**

```python
"""Phase 3b-4 ORM model invariants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_flare_creates_in_open_state(db_session, sample_system_with_lighthouse):
    from db.models import Flare, FlareArchetype, FlarePrizeTier, FlareState

    f = Flare(
        system_id=sample_system_with_lighthouse.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.STANDARD,
        prize_pool={"credits": 500},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(f)
    await db_session.flush()
    await db_session.refresh(f)
    assert f.state == FlareState.OPEN
    assert f.winners == []


async def test_flare_clicks_unique_per_player(db_session, sample_user, sample_system_with_lighthouse):
    """A player can only register one click per flare (PK enforces it)."""
    from db.models import Flare, FlareArchetype, FlareClick, FlarePrizeTier
    import pytest
    from sqlalchemy.exc import IntegrityError

    f = Flare(
        system_id=sample_system_with_lighthouse.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.SMALL,
        prize_pool={},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(f)
    await db_session.flush()

    db_session.add(FlareClick(flare_id=f.id, player_id=sample_user.discord_id))
    await db_session.flush()
    db_session.add(FlareClick(flare_id=f.id, player_id=sample_user.discord_id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_pride_event_signed_delta(db_session, sample_system_with_lighthouse):
    from db.models import Lighthouse, PrideEvent
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    db_session.add(PrideEvent(lighthouse_id=lh.id, delta=20, reason="goal_completed"))
    db_session.add(PrideEvent(lighthouse_id=lh.id, delta=-3, reason="outsider_flare_win"))
    await db_session.flush()
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase3b_4_models.py -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Add enums + models in `db/models.py`**

```python
class FlareArchetype(str, enum.Enum):
    SALVAGE_DRIFT = "salvage_drift"
    SIGNAL_PULSE = "signal_pulse"


class FlarePrizeTier(str, enum.Enum):
    SMALL = "small"
    STANDARD = "standard"
    PREMIUM = "premium"


class FlareState(str, enum.Enum):
    OPEN = "open"
    WON = "won"
    EXPIRED = "expired"
```

Extend `JobType` with `FLARE_SPAWNER`, `FLARE_RESOLVE`, `PRIDE_DECAY`.

Extend `System` model — add `last_human_message_at`:

```python
    last_human_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Add models `Flare`, `FlareClick`, `PrideEvent`:

```python
class Flare(Base):
    __tablename__ = "flares"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("systems.channel_id", ondelete="CASCADE"), nullable=False, index=True
    )
    archetype: Mapped[FlareArchetype] = mapped_column(
        Enum(FlareArchetype, values_callable=lambda x: [e.value for e in x], name="flare_archetype"),
        nullable=False,
    )
    prize_tier: Mapped[FlarePrizeTier] = mapped_column(
        Enum(FlarePrizeTier, values_callable=lambda x: [e.value for e in x], name="flare_prize_tier"),
        nullable=False,
    )
    prize_pool: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    triggered_by: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("users.discord_id", ondelete="SET NULL"), nullable=True
    )
    neighbor_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    spawned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    coalesce_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[FlareState] = mapped_column(
        Enum(FlareState, values_callable=lambda x: [e.value for e in x], name="flare_state"),
        nullable=False,
        default=FlareState.OPEN,
        server_default=FlareState.OPEN.value,
    )
    winners: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    channel_message_id: Mapped[str | None] = mapped_column(String(20), nullable=True)


class FlareClick(Base):
    __tablename__ = "flare_clicks"

    flare_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flares.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id", ondelete="CASCADE"), primary_key=True
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PrideEvent(Base):
    __tablename__ = "pride_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lighthouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lighthouses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

(`metadata` is a SQLAlchemy reserved name on `Base` — alias to `metadata_` in the Mapped[] declaration with the explicit column name.)

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_phase3b_4_models.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_phase3b_4_models.py
git commit -m "feat(phase3b-4): ORM for flares, flare_clicks, pride_events"
```

---

## Task 3: Pride engine — `apply_pride` + decay

**Files:**
- Create: `engine/pride_engine.py`
- Create: `tests/test_engine_pride.py`

- [ ] **Step 1: Write the failing test**

```python
"""Pride writes, decay, floor at 0."""

from __future__ import annotations


async def test_apply_pride_writes_event_and_updates_score(
    db_session, sample_system_with_lighthouse
):
    from db.models import Lighthouse, PrideEvent
    from engine.pride_engine import apply_pride
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()

    await apply_pride(db_session, lighthouse_id=lh.id, delta=20, reason="goal_completed")
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.pride_score == 20

    events = (await db_session.execute(select(PrideEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].delta == 20


async def test_apply_pride_floors_at_zero(db_session, sample_system_with_lighthouse):
    from db.models import Lighthouse
    from engine.pride_engine import apply_pride
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    lh.pride_score = 5
    await db_session.flush()

    await apply_pride(db_session, lighthouse_id=lh.id, delta=-50, reason="auto_abdicate")
    await db_session.refresh(lh)
    assert lh.pride_score == 0


async def test_decay_one_percent_floors_at_zero(db_session, sample_system_with_lighthouse):
    from db.models import Lighthouse
    from engine.pride_engine import apply_daily_decay
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    lh.pride_score = 1000
    await db_session.flush()

    n = await apply_daily_decay(db_session)
    await db_session.refresh(lh)
    # 1000 * 0.99 = 990
    assert lh.pride_score == 990
    assert n == 1


async def test_decay_skips_zero_pride(db_session, sample_system_with_lighthouse):
    from db.models import Lighthouse
    from engine.pride_engine import apply_daily_decay
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    lh.pride_score = 0
    await db_session.flush()

    await apply_daily_decay(db_session)
    await db_session.refresh(lh)
    assert lh.pride_score == 0
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_pride.py -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Implement `engine/pride_engine.py`**

```python
"""System Pride writes + decay.

Single writer for `lighthouses.pride_score`. Every event goes through
`apply_pride` so the change is also recorded in `pride_events` for the
recent-activity panel.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Lighthouse, PrideEvent

DECAY_FACTOR = 0.99  # 1% daily decay, spec §13.2


async def apply_pride(
    session: AsyncSession,
    *,
    lighthouse_id,
    delta: int,
    reason: str,
    metadata: dict | None = None,
) -> int:
    """Apply a Pride change. Returns the lighthouse's new score (floored at 0).

    Writes a pride_events row for the recent-activity panel.
    """
    lh = await session.get(Lighthouse, lighthouse_id, with_for_update=True)
    if lh is None:
        return 0
    new_score = max(0, lh.pride_score + delta)
    lh.pride_score = new_score
    session.add(
        PrideEvent(
            lighthouse_id=lighthouse_id,
            delta=delta,
            reason=reason,
            metadata_=metadata or {},
        )
    )
    return new_score


async def apply_daily_decay(session: AsyncSession) -> int:
    """Apply 1% decay to every Lighthouse's pride_score; return rows changed."""
    rows = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.pride_score > 0)
        )
    ).scalars().all()
    for lh in rows:
        new_score = int(lh.pride_score * DECAY_FACTOR)
        lh.pride_score = max(0, new_score)
    return len(rows)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_pride.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/pride_engine.py tests/test_engine_pride.py
git commit -m "feat(phase3b-4): pride writes + 1% daily decay"
```

---

## Task 4: Pride decay daily handler

**Files:**
- Create: `scheduler/jobs/pride_decay.py`
- Create: `tests/test_handler_pride_decay.py`

- [ ] **Step 1: Write the test**

```python
"""Pride decay handler runs apply_daily_decay and reschedules."""

from __future__ import annotations

from datetime import datetime, timezone


async def test_decay_handler_completes_job(db_session, sample_system_with_lighthouse):
    from db.models import JobState, JobType, Lighthouse, ScheduledJob
    from scheduler.jobs.pride_decay import handle_pride_decay
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    lh.pride_score = 200
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.PRIDE_DECAY,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_pride_decay(db_session, job)
    await db_session.refresh(lh)
    assert lh.pride_score == 198  # 200 * 0.99 = 198
    assert job.state == JobState.COMPLETED
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement**

Create `scheduler/jobs/pride_decay.py`:

```python
"""PRIDE_DECAY handler — daily 1% decay of pride_score across all Lighthouses."""

from __future__ import annotations

from sqlalchemy import func

from config.logging import get_logger
from db.models import JobState, JobType, ScheduledJob
from engine.pride_engine import apply_daily_decay
from scheduler.dispatch import HandlerResult, register

log = get_logger(__name__)


async def handle_pride_decay(session, job: ScheduledJob) -> HandlerResult:
    n = await apply_daily_decay(session)
    log.info("pride_decay: decayed %d lighthouses", n)
    job.state = JobState.COMPLETED
    job.completed_at = func.now()
    return HandlerResult()


register(JobType.PRIDE_DECAY, handle_pride_decay)
```

Schedule it on startup the same way `tribute_drip` is scheduled (3b-3 Task 13). Both run daily; consider scheduling them at different times (e.g. tribute at 00:00 UTC, pride at 00:30) to spread load.

- [ ] **Step 4: Commit**

```bash
git add scheduler/jobs/pride_decay.py tests/test_handler_pride_decay.py bot/main.py
git commit -m "feat(phase3b-4): daily pride decay handler"
```

---

## Task 5: Hook Pride into 3b-3 events (donate, install_goal, cancel_goal)

**Files:**
- Modify: `engine/upgrade_engine.py`
- Modify: `tests/test_engine_upgrade_donate.py`, `tests/test_engine_upgrade_install.py`, `tests/test_engine_upgrade_cancel.py`

- [ ] **Step 1: Add Pride writes in `engine/upgrade_engine.py`**

In `donate`, after the goal/ledger write:

```python
        # Pride: home citizen donations grant Pride to the recipient system.
        # Outsider donations grant Pride to the recipient (spec §8.4 — recipient,
        # not donor's home).
        from engine.pride_engine import apply_pride

        pride_delta = (effective_credits_offered // 100) + parts
        if pride_delta > 0:
            await apply_pride(
                session,
                lighthouse_id=lh.id,
                delta=pride_delta,
                reason="donation",
                metadata={"goal_id": str(goal_id), "donor_id": donor_id},
            )
```

In `install_goal`, after status flip to INSTALLED:

```python
        from engine.pride_engine import apply_pride
        await apply_pride(
            session,
            lighthouse_id=lh.id,
            delta=20,  # spec §13.1
            reason="goal_completed",
            metadata={"goal_id": str(goal_id), "upgrade_id": goal.upgrade_id},
        )
```

In `cancel_goal`, after status flip to CANCELLED:

```python
        from engine.pride_engine import apply_pride
        await apply_pride(
            session,
            lighthouse_id=lh.id,
            delta=-10,  # spec §13.1
            reason="goal_cancelled",
            metadata={"goal_id": str(goal_id)},
        )
```

- [ ] **Step 2: Update tests**

Append to `tests/test_engine_upgrade_donate.py`:

```python
async def test_donate_grants_pride_to_recipient(db_session, posted_goal, home_citizen):
    from db.models import Lighthouse, PrideEvent
    from engine.upgrade_engine import donate
    from sqlalchemy import select

    home_citizen.user.currency = 5000
    await db_session.flush()
    await donate(db_session, donor_id=home_citizen.user.discord_id, goal_id=posted_goal.id, credits=1000, parts=5)
    await db_session.flush()

    rows = (await db_session.execute(select(PrideEvent))).scalars().all()
    assert any(r.reason == "donation" for r in rows)
```

Add similar tests for install (+20) and cancel (-10).

- [ ] **Step 3: Run, confirm passes**

Run: relevant tests.

- [ ] **Step 4: Commit**

```bash
git add engine/upgrade_engine.py tests/test_engine_upgrade_*.py
git commit -m "feat(phase3b-4): hook pride into donate, install, cancel"
```

---

## Task 6: Activity-cut tribute via `apply_reward`

**Files:**
- Modify: `engine/rewards.py`
- Create: `tests/test_engine_activity_cut.py`

- [ ] **Step 1: Audit `apply_reward`**

Read `engine/rewards.py`. The function is the central, idempotent reward writer. Find the path that writes credits to a user from a system-context source (expedition, job, flare-win). Insert a hook there that:

1. Looks up the system the reward originated in (from the source — for expeditions, the build's system context; for jobs, the system_id stored on the job; for flare wins, the flare's system_id).
2. If the system has a Warden (`Lighthouse.warden_id is not None`), credit 3% of the credit amount to `tribute_ledger` with `source_type=ACTIVITY_CUT`.

- [ ] **Step 2: Write the failing test**

```python
"""3% activity-cut tribute lands when a citizen earns credits in a Warden's system."""

from __future__ import annotations


async def test_credit_reward_routes_3pct_to_warden(
    db_session, warden_with_held_lighthouse, home_citizen
):
    from db.models import RewardSourceType, TributeLedger, TributeSourceType
    from engine.rewards import apply_reward
    from sqlalchemy import select

    # 1000c reward to home_citizen, sourced inside the Warden's system.
    await apply_reward(
        db_session,
        user_id=home_citizen.user.discord_id,
        kind="credits",
        amount=1000,
        source_type=RewardSourceType.EXPEDITION_OUTCOME,
        source_id="ex-test-1",
        system_id=warden_with_held_lighthouse.system.channel_id,
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(TributeLedger).where(TributeLedger.source_type == TributeSourceType.ACTIVITY_CUT)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].warden_id == warden_with_held_lighthouse.warden.discord_id
    assert rows[0].amount == 30  # 3% of 1000


async def test_donation_does_not_trigger_activity_cut(
    db_session, warden_with_held_lighthouse, home_citizen
):
    """Spec §10.1: donations are not counted in the activity cut."""
    from db.models import TributeLedger, TributeSourceType
    from engine.upgrade_engine import donate, post_goal
    from sqlalchemy import select

    home_citizen.user.currency = 5000
    await db_session.flush()
    g = await post_goal(
        db_session,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        lighthouse_id=warden_with_held_lighthouse.lighthouse.id,
        upgrade_id="local_fog_damper",
    )
    await db_session.flush()
    await donate(db_session, donor_id=home_citizen.user.discord_id, goal_id=g.id, credits=1000, parts=0)
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(TributeLedger).where(TributeLedger.source_type == TributeSourceType.ACTIVITY_CUT)
        )
    ).scalars().all()
    assert rows == []
```

- [ ] **Step 3: Modify `apply_reward`**

The signature change adds `system_id: str | None = None`. Existing callers pass nothing → no activity cut. Phase 2b expedition rewards already know the system_id; pass it through.

```python
async def apply_reward(
    session,
    *,
    user_id: str,
    kind: str,
    amount: int,
    source_type: RewardSourceType,
    source_id: str,
    system_id: str | None = None,  # new in 3b-4
):
    # ... existing reward write ...

    if kind == "credits" and system_id is not None and amount > 0:
        await _credit_activity_cut_tribute(session, user_id, system_id, amount, source_type)


async def _credit_activity_cut_tribute(
    session, user_id: str, system_id: str, amount: int, source_type: RewardSourceType
) -> None:
    """3% of citizen credit-equivalent rewards flow to the system's Warden.

    Donations (`source_type=DONATION_REFUND`) and other non-activity sources
    are excluded.
    """
    from db.models import Lighthouse, TributeLedger, TributeSourceType
    from sqlalchemy import select

    EXCLUDED = {RewardSourceType.DONATION_REFUND}
    if source_type in EXCLUDED:
        return

    lh = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.system_id == system_id)
        )
    ).scalar_one_or_none()
    if lh is None or lh.warden_id is None:
        return
    if lh.warden_id == user_id:
        return  # Warden's own activity is not their tribute source

    cut = int(amount * 0.03)
    if cut <= 0:
        return
    session.add(
        TributeLedger(
            warden_id=lh.warden_id,
            source_system_id=system_id,
            source_type=TributeSourceType.ACTIVITY_CUT,
            amount=cut,
        )
    )
```

Then update existing callers — most importantly the expedition reward path — to pass `system_id`.

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_activity_cut.py -v --no-cov`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/rewards.py tests/test_engine_activity_cut.py
git commit -m "feat(phase3b-4): activity-cut tribute (3% of citizen rewards) via apply_reward"
```

---

## Task 7: Flare engine — spawn (passive + called)

**Files:**
- Create: `engine/flare_engine.py`
- Create: `tests/test_engine_flare_spawn.py`

- [ ] **Step 1: Write the failing test**

```python
"""Flare spawn — passive + Warden-called, prize-tier mapping by Lighthouse upgrades."""

from __future__ import annotations


async def test_spawn_passive_creates_open_flare(
    db_session, warden_with_held_lighthouse
):
    from db.models import Flare, FlareArchetype, FlareState
    from engine.flare_engine import spawn_passive
    from sqlalchemy import select

    flare = await spawn_passive(
        db_session,
        system_id=warden_with_held_lighthouse.system.channel_id,
    )
    await db_session.flush()
    assert flare is not None
    assert flare.state == FlareState.OPEN
    assert flare.archetype in (FlareArchetype.SALVAGE_DRIFT, FlareArchetype.SIGNAL_PULSE)


async def test_spawn_passive_skips_when_one_already_open(
    db_session, warden_with_held_lighthouse
):
    from engine.flare_engine import spawn_passive

    a = await spawn_passive(db_session, system_id=warden_with_held_lighthouse.system.channel_id)
    await db_session.flush()
    b = await spawn_passive(db_session, system_id=warden_with_held_lighthouse.system.channel_id)
    assert a is not None
    assert b is None  # one open per system at a time


async def test_spawn_called_deducts_tribute(
    db_session, warden_with_held_lighthouse
):
    from db.models import Flare, FlareArchetype, FlarePrizeTier, TributeLedger, TributeSourceType
    from engine.flare_engine import spawn_called
    from sqlalchemy import func, select

    # Pre-credit Warden with 500 tribute.
    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=warden_with_held_lighthouse.system.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=500,
        )
    )
    await db_session.flush()

    flare = await spawn_called(
        db_session,
        system_id=warden_with_held_lighthouse.system.channel_id,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        archetype=FlareArchetype.SIGNAL_PULSE,
        prize_tier=FlarePrizeTier.STANDARD,
    )
    await db_session.flush()
    assert flare is not None
    assert flare.triggered_by == warden_with_held_lighthouse.warden.discord_id

    balance = (
        await db_session.execute(
            select(func.sum(TributeLedger.amount)).where(
                TributeLedger.warden_id == warden_with_held_lighthouse.warden.discord_id
            )
        )
    ).scalar_one()
    # Standard called flare costs 250 (spec §10.3); 500 - 250 = 250.
    assert balance == 250


async def test_spawn_called_rejects_insufficient_tribute(
    db_session, warden_with_held_lighthouse
):
    """Warden with 0 tribute can't call a flare."""
    import pytest

    from db.models import FlareArchetype, FlarePrizeTier
    from engine.flare_engine import FlareError, spawn_called

    with pytest.raises(FlareError, match="tribute"):
        await spawn_called(
            db_session,
            system_id=warden_with_held_lighthouse.system.channel_id,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            archetype=FlareArchetype.SIGNAL_PULSE,
            prize_tier=FlarePrizeTier.STANDARD,
        )
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_flare_spawn.py -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Implement spawn**

Create `engine/flare_engine.py`:

```python
"""Beacon Flare lifecycle: spawn, click, finalize.

Salvage Drift: single winner, first valid click wins entire prize pool. 5-min outer window.
Signal Pulse: multi-winner, 30s coalesce window after first click. 10-min outer for trigger.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Flare,
    FlareArchetype,
    FlareClick,
    FlarePrizeTier,
    FlareState,
    Lighthouse,
    LighthouseUpgrade,
    SlotCategory,
    System,
    TributeLedger,
    TributeSourceType,
)


class FlareError(ValueError):
    """Spawn or click rejected for a precondition reason."""


SALVAGE_DRIFT_OUTER_MINUTES = 5
SIGNAL_PULSE_OUTER_MINUTES = 10
SIGNAL_PULSE_COALESCE_SECONDS = 30
NEIGHBOR_DELAY_RANGE = (30, 60)

# Spec §10.3: Warden flare-call costs.
_CALLED_FLARE_COSTS = {
    FlarePrizeTier.SMALL: 100,
    FlarePrizeTier.STANDARD: 250,
    FlarePrizeTier.PREMIUM: 750,
}


# Spec §12.7 prize tier sample table — placeholders for tuning.
_PRIZE_POOL_SAMPLES = {
    (FlareArchetype.SALVAGE_DRIFT, FlarePrizeTier.SMALL): {"credits": (100, 500)},
    (FlareArchetype.SALVAGE_DRIFT, FlarePrizeTier.STANDARD): {"credits": (200, 800)},
    (FlareArchetype.SALVAGE_DRIFT, FlarePrizeTier.PREMIUM): {"credits": (300, 1200)},
    (FlareArchetype.SIGNAL_PULSE, FlarePrizeTier.SMALL): {"credits": (300, 900)},
    (FlareArchetype.SIGNAL_PULSE, FlarePrizeTier.STANDARD): {"credits": (450, 1200)},
    (FlareArchetype.SIGNAL_PULSE, FlarePrizeTier.PREMIUM): {"credits": (900, 2800)},
}


async def _has_open_flare(session: AsyncSession, system_id: str) -> bool:
    return (
        await session.execute(
            select(Flare).where(Flare.system_id == system_id, Flare.state == FlareState.OPEN)
        )
    ).first() is not None


async def _max_eligible_prize_tier(session: AsyncSession, lighthouse_id: uuid.UUID) -> FlarePrizeTier:
    """Read installed Fog Clearance tier; map to allowed prize tier."""
    rows = (
        await session.execute(
            select(LighthouseUpgrade)
            .where(LighthouseUpgrade.lighthouse_id == lighthouse_id)
            .where(LighthouseUpgrade.slot_category == SlotCategory.FOG)
        )
    ).scalars().all()
    if not rows:
        return FlarePrizeTier.SMALL
    tier = rows[0].tier
    if tier >= 2:
        return FlarePrizeTier.PREMIUM
    if tier == 1:
        return FlarePrizeTier.STANDARD
    return FlarePrizeTier.SMALL


def _roll_prize_pool(rng: random.Random, archetype: FlareArchetype, tier: FlarePrizeTier) -> dict:
    sample = _PRIZE_POOL_SAMPLES[(archetype, tier)]
    lo, hi = sample["credits"]
    return {"credits": rng.randint(lo, hi)}


async def spawn_passive(session: AsyncSession, system_id: str) -> Flare | None:
    """Spawn a passive flare on the system. Returns None if one is already open
    or if the Lighthouse is not active.
    """
    if await _has_open_flare(session, system_id):
        return None

    lh = (
        await session.execute(select(Lighthouse).where(Lighthouse.system_id == system_id))
    ).scalar_one_or_none()
    if lh is None or lh.state.value != "active":
        return None

    return await _create_flare(session, system_id, lh, triggered_by=None, prize_tier=None)


async def spawn_called(
    session: AsyncSession,
    *,
    system_id: str,
    warden_id: str,
    archetype: FlareArchetype,
    prize_tier: FlarePrizeTier,
) -> Flare:
    """Warden-called flare. Deducts tribute. Queues if a passive is open
    (3b-4 simplification: rejects if open passive exists; queueing lands later).
    """
    lh = (
        await session.execute(select(Lighthouse).where(Lighthouse.system_id == system_id))
    ).scalar_one_or_none()
    if lh is None or lh.warden_id != warden_id:
        raise FlareError("only the warden can call flares for this system")

    if await _has_open_flare(session, system_id):
        raise FlareError("a flare is already active in this system")

    cost = _CALLED_FLARE_COSTS[prize_tier]
    balance = (
        await session.execute(
            select(func.coalesce(func.sum(TributeLedger.amount), 0)).where(
                TributeLedger.warden_id == warden_id
            )
        )
    ).scalar_one()
    if balance < cost:
        raise FlareError(f"insufficient tribute: {balance} available, {cost} required")

    session.add(
        TributeLedger(
            warden_id=warden_id,
            source_system_id=system_id,
            source_type=TributeSourceType.FLARE_CALL_COST,
            amount=-cost,
        )
    )

    return await _create_flare(
        session,
        system_id,
        lh,
        triggered_by=warden_id,
        archetype_override=archetype,
        prize_tier=prize_tier,
    )


async def _create_flare(
    session: AsyncSession,
    system_id: str,
    lh,
    *,
    triggered_by: str | None,
    archetype_override: FlareArchetype | None = None,
    prize_tier: FlarePrizeTier | None = None,
) -> Flare:
    rng = random.Random()
    archetype = archetype_override or rng.choice(
        [FlareArchetype.SALVAGE_DRIFT, FlareArchetype.SIGNAL_PULSE]
    )
    tier = prize_tier or await _max_eligible_prize_tier(session, lh.id)
    now = datetime.now(timezone.utc)
    outer = (
        SALVAGE_DRIFT_OUTER_MINUTES
        if archetype == FlareArchetype.SALVAGE_DRIFT
        else SIGNAL_PULSE_OUTER_MINUTES
    )
    neighbor_delay = rng.randint(*NEIGHBOR_DELAY_RANGE)

    flare = Flare(
        system_id=system_id,
        archetype=archetype,
        prize_tier=tier,
        prize_pool=_roll_prize_pool(rng, archetype, tier),
        triggered_by=triggered_by,
        neighbor_delay_seconds=neighbor_delay,
        spawned_at=now,
        expires_at=now + timedelta(minutes=outer),
    )
    session.add(flare)
    await session.flush()
    return flare
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_flare_spawn.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/flare_engine.py tests/test_engine_flare_spawn.py
git commit -m "feat(phase3b-4): flare spawn (passive + Warden-called)"
```

---

## Task 8: Flare engine — `register_click` with audience-tier check

**Files:**
- Modify: `engine/flare_engine.py`
- Create: `tests/test_engine_flare_audience_tier.py`

- [ ] **Step 1: Write the failing test**

```python
"""Audience-tier check: citizens 0s, neighbors after delay, others denied."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


async def test_citizen_can_click_immediately(
    db_session, warden_with_held_lighthouse, home_citizen
):
    from db.models import Flare, FlareArchetype, FlarePrizeTier
    from engine.flare_engine import register_click

    f = Flare(
        system_id=warden_with_held_lighthouse.system.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.SMALL,
        prize_pool={"credits": 200},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        neighbor_delay_seconds=45,
    )
    db_session.add(f)
    await db_session.flush()

    accepted = await register_click(
        db_session, flare_id=f.id, player_id=home_citizen.user.discord_id
    )
    assert accepted is True


async def test_neighbor_blocked_before_delay(
    db_session, warden_with_held_lighthouse, neighbor_citizen
):
    """A same-Sector neighbor citizen can't click within the delay window."""
    from db.models import Flare, FlareArchetype, FlarePrizeTier
    from engine.flare_engine import FlareError, register_click

    f = Flare(
        system_id=warden_with_held_lighthouse.system.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.SMALL,
        prize_pool={"credits": 200},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        neighbor_delay_seconds=45,
    )
    db_session.add(f)
    await db_session.flush()

    # Just-spawned: neighbor must wait 45s.
    with pytest.raises(FlareError, match="window"):
        await register_click(db_session, flare_id=f.id, player_id=neighbor_citizen.user.discord_id)


async def test_cross_sector_player_denied(
    db_session, warden_with_held_lighthouse, cross_sector_user
):
    """A player not citizen of any same-Sector system can't click in 3b-4."""
    from db.models import Flare, FlareArchetype, FlarePrizeTier
    from engine.flare_engine import FlareError, register_click

    f = Flare(
        system_id=warden_with_held_lighthouse.system.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.SMALL,
        prize_pool={"credits": 200},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        neighbor_delay_seconds=45,
    )
    db_session.add(f)
    await db_session.flush()

    with pytest.raises(FlareError, match="audience"):
        await register_click(db_session, flare_id=f.id, player_id=cross_sector_user.discord_id)
```

The fixtures `neighbor_citizen` and `cross_sector_user` are referenced — add them.

- [ ] **Step 2: Add fixtures**

```python
@pytest.fixture
async def neighbor_citizen(db_session, warden_with_held_lighthouse, sample_system2, sample_user2):
    """sample_user2 docked at sample_system2 (same sector as Warden's system)."""
    from db.models import Citizenship
    db_session.add(
        Citizenship(player_id=sample_user2.discord_id, system_id=sample_system2.channel_id)
    )
    await db_session.flush()
    @dataclass
    class _N:
        user: object
    return _N(user=sample_user2)


@pytest.fixture
async def cross_sector_user(db_session):
    """A user with no citizenship in the test sector."""
    from db.models import HullClass, Sector, System, User

    other_sector = Sector(guild_id="9999999", name="Other", owner_discord_id="9000")
    db_session.add(other_sector)
    await db_session.flush()
    other_system = System(channel_id="9990001", sector_id=other_sector.guild_id, name="far-away")
    db_session.add(other_system)
    await db_session.flush()
    u = User(discord_id="3333333", username="far-pilot", hull_class=HullClass.SCOUT)
    db_session.add(u)
    await db_session.flush()
    from db.models import Citizenship
    db_session.add(Citizenship(player_id=u.discord_id, system_id=other_system.channel_id))
    await db_session.flush()
    await db_session.refresh(u)
    return u
```

- [ ] **Step 3: Implement `register_click`**

Append to `engine/flare_engine.py`:

```python
async def register_click(session: AsyncSession, *, flare_id, player_id: str) -> bool:
    """Register a click. Returns True on accept; raises FlareError on reject.

    Audience-tier rules (spec §12.1):
    - Citizens of the firing system: any time after spawned_at.
    - Same-Sector neighbors: only after spawned_at + neighbor_delay_seconds.
    - Cross-Sector players: blocked entirely in 3b-4 (universe-wide tier is 3e).
    """
    flare = await session.get(Flare, flare_id, with_for_update=True)
    if flare is None:
        raise FlareError("flare not found")
    if flare.state != FlareState.OPEN:
        raise FlareError(f"flare is {flare.state.value}")

    audience = await _resolve_audience_tier(session, flare, player_id)
    now = datetime.now(timezone.utc)

    if audience == "citizen":
        pass  # 0s delay
    elif audience == "neighbor":
        earliest = flare.spawned_at + timedelta(seconds=flare.neighbor_delay_seconds)
        if now < earliest:
            wait = (earliest - now).total_seconds()
            raise FlareError(f"visibility window: wait {wait:.0f}s as a neighbor")
    else:
        raise FlareError("audience: not eligible to click this flare")

    # Insert click — DB tx order is the tiebreaker.
    session.add(FlareClick(flare_id=flare_id, player_id=player_id, clicked_at=now))
    await session.flush()
    return True


async def _resolve_audience_tier(
    session: AsyncSession, flare: Flare, player_id: str
) -> str:
    """Return 'citizen' | 'neighbor' | 'outsider'."""
    from db.models import Citizenship, Sector, System

    flare_system = await session.get(System, flare.system_id)
    flare_sector_id = flare_system.sector_id if flare_system else None

    citizenship = (
        await session.execute(
            select(Citizenship)
            .where(Citizenship.player_id == player_id)
            .where(Citizenship.ended_at.is_(None))
        )
    ).scalar_one_or_none()
    if citizenship is None:
        return "outsider"
    if citizenship.system_id == flare.system_id:
        return "citizen"

    home_system = await session.get(System, citizenship.system_id)
    if home_system and home_system.sector_id == flare_sector_id:
        return "neighbor"
    return "outsider"
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_flare_audience_tier.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/flare_engine.py tests/test_engine_flare_audience_tier.py tests/conftest.py
git commit -m "feat(phase3b-4): flare register_click with audience-tier check"
```

---

## Task 9: Flare engine — `finalize` per archetype + prize delivery

**Files:**
- Modify: `engine/flare_engine.py`
- Create: `tests/test_engine_flare_finalize.py`

- [ ] **Step 1: Write the failing test**

```python
"""finalize_flare: Salvage Drift single winner; Signal Pulse multi-winner coalesce."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_salvage_drift_first_clicker_wins(
    db_session, warden_with_held_lighthouse, home_citizen
):
    from db.models import Flare, FlareArchetype, FlareClick, FlarePrizeTier, FlareState, User
    from engine.flare_engine import finalize_flare
    from sqlalchemy import select

    f = Flare(
        system_id=warden_with_held_lighthouse.system.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.SMALL,
        prize_pool={"credits": 500},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(f)
    await db_session.flush()
    db_session.add(
        FlareClick(
            flare_id=f.id,
            player_id=home_citizen.user.discord_id,
            clicked_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    initial_credits = (
        await db_session.execute(select(User.currency).where(User.discord_id == home_citizen.user.discord_id))
    ).scalar_one()

    await finalize_flare(db_session, flare_id=f.id)
    await db_session.flush()
    await db_session.refresh(f)
    assert f.state == FlareState.WON
    assert f.winners == [home_citizen.user.discord_id]

    new_credits = (
        await db_session.execute(select(User.currency).where(User.discord_id == home_citizen.user.discord_id))
    ).scalar_one()
    assert new_credits == initial_credits + 500


async def test_signal_pulse_splits_among_joiners(
    db_session, warden_with_held_lighthouse, home_citizen, sample_user2
):
    from db.models import Flare, FlareArchetype, FlareClick, FlarePrizeTier, FlareState
    from engine.flare_engine import finalize_flare
    from sqlalchemy import select

    f = Flare(
        system_id=warden_with_held_lighthouse.system.channel_id,
        archetype=FlareArchetype.SIGNAL_PULSE,
        prize_tier=FlarePrizeTier.STANDARD,
        prize_pool={"credits": 1000},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add(f)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(FlareClick(flare_id=f.id, player_id=home_citizen.user.discord_id, clicked_at=now))
    db_session.add(FlareClick(flare_id=f.id, player_id=sample_user2.discord_id, clicked_at=now + timedelta(seconds=5)))
    await db_session.flush()

    await finalize_flare(db_session, flare_id=f.id)
    await db_session.flush()
    await db_session.refresh(f)
    assert f.state == FlareState.WON
    assert set(f.winners) == {home_citizen.user.discord_id, sample_user2.discord_id}
    # 500 each.


async def test_no_clicks_marks_expired(
    db_session, warden_with_held_lighthouse
):
    from db.models import Flare, FlareArchetype, FlarePrizeTier, FlareState
    from engine.flare_engine import finalize_flare

    f = Flare(
        system_id=warden_with_held_lighthouse.system.channel_id,
        archetype=FlareArchetype.SALVAGE_DRIFT,
        prize_tier=FlarePrizeTier.SMALL,
        prize_pool={"credits": 200},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),  # already expired
    )
    db_session.add(f)
    await db_session.flush()

    await finalize_flare(db_session, flare_id=f.id)
    await db_session.refresh(f)
    assert f.state == FlareState.EXPIRED
    assert f.winners == []
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_flare_finalize.py -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Implement `finalize_flare`**

Append to `engine/flare_engine.py`:

```python
async def finalize_flare(session: AsyncSession, *, flare_id) -> None:
    """Resolve a flare. Idempotent — no-op if state != OPEN.

    Salvage Drift: first FlareClick by clicked_at wins entire prize pool.
    Signal Pulse: all FlareClicks within `coalesce_close_at` window split equally.
    No clicks → EXPIRED.
    Pride writes: home citizen wins → +5; outsider citizen wins (visiting from
    a same-Sector neighbor) → -3 to host, +2 to outsider's home.
    """
    from engine.pride_engine import apply_pride
    from engine.rewards import apply_reward
    from db.models import (
        Citizenship,
        Lighthouse,
        RewardSourceType,
        System,
    )

    flare = await session.get(Flare, flare_id, with_for_update=True)
    if flare is None or flare.state != FlareState.OPEN:
        return

    clicks = (
        await session.execute(
            select(FlareClick)
            .where(FlareClick.flare_id == flare_id)
            .order_by(FlareClick.clicked_at.asc())
        )
    ).scalars().all()

    if not clicks:
        flare.state = FlareState.EXPIRED
        return

    if flare.archetype == FlareArchetype.SALVAGE_DRIFT:
        winners = [clicks[0].player_id]
    else:  # SIGNAL_PULSE
        first_click_at = clicks[0].clicked_at
        cutoff = first_click_at + timedelta(seconds=SIGNAL_PULSE_COALESCE_SECONDS)
        winners = [c.player_id for c in clicks if c.clicked_at <= cutoff]

    flare.state = FlareState.WON
    flare.winners = winners

    # Prize delivery — split credits equally among winners.
    pool = dict(flare.prize_pool)
    credits_total = int(pool.get("credits", 0))
    if credits_total > 0 and winners:
        per_winner = credits_total // len(winners)
        for w in winners:
            await apply_reward(
                session,
                user_id=w,
                kind="credits",
                amount=per_winner,
                source_type=RewardSourceType.EXPEDITION_OUTCOME,  # closest existing kind; consider a new FLARE_WIN value in 3b-5
                source_id=f"flare:{flare_id}:{w}",
                system_id=flare.system_id,
            )

    # Pride writes per spec §13.1.
    host_lh = (
        await session.execute(select(Lighthouse).where(Lighthouse.system_id == flare.system_id))
    ).scalar_one_or_none()
    if host_lh is None:
        return

    for w in winners:
        citz = (
            await session.execute(
                select(Citizenship)
                .where(Citizenship.player_id == w)
                .where(Citizenship.ended_at.is_(None))
            )
        ).scalar_one_or_none()
        if citz is None:
            continue
        if citz.system_id == flare.system_id:
            # Home win → +5 to host.
            await apply_pride(session, lighthouse_id=host_lh.id, delta=5, reason="home_flare_win")
        else:
            # Outsider (same-Sector neighbor) won → -3 host, +2 outsider's home.
            await apply_pride(session, lighthouse_id=host_lh.id, delta=-3, reason="outsider_flare_win")
            outsider_lh = (
                await session.execute(
                    select(Lighthouse).where(Lighthouse.system_id == citz.system_id)
                )
            ).scalar_one_or_none()
            if outsider_lh is not None:
                await apply_pride(
                    session, lighthouse_id=outsider_lh.id, delta=2, reason="snipe_flare_win"
                )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_flare_finalize.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/flare_engine.py tests/test_engine_flare_finalize.py
git commit -m "feat(phase3b-4): finalize flare — Salvage Drift + Signal Pulse + Pride writes"
```

---

## Task 10: Flare spawner scheduler job

**Files:**
- Create: `scheduler/jobs/flare_spawner.py`
- Create: `tests/test_handler_flare_spawner.py`

- [ ] **Step 1: Implement the spawner**

The spawner runs every ~5 minutes globally. Each tick: iterate all active Lighthouses, decide for each whether to spawn now based on:
- Last passive flare's spawn time (if any open, skip)
- Lighthouse's Fog Clearance tier → cadence band (spec §12.6 table)
- `last_human_message_at` → auto-throttle multiplier (>12h: 1.5x, >24h: pause)
- Random jitter

Create `scheduler/jobs/flare_spawner.py`:

```python
"""FLARE_SPAWNER handler — periodic per-Lighthouse passive spawn decision."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config.logging import get_logger
from db.models import (
    Flare,
    FlareState,
    JobState,
    JobType,
    Lighthouse,
    LighthouseState,
    LighthouseUpgrade,
    ScheduledJob,
    SlotCategory,
    System,
)
from engine.flare_engine import spawn_passive
from scheduler.dispatch import HandlerResult, register

log = get_logger(__name__)

TICK_INTERVAL_MINUTES = 5

# Spec §12.6 base intervals (minutes).
_BASE_INTERVAL_BY_TIER = {
    None: (90, 180),       # bare Lighthouse
    1: (60, 120),          # Fog Clearance Tier I
    2: (30, 60),           # Fog Clearance Tier II
}
_UNCLAIMED_INTERVAL = (120, 240)


async def handle_flare_spawner(session, job: ScheduledJob) -> HandlerResult:
    rows = (
        await session.execute(
            select(Lighthouse, System)
            .join(System, System.channel_id == Lighthouse.system_id)
            .where(Lighthouse.state == LighthouseState.ACTIVE)
        )
    ).all()

    spawned = 0
    rng = random.Random()
    for lh, sys_obj in rows:
        if not await _should_spawn_now(session, lh, sys_obj, rng):
            continue
        flare = await spawn_passive(session, lh.system_id)
        if flare is not None:
            spawned += 1

    log.info("flare_spawner: %d/%d spawned this tick", spawned, len(rows))
    job.state = JobState.COMPLETED
    job.completed_at = func.now()
    return HandlerResult()


async def _should_spawn_now(session, lh, sys_obj, rng) -> bool:
    """Probability gate per Lighthouse.

    Skip if:
    - already an open flare in this system
    - channel silent >24h (auto-pause; spec §12.6)
    - last spawn was within the band's interval

    Otherwise: roll p ≈ TICK_INTERVAL_MINUTES / mean(interval).
    """
    open_flare = (
        await session.execute(
            select(Flare).where(Flare.system_id == lh.system_id, Flare.state == FlareState.OPEN)
        )
    ).first()
    if open_flare:
        return False

    now = datetime.now(timezone.utc)
    if sys_obj.last_human_message_at is not None:
        silence = now - sys_obj.last_human_message_at
        if silence > timedelta(hours=24):
            return False
        silence_multiplier = 1.5 if silence > timedelta(hours=12) else 1.0
    else:
        silence_multiplier = 1.0

    if lh.warden_id is None:
        lo, hi = _UNCLAIMED_INTERVAL
    else:
        fog = (
            await session.execute(
                select(LighthouseUpgrade)
                .where(LighthouseUpgrade.lighthouse_id == lh.id)
                .where(LighthouseUpgrade.slot_category == SlotCategory.FOG)
            )
        ).scalars().first()
        tier_key = fog.tier if fog and fog.tier > 0 else None
        lo, hi = _BASE_INTERVAL_BY_TIER[tier_key]

    mean_interval = ((lo + hi) / 2) * silence_multiplier
    p = TICK_INTERVAL_MINUTES / mean_interval
    return rng.random() < min(0.99, p)


register(JobType.FLARE_SPAWNER, handle_flare_spawner)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_handler_flare_spawner.py`:

```python
"""Spawner respects auto-throttle and one-flare-per-system."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_spawner_skips_silent_channel_over_24h(
    db_session, warden_with_held_lighthouse
):
    from db.models import Flare, JobState, JobType, ScheduledJob, System
    from scheduler.jobs.flare_spawner import handle_flare_spawner
    from sqlalchemy import select

    sys_obj = await db_session.get(System, warden_with_held_lighthouse.system.channel_id)
    sys_obj.last_human_message_at = datetime.now(timezone.utc) - timedelta(hours=30)
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.FLARE_SPAWNER,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_flare_spawner(db_session, job)
    await db_session.flush()

    flares = (await db_session.execute(select(Flare))).scalars().all()
    assert flares == []  # silenced
```

(Two more tests: one for normal spawn, one for the one-flare-per-system rule.)

- [ ] **Step 3: Run, confirm passes**

Expected: PASS.

- [ ] **Step 4: Schedule the recurring job**

In `bot/main.py::setup_hook`, mirror the tribute_drip / pride_decay seed pattern but with a 5-minute recurrence.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/flare_spawner.py tests/test_handler_flare_spawner.py bot/main.py
git commit -m "feat(phase3b-4): periodic flare spawner with cadence + auto-throttle"
```

---

## Task 11: Flare resolve scheduler job (outer-window expiry)

**Files:**
- Create: `scheduler/jobs/flare_resolve.py`

- [ ] **Step 1: Implement**

```python
"""FLARE_RESOLVE handler — fires when a flare's outer window closes."""

from __future__ import annotations

from sqlalchemy import func

from config.logging import get_logger
from db.models import JobState, JobType, ScheduledJob
from engine.flare_engine import finalize_flare
from scheduler.dispatch import HandlerResult, register

log = get_logger(__name__)


async def handle_flare_resolve(session, job: ScheduledJob) -> HandlerResult:
    flare_id = job.payload["flare_id"]
    await finalize_flare(session, flare_id=flare_id)
    job.state = JobState.COMPLETED
    job.completed_at = func.now()
    return HandlerResult()


register(JobType.FLARE_RESOLVE, handle_flare_resolve)
```

In `engine/flare_engine.py::_create_flare`, after creating the flare row, schedule the resolve:

```python
        from db.models import JobState, JobType, ScheduledJob

        session.add(
            ScheduledJob(
                type=JobType.FLARE_RESOLVE,
                run_at=flare.expires_at,
                state=JobState.PENDING,
                payload={"flare_id": str(flare.id)},
            )
        )
```

For Signal Pulse, when the *first* click arrives, also schedule a coalesce-close job (run_at = first_click + 30s). The spawner doesn't know when first click happens, so this lives in `register_click`:

```python
    # Signal Pulse: schedule coalesce-close on the first click.
    if flare.archetype == FlareArchetype.SIGNAL_PULSE and flare.coalesce_close_at is None:
        coalesce_close_at = now + timedelta(seconds=SIGNAL_PULSE_COALESCE_SECONDS)
        flare.coalesce_close_at = coalesce_close_at
        from db.models import JobState, JobType, ScheduledJob
        session.add(
            ScheduledJob(
                type=JobType.FLARE_RESOLVE,
                run_at=coalesce_close_at,
                state=JobState.PENDING,
                payload={"flare_id": str(flare_id)},
            )
        )
```

- [ ] **Step 2: Test**

Add to `tests/test_handler_flare_resolve.py` covering the outer-window expiry path.

- [ ] **Step 3: Commit**

```bash
git add scheduler/jobs/flare_resolve.py engine/flare_engine.py tests/test_handler_flare_resolve.py bot/main.py
git commit -m "feat(phase3b-4): flare resolve handler + auto-schedule on spawn/click"
```

---

## Task 12: Channel-silence tracking via `on_message` listener

**Files:**
- Modify: `bot/main.py`
- Create: `tests/test_on_message_silence_tracking.py`

- [ ] **Step 1: Add the listener**

In `bot/main.py`, on `Dare2DriveBot`:

```python
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return  # don't reset on the bot's own posts
        if message.guild is None:
            return  # DMs don't represent system channels

        async with async_session() as session, session.begin():
            from db.models import System
            from sqlalchemy import update
            await session.execute(
                update(System)
                .where(System.channel_id == str(message.channel.id))
                .values(last_human_message_at=func.now())
            )
        # Don't process commands here — slash commands route via the tree.
```

- [ ] **Step 2: Test**

Create the test that sends a mock `Message` and asserts the column updates.

- [ ] **Step 3: Commit**

```bash
git add bot/main.py tests/test_on_message_silence_tracking.py
git commit -m "feat(phase3b-4): on_message listener tracks last_human_message_at"
```

---

## Task 13: Flare embed view with ClaimButton DynamicItem

**Files:**
- Create: `bot/views/flare_view.py`
- Modify: `bot/main.py` (register DynamicItem)

- [ ] **Step 1: Implement the view**

Create `bot/views/flare_view.py`:

```python
"""Flare embed + ClaimButton DynamicItem.

custom_id format: flare:claim:<flare_id>
"""

from __future__ import annotations

import uuid

import discord
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session
from engine.flare_engine import FlareError, register_click

CUSTOM_ID_PREFIX = "flare:claim"


def make_claim_custom_id(flare_id: uuid.UUID) -> str:
    return f"{CUSTOM_ID_PREFIX}:{flare_id}"


def parse_claim_custom_id(custom_id: str) -> uuid.UUID | None:
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != "flare" or parts[1] != "claim":
        return None
    try:
        return uuid.UUID(parts[2])
    except ValueError:
        return None


class ClaimButton(discord.ui.DynamicItem[discord.ui.Button], template=r"flare:claim:[^:]+"):
    def __init__(self, flare_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Claim",
                style=discord.ButtonStyle.success,
                custom_id=make_claim_custom_id(flare_id),
            )
        )
        self.flare_id = flare_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        gid = parse_claim_custom_id(item.custom_id)
        if gid is None:
            raise ValueError(f"unparseable: {item.custom_id}")
        return cls(gid)

    async def callback(self, interaction: discord.Interaction) -> None:
        async with async_session() as session, session.begin():
            try:
                await register_click(
                    session, flare_id=self.flare_id, player_id=str(interaction.user.id)
                )
            except FlareError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return
        await interaction.response.send_message("Click registered.", ephemeral=True)


def build_flare_embed(flare, system_name: str) -> discord.Embed:
    e = discord.Embed(
        title=f"⚡ {flare.archetype.value.replace('_', ' ').title()} — #{system_name}",
        color=discord.Color.orange(),
    )
    if flare.archetype.value == "salvage_drift":
        e.description = "First click wins the entire pool."
    else:
        e.description = "First click opens a 30s coalesce window — split the pool."
    e.add_field(
        name="Prize",
        value=", ".join(f"{v} {k}" for k, v in flare.prize_pool.items()),
    )
    e.add_field(name="Tier", value=flare.prize_tier.value)
    e.set_footer(text=f"Citizens 0s · neighbors {flare.neighbor_delay_seconds}s delay")
    return e


def build_flare_view(flare) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(ClaimButton(flare.id))
    return view
```

In `bot/main.py::setup_hook`, register `ClaimButton`:

```python
        from bot.views.flare_view import ClaimButton
        self.add_dynamic_items(ClaimButton)
```

- [ ] **Step 2: Wire the embed post**

When `_create_flare` runs (in `flare_engine.py`), the engine itself can't post a Discord message (no bot reference). Instead, the spawner job collects the new flare and the calling cog/scheduler posts the embed afterward. Pragmatic shape: `flare_spawner` is kicked from a top-level Bot task (not a pure handler) so it has access to `self`. The simplest path is a small post-spawn helper in `bot/cogs/lighthouse.py` that reads recently-spawned flares and posts embeds:

For 3b-4, schedule this as a follow-up task — Task 14.

- [ ] **Step 3: Test the view interaction routing**

Add `tests/test_view_flare.py` covering `parse_claim_custom_id` and the round-trip with a stub interaction.

- [ ] **Step 4: Commit**

```bash
git add bot/views/flare_view.py bot/main.py tests/test_view_flare.py
git commit -m "feat(phase3b-4): ClaimButton DynamicItem + flare embed renderer"
```

---

## Task 14: Post flare embeds to the system channel after spawn

**Files:**
- Modify: `scheduler/jobs/flare_spawner.py` to surface new flares; OR
- Add a follow-on dispatcher.

- [ ] **Step 1: Decide the post-spawn pattern**

Two options:
- (a) Spawner returns the new flare row IDs; the bot's notification consumer (or a new `flare_post` job type) takes care of posting. Cleanest.
- (b) Spawner directly uses a bot reference passed at scheduler startup. Simpler but couples the scheduler to discord.py.

**Recommend (a):** introduce a tiny `flare_post` queue. After `_create_flare`, write a notification request that the existing notification consumer dispatches. The consumer iterates pending posts and calls `channel.send(embed=..., view=...)` then writes the resulting `message_id` back to `flares.channel_message_id`.

The `bot/notifications.py` consumer already handles DM dispatch — extend it to handle a `flare_channel_post` category that posts to a channel rather than a DM.

- [ ] **Step 2: Implement and test**

Stub task — the executor should look at `bot/notifications.py` and decide the integration. Detailed implementation is left to the executor since the existing notification shape determines the cleanest extension. Acceptance: a passive flare spawn results in a public embed in the system's channel within a few seconds of the spawner tick.

- [ ] **Step 3: Commit**

Multiple commits expected; final one:

```bash
git commit -m "feat(phase3b-4): post flare embeds via notification consumer"
```

---

## Task 15: `/lighthouse flare call` Warden subcommand

**Files:**
- Modify: `bot/cogs/lighthouse.py`
- Create: `tests/test_cog_lighthouse_flare.py`

- [ ] **Step 1: Add the subgroup + subcommand**

```python
class FlareSubgroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="flare", description="Warden flare controls.")

    @app_commands.command(name="call", description="Spend tribute to call a flare.")
    @app_commands.choices(
        archetype=[
            app_commands.Choice(name="Salvage Drift", value="salvage_drift"),
            app_commands.Choice(name="Signal Pulse", value="signal_pulse"),
        ],
        prize_tier=[
            app_commands.Choice(name="small (100 tribute)", value="small"),
            app_commands.Choice(name="standard (250 tribute)", value="standard"),
            app_commands.Choice(name="premium (750 tribute)", value="premium"),
        ],
    )
    async def call(
        self,
        interaction: discord.Interaction,
        archetype: app_commands.Choice[str],
        prize_tier: app_commands.Choice[str],
    ) -> None:
        async with async_session() as session, session.begin():
            from db.models import FlareArchetype, FlarePrizeTier, Lighthouse
            from engine.flare_engine import FlareError, spawn_called
            from sqlalchemy import select

            # Resolve which Lighthouse the warden is acting on (their primary).
            lh = (
                await session.execute(
                    select(Lighthouse).where(Lighthouse.warden_id == str(interaction.user.id))
                )
            ).scalar_one_or_none()
            if lh is None:
                await interaction.response.send_message(
                    "You are not a Warden.", ephemeral=True
                )
                return
            try:
                flare = await spawn_called(
                    session,
                    system_id=lh.system_id,
                    warden_id=str(interaction.user.id),
                    archetype=FlareArchetype(archetype.value),
                    prize_tier=FlarePrizeTier(prize_tier.value),
                )
            except FlareError as e:
                await interaction.response.send_message(f"Flare rejected: {e}", ephemeral=True)
                return

        await interaction.response.send_message(
            f"Flare called — {archetype.name} ({prize_tier.name}). The embed will land in the channel shortly.",
            ephemeral=True,
        )
```

Wire `FlareSubgroup` into `LighthouseGroup.add_command(FlareSubgroup())` in `setup`.

- [ ] **Step 2: Test**

Create `tests/test_cog_lighthouse_flare.py` covering the happy path + tribute insufficient + non-Warden rejection.

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/lighthouse.py tests/test_cog_lighthouse_flare.py
git commit -m "feat(phase3b-4): /lighthouse flare call Warden subcommand"
```

---

## Task 16: Extend `/system info` with Pride scoreboard + recent activity

**Files:**
- Modify: `bot/cogs/admin.py`
- Modify: `tests/test_systems_sectors.py`

- [ ] **Step 1: Add the panels**

Extend `_sector_info_logic` (or a new `_system_info_logic`) to include:

- Top 3 donor-contributors this week (read `donation_ledger`, group by `player_id`, filter to the system, ORDER BY effective_credits DESC LIMIT 3).
- Last 5 flare events (read `flares` ORDER BY spawned_at DESC LIMIT 5; format as "WIN by <player>" / "lost to outsider" / "expired").
- Per-Sector neighbor scoreboard ("stolen from / stolen by"): aggregate `flares.winners` and `pride_events` to produce per-pair counters.

This is read-mostly UI work — pure SQL aggregations.

- [ ] **Step 2: Test**

Append a few cases to `tests/test_systems_sectors.py`.

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/admin.py tests/test_systems_sectors.py
git commit -m "feat(phase3b-4): /system info shows Pride + flare activity + neighbor scoreboard"
```

---

## Task 17: System gating + cog wiring

**Files:**
- Modify: `bot/system_gating.py`, `bot/cogs/lighthouse.py`

- [ ] **Step 1: Add the new subcommand qualified names**

```python
UNIVERSE_WIDE_COMMANDS = {
    # existing 3b-1..3 entries
    "lighthouse flare call",
}
```

- [ ] **Step 2: Test + commit**

```bash
git add bot/system_gating.py tests/test_system_gating.py
git commit -m "feat(phase3b-4): /lighthouse flare call universe-wide"
```

---

## Task 18: End-to-end scenario — flare race + Pride

**Files:**
- Create: `tests/test_scenarios/test_flare_race.py`

- [ ] **Step 1: Write the scenario**

```python
"""Scenario: passive flare spawns → home citizen clicks → finalizes → Pride moves."""

from __future__ import annotations

from datetime import datetime, timezone


async def test_full_flare_race(db_session, warden_with_held_lighthouse, home_citizen):
    from db.models import Flare, FlareState, Lighthouse, PrideEvent
    from engine.flare_engine import finalize_flare, register_click, spawn_passive
    from sqlalchemy import select

    # 1. Spawn.
    flare = await spawn_passive(db_session, system_id=warden_with_held_lighthouse.system.channel_id)
    await db_session.flush()
    assert flare is not None

    # 2. Citizen clicks.
    await register_click(db_session, flare_id=flare.id, player_id=home_citizen.user.discord_id)
    await db_session.flush()

    # 3. Finalize (simulating outer-window expiry).
    await finalize_flare(db_session, flare_id=flare.id)
    await db_session.flush()
    await db_session.refresh(flare)
    assert flare.state == FlareState.WON
    assert flare.winners == [home_citizen.user.discord_id]

    # 4. Pride moved on host (+5 home-flare-win).
    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == warden_with_held_lighthouse.system.channel_id)
        )
    ).scalar_one()
    assert lh.pride_score >= 5

    events = (await db_session.execute(select(PrideEvent))).scalars().all()
    assert any(e.reason == "home_flare_win" for e in events)
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_scenarios/test_flare_race.py
git commit -m "test(phase3b-4): scenario — flare race → win → pride moves"
```

---

## Task 19: Documentation

**Files:**
- Create: `docs/authoring/flares_and_pride.md`

- [ ] **Step 1: Write the doc**

```markdown
# Authoring: Flares + Pride

## Flare cadence

`scheduler/jobs/flare_spawner.py` runs every 5 minutes and decides per
Lighthouse whether to spawn. The cadence band depends on:

- Lighthouse claim status (unclaimed = slowest)
- Fog Clearance tier installed (Tier II = fastest)
- `last_human_message_at` (>12h: 1.5x slower, >24h: paused)

Tuning: `_BASE_INTERVAL_BY_TIER` and `_UNCLAIMED_INTERVAL` in
`scheduler/jobs/flare_spawner.py`.

## Prize pools

`engine.flare_engine._PRIZE_POOL_SAMPLES` maps `(archetype, tier)` to
`(lo, hi)` credit ranges. Edit there to retune; no schema change needed.

## Pride sources

`engine.pride_engine.apply_pride` is the single writer. Reasons used so far:

| Reason | Delta | Source |
|---|---|---|
| `donation` | +1/100c +1/part | 3b-3 donate (recipient) |
| `goal_completed` | +20 | 3b-3 install_goal |
| `goal_cancelled` | -10 | 3b-3 cancel_goal |
| `home_flare_win` | +5 | finalize_flare |
| `outsider_flare_win` | -3 | finalize_flare (host) |
| `snipe_flare_win` | +2 | finalize_flare (outsider's home) |
| `auto_abdicate` | -50 | 3b-5 lapse handler |

## Audience tiers

`engine.flare_engine._resolve_audience_tier` returns one of `citizen | neighbor | outsider`.
The check is server-side at click time. Cross-Sector clicks are denied in 3b-4
and unlocked in 3e.

## Channel-silence auto-throttle

`bot/main.py` updates `systems.last_human_message_at` on every human message.
The spawner reads it. If you need to tune the silence thresholds, change the
constants in `_should_spawn_now`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/authoring/flares_and_pride.md
git commit -m "docs(phase3b-4): flares + pride authoring guide"
```

---

## Task 20: Final integration smoke

**Files:** none — verification only.

- [ ] **Step 1: Full suite + migration round-trip**

Run: `pytest --no-cov -q` then `alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 2: Manual verification (needs 2 Discord accounts)**

- Account A is Warden. `/lighthouse flare call salvage_drift small` — embed appears in the system channel.
- Account A (citizen of own system) clicks Claim — accepted.
- Account B (citizen of a sibling system in the same guild) clicks Claim within 45s — rejected with "wait Ns".
- Wait out the delay → Account B clicks → registered.
- Wait for the outer window or trigger the resolve manually — flare resolves.
- `/system info` should now show the win in the recent-flare panel + Pride moved.

- [ ] **Step 3: Push and PR**

```bash
gh pr create --title "Phase 3b-4: Beacon Flares + Pride + activity-cut tribute" --body "$(cat <<'EOF'
## Summary
- `flares` + `flare_clicks` + `pride_events` tables; Salvage Drift + Signal Pulse archetypes.
- Audience-tier delay: citizen 0s, same-Sector neighbor 30-60s, cross-Sector denied (3e unlocks).
- Periodic flare_spawner with cadence bands by Fog tier + auto-throttle on silent channels (>12h slows, >24h pauses).
- Warden-called flares via `/lighthouse flare call` (deducts tribute).
- Pride engine — single writer, decay 1%/day, 6 source kinds (donation, goal completed/cancelled, flare wins).
- Activity-cut tribute: 3% of citizen credit-equivalent rewards in-system flow to Warden via apply_reward hook.
- on_message listener tracks last_human_message_at for silence auto-throttle.
- Goal embed re-render path lifted to notification-consumer pattern (Task 14 — same as future 3b-5 lapse posts).

## Test plan
- [x] All previously-green stays green
- [x] Migration round-trips
- [x] Scenario: spawn → citizen click → finalize → Pride moves
- [ ] Manual: dev bot, two accounts, citizen vs neighbor click race; verify delay enforcement + Pride scoreboard

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Spec coverage check (self-review)

| Spec section | Covered by | Notes |
|---|---|---|
| §10.1 Activity cut | Task 6 | apply_reward hook |
| §10.3 Flare-call cost | Task 7 | spawn_called deducts tribute |
| §12.1 Audience tiers | Task 8 | _resolve_audience_tier |
| §12.2 Anatomy | Tasks 1, 2 | flares + flare_clicks tables |
| §12.3 Lifecycle | Tasks 7-11 | spawn → click → resolve |
| §12.4 Salvage Drift | Task 9 | first-click winner |
| §12.5 Signal Pulse | Tasks 9, 11 | 30s coalesce close |
| §12.6 Spawn cadence + auto-throttle | Tasks 10, 12 | flare_spawner + on_message |
| §12.7 Prize tiers | Task 7 | _PRIZE_POOL_SAMPLES |
| §12.8 Reward delivery | Task 9 | apply_reward routes credits |
| §13.1 Pride sources | Tasks 3, 5, 9 | apply_pride writes |
| §13.2 Decay | Tasks 3, 4 | apply_daily_decay + handler |
| §13.3 Visibility | Task 16 | /system info panels |
| §13.6 Storage | Task 1 | pride_score on Lighthouse + pride_events |
| §16.1 /lighthouse flare call | Task 15 | subcommand |
| §16.4 Flare embed | Tasks 13, 14 | DynamicItem + post path |

Sections deferred listed in plan header.

---

## Open Questions

1. **Reward source kind for flare wins.** `apply_reward` in 3b-4 routes flare prizes through `RewardSourceType.EXPEDITION_OUTCOME`. That's misleading — consider adding a `FLARE_WIN` value in 3b-5's migration. For 3b-4 the existing kind preserves idempotency without a schema change; downstream analytics will conflate.
2. **Notification consumer extension for channel posts.** Task 14 punts the implementation detail because it depends on the existing `bot/notifications.py` shape. The executor should plan a small subtask once they read that file. If it's genuinely complex, carve it into its own PR.
3. **Concurrent click race correctness.** The PK on `flare_clicks(flare_id, player_id)` prevents double-clicks per player. The order of clicks across players is the DB tx commit order — Postgres serializes correctly under `READ COMMITTED`. No `SELECT FOR UPDATE` needed; the test in Task 9 verifies via `clicked_at` ordering. If real-world rates ever show clock-skew artifacts, add a `serial` column for tiebreaking.

---

## Execution Handoff

Plan complete. Two execution options as in prior sub-plans.

---

## Next sub-plans (not in this file)

- `2026-05-02-phase-3b-5-lapse.md` — Lapse / vacation / general tribute spending / abdication
- `2026-05-02-phase-3b-6-llm-narrative.md` — Real LLM narrative seed pass
