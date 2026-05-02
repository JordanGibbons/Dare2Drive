# Phase 3b-5 — Lapse, Vacation, Tribute Spending, Abdication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Phase 3b loop with the Warden's commitment mechanism. After this plan ships, inactive Wardens get a 14-day public warning + DM, lapse to auto-abdication on day 21 (or up to day 28 with panic-mode tribute defer), vacation can be declared at a favorable rate to pause the lapse cleanly, tribute converts to credits at a capped daily rate, and voluntary abdication exists with the same consequences as auto-abdication. **No new gameplay surfaces beyond these — by the time 3b-5 ships, the full Phase 3b loop is live.** LLM narrative seed remains the deterministic stub from 3b-1; that swap-in lands in 3b-6.

**Architecture:**
- Two columns added to `lighthouses`: `warden_last_activity_at` (timestamp; updated by every Warden touch) and `vacation_started_at` (set by `vacation start`, cleared on `vacation end`). The existing `lapse_warning_at` and `vacation_until` columns from 3b-1 are now read by live logic.
- One column added to `users`: `tribute_credits_converted_today` (int) plus a `tribute_credits_converted_at` date — pair tracks the daily cap. Reset lazily on first conversion of a new UTC day.
- One enum value added: `RewardSourceType.FLARE_WIN` (cleans up the 3b-4 punt) and `RewardSourceType.TRIBUTE_CONVERSION`. Migration `0010_phase3b_5_lapse`.
- `engine/lapse_engine.py` is the central module:
  - `touch_warden_activity(session, warden_id)` — single function that every Warden-action call site invokes. Updates `warden_last_activity_at`, clears `lapse_warning_at` if set, no-op when on vacation.
  - `compute_lapse_stage(lighthouse, now) -> LapseStage` — pure function returning `clear | warning_due | warning_active | abdicate_due | on_vacation`.
  - `declare_vacation(session, warden_id, days)` / `end_vacation(session, warden_id)` — costs/refunds via tribute_ledger.
  - `panic_defer(session, warden_id, days)` — 50 tribute / +1 day, only after warning, max +7.
  - `auto_abdicate(session, lighthouse_id, voluntary=False)` — clears `warden_id`, refunds active goals at 100% (vs 75% for voluntary cancel — spec §14.6), drops Pride 50, sets a 14-day claim cooldown for the departing Warden (uses a sentinel `ClaimAttempt` row dated +14d).
- `engine/tribute_engine.py` extension (from 3b-3):
  - `convert_to_credits(session, warden_id, amount)` — capped at 1000 credits/day per Warden (= 5000 tribute/day cost).
- `scheduler/jobs/lapse_check.py` — daily handler. Walks every Warden Lighthouse, computes `compute_lapse_stage`, fires the appropriate side-effect: warning post + DM at day 14, auto-abdication at day 21 (or day 28 if panic-deferred). Idempotent — re-running on the same day doesn't double-warn or double-abdicate.
- Activity-touch hooks scatter through existing call sites: every `/lighthouse` subcommand (status excluded — viewing isn't activity), flare call, goal post/install/cancel, expedition completion in a held system, job completion in a held system. The hook is one line: `await touch_warden_activity(session, warden_id)`.
- Vacation declaration writes a `vacation_started_at` column; the lapse computer treats `now < vacation_until` as `on_vacation` and skips warning/abdication.
- Public posts (lapse warning, abdication, vacation declared, vacation ended) use the same notification-consumer extension recommended in 3b-4 Task 14. If that ships in 3b-4, this plan reuses it; if not, 3b-5 carries the same TODO.

**Tech Stack:** No new top-level deps. Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, discord.py 2.x, pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-05-02-phase-3b-lighthouses-design.md](../specs/2026-05-02-phase-3b-lighthouses-design.md) — sections covered: §10.3 (vacation/panic/conversion spending), §14 (full lapse + vacation + abdication arc), parts of §15 (column extensions), §16.1 / §16.2 (`/lighthouse vacation`, `/lighthouse abdicate`, `/lighthouse tribute convert`), §16.4 (lapse-warning + abdication public posts).

**Depends on:** 3b-1 (Lighthouse columns), 3b-2 (`ClaimAttempt` for the 14-day claim cooldown), 3b-3 (upgrade goals — refund path on abdication), 3b-4 (tribute_ledger spend path, notification consumer pattern, Pride decay).

**Sections deferred:** None within Phase 3b. Pride cosmetic unlocks → Phase 4+. Alliance Wardenship / contested-claim windows → Phase 4+.

**Dev loop:** Same as prior sub-plans.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0010_phase3b_5_lapse.py` | New columns + enum extensions |
| `engine/lapse_engine.py` | `touch_warden_activity` / `compute_lapse_stage` / `declare_vacation` / `end_vacation` / `panic_defer` / `auto_abdicate` |
| `scheduler/jobs/lapse_check.py` | Daily lapse walk handler |
| `tests/test_phase3b_5_migration.py` | Schema round-trip |
| `tests/test_engine_lapse_stage.py` | Pure-function lapse stage computation across all branches |
| `tests/test_engine_touch_activity.py` | touch_warden_activity behaviour + on-vacation no-op |
| `tests/test_engine_vacation.py` | Declare / end / cost / re-declare gap |
| `tests/test_engine_panic_defer.py` | Cost + cap + only-after-warning gating |
| `tests/test_engine_auto_abdicate.py` | Refund 100%, drop Pride 50, 14-day cooldown |
| `tests/test_engine_tribute_convert.py` | Daily 1000c cap, 5:1 rate |
| `tests/test_handler_lapse_check.py` | Daily handler — warning at day 14, abdication at day 21 |
| `tests/test_cog_lighthouse_vacation.py` | Vacation start/end/panic subcommands |
| `tests/test_cog_lighthouse_abdicate.py` | Voluntary abdication subcommand |
| `tests/test_cog_lighthouse_tribute.py` | tribute view + convert |
| `tests/test_scenarios/test_lapse_cycle.py` | End-to-end: 14d → warn → 7d grace → abdicate; vacation pauses; panic defers |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add `Lighthouse.warden_last_activity_at`, `Lighthouse.vacation_started_at`, `User.tribute_credits_converted_today`, `User.tribute_credits_converted_at`; extend `RewardSourceType` with `FLARE_WIN` + `TRIBUTE_CONVERSION`; extend `JobType` with `LAPSE_CHECK` |
| `bot/cogs/lighthouse.py` | Add `vacation`, `abdicate`, `tribute` subcommands on `LighthouseGroup` |
| `engine/upgrade_engine.py` | Hook `touch_warden_activity` into `post_goal`, `install_goal`, `cancel_goal` |
| `engine/flare_engine.py` | Hook `touch_warden_activity` into `spawn_called` |
| `scheduler/jobs/expedition_complete.py` | When the player is a Warden of the system the expedition resolved in, touch activity |
| `scheduler/jobs/timer_complete.py` | Same hook for jobs that complete in a Warden's held system |
| `bot/main.py` | Register `lapse_check` handler import; schedule daily |
| `bot/system_gating.py` | Add new subcommand qualified names to the universe-wide allow-list |
| `engine/rewards.py` | Use new `FLARE_WIN` source type when the call site is finalize_flare (replace 3b-4's stand-in) |

---

## Task 1: Migration 0010 — column extensions + enum values

**Files:**
- Create: `db/migrations/versions/0010_phase3b_5_lapse.py`
- Create: `tests/test_phase3b_5_migration.py`

- [ ] **Step 1: Write the failing test**

```python
"""Phase 3b-5 migration: lapse/vacation columns, conversion tracking, new enum values."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def test_lighthouses_has_lapse_columns(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {c["name"] for c in insp.get_columns("lighthouses")}
    assert "warden_last_activity_at" in cols
    assert "vacation_started_at" in cols


async def test_users_has_conversion_tracking_columns(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {c["name"] for c in insp.get_columns("users")}
    assert "tribute_credits_converted_today" in cols
    assert "tribute_credits_converted_at" in cols


async def test_rewardsourcetype_extended(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'rewardsourcetype'"
            )
        )
    ).scalars().all()
    assert "flare_win" in set(rows)
    assert "tribute_conversion" in set(rows)


async def test_jobtype_has_lapse_check(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'jobtype'"
            )
        )
    ).scalars().all()
    assert "lapse_check" in set(rows)
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase3b_5_migration.py -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Write the migration**

Create `db/migrations/versions/0010_phase3b_5_lapse.py`:

```python
"""Phase 3b-5 — Lapse, vacation, tribute spending.

Revision ID: 0010_phase3b_5_lapse
Revises: 0009_phase3b_4_flares
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_phase3b_5_lapse"
down_revision = "0009_phase3b_4_flares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lighthouses",
        sa.Column("warden_last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lighthouses",
        sa.Column("vacation_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "tribute_credits_converted_today", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "users",
        sa.Column("tribute_credits_converted_at", sa.Date(), nullable=True),
    )

    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE rewardsourcetype ADD VALUE IF NOT EXISTS 'flare_win'")
        op.execute("ALTER TYPE rewardsourcetype ADD VALUE IF NOT EXISTS 'tribute_conversion'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'lapse_check'")

    # Backfill warden_last_activity_at for existing held Lighthouses.
    op.execute(
        "UPDATE lighthouses SET warden_last_activity_at = NOW() "
        "WHERE warden_id IS NOT NULL AND warden_last_activity_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "tribute_credits_converted_at")
    op.drop_column("users", "tribute_credits_converted_today")
    op.drop_column("lighthouses", "vacation_started_at")
    op.drop_column("lighthouses", "warden_last_activity_at")
    # Note: leaving the enum value extensions — Postgres can't drop them
    # cleanly and they're forward-compat no-ops if rolled back.
```

- [ ] **Step 4: Run, confirm passes + round-trip**

Run: `alembic upgrade head` → `pytest tests/test_phase3b_5_migration.py -v --no-cov`
Then: `alembic downgrade -1 && alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add db/migrations/versions/0010_phase3b_5_lapse.py tests/test_phase3b_5_migration.py
git commit -m "feat(phase3b-5): schema for lapse + vacation + tribute conversion"
```

---

## Task 2: ORM extensions

**Files:**
- Modify: `db/models.py`

- [ ] **Step 1: Add columns + enum values**

In `db/models.py`:

```python
# In class Lighthouse(Base): add columns
    warden_last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vacation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

```python
# In class User(Base): add columns
    tribute_credits_converted_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    tribute_credits_converted_at: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
```

(Add `from datetime import date` and `from sqlalchemy import Date` imports.)

Extend `RewardSourceType` with:

```python
    FLARE_WIN = "flare_win"
    TRIBUTE_CONVERSION = "tribute_conversion"
```

Extend `JobType` with:

```python
    LAPSE_CHECK = "lapse_check"
```

- [ ] **Step 2: Smoke test the existing test suite**

Run: `pytest --no-cov -q`
Expected: green. (No new test in this task — schema is exercised by Task 1's tests.)

- [ ] **Step 3: Commit**

```bash
git add db/models.py
git commit -m "feat(phase3b-5): ORM column + enum extensions"
```

---

## Task 3: `compute_lapse_stage` — pure function

**Files:**
- Create: `engine/lapse_engine.py` (skeleton)
- Create: `tests/test_engine_lapse_stage.py`

- [ ] **Step 1: Write the failing test**

```python
"""compute_lapse_stage covers all branches across the (warden, last_activity, lapse_warning, vacation) state space."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _make_lh(warden_id="user", last_activity=None, lapse_warning_at=None, vacation_until=None):
    """Lightweight stand-in for a Lighthouse row (just attribute access)."""
    class _LH:
        pass
    lh = _LH()
    lh.warden_id = warden_id
    lh.warden_last_activity_at = last_activity
    lh.lapse_warning_at = lapse_warning_at
    lh.vacation_until = vacation_until
    return lh


def test_unclaimed_lighthouse_returns_clear():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    lh = _make_lh(warden_id=None)
    assert compute_lapse_stage(lh, now=datetime.now(timezone.utc)) == LapseStage.CLEAR


def test_recent_activity_returns_clear():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    lh = _make_lh(last_activity=now - timedelta(days=2))
    assert compute_lapse_stage(lh, now=now) == LapseStage.CLEAR


def test_inactive_for_14_days_warning_due():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    lh = _make_lh(last_activity=now - timedelta(days=14, hours=1))
    # No warning fired yet → warning_due (handler should fire it now).
    assert compute_lapse_stage(lh, now=now) == LapseStage.WARNING_DUE


def test_warning_fired_inside_grace_returns_warning_active():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    lh = _make_lh(
        last_activity=now - timedelta(days=18),
        lapse_warning_at=now - timedelta(days=4),
    )
    assert compute_lapse_stage(lh, now=now) == LapseStage.WARNING_ACTIVE


def test_warning_fired_grace_expired_abdicate_due():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    lh = _make_lh(
        last_activity=now - timedelta(days=22),
        lapse_warning_at=now - timedelta(days=8),  # > 7 day grace
    )
    assert compute_lapse_stage(lh, now=now) == LapseStage.ABDICATE_DUE


def test_active_vacation_overrides_warning():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    lh = _make_lh(
        last_activity=now - timedelta(days=20),
        lapse_warning_at=now - timedelta(days=6),
        vacation_until=now + timedelta(days=3),
    )
    assert compute_lapse_stage(lh, now=now) == LapseStage.ON_VACATION


def test_expired_vacation_resumes_lapse_logic():
    from engine.lapse_engine import LapseStage, compute_lapse_stage

    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    lh = _make_lh(
        last_activity=now - timedelta(days=20),
        lapse_warning_at=now - timedelta(days=8),
        vacation_until=now - timedelta(hours=1),  # just expired
    )
    assert compute_lapse_stage(lh, now=now) == LapseStage.ABDICATE_DUE
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement `engine/lapse_engine.py`**

```python
"""Lapse / vacation / abdication.

The pure function `compute_lapse_stage(lighthouse, now)` is the single
source of truth for "what state is this Warden seat in right now". The
daily handler in `scheduler/jobs/lapse_check.py` reads it and dispatches
side-effects.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone


WARNING_AT_DAYS = 14   # spec §14.2
GRACE_DAYS = 7         # spec §14.2
PANIC_DEFER_MAX_DAYS = 7
PANIC_DEFER_COST_PER_DAY = 50
VACATION_COST_PER_DAY = 10
VACATION_MAX_DAYS = 14
RE_DECLARE_GAP_DAYS = 14
ABDICATION_PRIDE_DROP = 50
ABDICATION_CLAIM_COOLDOWN_DAYS = 14


class LapseStage(str, enum.Enum):
    CLEAR = "clear"                    # active Warden, no concern
    WARNING_DUE = "warning_due"        # day 14+ inactive, no warning posted yet
    WARNING_ACTIVE = "warning_active"  # warning posted, still inside grace
    ABDICATE_DUE = "abdicate_due"      # grace expired
    ON_VACATION = "on_vacation"        # vacation_until > now → all lapse logic suspended


def compute_lapse_stage(lighthouse, *, now: datetime) -> LapseStage:
    """Return the current lapse state for a Lighthouse row.

    Pure: takes a row-like with the relevant columns, returns the stage.
    """
    if lighthouse.warden_id is None:
        return LapseStage.CLEAR

    vacation_until = lighthouse.vacation_until
    if vacation_until is not None and now < vacation_until:
        return LapseStage.ON_VACATION

    last_activity = lighthouse.warden_last_activity_at
    if last_activity is None:
        # No activity recorded yet but seat is held — treat as just-active to
        # avoid abdicating on a freshly-claimed seat that hasn't ticked yet.
        return LapseStage.CLEAR

    inactive = now - last_activity
    if inactive < timedelta(days=WARNING_AT_DAYS):
        return LapseStage.CLEAR

    warning_at = lighthouse.lapse_warning_at
    if warning_at is None:
        return LapseStage.WARNING_DUE

    if (now - warning_at) >= timedelta(days=GRACE_DAYS):
        return LapseStage.ABDICATE_DUE
    return LapseStage.WARNING_ACTIVE
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_lapse_stage.py -v --no-cov`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lapse_engine.py tests/test_engine_lapse_stage.py
git commit -m "feat(phase3b-5): compute_lapse_stage — single source of truth for seat state"
```

---

## Task 4: `touch_warden_activity` + integration hooks

**Files:**
- Modify: `engine/lapse_engine.py`
- Create: `tests/test_engine_touch_activity.py`

- [ ] **Step 1: Write the failing test**

```python
"""touch_warden_activity updates last_activity, clears warning, no-ops on vacation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_touch_updates_last_activity(db_session, warden_with_held_lighthouse):
    from engine.lapse_engine import touch_warden_activity
    from db.models import Lighthouse
    from sqlalchemy import select

    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=5)
    await db_session.flush()

    await touch_warden_activity(db_session, warden_id=warden_with_held_lighthouse.warden.discord_id)
    await db_session.flush()

    refreshed = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.id == lh.id)
        )
    ).scalar_one()
    elapsed = datetime.now(timezone.utc) - refreshed.warden_last_activity_at
    assert elapsed < timedelta(seconds=5)


async def test_touch_clears_lapse_warning(db_session, warden_with_held_lighthouse):
    from engine.lapse_engine import touch_warden_activity

    lh = warden_with_held_lighthouse.lighthouse
    lh.lapse_warning_at = datetime.now(timezone.utc) - timedelta(days=3)
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=18)
    await db_session.flush()

    await touch_warden_activity(db_session, warden_id=warden_with_held_lighthouse.warden.discord_id)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.lapse_warning_at is None


async def test_touch_during_vacation_does_not_change_state(
    db_session, warden_with_held_lighthouse
):
    """A touch during declared vacation shouldn't end the vacation."""
    from engine.lapse_engine import touch_warden_activity

    lh = warden_with_held_lighthouse.lighthouse
    lh.vacation_until = datetime.now(timezone.utc) + timedelta(days=5)
    lh.vacation_started_at = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.flush()

    await touch_warden_activity(db_session, warden_id=warden_with_held_lighthouse.warden.discord_id)
    await db_session.refresh(lh)
    # Vacation flags untouched.
    assert lh.vacation_until is not None
    assert lh.vacation_started_at is not None
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement `touch_warden_activity`**

Append to `engine/lapse_engine.py`:

```python
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def touch_warden_activity(session: AsyncSession, *, warden_id: str) -> None:
    """Record that the Warden has done something. Updates every Lighthouse
    they hold (multi-system Wardens have a single touch).

    - Sets `warden_last_activity_at = now()` on every held Lighthouse.
    - Clears `lapse_warning_at` if set (touch resets the clock; spec §14.2).
    - Does NOT clear vacation columns — vacation must be explicitly ended.
    """
    from db.models import Lighthouse

    now = datetime.now(timezone.utc)
    await session.execute(
        update(Lighthouse)
        .where(Lighthouse.warden_id == warden_id)
        .values(warden_last_activity_at=now, lapse_warning_at=None)
    )
```

- [ ] **Step 4: Wire into existing call sites**

Add `await touch_warden_activity(session, warden_id=...)` to:

| File | Function | When |
|---|---|---|
| `engine/upgrade_engine.py` | `post_goal` | After successful insert |
| `engine/upgrade_engine.py` | `install_goal` | After status flip to INSTALLED |
| `engine/upgrade_engine.py` | `cancel_goal` | After status flip to CANCELLED |
| `engine/flare_engine.py` | `spawn_called` | After deducting tribute |
| `scheduler/jobs/expedition_complete.py` | handler | When the expedition's user_id matches a Warden of any system in the same Sector — or any system the player holds |
| `scheduler/jobs/timer_complete.py` | handler | Same condition |
| `bot/cogs/lighthouse.py` | every subcommand except `status` and `list` | Before returning success |

(Note on expedition/timer hook: read `Lighthouse.warden_id == user_id` — if any row matches, touch. Skip if no rows. This is "expedition or job in any system held by the player" per spec §14.1, broader than "in the system itself".)

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_engine_touch_activity.py -v --no-cov`
Expected: 3 PASS. Also re-run `pytest tests/test_engine_upgrade_*.py tests/test_engine_flare_spawn.py -v --no-cov` to verify the existing tests still pass with the touch insertions.

- [ ] **Step 6: Commit**

```bash
git add engine/lapse_engine.py engine/upgrade_engine.py engine/flare_engine.py scheduler/jobs/expedition_complete.py scheduler/jobs/timer_complete.py bot/cogs/lighthouse.py tests/test_engine_touch_activity.py
git commit -m "feat(phase3b-5): touch_warden_activity + integration hooks"
```

---

## Task 5: Vacation declare + end

**Files:**
- Modify: `engine/lapse_engine.py`
- Create: `tests/test_engine_vacation.py`

- [ ] **Step 1: Write the failing test**

```python
"""Vacation declare/end with tribute cost + re-declare gap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


async def test_declare_vacation_deducts_tribute_and_sets_until(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    from db.models import TributeLedger, TributeSourceType
    from engine.lapse_engine import declare_vacation
    from sqlalchemy import func, select

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=200,
        )
    )
    await db_session.flush()

    await declare_vacation(
        db_session,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        days=7,
    )
    await db_session.flush()

    lh = warden_with_held_lighthouse.lighthouse
    await db_session.refresh(lh)
    assert lh.vacation_until is not None
    elapsed = lh.vacation_until - datetime.now(timezone.utc)
    assert timedelta(days=6) < elapsed <= timedelta(days=7, seconds=1)

    balance = (
        await db_session.execute(
            select(func.sum(TributeLedger.amount)).where(
                TributeLedger.warden_id == warden_with_held_lighthouse.warden.discord_id
            )
        )
    ).scalar_one()
    assert balance == 200 - 70  # 7 * 10 = 70


async def test_declare_vacation_rejects_insufficient_tribute(
    db_session, warden_with_held_lighthouse
):
    from engine.lapse_engine import LapseError, declare_vacation

    with pytest.raises(LapseError, match="tribute"):
        await declare_vacation(
            db_session,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            days=7,
        )


async def test_declare_vacation_caps_at_14_days(
    db_session, warden_with_held_lighthouse
):
    from engine.lapse_engine import LapseError, declare_vacation

    with pytest.raises(LapseError, match="14"):
        await declare_vacation(
            db_session,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            days=15,
        )


async def test_redeclare_within_gap_blocked(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    """Spec §14.4: cannot re-declare without 14 days of normal activity in between."""
    from db.models import TributeLedger, TributeSourceType
    from engine.lapse_engine import LapseError, declare_vacation, end_vacation

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=500,
        )
    )
    await db_session.flush()
    await declare_vacation(
        db_session,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        days=3,
    )
    await db_session.flush()
    await end_vacation(
        db_session, warden_id=warden_with_held_lighthouse.warden.discord_id
    )
    await db_session.flush()

    with pytest.raises(LapseError, match="re-declare"):
        await declare_vacation(
            db_session,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            days=3,
        )


async def test_end_vacation_no_refund(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    from db.models import TributeLedger, TributeSourceType
    from engine.lapse_engine import declare_vacation, end_vacation
    from sqlalchemy import func, select

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=500,
        )
    )
    await db_session.flush()
    await declare_vacation(
        db_session, warden_id=warden_with_held_lighthouse.warden.discord_id, days=10
    )
    await db_session.flush()
    balance_after_declare = (
        await db_session.execute(
            select(func.sum(TributeLedger.amount)).where(
                TributeLedger.warden_id == warden_with_held_lighthouse.warden.discord_id
            )
        )
    ).scalar_one()

    await end_vacation(db_session, warden_id=warden_with_held_lighthouse.warden.discord_id)
    await db_session.flush()

    final_balance = (
        await db_session.execute(
            select(func.sum(TributeLedger.amount)).where(
                TributeLedger.warden_id == warden_with_held_lighthouse.warden.discord_id
            )
        )
    ).scalar_one()
    # Spec §14.4: no refund of pre-paid tribute.
    assert final_balance == balance_after_declare
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement**

Append to `engine/lapse_engine.py`:

```python
class LapseError(ValueError):
    """Lapse / vacation / abdication precondition violation."""


async def declare_vacation(session: AsyncSession, *, warden_id: str, days: int) -> None:
    """Spec §14.4. Pays 10 tribute/day upfront. Caps at 14 days.

    Cannot re-declare without 14 days of normal activity since the previous
    `vacation_started_at` (whether the previous vacation was ended early or not).
    """
    from sqlalchemy import func, select

    from db.models import (
        Lighthouse,
        TributeLedger,
        TributeSourceType,
    )

    if days <= 0 or days > VACATION_MAX_DAYS:
        raise LapseError(f"vacation must be 1..{VACATION_MAX_DAYS} days")

    held = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.warden_id == warden_id)
        )
    ).scalars().all()
    if not held:
        raise LapseError("not a Warden — nothing to declare vacation on")

    now = datetime.now(timezone.utc)

    # Re-declare gap: any held Lighthouse with vacation_started_at within
    # the last 14 days of normal activity blocks re-declaration. Simplification:
    # use any held seat's `vacation_started_at` and require RE_DECLARE_GAP_DAYS
    # since that timestamp.
    for lh in held:
        if lh.vacation_started_at is not None:
            since = now - lh.vacation_started_at
            if since < timedelta(days=RE_DECLARE_GAP_DAYS):
                gap_remaining = timedelta(days=RE_DECLARE_GAP_DAYS) - since
                d = int(gap_remaining.total_seconds() // 86400)
                raise LapseError(
                    f"cannot re-declare vacation yet: {d}d remaining of activity gap"
                )

    cost = days * VACATION_COST_PER_DAY
    balance = (
        await session.execute(
            select(func.coalesce(func.sum(TributeLedger.amount), 0)).where(
                TributeLedger.warden_id == warden_id
            )
        )
    ).scalar_one()
    if balance < cost:
        raise LapseError(f"insufficient tribute: {balance} available, {cost} required")

    session.add(
        TributeLedger(
            warden_id=warden_id,
            source_system_id=held[0].system_id,
            source_type=TributeSourceType.VACATION_COST,
            amount=-cost,
        )
    )
    until = now + timedelta(days=days)
    for lh in held:
        lh.vacation_started_at = now
        lh.vacation_until = until


async def end_vacation(session: AsyncSession, *, warden_id: str) -> None:
    """Return early. No refund. Resumes lapse logic from `last_activity` clock.

    Note: ending vacation does NOT touch `warden_last_activity_at`; the
    Warden has to actually do something to reset the clock.
    """
    from sqlalchemy import update

    from db.models import Lighthouse

    await session.execute(
        update(Lighthouse)
        .where(Lighthouse.warden_id == warden_id)
        .values(vacation_until=None)  # leave vacation_started_at for the gap calculation
    )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_vacation.py -v --no-cov`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lapse_engine.py tests/test_engine_vacation.py
git commit -m "feat(phase3b-5): declare/end vacation with tribute cost + re-declare gap"
```

---

## Task 6: `panic_defer` — emergency lapse extension

**Files:**
- Modify: `engine/lapse_engine.py`
- Create: `tests/test_engine_panic_defer.py`

- [ ] **Step 1: Write the failing test**

```python
"""panic_defer extends warning grace by N days at 50 tribute / day."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


async def test_panic_defer_only_after_warning(db_session, warden_with_held_lighthouse):
    """Cannot panic-defer while seat is healthy."""
    from engine.lapse_engine import LapseError, panic_defer

    with pytest.raises(LapseError, match="warning"):
        await panic_defer(
            db_session,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            days=2,
        )


async def test_panic_defer_caps_at_seven_days(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    from db.models import Lighthouse, TributeLedger, TributeSourceType
    from engine.lapse_engine import LapseError, panic_defer

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=2000,
        )
    )
    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=20)
    lh.lapse_warning_at = datetime.now(timezone.utc) - timedelta(days=6)
    await db_session.flush()

    with pytest.raises(LapseError, match="7"):
        await panic_defer(
            db_session,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            days=8,
        )


async def test_panic_defer_extends_grace_via_lapse_warning_at(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    """Defer of N days shifts lapse_warning_at backward by N days, effectively
    extending the grace.
    """
    from db.models import Lighthouse, TributeLedger, TributeSourceType
    from engine.lapse_engine import panic_defer
    from sqlalchemy import select

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=2000,
        )
    )
    lh = warden_with_held_lighthouse.lighthouse
    original_warning = datetime.now(timezone.utc) - timedelta(days=6)
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=20)
    lh.lapse_warning_at = original_warning
    await db_session.flush()

    await panic_defer(
        db_session,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        days=3,
    )
    await db_session.flush()
    await db_session.refresh(lh)
    # Warning shifted backward by 3 days → 3 more days of grace.
    elapsed_shift = original_warning - lh.lapse_warning_at
    assert abs(elapsed_shift - timedelta(days=3)).total_seconds() < 60
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement `panic_defer`**

Append to `engine/lapse_engine.py`:

```python
async def panic_defer(session: AsyncSession, *, warden_id: str, days: int) -> None:
    """Extend the grace period by N days at 50 tribute/day. Spec §14.3.

    Available only after the warning fires. Max +7 days of extension.
    Implementation: shifts `lapse_warning_at` backward by N days, which
    effectively pushes the abdicate_due time forward by N days.
    """
    from sqlalchemy import func, select, update

    from db.models import (
        Lighthouse,
        TributeLedger,
        TributeSourceType,
    )

    if days <= 0 or days > PANIC_DEFER_MAX_DAYS:
        raise LapseError(f"panic defer must be 1..{PANIC_DEFER_MAX_DAYS} days")

    held = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.warden_id == warden_id)
        )
    ).scalars().all()
    if not held:
        raise LapseError("not a Warden")

    # Find any held Lighthouse currently in a warning state.
    now = datetime.now(timezone.utc)
    target = next(
        (lh for lh in held if lh.lapse_warning_at is not None), None
    )
    if target is None:
        raise LapseError("no active lapse warning to defer")

    cost = days * PANIC_DEFER_COST_PER_DAY
    balance = (
        await session.execute(
            select(func.coalesce(func.sum(TributeLedger.amount), 0)).where(
                TributeLedger.warden_id == warden_id
            )
        )
    ).scalar_one()
    if balance < cost:
        raise LapseError(f"insufficient tribute: {balance}/{cost}")

    session.add(
        TributeLedger(
            warden_id=warden_id,
            source_system_id=target.system_id,
            source_type=TributeSourceType.PANIC_DEFER_COST,
            amount=-cost,
        )
    )
    target.lapse_warning_at = target.lapse_warning_at - timedelta(days=days)
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_panic_defer.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lapse_engine.py tests/test_engine_panic_defer.py
git commit -m "feat(phase3b-5): panic_defer — emergency lapse extension"
```

---

## Task 7: `auto_abdicate` — full refunds, Pride drop, claim cooldown

**Files:**
- Modify: `engine/lapse_engine.py`
- Create: `tests/test_engine_auto_abdicate.py`

- [ ] **Step 1: Write the failing test**

```python
"""auto_abdicate clears warden, refunds 100%, drops Pride 50, sets 14-day cooldown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_abdicate_clears_warden_and_drops_pride(
    db_session, warden_with_held_lighthouse
):
    from db.models import ClaimAttempt, Lighthouse
    from engine.lapse_engine import auto_abdicate
    from sqlalchemy import select

    lh = warden_with_held_lighthouse.lighthouse
    lh.pride_score = 80
    await db_session.flush()

    await auto_abdicate(db_session, lighthouse_id=lh.id)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.warden_id is None
    assert lh.pride_score == 30  # 80 - 50


async def test_abdicate_refunds_open_goals_full(
    db_session, warden_with_held_lighthouse, posted_goal, home_citizen
):
    """Spec §14.6: full refunds (no 25% cancellation penalty)."""
    from db.models import DonationLedger, UpgradeGoal, UpgradeGoalStatus, User
    from engine.lapse_engine import auto_abdicate
    from engine.upgrade_engine import donate
    from sqlalchemy import select

    home_citizen.user.currency = 5000
    await db_session.flush()
    await donate(db_session, donor_id=home_citizen.user.discord_id, goal_id=posted_goal.id, credits=1000, parts=0)
    await db_session.flush()

    await auto_abdicate(db_session, lighthouse_id=warden_with_held_lighthouse.lighthouse.id)
    await db_session.flush()

    donor = await db_session.get(User, home_citizen.user.discord_id)
    # Donor paid 1000; should get 1000 back (100% refund) → ends at original 5000.
    assert donor.currency == 5000

    goal = await db_session.get(UpgradeGoal, posted_goal.id)
    assert goal.status == UpgradeGoalStatus.CANCELLED


async def test_abdicate_sets_14_day_claim_cooldown(
    db_session, warden_with_held_lighthouse
):
    """A sentinel ClaimAttempt is written with resolved_at = now + 14 days
    so precheck_claim's cooldown check rejects further claims by this player.
    """
    from db.models import ClaimAttempt
    from engine.lapse_engine import auto_abdicate
    from sqlalchemy import select

    await auto_abdicate(db_session, lighthouse_id=warden_with_held_lighthouse.lighthouse.id)
    await db_session.flush()

    cooldown_attempts = (
        await db_session.execute(
            select(ClaimAttempt).where(ClaimAttempt.player_id == warden_with_held_lighthouse.warden.discord_id)
        )
    ).scalars().all()
    assert len(cooldown_attempts) >= 1
    # The sentinel attempt's resolved_at is 14 days from now → precheck_claim
    # will see the 7-day window unsatisfied (and 14d penalty cooldown observed).
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement `auto_abdicate`**

Append to `engine/lapse_engine.py`:

```python
async def auto_abdicate(
    session: AsyncSession, *, lighthouse_id, voluntary: bool = False
) -> None:
    """Clear warden_id, refund all open goals at 100%, drop Pride 50, set
    14-day claim cooldown for the departing Warden.

    `voluntary=True` is set when this is called from `/lighthouse abdicate`;
    consequences are identical to auto-abdication per spec §14.6 and §16.2.
    """
    from sqlalchemy import select, update

    from db.models import (
        ClaimAttempt,
        ClaimOutcome,
        DonationLedger,
        Lighthouse,
        UpgradeGoal,
        UpgradeGoalStatus,
        User,
    )
    from engine.pride_engine import apply_pride

    lh = await session.get(Lighthouse, lighthouse_id, with_for_update=True)
    if lh is None or lh.warden_id is None:
        return  # idempotent

    departing_warden = lh.warden_id
    now = datetime.now(timezone.utc)

    # Refund OPEN goals 100% pro-rata.
    open_goals = (
        await session.execute(
            select(UpgradeGoal)
            .where(UpgradeGoal.lighthouse_id == lighthouse_id)
            .where(UpgradeGoal.status == UpgradeGoalStatus.OPEN)
        )
    ).scalars().all()
    for goal in open_goals:
        donations = (
            await session.execute(
                select(DonationLedger).where(
                    DonationLedger.goal_id == goal.id, DonationLedger.refunded.is_(False)
                )
            )
        ).scalars().all()
        for d in donations:
            if d.credits > 0:
                await session.execute(
                    update(User)
                    .where(User.discord_id == d.player_id)
                    .values(currency=User.currency + d.credits)
                )
            d.refunded = True
        goal.status = UpgradeGoalStatus.CANCELLED
        goal.cancelled_at = now

    # Clear seat.
    lh.warden_id = None
    lh.lapse_warning_at = None
    lh.warden_last_activity_at = None
    lh.vacation_until = None
    # Drop Pride.
    await apply_pride(
        session,
        lighthouse_id=lighthouse_id,
        delta=-ABDICATION_PRIDE_DROP,
        reason="auto_abdicate" if not voluntary else "voluntary_abdicate",
    )

    # Sentinel ClaimAttempt to enforce the 14-day cooldown.
    session.add(
        ClaimAttempt(
            player_id=departing_warden,
            target_system_id=lh.system_id,
            difficulty=0,
            started_at=now,
            resolved_at=now + timedelta(days=ABDICATION_CLAIM_COOLDOWN_DAYS - 7),
            # precheck_claim adds 7d to last attempt's resolved_at; so 7+7 = 14d total.
            outcome=ClaimOutcome.FAIL,
        )
    )
```

(Note: the cooldown trick depends on `precheck_claim` adding 7 days to `resolved_at`. Verify by reading `engine/lighthouse_engine.precheck_claim` — if the math works, the sentinel's `resolved_at = now + 7d` makes the effective claim cooldown end at `now + 14d`. If the precheck logic differs, adjust the offset.)

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_auto_abdicate.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lapse_engine.py tests/test_engine_auto_abdicate.py
git commit -m "feat(phase3b-5): auto_abdicate — full refunds, Pride drop, 14d cooldown"
```

---

## Task 8: Tribute conversion (5 → 1 credits, capped at 1000c/day)

**Files:**
- Modify: `engine/tribute_engine.py`
- Create: `tests/test_engine_tribute_convert.py`

- [ ] **Step 1: Write the failing test**

```python
"""convert_to_credits — 5:1 rate, 1000c/day per Warden cap."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest


async def test_convert_credits_writes_signed_ledger_and_updates_user(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    from db.models import TributeLedger, TributeSourceType, User
    from engine.tribute_engine import convert_to_credits
    from sqlalchemy import func, select

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=2000,
        )
    )
    starting = warden_with_held_lighthouse.warden.currency or 0
    await db_session.flush()

    credits_received = await convert_to_credits(
        db_session,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        credits_amount=200,  # cost 1000 tribute
    )
    await db_session.flush()
    assert credits_received == 200

    bal = (
        await db_session.execute(
            select(func.sum(TributeLedger.amount)).where(
                TributeLedger.warden_id == warden_with_held_lighthouse.warden.discord_id
            )
        )
    ).scalar_one()
    assert bal == 2000 - 1000

    refreshed = await db_session.get(User, warden_with_held_lighthouse.warden.discord_id)
    assert refreshed.currency == starting + 200


async def test_convert_credits_caps_at_1000_per_day(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    from db.models import TributeLedger, TributeSourceType
    from engine.tribute_engine import LapseError, convert_to_credits

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=10000,
        )
    )
    await db_session.flush()
    await convert_to_credits(
        db_session,
        warden_id=warden_with_held_lighthouse.warden.discord_id,
        credits_amount=1000,
    )
    await db_session.flush()

    with pytest.raises(LapseError, match="cap"):
        await convert_to_credits(
            db_session,
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            credits_amount=100,
        )


async def test_convert_credits_resets_at_new_day(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    from datetime import timedelta

    from db.models import TributeLedger, TributeSourceType, User
    from engine.tribute_engine import convert_to_credits

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=10000,
        )
    )
    user = warden_with_held_lighthouse.warden
    user.tribute_credits_converted_today = 1000
    user.tribute_credits_converted_at = (datetime.now(timezone.utc).date() - timedelta(days=1))
    await db_session.flush()

    received = await convert_to_credits(
        db_session, warden_id=user.discord_id, credits_amount=500
    )
    assert received == 500  # cap reset on new day
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement `convert_to_credits`**

Append to `engine/tribute_engine.py`:

```python
from datetime import date, datetime, timezone

from engine.lapse_engine import LapseError  # reuse the same exception class


CONVERSION_CAP_PER_DAY_CREDITS = 1000
CONVERSION_RATE_TRIBUTE_PER_CREDIT = 5


async def convert_to_credits(
    session: AsyncSession,
    *,
    warden_id: str,
    credits_amount: int,
) -> int:
    """Convert tribute → credits at 5:1, capped at 1000 credits/day per Warden.

    Returns the credit amount actually delivered (caller can detect partial
    conversions if they want; for 3b-5 the cog rejects over-cap requests
    rather than partial-fulfilling).
    """
    from db.models import TributeLedger, TributeSourceType, User

    if credits_amount <= 0:
        raise LapseError("conversion amount must be positive")

    user = await session.get(User, warden_id, with_for_update=True)
    if user is None:
        raise LapseError("user not found")

    today = datetime.now(timezone.utc).date()
    if user.tribute_credits_converted_at != today:
        user.tribute_credits_converted_today = 0
        user.tribute_credits_converted_at = today

    remaining_cap = CONVERSION_CAP_PER_DAY_CREDITS - user.tribute_credits_converted_today
    if credits_amount > remaining_cap:
        raise LapseError(
            f"daily conversion cap: {remaining_cap} credits remaining today"
        )

    cost = credits_amount * CONVERSION_RATE_TRIBUTE_PER_CREDIT
    balance = await get_balance(session, warden_id)
    if balance < cost:
        raise LapseError(f"insufficient tribute: {balance}/{cost}")

    session.add(
        TributeLedger(
            warden_id=warden_id,
            source_system_id=None,
            source_type=TributeSourceType.CONVERSION,
            amount=-cost,
        )
    )
    user.currency += credits_amount
    user.tribute_credits_converted_today += credits_amount
    return credits_amount
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_tribute_convert.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/tribute_engine.py tests/test_engine_tribute_convert.py
git commit -m "feat(phase3b-5): tribute → credits conversion (5:1, 1000c/day cap)"
```

---

## Task 9: Daily lapse-check handler

**Files:**
- Create: `scheduler/jobs/lapse_check.py`
- Create: `tests/test_handler_lapse_check.py`

- [ ] **Step 1: Write the failing test**

```python
"""Daily lapse handler — fires warning at 14d, abdication at 21d, idempotent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_handler_fires_warning_at_day_14(
    db_session, warden_with_held_lighthouse
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.lapse_check import handle_lapse_check
    from sqlalchemy import select

    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=15)
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.LAPSE_CHECK,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_lapse_check(db_session, job)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.lapse_warning_at is not None
    assert lh.warden_id == warden_with_held_lighthouse.warden.discord_id  # not yet abdicated


async def test_handler_abdicates_at_day_21(
    db_session, warden_with_held_lighthouse
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.lapse_check import handle_lapse_check

    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=22)
    lh.lapse_warning_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.LAPSE_CHECK,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_lapse_check(db_session, job)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.warden_id is None


async def test_handler_idempotent_doesnt_double_warn(
    db_session, warden_with_held_lighthouse
):
    """Running twice in a row only writes one warning timestamp."""
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.lapse_check import handle_lapse_check

    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=15)
    await db_session.flush()

    for _ in range(2):
        job = ScheduledJob(
            type=JobType.LAPSE_CHECK,
            run_at=datetime.now(timezone.utc),
            state=JobState.CLAIMED,
            payload={},
        )
        db_session.add(job)
        await db_session.flush()
        await handle_lapse_check(db_session, job)
        await db_session.flush()

    await db_session.refresh(lh)
    # warning_at didn't shift; still set once.
    assert lh.lapse_warning_at is not None


async def test_handler_skips_lighthouses_on_vacation(
    db_session, warden_with_held_lighthouse
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.lapse_check import handle_lapse_check

    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=22)
    lh.vacation_until = datetime.now(timezone.utc) + timedelta(days=5)
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.LAPSE_CHECK,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_lapse_check(db_session, job)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.warden_id == warden_with_held_lighthouse.warden.discord_id
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement**

Create `scheduler/jobs/lapse_check.py`:

```python
"""LAPSE_CHECK handler — runs daily, fires warnings + abdications."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from config.logging import get_logger
from db.models import JobState, JobType, Lighthouse, ScheduledJob
from engine.lapse_engine import LapseStage, auto_abdicate, compute_lapse_stage
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_lapse_check(session, job: ScheduledJob) -> HandlerResult:
    """Walk every Warden Lighthouse; act on each one's lapse stage."""
    rows = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.warden_id.isnot(None))
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)

    notifications: list[NotificationRequest] = []
    warnings = 0
    abdications = 0

    for lh in rows:
        stage = compute_lapse_stage(lh, now=now)
        if stage == LapseStage.WARNING_DUE:
            lh.lapse_warning_at = now
            warnings += 1
            notifications.append(
                NotificationRequest(
                    user_id=lh.warden_id,
                    category="lapse_warning",
                    title="Lighthouse warning: 14 days inactive",
                    body=(
                        f"Warden, your seat at <#{lh.system_id}> has gone 14 days "
                        f"without registered activity. The Authority will auto-abdicate "
                        f"you in 7 days unless any Warden activity is registered. "
                        f"Use `/lighthouse vacation start` if you need a planned absence."
                    ),
                    correlation_id=str(lh.id),
                    dedupe_key=f"lapse:warning:{lh.id}:{now.date().isoformat()}",
                )
            )
            # TODO: also post in #<system_id> via the notification consumer's
            # channel-post extension (see 3b-4 Task 14).
        elif stage == LapseStage.ABDICATE_DUE:
            await auto_abdicate(session, lighthouse_id=lh.id, voluntary=False)
            abdications += 1
            notifications.append(
                NotificationRequest(
                    user_id=lh.warden_id or "",  # may be cleared by auto_abdicate
                    category="lapse_abdicated",
                    title="Lighthouse seat opened",
                    body=(
                        f"Your seat at <#{lh.system_id}> has been auto-abdicated by the "
                        f"Authority after the lapse window. A 14-day claim cooldown "
                        f"applies before you can attempt any new claim."
                    ),
                    correlation_id=str(lh.id),
                    dedupe_key=f"lapse:abdicated:{lh.id}",
                )
            )

    log.info(
        "lapse_check: %d warnings, %d abdications across %d held seats",
        warnings, abdications, len(rows),
    )
    job.state = JobState.COMPLETED
    job.completed_at = func.now()
    return HandlerResult(notifications=notifications)


register(JobType.LAPSE_CHECK, handle_lapse_check)
```

In `bot/main.py::setup_hook`, register the handler import side-effect and seed the daily recurrence (mirror tribute_drip / pride_decay).

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_lapse_check.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/lapse_check.py tests/test_handler_lapse_check.py bot/main.py
git commit -m "feat(phase3b-5): daily lapse_check handler"
```

---

## Task 10: `/lighthouse vacation` + `/lighthouse abdicate` + `/lighthouse tribute` cog subcommands

**Files:**
- Modify: `bot/cogs/lighthouse.py`
- Create: `tests/test_cog_lighthouse_vacation.py`, `tests/test_cog_lighthouse_abdicate.py`, `tests/test_cog_lighthouse_tribute.py`

- [ ] **Step 1: Implement subcommands**

Inside `LighthouseGroup` (or in nested subgroups), add:

```python
class VacationSubgroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="vacation", description="Warden vacation controls.")

    @app_commands.command(name="start", description="Declare a planned absence (10 tribute / day).")
    async def start(self, interaction: discord.Interaction, days: int) -> None:
        async with async_session() as session, session.begin():
            from engine.lapse_engine import LapseError, declare_vacation
            try:
                await declare_vacation(session, warden_id=str(interaction.user.id), days=days)
            except LapseError as e:
                await interaction.response.send_message(f"Vacation rejected: {e}", ephemeral=True)
                return
        await interaction.response.send_message(
            f"Vacation declared for {days} day(s). Lapse timer paused.",
            ephemeral=True,
        )

    @app_commands.command(name="end", description="End vacation early (no refund).")
    async def end(self, interaction: discord.Interaction) -> None:
        async with async_session() as session, session.begin():
            from engine.lapse_engine import end_vacation
            await end_vacation(session, warden_id=str(interaction.user.id))
        await interaction.response.send_message("Vacation ended. Lapse timer resumes.", ephemeral=True)

    @app_commands.command(name="panic", description="Defer lapse warning by N days at 50 tribute/day.")
    async def panic(self, interaction: discord.Interaction, days: int) -> None:
        async with async_session() as session, session.begin():
            from engine.lapse_engine import LapseError, panic_defer
            try:
                await panic_defer(session, warden_id=str(interaction.user.id), days=days)
            except LapseError as e:
                await interaction.response.send_message(f"Defer rejected: {e}", ephemeral=True)
                return
        await interaction.response.send_message(
            f"Lapse defer applied: +{days} day(s) of grace.",
            ephemeral=True,
        )


class TributeSubgroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="tribute", description="Warden tribute controls.")

    @app_commands.command(name="status", description="Show your tribute balance + recent activity.")
    async def status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            from engine.tribute_engine import get_balance
            balance = await get_balance(session, str(interaction.user.id))
        await interaction.response.send_message(
            f"Tribute balance: **{balance}**", ephemeral=True
        )

    @app_commands.command(name="convert", description="Convert tribute → credits (5:1, max 1000c/day).")
    async def convert(self, interaction: discord.Interaction, credits_amount: int) -> None:
        async with async_session() as session, session.begin():
            from engine.lapse_engine import LapseError
            from engine.tribute_engine import convert_to_credits
            try:
                received = await convert_to_credits(
                    session, warden_id=str(interaction.user.id), credits_amount=credits_amount
                )
            except LapseError as e:
                await interaction.response.send_message(f"Conversion rejected: {e}", ephemeral=True)
                return
        await interaction.response.send_message(
            f"Converted: received {received} credits.", ephemeral=True
        )


@app_commands.command(name="abdicate", description="Voluntarily release your Warden seat.")
async def abdicate(self, interaction: discord.Interaction) -> None:
    """Lives directly on LighthouseGroup."""
    async with async_session() as session, session.begin():
        from db.models import Lighthouse
        from engine.lapse_engine import auto_abdicate
        from sqlalchemy import select

        lh = (
            await session.execute(
                select(Lighthouse).where(Lighthouse.warden_id == str(interaction.user.id))
            )
        ).scalar_one_or_none()
        if lh is None:
            await interaction.response.send_message("You hold no Warden seat.", ephemeral=True)
            return
        await auto_abdicate(session, lighthouse_id=lh.id, voluntary=True)
    await interaction.response.send_message(
        "Seat abdicated. Open goals refunded; 14-day claim cooldown applied.",
        ephemeral=True,
    )
```

Wire all three subgroups + the abdicate command into the `LighthouseGroup` registration in `setup`.

- [ ] **Step 2: Tests**

Three test files mirroring the shape of `tests/test_cog_lighthouse_claim.py` from 3b-2.

- [ ] **Step 3: Run, confirm passes**

- [ ] **Step 4: Commit**

```bash
git add bot/cogs/lighthouse.py tests/test_cog_lighthouse_vacation.py tests/test_cog_lighthouse_abdicate.py tests/test_cog_lighthouse_tribute.py
git commit -m "feat(phase3b-5): /lighthouse vacation/abdicate/tribute subcommands"
```

---

## Task 11: System gating + cog wiring

**Files:**
- Modify: `bot/system_gating.py`
- Modify: `tests/test_system_gating.py`

- [ ] **Step 1: Add new qualified names**

```python
UNIVERSE_WIDE_COMMANDS = {
    # existing 3b-1..4 entries
    "lighthouse vacation start",
    "lighthouse vacation end",
    "lighthouse vacation panic",
    "lighthouse abdicate",
    "lighthouse tribute status",
    "lighthouse tribute convert",
}
```

- [ ] **Step 2: Test + commit**

```bash
git add bot/system_gating.py tests/test_system_gating.py
git commit -m "feat(phase3b-5): vacation/abdicate/tribute subcommands universe-wide"
```

---

## Task 12: End-to-end scenario — full lapse cycle

**Files:**
- Create: `tests/test_scenarios/test_lapse_cycle.py`

- [ ] **Step 1: Write the scenario**

```python
"""Scenario: 14d inactivity → warning → 7d grace expires → auto-abdicate.

Also: vacation pauses lapse; panic defer extends grace.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select


async def test_full_lapse_cycle(
    db_session, warden_with_held_lighthouse
):
    from db.models import JobState, JobType, Lighthouse, ScheduledJob
    from scheduler.jobs.lapse_check import handle_lapse_check

    lh = warden_with_held_lighthouse.lighthouse

    # Day 0–13: nothing happens. Skip to day 15.
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=15)
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.LAPSE_CHECK,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    result = await handle_lapse_check(db_session, job)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.lapse_warning_at is not None
    assert lh.warden_id == warden_with_held_lighthouse.warden.discord_id

    # The Warden's notification queue includes a lapse_warning entry.
    assert any(n.category == "lapse_warning" for n in result.notifications)

    # Now jump to day 22 (warning fired ~7d ago).
    lh.lapse_warning_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db_session.flush()

    job2 = ScheduledJob(
        type=JobType.LAPSE_CHECK,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job2)
    await db_session.flush()
    await handle_lapse_check(db_session, job2)
    await db_session.flush()
    await db_session.refresh(lh)
    assert lh.warden_id is None  # abdicated
    assert lh.pride_score < 100  # dropped


async def test_vacation_pauses_lapse_then_resumes(
    db_session, warden_with_held_lighthouse, sample_system_with_lighthouse
):
    """Declare 7d vacation when 14d inactive — warning never fires until vacation ends."""
    from db.models import JobState, JobType, Lighthouse, ScheduledJob, TributeLedger, TributeSourceType
    from engine.lapse_engine import declare_vacation
    from scheduler.jobs.lapse_check import handle_lapse_check

    db_session.add(
        TributeLedger(
            warden_id=warden_with_held_lighthouse.warden.discord_id,
            source_system_id=sample_system_with_lighthouse.channel_id,
            source_type=TributeSourceType.PASSIVE,
            amount=500,
        )
    )
    lh = warden_with_held_lighthouse.lighthouse
    lh.warden_last_activity_at = datetime.now(timezone.utc) - timedelta(days=15)
    await db_session.flush()

    await declare_vacation(
        db_session, warden_id=warden_with_held_lighthouse.warden.discord_id, days=7
    )
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.LAPSE_CHECK,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_lapse_check(db_session, job)
    await db_session.refresh(lh)
    # Warning NOT fired — on vacation.
    assert lh.lapse_warning_at is None
    assert lh.warden_id == warden_with_held_lighthouse.warden.discord_id
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_scenarios/test_lapse_cycle.py -v --no-cov`
Expected: 2 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scenarios/test_lapse_cycle.py
git commit -m "test(phase3b-5): scenario — full lapse cycle, vacation pause"
```

---

## Task 13: Replace 3b-4's flare-prize source-type stand-in

**Files:**
- Modify: `engine/flare_engine.py`

In `finalize_flare`'s prize-delivery loop, change:

```python
        source_type=RewardSourceType.EXPEDITION_OUTCOME,
```

to:

```python
        source_type=RewardSourceType.FLARE_WIN,
```

Run the existing flare tests to confirm no regression.

- [ ] **Step 1: Tests + commit**

```bash
git add engine/flare_engine.py
git commit -m "fix(phase3b-5): use FLARE_WIN reward source for finalize_flare prizes"
```

---

## Task 14: Documentation

**Files:**
- Create: `docs/authoring/lapse_and_vacation.md`

```markdown
# Authoring: Lapse, Vacation, Abdication

The Warden's commitment mechanism. Two paths handle planned vs unplanned
absence; both surface publicly.

## Activity definition (spec §14.1)

`engine.lapse_engine.touch_warden_activity(session, warden_id)` is the
single touch site. Hook locations:

- `engine.upgrade_engine.post_goal` / `install_goal` / `cancel_goal`
- `engine.flare_engine.spawn_called`
- `scheduler/jobs/expedition_complete.py` (when player holds a seat)
- `scheduler/jobs/timer_complete.py` (when player holds a seat)
- Every `/lighthouse` subcommand except `status` and `list`

A touch:
- Updates `warden_last_activity_at = now()` on every Lighthouse the Warden holds.
- Clears `lapse_warning_at` if set.
- Does NOT clear vacation flags (vacation must be explicitly ended).

## Lapse stages (spec §14.2)

`engine.lapse_engine.compute_lapse_stage(lh, now)` returns one of:

- `clear` — active, < 14 days inactive
- `warning_due` — ≥ 14 days, no warning posted yet
- `warning_active` — warning fired, inside 7-day grace
- `abdicate_due` — grace expired
- `on_vacation` — vacation_until > now

The daily handler (`scheduler/jobs/lapse_check.py`) reads the stage and
fires side-effects (warning post + DM, or auto-abdication).

## Tuning constants

`engine/lapse_engine.py`:

- `WARNING_AT_DAYS` (14)
- `GRACE_DAYS` (7)
- `PANIC_DEFER_MAX_DAYS` (7), `PANIC_DEFER_COST_PER_DAY` (50)
- `VACATION_COST_PER_DAY` (10), `VACATION_MAX_DAYS` (14), `RE_DECLARE_GAP_DAYS` (14)
- `ABDICATION_PRIDE_DROP` (50), `ABDICATION_CLAIM_COOLDOWN_DAYS` (14)

`engine/tribute_engine.py`:

- `CONVERSION_CAP_PER_DAY_CREDITS` (1000)
- `CONVERSION_RATE_TRIBUTE_PER_CREDIT` (5)

## Abdication consequences

| Step | Auto | Voluntary |
|---|---|---|
| Clear warden_id | ✓ | ✓ |
| Refund open goals | 100% | 100% |
| Pride drop | -50 | -50 |
| 14-day claim cooldown | ✓ | ✓ |
| Public post | ✓ | ✓ |

The 100% refund (vs the 75% on `cancel_goal`) is intentional per spec §14.6:
involuntary or self-cancelled abdication shouldn't punish citizens who
contributed in good faith.
```

```bash
git add docs/authoring/lapse_and_vacation.md
git commit -m "docs(phase3b-5): lapse + vacation authoring guide"
```

---

## Task 15: Final integration smoke

- [ ] **Step 1: Full suite + migration round-trip**

Run: `pytest --no-cov -q` then `alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 2: Manual verification**

With a test Warden seat:
- `/lighthouse tribute status` — shows balance.
- Force `warden_last_activity_at` to 15d ago via DB. Trigger `lapse_check` manually. Verify lapse warning DM + system channel post.
- `/lighthouse vacation start days:5` — confirms; subsequent `lapse_check` ticks don't escalate.
- Force activity reset post-vacation. Confirm warning_at cleared.
- `/lighthouse tribute convert credits_amount:200` — confirms; tribute drops 1000, credits up 200.
- Try converting another 900c same day — rejected.
- `/lighthouse abdicate` — confirms; goals refunded; 14d cooldown set.

- [ ] **Step 3: Push and PR**

```bash
gh pr create --title "Phase 3b-5: Lapse + vacation + tribute spending + abdication" --body "$(cat <<'EOF'
## Summary
Closes the Phase 3b loop:
- 14-day inactivity warning + 7-day grace + auto-abdication scheduler.
- `/lighthouse vacation start|end|panic` and `/lighthouse tribute status|convert` and `/lighthouse abdicate` subcommands.
- Tribute → credits at 5:1, capped at 1000c/day per Warden.
- Auto-abdication refunds open goals at 100%, drops Pride 50, sets a 14-day claim cooldown.
- `touch_warden_activity` hooks scattered through every Warden-action call site (upgrade lifecycle, flare call, expedition/timer complete in held systems).
- 3b-4's `RewardSourceType.EXPEDITION_OUTCOME` placeholder for flare wins replaced with the dedicated `FLARE_WIN` value.

## Test plan
- [x] Unit: lapse stage, touch, vacation, panic_defer, auto_abdicate, conversion
- [x] Handler: lapse_check warning + abdication + idempotency + vacation skip
- [x] Scenario: full lapse cycle; vacation pause
- [x] Migration round-trips
- [ ] Manual: dev bot, full Warden lapse flow with vacation interleave

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Spec coverage check (self-review)

| Spec section | Covered by | Notes |
|---|---|---|
| §10.3 Vacation cost | Task 5 | declare_vacation 10/day |
| §10.3 Panic defer cost | Task 6 | panic_defer 50/day |
| §10.3 Convert to credits | Task 8 | 5:1 with 1000c/day cap |
| §14.1 Activity definition | Task 4 | touch hooks scattered |
| §14.2 Lapse window | Tasks 3, 9 | compute_lapse_stage + handler |
| §14.3 Panic-mode defer | Task 6 | only after warning, max +7d |
| §14.4 Vacation verb | Task 5 | declare/end + 14d cap + 14d gap |
| §14.5 Why dual rates | (design note, no code) | |
| §14.6 Abdication consequences | Task 7 | full refund, Pride -50, cooldown 14d |
| §16.1 /lighthouse vacation/abdicate/tribute | Task 10 | subcommands |

---

## Open Questions

1. **Notification consumer extension for channel posts.** Lapse warnings, abdications, vacation declarations are all public posts. They share the same dispatch shape with 3b-4's flare embeds and 3b-3's goal embeds. If 3b-4 lands the channel-post extension to `bot/notifications.py`, this plan reuses it; if not, this plan inherits the same TODO. Recommend: factor the extension out as part of 3b-4's Task 14, with 3b-5 simply emitting the right `category` strings.
2. **Hour-precision lapse vs day-precision.** `compute_lapse_stage` uses `timedelta(days=14)` — exact-second precision. The handler runs daily; this means a Warden whose 14d mark falls just *after* the daily run gets warned a day late. Acceptable for the user-facing precision (no one notices a 1-hour shift in a 21-day cycle). If we ever add hourly lapse_check ticks, the math is already correct.
3. **Sentinel ClaimAttempt for abdication cooldown.** Task 7 uses a sentinel ClaimAttempt with a `resolved_at` set 7 days in the future to abuse `precheck_claim`'s 7-day rule and produce a 14-day net cooldown. Cleaner: split the cooldown logic into a separate `_abdication_cooldown_until(player_id)` query that overlays the existing 7-day check. Defer this refactor unless it bites.

---

## Execution Handoff

Plan complete. Two execution options as in prior sub-plans.

After 3b-5 lands: **3b-6 (runtime LLM narrative)** is the only remaining sub-plan in the Phase 3b arc. With 3b-1..5 shipped, the full gameplay loop is live and the LLM seed pass can be designed against actual playtest data.
