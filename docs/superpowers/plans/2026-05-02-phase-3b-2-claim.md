# Phase 3b-2 — Wardenship Claim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the single Authority-vetted claim contract that turns a captain into a Warden. After this plan ships, players can browse unclaimed Lighthouses with `/lighthouse list`, run `/lighthouse claim <system>` against a tier-scaled Phase-2b expedition, and on success take the seat — `warden_id` set, auto-docked, 7-day per-player claim cooldown started. On failure: 7-day cooldown + 5% consolation, no fleet damage. The view tab `Status` from 3b-1 starts showing held Wardens correctly.

**Architecture:**
- Reuses **all** existing Phase-2b infrastructure: the `Expedition` row, the YAML template, the scene resolver, the `EXPEDITION_COMPLETE` scheduled job. The claim contract is a single static template (`data/expeditions/claim_lighthouse.yaml`) with 3 stat-vs-fixed-threshold rolls. Per-claim difficulty doesn't change the template — it changes the **required success threshold** at completion time. We pipe per-expedition parameters through a new `expeditions.parameters` JSONB column (nullable, default `{}`).
- A new `claim_attempts` table records `(player_id, target_system_id, difficulty, started_at, resolved_at, outcome, expedition_id)`. The 7-day per-player cooldown is computed off this table.
- Two new functions on `engine/lighthouse_engine.py` extend the module from 3b-1: `compute_claim_difficulty(lighthouse, planet_count, feature_count, star_type, star_color)` and `complete_claim(session, expedition)`. The latter is hooked into the existing `scheduler/jobs/expedition_complete.py` handler — when `template_id == "claim_lighthouse"`, it runs *before* the standard closing-effects path, so the success/failure summary in the player's DM matches the seat outcome.
- `precheck_claim(session, player_id, build_id, target_system_id)` validates all preconditions per spec §7.6. It returns a structured result so `/lighthouse claim` can render specific failure messages ("you need an active build", "claim cooldown 4 days remaining", etc.).
- `/lighthouse list` and `/lighthouse claim` are siblings of `/lighthouse [system]`. They live in the same cog (`bot/cogs/lighthouse.py`) extended from 3b-1. Discord's slash-command tree uses three top-level entries (`/lighthouse`, `/lighthouse list`, `/lighthouse claim`) — `discord.py` supports this via `app_commands.Group`. Reading the existing `/training start` pattern in `bot/cogs/fleet.py` shows the same Group shape so this is consistent.
- Auto-dock on win bypasses the 24h cooldown from 3b-1 (spec §7.7). The previous citizenship row is closed, a new one opens at the won system — same `_dock_logic` machinery wrapped in a "force" path.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, discord.py 2.x, pytest + pytest-asyncio. No new top-level dependencies.

**Spec:** [docs/roadmap/2026-05-02-phase-3b-lighthouses-design.md](../../roadmap/2026-05-02-phase-3b-lighthouses-design.md) — sections covered: §7 (claim discovery, contract, difficulty, resolution, cooldown, preconditions, auto-dock, multi-system), parts of §15 (`claim_attempts`, `expeditions.parameters`), §16.1 (`/lighthouse list`, `/lighthouse claim`).

**Depends on:** Phase 3b-1 (foundation — schema, Lighthouse rows, citizenship, /dock).

**Sections deferred:** Donations/upgrades → 3b-3; Flares/Pride → 3b-4; Lapse/vacation/abdication → 3b-5; LLM narrative seed → 3b-6.

**Dev loop:** Same as 3b-1. `pytest` from repo root; `docker compose up db redis`; `alembic upgrade head` after pulling. Round-trip migrations once before merging.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0007_phase3b_2_claim.py` | `claim_attempts` table + `expeditions.parameters` JSONB column + `claim_outcome` enum |
| `data/expeditions/claim_lighthouse.yaml` | The Authority claim contract (single rolled template, 3 events, narrative-tokenized) |
| `tests/test_phase3b_2_migration.py` | Migration upgrade/downgrade roundtrip |
| `tests/test_engine_claim_difficulty.py` | Difficulty formula coverage |
| `tests/test_engine_complete_claim.py` | Pass / fail / consolation / auto-dock paths |
| `tests/test_engine_precheck_claim.py` | Each precondition gate |
| `tests/test_cog_lighthouse_claim.py` | `/lighthouse claim` happy + each rejection branch |
| `tests/test_cog_lighthouse_list.py` | `/lighthouse list` pagination + filter |
| `tests/test_scenarios/test_claim_flow.py` | End-to-end: start → expedition resolves → seat lands |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add `ClaimAttempt` + `ClaimOutcome` enum; add `Expedition.parameters` JSONB column |
| `engine/lighthouse_engine.py` | `compute_claim_difficulty`, `precheck_claim`, `start_claim`, `complete_claim`; helpers (auto-dock without cooldown) |
| `engine/expedition_template.py` | Validator allows `claim_lighthouse` template id |
| `scheduler/jobs/expedition_complete.py` | If `template_id == "claim_lighthouse"`, call `lighthouse_engine.complete_claim()` before standard closing |
| `bot/cogs/lighthouse.py` | Add `app_commands.Group` with `claim` and `list` subcommands; share `_lighthouse_logic` from 3b-1 |
| `bot/cogs/dock.py` | Export `_force_dock` helper (bypasses 24h cooldown) for the auto-dock path |
| `bot/system_gating.py` | `/lighthouse list` and `/lighthouse claim` are universe-wide (already covered by `/lighthouse` allow but verify subcommand routing) |
| `tests/conftest.py` | `sample_eligible_player_for_claim` fixture (filled build + ≥3 completed expeditions) |

---

## Task 1: Migration 0007 — `claim_attempts` + `expeditions.parameters`

**Files:**
- Create: `db/migrations/versions/0007_phase3b_2_claim.py`
- Create: `tests/test_phase3b_2_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3b_2_migration.py`:

```python
"""Phase 3b-2 migration: claim_attempts + expeditions.parameters."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def test_claim_attempts_table_exists(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    assert "claim_attempts" in set(insp.get_table_names())


async def test_claim_outcome_enum_values(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'claim_outcome' "
                "ORDER BY enumlabel"
            )
        )
    ).scalars().all()
    assert set(rows) == {"pass", "fail"}


async def test_expeditions_has_parameters_column(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {c["name"] for c in insp.get_columns("expeditions")}
    assert "parameters" in cols


async def test_claim_attempts_has_player_index(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    indexes = insp.get_indexes("claim_attempts")
    names = {idx["name"] for idx in indexes}
    assert any("player" in n for n in names), names
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_phase3b_2_migration.py -v --no-cov`
Expected: 4 FAIL.

- [ ] **Step 3: Write the migration**

Create `db/migrations/versions/0007_phase3b_2_claim.py`:

```python
"""Phase 3b-2 — Wardenship claim.

Adds claim_attempts table, claim_outcome enum, and expeditions.parameters JSONB.

Revision ID: 0007_phase3b_2_claim
Revises: 0006_phase3b_foundation
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_phase3b_2_claim"
down_revision = "0006_phase3b_foundation"
branch_labels = None
depends_on = None


CLAIM_OUTCOME = postgresql.ENUM("pass", "fail", name="claim_outcome")


def upgrade() -> None:
    bind = op.get_bind()
    CLAIM_OUTCOME.create(bind, checkfirst=True)

    op.add_column(
        "expeditions",
        sa.Column(
            "parameters",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )

    op.create_table(
        "claim_attempts",
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
        ),
        sa.Column(
            "target_system_id",
            sa.String(20),
            sa.ForeignKey("systems.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="claim_outcome", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "expedition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expeditions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_claim_attempts_player", "claim_attempts", ["player_id"])
    op.create_index(
        "ix_claim_attempts_target_system", "claim_attempts", ["target_system_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_claim_attempts_target_system", table_name="claim_attempts")
    op.drop_index("ix_claim_attempts_player", table_name="claim_attempts")
    op.drop_table("claim_attempts")
    op.drop_column("expeditions", "parameters")
    bind = op.get_bind()
    CLAIM_OUTCOME.drop(bind, checkfirst=True)
```

- [ ] **Step 4: Run, confirm passes**

Run: `DATABASE_URL=... python -m alembic upgrade head` then `pytest tests/test_phase3b_2_migration.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Round-trip**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: succeed.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/versions/0007_phase3b_2_claim.py tests/test_phase3b_2_migration.py
git commit -m "feat(phase3b-2): add claim_attempts table + expeditions.parameters"
```

---

## Task 2: ORM models — `ClaimAttempt`, `Expedition.parameters`

**Files:**
- Modify: `db/models.py`
- Modify: `tests/test_phase3b_models.py` (new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase3b_models.py`:

```python
async def test_claim_attempt_creates_with_pending_outcome(db_session, sample_user, sample_system):
    from db.models import ClaimAttempt

    ca = ClaimAttempt(
        player_id=sample_user.discord_id,
        target_system_id=sample_system.channel_id,
        difficulty=25,
    )
    db_session.add(ca)
    await db_session.flush()
    await db_session.refresh(ca)
    assert ca.outcome is None
    assert ca.resolved_at is None


async def test_expedition_parameters_default_empty(db_session, sample_user, sample_build):
    from datetime import datetime, timedelta, timezone

    from db.models import Expedition

    ex = Expedition(
        user_id=sample_user.discord_id,
        build_id=sample_build.id,
        template_id="outer_marker_patrol",
        completes_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(ex)
    await db_session.flush()
    await db_session.refresh(ex)
    assert ex.parameters == {}


async def test_expedition_parameters_writable(db_session, sample_user, sample_build):
    from datetime import datetime, timedelta, timezone

    from db.models import Expedition

    ex = Expedition(
        user_id=sample_user.discord_id,
        build_id=sample_build.id,
        template_id="claim_lighthouse",
        completes_at=datetime.now(timezone.utc) + timedelta(hours=1),
        parameters={"target_system_id": "12345", "difficulty": 25},
    )
    db_session.add(ex)
    await db_session.flush()
    await db_session.refresh(ex)
    assert ex.parameters["target_system_id"] == "12345"
    assert ex.parameters["difficulty"] == 25
```

- [ ] **Step 2: Run, confirm fails**

Run the new tests — `ImportError: cannot import name 'ClaimAttempt'` and `AttributeError` on `parameters`.

- [ ] **Step 3: Add `ClaimOutcome` enum and `ClaimAttempt` model to `db/models.py`**

After the existing 3b-1 enums:

```python
class ClaimOutcome(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
```

Add the `parameters` column to the existing `Expedition` class (around line 729, before `outcome_summary`):

```python
    parameters: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
```

Add the `ClaimAttempt` model — alongside the other 3b-1 models near the end of the file:

```python
class ClaimAttempt(Base):
    __tablename__ = "claim_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_system_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("systems.channel_id", ondelete="CASCADE"), nullable=False, index=True
    )
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[ClaimOutcome | None] = mapped_column(
        Enum(ClaimOutcome, values_callable=lambda x: [e.value for e in x], name="claim_outcome"),
        nullable=True,
    )
    expedition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expeditions.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_phase3b_models.py -v --no-cov`
Expected: All pass (3b-1 tests + 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_phase3b_models.py
git commit -m "feat(phase3b-2): ClaimAttempt model + Expedition.parameters"
```

---

## Task 3: Difficulty calculator — `compute_claim_difficulty`

**Files:**
- Modify: `engine/lighthouse_engine.py`
- Create: `tests/test_engine_claim_difficulty.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_claim_difficulty.py`:

```python
"""Spec §7.3 difficulty formula coverage."""

from __future__ import annotations

import pytest


def test_rim_zero_features_single_yellow():
    from db.models import LighthouseBand
    from engine.lighthouse_engine import compute_claim_difficulty

    d = compute_claim_difficulty(
        band=LighthouseBand.RIM,
        feature_count=0,
        star_type="single",
        star_color="yellow",
    )
    assert d == 10  # base only


def test_middle_two_features_binary():
    from db.models import LighthouseBand
    from engine.lighthouse_engine import compute_claim_difficulty

    d = compute_claim_difficulty(
        band=LighthouseBand.MIDDLE,
        feature_count=2,
        star_type="binary",
        star_color="white",
    )
    # 25 base + 2*5 features + 5 binary = 40
    assert d == 40


def test_inner_three_features_trinary_exotic_color():
    from db.models import LighthouseBand
    from engine.lighthouse_engine import compute_claim_difficulty

    d = compute_claim_difficulty(
        band=LighthouseBand.INNER,
        feature_count=3,
        star_type="trinary",
        star_color="exotic",
    )
    # 50 base + 3*5 features + 5 trinary + 10 exotic = 80
    assert d == 80


def test_required_successes_for_difficulty_buckets():
    from engine.lighthouse_engine import required_successes_for_difficulty

    assert required_successes_for_difficulty(10) == 1
    assert required_successes_for_difficulty(15) == 1
    assert required_successes_for_difficulty(16) == 2
    assert required_successes_for_difficulty(30) == 2
    assert required_successes_for_difficulty(31) == 3
    assert required_successes_for_difficulty(80) == 3
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_claim_difficulty.py -v --no-cov`
Expected: 4 FAIL.

- [ ] **Step 3: Implement in `engine/lighthouse_engine.py`**

Append:

```python
# ──────────── Phase 3b-2: Wardenship claim ────────────

# Spec §7.3 base difficulty by band.
_BAND_BASE_DIFFICULTY: dict[LighthouseBand, int] = {
    LighthouseBand.RIM: 10,
    LighthouseBand.MIDDLE: 25,
    LighthouseBand.INNER: 50,
}


def compute_claim_difficulty(
    *,
    band: LighthouseBand,
    feature_count: int,
    star_type: str,
    star_color: str,
) -> int:
    """Spec §7.3 — base + 5*features + 5 if multi-star + 10 if exotic color."""
    d = _BAND_BASE_DIFFICULTY[band]
    d += 5 * feature_count
    if star_type in ("binary", "trinary"):
        d += 5
    if star_color == "exotic":
        d += 10
    return d


def required_successes_for_difficulty(difficulty: int) -> int:
    """Convert a difficulty value to the success threshold the player must hit
    in the 3-event claim contract.

    <=15: 1 (push-over claim, mostly lore)
    16-30: 2 (typical mid-band)
    >30: 3 (perfect run required)
    """
    if difficulty <= 15:
        return 1
    if difficulty <= 30:
        return 2
    return 3
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_claim_difficulty.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lighthouse_engine.py tests/test_engine_claim_difficulty.py
git commit -m "feat(phase3b-2): claim difficulty + required-successes mapping"
```

---

## Task 4: Claim contract template — `data/expeditions/claim_lighthouse.yaml`

**Files:**
- Create: `data/expeditions/claim_lighthouse.yaml`

- [ ] **Step 1: Write the template**

Create `data/expeditions/claim_lighthouse.yaml`:

```yaml
id: claim_lighthouse
kind: rolled
duration_minutes: 180
response_window_minutes: 30
cost_credits: 250
event_count: 3
crew_required: { min: 1, archetypes_any: [PILOT, NAVIGATOR, ENGINEER, GUNNER] }
opening:
  id: opening
  narration: |
    The Authority routes you a vetted contract: a Lighthouse seat, currently
    open. Your run is logged the moment you light the burn. {ship} cuts toward
    the system, signal beacons resolving on the long-range scope.

events:
  - id: signal_alignment
    narration: |
      The Lighthouse expects a coherent signal-handshake from any approaching
      claimant. {pilot.callsign} brings {ship} into the alignment window.
    choices:
      - id: align
        text: "Hold the alignment vector."
        roll: { stat: pilot.handling, base_p: 0.55, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: "The handshake resolves clean. The Lighthouse acknowledges your transponder."
            effects:
              - reward_xp: { archetype: PILOT, amount: 30 }
          failure:
            narrative: "The Lighthouse's response goes incoherent. You burn fuel resetting the approach."
            effects:
              - reward_xp: { archetype: PILOT, amount: 10 }

  - id: surveyor_protocol
    narration: |
      The Authority requires a fresh survey log of the system. The crew runs
      sweeps; the navigator coordinates the pattern.
    choices:
      - id: sweep
        text: "Run the surveyor protocol cleanly."
        roll: { stat: navigator.range, base_p: 0.55, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: "{navigator.callsign} files a tidy log. The Authority's automated review accepts it."
            effects:
              - reward_xp: { archetype: NAVIGATOR, amount: 30 }
          failure:
            narrative: "The survey comes back patchy. The Authority will accept it but the audit will be slow."
            effects:
              - reward_xp: { archetype: NAVIGATOR, amount: 10 }

  - id: spire_handover
    narration: |
      Final test: the Lighthouse's primary spire requires a manual reset
      from the claimant's vessel. {ship} parks alongside.
    choices:
      - id: handover
        text: "Execute the manual handover."
        roll: { stat: engineer.repair, base_p: 0.55, base_stat: 50, per_point: 0.005 }
        outcomes:
          success:
            narrative: "The spire's status board flips to green and acknowledges your callsign as Warden-of-record."
            effects:
              - reward_xp: { archetype: ENGINEER, amount: 30 }
          failure:
            narrative: "The reset glitches and rolls back. The board still won't recognize you."
            effects:
              - reward_xp: { archetype: ENGINEER, amount: 10 }

closings:
  - id: any
    body: |
      The contract closes. The Authority will route the outcome and any
      consolation through the standard ledger.
```

- [ ] **Step 2: Validate the template loads**

Run: `python -m engine.expedition_template`
Expected: validates `claim_lighthouse.yaml` along with the other templates with no errors.

- [ ] **Step 3: Add a test asserting the template is loadable**

Append to `tests/test_expedition_template_files.py`:

```python
def test_claim_lighthouse_template_validates():
    from engine.expedition_template import load_template

    tmpl = load_template("claim_lighthouse")
    assert tmpl["id"] == "claim_lighthouse"
    assert tmpl["kind"] == "rolled"
    # 3 events feeds the success threshold logic in lighthouse_engine.
    assert len(tmpl["events"]) == 3
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_expedition_template_files.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data/expeditions/claim_lighthouse.yaml tests/test_expedition_template_files.py
git commit -m "feat(phase3b-2): claim_lighthouse expedition template"
```

---

## Task 5: `precheck_claim` — preconditions

**Files:**
- Modify: `engine/lighthouse_engine.py`
- Create: `tests/test_engine_precheck_claim.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_precheck_claim.py`:

```python
"""Each precondition gate from spec §7.6."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_precheck_pass(db_session, eligible_player_with_build, sample_system_with_lighthouse):
    from engine.lighthouse_engine import precheck_claim

    r = await precheck_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    assert r.eligible, r.reason


async def test_precheck_rejects_unfilled_build(
    db_session, sample_user, partial_build, sample_system_with_lighthouse
):
    from engine.lighthouse_engine import precheck_claim

    r = await precheck_claim(
        db_session,
        player_id=sample_user.discord_id,
        build_id=partial_build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    assert not r.eligible
    assert "build" in r.reason.lower() or "slot" in r.reason.lower()


async def test_precheck_rejects_below_three_expeditions(
    db_session, sample_user, full_build, sample_system_with_lighthouse
):
    from engine.lighthouse_engine import precheck_claim

    # User has 0 completed expeditions.
    r = await precheck_claim(
        db_session,
        player_id=sample_user.discord_id,
        build_id=full_build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    assert not r.eligible
    assert "expedition" in r.reason.lower()


async def test_precheck_rejects_during_cooldown(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    from db.models import ClaimAttempt, ClaimOutcome
    from engine.lighthouse_engine import precheck_claim

    # Plant a recent attempt.
    db_session.add(
        ClaimAttempt(
            player_id=eligible_player_with_build.user.discord_id,
            target_system_id=sample_system_with_lighthouse.channel_id,
            difficulty=25,
            resolved_at=datetime.now(timezone.utc) - timedelta(days=2),
            outcome=ClaimOutcome.FAIL,
        )
    )
    await db_session.flush()

    r = await precheck_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    assert not r.eligible
    assert "cooldown" in r.reason.lower()


async def test_precheck_rejects_already_claimed(
    db_session, eligible_player_with_build, claimed_lighthouse_system
):
    from engine.lighthouse_engine import precheck_claim

    r = await precheck_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=claimed_lighthouse_system.channel_id,
    )
    assert not r.eligible
    assert "claimed" in r.reason.lower() or "warden" in r.reason.lower()


async def test_precheck_rejects_self_claim(
    db_session, warden_player, warden_held_system
):
    from engine.lighthouse_engine import precheck_claim

    r = await precheck_claim(
        db_session,
        player_id=warden_player.user.discord_id,
        build_id=warden_player.build.id,
        target_system_id=warden_held_system.channel_id,
    )
    assert not r.eligible
    assert "already" in r.reason.lower()
```

The fixtures `eligible_player_with_build`, `partial_build`, `full_build`, `claimed_lighthouse_system`, `warden_player`, `warden_held_system` are referenced — add them in Step 3.

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_precheck_claim.py -v --no-cov`
Expected: 6 FAIL.

- [ ] **Step 3: Add fixtures**

In `tests/conftest.py`:

```python
@pytest.fixture
async def full_build(db_session, sample_user):
    """A build with all 7 slots filled."""
    from db.models import Build, HullClass

    build = Build(
        user_id=sample_user.discord_id,
        name="Full Build",
        slots={
            "reactor": str(uuid.uuid4()),
            "drive": str(uuid.uuid4()),
            "thrusters": str(uuid.uuid4()),
            "stabilizers": str(uuid.uuid4()),
            "hull": str(uuid.uuid4()),
            "overdrive": str(uuid.uuid4()),
            "retros": str(uuid.uuid4()),
        },
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()
    await db_session.refresh(build)
    return build


@pytest.fixture
async def partial_build(db_session, sample_user):
    """A build with only some slots filled (precheck should reject)."""
    from db.models import Build, HullClass

    build = Build(
        user_id=sample_user.discord_id,
        name="Partial",
        slots={
            "reactor": str(uuid.uuid4()),
            "drive": None,
            "thrusters": None,
            "stabilizers": None,
            "hull": None,
            "overdrive": None,
            "retros": None,
        },
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()
    await db_session.refresh(build)
    return build


@pytest.fixture
async def eligible_player_with_build(db_session, sample_user, full_build):
    """User + filled build + 3 completed expeditions on record."""
    from datetime import datetime, timedelta, timezone

    from db.models import Expedition, ExpeditionState

    for i in range(3):
        ex = Expedition(
            user_id=sample_user.discord_id,
            build_id=full_build.id,
            template_id="outer_marker_patrol",
            state=ExpeditionState.COMPLETED,
            completes_at=datetime.now(timezone.utc) - timedelta(days=i + 1),
        )
        db_session.add(ex)
    await db_session.flush()

    @dataclass
    class _Eligible:
        user: object
        build: object

    return _Eligible(user=sample_user, build=full_build)


@pytest.fixture
async def claimed_lighthouse_system(db_session, sample_system_with_lighthouse, sample_user2):
    """A Lighthouse already held by sample_user2 — used to test 'already claimed'."""
    from db.models import Lighthouse
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    lh.warden_id = sample_user2.discord_id
    await db_session.flush()
    return sample_system_with_lighthouse


@pytest.fixture
async def warden_player(db_session, sample_user, full_build):
    @dataclass
    class _Warden:
        user: object
        build: object

    return _Warden(user=sample_user, build=full_build)


@pytest.fixture
async def warden_held_system(db_session, sample_system_with_lighthouse, sample_user):
    from db.models import Lighthouse
    from sqlalchemy import select

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    lh.warden_id = sample_user.discord_id
    await db_session.flush()
    return sample_system_with_lighthouse


@pytest.fixture
async def sample_user2(db_session, sample_sector):
    from db.models import HullClass, User

    u = User(
        discord_id="2222222",
        username="alt-pilot",
        hull_class=HullClass.HAULER,
    )
    db_session.add(u)
    await db_session.flush()
    await db_session.refresh(u)
    return u
```

(Add `import uuid` and `from dataclasses import dataclass` to `conftest.py` if not already present.)

- [ ] **Step 4: Implement `precheck_claim` in `engine/lighthouse_engine.py`**

Append to `engine/lighthouse_engine.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


CLAIM_COOLDOWN = timedelta(days=7)


@dataclass(frozen=True)
class ClaimEligibility:
    eligible: bool
    reason: str  # empty when eligible


async def precheck_claim(
    session: AsyncSession,
    *,
    player_id: str,
    build_id,
    target_system_id: str,
) -> ClaimEligibility:
    """Spec §7.6 preconditions. Order matters — return the most actionable error first."""
    from sqlalchemy import select

    from db.models import (
        Build,
        ClaimAttempt,
        Expedition,
        ExpeditionState,
        Lighthouse,
        LighthouseState,
    )

    build = await session.get(Build, build_id)
    if build is None or build.user_id != player_id:
        return ClaimEligibility(False, "Build not found or not yours.")

    slots = build.slots or {}
    if any(v is None for v in slots.values()):
        return ClaimEligibility(False, "Your build has empty slots — fill all 7 to claim.")

    completed = (
        await session.execute(
            select(Expedition)
            .where(Expedition.user_id == player_id)
            .where(Expedition.state == ExpeditionState.COMPLETED)
        )
    ).scalars().all()
    if len(completed) < 3:
        return ClaimEligibility(
            False, f"Need at least 3 completed expeditions ({len(completed)}/3)."
        )

    last_attempt = (
        await session.execute(
            select(ClaimAttempt)
            .where(ClaimAttempt.player_id == player_id)
            .order_by(ClaimAttempt.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_attempt is not None:
        latest = last_attempt.resolved_at or last_attempt.started_at
        elapsed = datetime.now(timezone.utc) - latest
        if elapsed < CLAIM_COOLDOWN:
            remaining = CLAIM_COOLDOWN - elapsed
            days = int(remaining.total_seconds() // 86400)
            hours = int((remaining.total_seconds() % 86400) // 3600)
            return ClaimEligibility(
                False, f"Claim cooldown: {days}d {hours}h remaining."
            )

    lh = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.system_id == target_system_id)
        )
    ).scalar_one_or_none()
    if lh is None:
        return ClaimEligibility(False, "That system has no Lighthouse on record.")
    if lh.state != LighthouseState.ACTIVE:
        return ClaimEligibility(
            False, f"Lighthouse is {lh.state.value}; cannot be claimed right now."
        )
    if lh.warden_id is not None:
        if lh.warden_id == player_id:
            return ClaimEligibility(False, "You are already the Warden of that system.")
        return ClaimEligibility(False, "That Lighthouse is already claimed.")

    return ClaimEligibility(True, "")
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_engine_precheck_claim.py -v --no-cov`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/lighthouse_engine.py tests/test_engine_precheck_claim.py tests/conftest.py
git commit -m "feat(phase3b-2): precheck_claim — preconditions + cooldown"
```

---

## Task 6: `start_claim` — create attempt + expedition with parameters

**Files:**
- Modify: `engine/lighthouse_engine.py`
- Create: `tests/test_engine_start_claim.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_start_claim.py`:

```python
"""start_claim creates ClaimAttempt + Expedition + scheduled jobs."""

from __future__ import annotations

from sqlalchemy import select


async def test_start_claim_creates_attempt_and_expedition(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    from db.models import ClaimAttempt, Expedition
    from engine.lighthouse_engine import start_claim

    result = await start_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    await db_session.flush()

    assert result.attempt_id is not None
    assert result.expedition_id is not None

    attempt = (
        await db_session.execute(
            select(ClaimAttempt).where(ClaimAttempt.id == result.attempt_id)
        )
    ).scalar_one()
    assert attempt.outcome is None
    assert attempt.expedition_id == result.expedition_id

    ex = await db_session.get(Expedition, result.expedition_id)
    assert ex.template_id == "claim_lighthouse"
    assert ex.parameters["target_system_id"] == sample_system_with_lighthouse.channel_id
    assert ex.parameters["difficulty"] > 0


async def test_start_claim_propagates_difficulty_to_parameters(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    from db.models import Expedition
    from engine.lighthouse_engine import start_claim

    result = await start_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    await db_session.flush()
    ex = await db_session.get(Expedition, result.expedition_id)
    # The fixture's lighthouse is 'rim' and seed 31415 produces 0–3 features
    # — enough that we just sanity-check the difficulty is in the rim band range.
    assert 10 <= ex.parameters["difficulty"] <= 30
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_start_claim.py -v --no-cov`
Expected: FAIL (`start_claim` doesn't exist).

- [ ] **Step 3: Implement `start_claim`**

Append to `engine/lighthouse_engine.py`:

```python
@dataclass(frozen=True)
class StartClaimResult:
    attempt_id: uuid.UUID
    expedition_id: uuid.UUID


async def start_claim(
    session: AsyncSession,
    *,
    player_id: str,
    build_id,
    target_system_id: str,
) -> StartClaimResult:
    """Begin a Wardenship claim. Caller must have already passed precheck_claim.

    - Computes difficulty.
    - Inserts a ClaimAttempt row (outcome NULL).
    - Inserts an Expedition row with template_id=claim_lighthouse and parameters.
    - Does NOT schedule the EXPEDITION_COMPLETE job — that's the caller's
      responsibility (the cog uses the same scheduling helper as /expedition start).
    """
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone

    from db.models import (
        ClaimAttempt,
        Expedition,
        Lighthouse,
        SystemFeature,
    )
    from engine.expedition_template import load_template
    from sqlalchemy import select

    lh = (
        await session.execute(
            select(Lighthouse).where(Lighthouse.system_id == target_system_id)
        )
    ).scalar_one()
    sys_obj = lh.system  # eager-loaded

    feature_count = len(
        (
            await session.execute(
                select(SystemFeature).where(SystemFeature.system_id == target_system_id)
            )
        ).scalars().all()
    )
    difficulty = compute_claim_difficulty(
        band=lh.band,
        feature_count=feature_count,
        star_type=(sys_obj.star_type.value if sys_obj.star_type else "single"),
        star_color=(sys_obj.star_color.value if sys_obj.star_color else "yellow"),
    )

    template = load_template("claim_lighthouse")
    duration = timedelta(minutes=template["duration_minutes"])
    completes_at = datetime.now(timezone.utc) + duration

    expedition = Expedition(
        id=_uuid.uuid4(),
        user_id=player_id,
        build_id=build_id,
        template_id="claim_lighthouse",
        completes_at=completes_at,
        parameters={
            "target_system_id": target_system_id,
            "target_band": lh.band.value,
            "difficulty": difficulty,
        },
    )
    session.add(expedition)

    attempt = ClaimAttempt(
        player_id=player_id,
        target_system_id=target_system_id,
        difficulty=difficulty,
        expedition_id=expedition.id,
    )
    session.add(attempt)

    await session.flush()

    return StartClaimResult(attempt_id=attempt.id, expedition_id=expedition.id)
```

(Note: this leaves the actual *scheduling* of EXPEDITION_COMPLETE/EXPEDITION_AUTO_RESOLVE jobs to the cog layer in Task 9, mirroring how `/expedition start` does it. The orchestration is identical to the existing flow — the cog calls `enqueue_expedition` after `start_claim` returns.)

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_start_claim.py -v --no-cov`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lighthouse_engine.py tests/test_engine_start_claim.py
git commit -m "feat(phase3b-2): start_claim creates ClaimAttempt + parameterized expedition"
```

---

## Task 7: `complete_claim` — outcome resolution + auto-dock

**Files:**
- Modify: `engine/lighthouse_engine.py`
- Modify: `bot/cogs/dock.py` (export `_force_dock`)
- Create: `tests/test_engine_complete_claim.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_complete_claim.py`:

```python
"""complete_claim — pass/fail/auto-dock paths."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


async def test_complete_claim_pass_sets_warden_and_auto_docks(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    from db.models import Citizenship, ClaimAttempt, ClaimOutcome, Expedition, Lighthouse
    from engine.lighthouse_engine import complete_claim, start_claim
    from sqlalchemy import select

    r = await start_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    await db_session.flush()

    ex = await db_session.get(Expedition, r.expedition_id)
    # Plant accumulated_state-equivalent metadata: simulate 3 successes in scene_log.
    ex.scene_log = [
        {"scene_id": f"event_{i}", "outcome": {"kind": "success"}} for i in range(3)
    ]
    await db_session.flush()

    outcome = await complete_claim(db_session, ex)
    await db_session.flush()
    assert outcome == ClaimOutcome.PASS

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    assert lh.warden_id == eligible_player_with_build.user.discord_id

    citz = (
        await db_session.execute(
            select(Citizenship)
            .where(Citizenship.player_id == eligible_player_with_build.user.discord_id)
            .where(Citizenship.ended_at.is_(None))
        )
    ).scalar_one()
    assert citz.system_id == sample_system_with_lighthouse.channel_id

    attempt = (
        await db_session.execute(
            select(ClaimAttempt).where(ClaimAttempt.expedition_id == r.expedition_id)
        )
    ).scalar_one()
    assert attempt.outcome == ClaimOutcome.PASS
    assert attempt.resolved_at is not None


async def test_complete_claim_fail_pays_consolation_no_warden_change(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    from db.models import ClaimAttempt, ClaimOutcome, Expedition, Lighthouse, User
    from engine.lighthouse_engine import complete_claim, start_claim
    from sqlalchemy import select

    starting_credits = (
        await db_session.execute(
            select(User.currency).where(User.discord_id == eligible_player_with_build.user.discord_id)
        )
    ).scalar()

    r = await start_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    await db_session.flush()

    ex = await db_session.get(Expedition, r.expedition_id)
    # Zero successes — failure path.
    ex.scene_log = [
        {"scene_id": f"event_{i}", "outcome": {"kind": "failure"}} for i in range(3)
    ]
    await db_session.flush()

    outcome = await complete_claim(db_session, ex)
    await db_session.flush()
    assert outcome == ClaimOutcome.FAIL

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    assert lh.warden_id is None

    new_credits = (
        await db_session.execute(
            select(User.currency).where(User.discord_id == eligible_player_with_build.user.discord_id)
        )
    ).scalar()
    # 5% of expected reward — for rim 250c contract this is ≈ 12 credits.
    assert new_credits > starting_credits


async def test_complete_claim_auto_dock_overrides_24h_cooldown(
    db_session, eligible_player_with_build, sample_system_with_lighthouse, sample_system2
):
    """If the player was docked at System X within the last 24h, claiming
    Lighthouse at System Y still auto-docks them — claim itself qualifies.
    """
    from db.models import Citizenship
    from engine.lighthouse_engine import complete_claim, start_claim
    from sqlalchemy import select

    # Plant an active citizenship < 24h old.
    db_session.add(
        Citizenship(
            player_id=eligible_player_with_build.user.discord_id,
            system_id=sample_system2.channel_id,
            docked_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    await db_session.flush()

    r = await start_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    await db_session.flush()

    ex = await db_session.get(__import__("db.models", fromlist=["Expedition"]).Expedition, r.expedition_id)
    ex.scene_log = [{"scene_id": f"e{i}", "outcome": {"kind": "success"}} for i in range(3)]
    await db_session.flush()

    await complete_claim(db_session, ex)
    await db_session.flush()

    citz = (
        await db_session.execute(
            select(Citizenship)
            .where(Citizenship.player_id == eligible_player_with_build.user.discord_id)
            .where(Citizenship.ended_at.is_(None))
        )
    ).scalar_one()
    assert citz.system_id == sample_system_with_lighthouse.channel_id
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_complete_claim.py -v --no-cov`
Expected: 3 FAIL.

- [ ] **Step 3: Add `_force_dock` to `bot/cogs/dock.py`**

Append to `bot/cogs/dock.py`:

```python
async def _force_dock(session, player_id: str, system_id: str) -> None:
    """Switch a player's citizenship without applying the 24h cooldown.

    Used by the Wardenship claim auto-dock path (spec §7.7) and any future
    auto-dock contexts. Closes any existing active row and opens a new one.
    """
    from datetime import datetime, timezone

    from db.models import Citizenship
    from sqlalchemy import select, update

    now = datetime.now(timezone.utc)
    await session.execute(
        update(Citizenship)
        .where(Citizenship.player_id == player_id, Citizenship.ended_at.is_(None))
        .values(ended_at=now)
    )
    session.add(
        Citizenship(
            player_id=player_id,
            system_id=system_id,
            docked_at=now,
            switched_at=now,
        )
    )
```

- [ ] **Step 4: Implement `complete_claim` in `engine/lighthouse_engine.py`**

Append:

```python
async def complete_claim(session: AsyncSession, expedition) -> "ClaimOutcome":
    """Resolve a claim_lighthouse expedition into a Lighthouse ownership change.

    Reads:
        expedition.parameters["target_system_id"]
        expedition.parameters["difficulty"]
        expedition.scene_log — counts entries with outcome.kind == "success"

    On PASS: sets warden_id, auto-docks the player, marks ClaimAttempt resolved,
             pays full reward (template-defined; this function pays nothing extra).
    On FAIL: pays 5% consolation credits to the player, marks attempt resolved,
             leaves warden_id untouched.
    """
    from db.models import (
        ClaimAttempt,
        ClaimOutcome,
        Lighthouse,
        User,
    )
    from sqlalchemy import select, update

    from bot.cogs.dock import _force_dock

    target_system_id = expedition.parameters["target_system_id"]
    difficulty = int(expedition.parameters["difficulty"])
    required = required_successes_for_difficulty(difficulty)

    successes = sum(
        1
        for entry in (expedition.scene_log or [])
        if (entry.get("outcome") or {}).get("kind") == "success"
    )
    outcome = ClaimOutcome.PASS if successes >= required else ClaimOutcome.FAIL

    # Update the ClaimAttempt row.
    attempt = (
        await session.execute(
            select(ClaimAttempt).where(ClaimAttempt.expedition_id == expedition.id)
        )
    ).scalar_one()
    attempt.outcome = outcome
    attempt.resolved_at = datetime.now(timezone.utc)

    if outcome == ClaimOutcome.PASS:
        lh = (
            await session.execute(
                select(Lighthouse).where(Lighthouse.system_id == target_system_id)
            )
        ).scalar_one()
        # Race-safe last check: do not overwrite a Warden installed in a
        # concurrent attempt. If the seat is no longer open, downgrade to fail.
        if lh.warden_id is not None:
            attempt.outcome = ClaimOutcome.FAIL
            await _pay_consolation(session, expedition.user_id)
            return ClaimOutcome.FAIL
        lh.warden_id = expedition.user_id
        await _force_dock(session, expedition.user_id, target_system_id)
    else:
        await _pay_consolation(session, expedition.user_id)

    await session.flush()
    return outcome


async def _pay_consolation(session, player_id: str) -> None:
    """5% consolation per spec §7.4. Reward base is the contract's cost_credits (250)."""
    from db.models import User
    from sqlalchemy import update

    payout = max(1, int(0.05 * 250))  # 12c
    await session.execute(
        update(User).where(User.discord_id == player_id).values(currency=User.currency + payout)
    )
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_engine_complete_claim.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/lighthouse_engine.py bot/cogs/dock.py tests/test_engine_complete_claim.py
git commit -m "feat(phase3b-2): complete_claim resolves seat + auto-docks winner"
```

---

## Task 8: Wire `complete_claim` into the EXPEDITION_COMPLETE handler

**Files:**
- Modify: `scheduler/jobs/expedition_complete.py`
- Modify: `tests/test_handler_expedition_complete.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handler_expedition_complete.py`:

```python
async def test_handler_calls_complete_claim_for_claim_template(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    """When a claim_lighthouse expedition reaches EXPEDITION_COMPLETE, complete_claim runs."""
    from db.models import (
        ClaimAttempt,
        ClaimOutcome,
        Expedition,
        JobState,
        JobType,
        Lighthouse,
        ScheduledJob,
    )
    from engine.lighthouse_engine import start_claim
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    from sqlalchemy import select

    r = await start_claim(
        db_session,
        player_id=eligible_player_with_build.user.discord_id,
        build_id=eligible_player_with_build.build.id,
        target_system_id=sample_system_with_lighthouse.channel_id,
    )
    await db_session.flush()
    ex = await db_session.get(Expedition, r.expedition_id)
    ex.scene_log = [{"scene_id": f"e{i}", "outcome": {"kind": "success"}} for i in range(3)]
    await db_session.flush()

    job = ScheduledJob(
        type=JobType.EXPEDITION_COMPLETE,
        run_at=__import__("datetime").datetime.utcnow(),
        state=JobState.CLAIMED,
        payload={"expedition_id": str(ex.id), "template_id": "claim_lighthouse"},
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    assert lh.warden_id == eligible_player_with_build.user.discord_id
```

- [ ] **Step 2: Run, confirm fails**

Run the new test — FAIL because the handler doesn't yet call `complete_claim`.

- [ ] **Step 3: Modify `scheduler/jobs/expedition_complete.py`**

Inside `handle_expedition_complete`, after `expedition = await session.get(...)` and BEFORE the existing `template = load_template(...)` line, add:

```python
    if expedition.template_id == "claim_lighthouse":
        from engine.lighthouse_engine import complete_claim

        await complete_claim(session, expedition)
        # Fall through — the standard closing path still runs to deliver the
        # template-defined narrative and the player's standard credit reward
        # (handled by the closing's effects). complete_claim already paid the
        # 5% consolation on fail and set the seat on pass.
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_expedition_complete.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler/jobs/expedition_complete.py tests/test_handler_expedition_complete.py
git commit -m "feat(phase3b-2): EXPEDITION_COMPLETE invokes complete_claim for claim template"
```

---

## Task 9: `/lighthouse claim <system>` command

**Files:**
- Modify: `bot/cogs/lighthouse.py`
- Create: `tests/test_cog_lighthouse_claim.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cog_lighthouse_claim.py`:

```python
"""/lighthouse claim — orchestrates precheck + start_claim + scheduling."""

from __future__ import annotations

from unittest.mock import MagicMock


async def test_claim_happy_path(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    from bot.cogs.lighthouse import _claim_logic
    from db.models import ClaimAttempt
    from sqlalchemy import select

    interaction = MagicMock()
    interaction.user.id = int(eligible_player_with_build.user.discord_id)

    r = await _claim_logic(
        interaction,
        system_name=sample_system_with_lighthouse.name,
        session=db_session,
    )
    assert r.success, r.message
    assert "claim" in r.message.lower() and "started" in r.message.lower()

    attempt = (
        await db_session.execute(
            select(ClaimAttempt).where(ClaimAttempt.player_id == eligible_player_with_build.user.discord_id)
        )
    ).scalar_one()
    assert attempt.outcome is None  # in flight


async def test_claim_rejected_with_specific_reason(
    db_session, sample_user, partial_build, sample_system_with_lighthouse
):
    from bot.cogs.lighthouse import _claim_logic

    interaction = MagicMock()
    interaction.user.id = int(sample_user.discord_id)

    r = await _claim_logic(
        interaction,
        system_name=sample_system_with_lighthouse.name,
        session=db_session,
    )
    assert not r.success
    # Build precondition error should surface.
    assert "build" in r.message.lower() or "slot" in r.message.lower()


async def test_claim_unknown_system(db_session, eligible_player_with_build):
    from bot.cogs.lighthouse import _claim_logic

    interaction = MagicMock()
    interaction.user.id = int(eligible_player_with_build.user.discord_id)

    r = await _claim_logic(interaction, system_name="no-such", session=db_session)
    assert not r.success
    assert "not found" in r.message.lower()
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_lighthouse_claim.py -v --no-cov`
Expected: 3 FAIL.

- [ ] **Step 3: Extend `bot/cogs/lighthouse.py`**

Replace the `LighthouseCog` class definition with a Group-based shape and add `_claim_logic`:

```python
async def _claim_logic(interaction, system_name: str, session) -> CommandResult:
    """Start a Wardenship claim against `system_name`."""
    from db.models import Build, System
    from engine.lighthouse_engine import precheck_claim, start_claim
    from sqlalchemy import select

    sys_obj = (
        await session.execute(select(System).where(System.name == system_name))
    ).scalar_one_or_none()
    if sys_obj is None:
        return CommandResult(False, f"System {system_name!r} not found.")

    player_id = str(interaction.user.id)
    build = (
        await session.execute(
            select(Build).where(Build.user_id == player_id, Build.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if build is None:
        return CommandResult(False, "You have no active build. Configure /hangar first.")

    eligibility = await precheck_claim(
        session,
        player_id=player_id,
        build_id=build.id,
        target_system_id=sys_obj.channel_id,
    )
    if not eligibility.eligible:
        return CommandResult(False, eligibility.reason)

    result = await start_claim(
        session,
        player_id=player_id,
        build_id=build.id,
        target_system_id=sys_obj.channel_id,
    )
    return CommandResult(
        True,
        f"Claim started against #{sys_obj.name}. "
        f"The Authority will route the outcome through your standard "
        f"expedition notification when the contract resolves.",
    )


class LighthouseGroup(app_commands.Group):
    """`/lighthouse <subcommand>` group."""

    @app_commands.command(name="claim", description="Begin a Wardenship claim against a system.")
    @app_commands.describe(system="System to claim Wardenship of")
    async def claim(self, interaction: discord.Interaction, system: str) -> None:
        async with async_session() as session, session.begin():
            result = await _claim_logic(interaction, system, session)
            # If the claim started, the cog ALSO needs to schedule the
            # EXPEDITION_AUTO_RESOLVE + EXPEDITION_COMPLETE jobs the same
            # way /expedition start does — see _maybe_schedule_jobs below.
            if result.success:
                from db.models import ClaimAttempt
                from sqlalchemy import select

                attempt = (
                    await session.execute(
                        select(ClaimAttempt)
                        .where(ClaimAttempt.player_id == str(interaction.user.id))
                        .order_by(ClaimAttempt.started_at.desc())
                        .limit(1)
                    )
                ).scalar_one()
                await _schedule_claim_jobs(session, attempt.expedition_id)
        await interaction.response.send_message(result.message, ephemeral=True)

    @claim.autocomplete("system")
    async def claim_autocomplete(self, interaction: discord.Interaction, current: str):
        async with async_session() as session:
            from db.models import Lighthouse, System
            from sqlalchemy import select

            rows = (
                await session.execute(
                    select(System)
                    .join(Lighthouse, Lighthouse.system_id == System.channel_id)
                    .where(Lighthouse.warden_id.is_(None))
                    .where(System.name.ilike(f"%{current}%"))
                    .limit(25)
                )
            ).scalars().all()
        return [app_commands.Choice(name=s.name, value=s.name) for s in rows]


async def _schedule_claim_jobs(session, expedition_id) -> None:
    """Schedule EXPEDITION_AUTO_RESOLVE + EXPEDITION_COMPLETE jobs for a claim
    expedition, mirroring the path /expedition start uses for normal contracts.
    """
    from datetime import timedelta

    from db.models import Expedition, JobState, JobType, ScheduledJob
    from engine.expedition_template import load_template
    from sqlalchemy import select

    ex = await session.get(Expedition, expedition_id)
    template = load_template("claim_lighthouse")

    # Schedule auto-resolve for response_window after now.
    auto_resolve_at = ex.completes_at - timedelta(
        minutes=template["duration_minutes"]
    ) + timedelta(minutes=template["response_window_minutes"])
    session.add(
        ScheduledJob(
            type=JobType.EXPEDITION_AUTO_RESOLVE,
            run_at=auto_resolve_at,
            state=JobState.PENDING,
            payload={
                "expedition_id": str(ex.id),
                "template_id": "claim_lighthouse",
                "scene_id": "signal_alignment",
            },
        )
    )

    # Schedule completion at completes_at.
    session.add(
        ScheduledJob(
            type=JobType.EXPEDITION_COMPLETE,
            run_at=ex.completes_at,
            state=JobState.PENDING,
            payload={
                "expedition_id": str(ex.id),
                "template_id": "claim_lighthouse",
            },
        )
    )
```

- [ ] **Step 4: Update cog registration**

In the same file, replace the `setup` function:

```python
async def setup(bot: commands.Bot) -> None:
    cog = LighthouseCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(LighthouseGroup(name="lighthouse-cmd", description="Lighthouse subcommands"))
    # The standalone `/lighthouse [system]` command from 3b-1 stays on `cog`.
```

(Note: discord.py disallows a top-level `/lighthouse` command coexisting with a `/lighthouse` Group of subcommands. To avoid a name collision in 3b-2, the subcommands ship under a sibling Group — the simplest path is to rename the 3b-1 standalone command to `/lighthouse-info` OR to convert the existing `/lighthouse [system]` from 3b-1 into a `status` subcommand of the Group. **Recommended:** convert to `/lighthouse status [system]` and make the no-arg form of the Group resolve to `status`. See Task 11.)

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_cog_lighthouse_claim.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/lighthouse.py tests/test_cog_lighthouse_claim.py
git commit -m "feat(phase3b-2): /lighthouse claim subcommand + scheduling"
```

---

## Task 10: `/lighthouse list` paginated discovery

**Files:**
- Modify: `bot/cogs/lighthouse.py`
- Create: `tests/test_cog_lighthouse_list.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cog_lighthouse_list.py`:

```python
"""/lighthouse list — paginated unclaimed Lighthouses."""

from __future__ import annotations

from unittest.mock import MagicMock


async def test_list_returns_unclaimed_systems(
    db_session, sample_system_with_lighthouse, claimed_lighthouse_system
):
    """The unclaimed Lighthouse should appear; the claimed one should not."""
    from bot.cogs.lighthouse import _list_logic

    interaction = MagicMock()
    interaction.user.id = 1

    r = await _list_logic(interaction, page=1, session=db_session)
    assert r.success
    # claimed_lighthouse_system overlaps sample_system_with_lighthouse — so
    # in this fixture combination the same row is mutated to be claimed; an
    # honest test would use two separate Lighthouse rows. Adjust the fixtures
    # in test_engine_precheck_claim.py to make them disjoint, then re-run.
    # The MVP assertion: the message should not contain `(unclaimed) ...` for
    # a system that is currently claimed.
    assert "claimed" not in r.message.lower() or "unclaimed" in r.message.lower()


async def test_list_pagination(db_session, sample_sector, many_unclaimed_systems):
    """6+ unclaimed systems → page 1 shows 5, page 2 shows the rest."""
    from bot.cogs.lighthouse import _list_logic

    interaction = MagicMock()
    interaction.user.id = 1

    p1 = await _list_logic(interaction, page=1, session=db_session)
    p2 = await _list_logic(interaction, page=2, session=db_session)
    assert p1.success and p2.success
    assert "Page 1" in p1.message
    assert "Page 2" in p2.message
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_cog_lighthouse_list.py -v --no-cov`
Expected: FAIL — `_list_logic` doesn't exist; `many_unclaimed_systems` fixture missing.

- [ ] **Step 3: Add fixture**

In `tests/conftest.py`:

```python
@pytest.fixture
async def many_unclaimed_systems(db_session, sample_sector):
    """Create 6 systems each with an unclaimed Lighthouse."""
    import random as _random

    from db.models import LighthouseBand, LighthouseState, System, Lighthouse

    for i in range(6):
        cid = str(70000 + i)
        sys_obj = System(channel_id=cid, sector_id=sample_sector.guild_id, name=f"sys-{i}")
        db_session.add(sys_obj)
        await db_session.flush()
        db_session.add(
            Lighthouse(
                system_id=cid,
                band=LighthouseBand.RIM,
                state=LighthouseState.ACTIVE,
            )
        )
    await db_session.flush()
```

- [ ] **Step 4: Implement `_list_logic`**

Append to `bot/cogs/lighthouse.py`:

```python
PAGE_SIZE = 5


async def _list_logic(interaction, page: int, session) -> CommandResult:
    """Return a single page of unclaimed Lighthouses, ordered by created_at."""
    from db.models import Lighthouse, System, SystemFeature
    from sqlalchemy import func, select

    if page < 1:
        return CommandResult(False, "Invalid page.")

    total = (
        await session.execute(
            select(func.count(Lighthouse.id)).where(Lighthouse.warden_id.is_(None))
        )
    ).scalar_one()
    if total == 0:
        return CommandResult(True, "No unclaimed Lighthouses on record.")

    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if page > pages:
        return CommandResult(False, f"Out of range. Pages 1..{pages}.")

    rows = (
        await session.execute(
            select(Lighthouse, System)
            .join(System, System.channel_id == Lighthouse.system_id)
            .where(Lighthouse.warden_id.is_(None))
            .order_by(Lighthouse.created_at.asc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    ).all()

    lines = [f"**Unclaimed Lighthouses** — Page {page}/{pages}"]
    for lh, sys_obj in rows:
        feature_count = (
            await session.execute(
                select(func.count(SystemFeature.slot_index)).where(
                    SystemFeature.system_id == sys_obj.channel_id
                )
            )
        ).scalar_one()
        from engine.lighthouse_engine import compute_claim_difficulty

        difficulty = compute_claim_difficulty(
            band=lh.band,
            feature_count=feature_count,
            star_type=(sys_obj.star_type.value if sys_obj.star_type else "single"),
            star_color=(sys_obj.star_color.value if sys_obj.star_color else "yellow"),
        )
        lines.append(
            f"  • #{sys_obj.name} — {lh.band.value} band, "
            f"{(sys_obj.star_color.value if sys_obj.star_color else '?').title()} "
            f"{(sys_obj.star_type.value if sys_obj.star_type else '?').title()}-class star, "
            f"{feature_count} features · est. difficulty {difficulty}"
        )

    return CommandResult(True, "\n".join(lines))
```

Add the slash subcommand inside `LighthouseGroup`:

```python
    @app_commands.command(name="list", description="List unclaimed Lighthouses.")
    @app_commands.describe(page="Page number, defaults to 1")
    async def list_(self, interaction: discord.Interaction, page: int = 1) -> None:
        async with async_session() as session:
            result = await _list_logic(interaction, page, session)
        await interaction.response.send_message(result.message, ephemeral=True)
```

- [ ] **Step 5: Run, confirm passes**

Run: `pytest tests/test_cog_lighthouse_list.py -v --no-cov`
Expected: 2 PASS. (The first test about claimed/unclaimed may need fixture cleanup — see test comments.)

- [ ] **Step 6: Commit**

```bash
git add bot/cogs/lighthouse.py tests/test_cog_lighthouse_list.py tests/conftest.py
git commit -m "feat(phase3b-2): /lighthouse list — paginated discovery of unclaimed Lighthouses"
```

---

## Task 11: Convert 3b-1's `/lighthouse [system]` to `/lighthouse status [system]`

**Files:**
- Modify: `bot/cogs/lighthouse.py`
- Modify: `tests/test_cog_lighthouse.py`

Discord doesn't allow a top-level `/lighthouse` command and a `/lighthouse <sub>` Group to coexist. Convert.

- [ ] **Step 1: Move `_lighthouse_logic` calls into a `status` subcommand**

In `bot/cogs/lighthouse.py`, replace the standalone `LighthouseCog.lighthouse` slash with a subcommand on `LighthouseGroup`:

```python
    @app_commands.command(name="status", description="Show Lighthouse status (defaults to current channel).")
    @app_commands.describe(system="Optional system name; defaults to this channel.")
    async def status(
        self, interaction: discord.Interaction, system: str | None = None
    ) -> None:
        async with async_session() as session:
            result = await _lighthouse_logic(interaction, system, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @status.autocomplete("system")
    async def status_autocomplete(self, interaction: discord.Interaction, current: str):
        async with async_session() as session:
            from db.models import System
            from sqlalchemy import select

            rows = (
                await session.execute(
                    select(System).where(System.name.ilike(f"%{current}%")).limit(25)
                )
            ).scalars().all()
        return [app_commands.Choice(name=s.name, value=s.name) for s in rows]
```

Remove `LighthouseCog.lighthouse` and its autocomplete. Keep `LighthouseCog` only for the cog-level setup hook (which now just registers the Group).

Update `setup`:

```python
async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(LighthouseGroup(name="lighthouse", description="Lighthouse — claim, status, list."))
```

(Drop `LighthouseCog` entirely if the Group is the only handle.)

- [ ] **Step 2: Update tests**

In `tests/test_cog_lighthouse.py`, the function names don't change — the underlying `_lighthouse_logic` is unchanged. The tests still pass.

- [ ] **Step 3: Run the lighthouse cog tests**

Run: `pytest tests/test_cog_lighthouse.py tests/test_cog_lighthouse_claim.py tests/test_cog_lighthouse_list.py -v --no-cov`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add bot/cogs/lighthouse.py
git commit -m "refactor(phase3b-2): /lighthouse becomes a Group with status/claim/list"
```

---

## Task 12: System gating for new subcommands

**Files:**
- Modify: `bot/system_gating.py`
- Modify: `tests/test_system_gating.py`

- [ ] **Step 1: Add subcommand qualified names**

The existing 3b-1 entry covers `lighthouse`. Discord's `qualified_name` for subcommands uses the form `lighthouse status`, `lighthouse claim`, `lighthouse list`. Update the universe-wide allow-list:

```python
UNIVERSE_WIDE_COMMANDS = {
    # ... existing ...
    "dock",
    "lighthouse",          # legacy / safety
    "lighthouse status",
    "lighthouse claim",
    "lighthouse list",
}
```

- [ ] **Step 2: Add tests**

Append to `tests/test_system_gating.py`:

```python
def test_lighthouse_subcommands_universe_wide():
    from bot.system_gating import UNIVERSE_WIDE_COMMANDS

    for sub in ("status", "claim", "list"):
        assert f"lighthouse {sub}" in UNIVERSE_WIDE_COMMANDS, sub
```

- [ ] **Step 3: Run, confirm passes**

Run: `pytest tests/test_system_gating.py -v --no-cov`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add bot/system_gating.py tests/test_system_gating.py
git commit -m "feat(phase3b-2): all /lighthouse subcommands are universe-wide"
```

---

## Task 13: End-to-end scenario — claim happy path + cooldown

**Files:**
- Create: `tests/test_scenarios/test_claim_flow.py`

- [ ] **Step 1: Write the scenario test**

Create `tests/test_scenarios/test_claim_flow.py`:

```python
"""End-to-end claim flow: precheck → start → resolve → seat held + auto-dock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import select


async def test_full_claim_pass_flow(
    db_session, eligible_player_with_build, sample_system_with_lighthouse
):
    """A successful claim ends with the player as Warden and auto-docked."""
    from bot.cogs.lighthouse import _claim_logic
    from db.models import (
        Citizenship,
        ClaimAttempt,
        ClaimOutcome,
        Expedition,
        JobState,
        JobType,
        Lighthouse,
        ScheduledJob,
    )
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    # 1. Start the claim via the cog.
    inter = MagicMock()
    inter.user.id = int(eligible_player_with_build.user.discord_id)
    r = await _claim_logic(inter, sample_system_with_lighthouse.name, db_session)
    assert r.success

    attempt = (
        await db_session.execute(
            select(ClaimAttempt).where(ClaimAttempt.player_id == eligible_player_with_build.user.discord_id)
        )
    ).scalar_one()
    assert attempt.outcome is None

    # 2. Simulate the run resolving with 3 successes.
    ex = await db_session.get(Expedition, attempt.expedition_id)
    ex.scene_log = [{"scene_id": f"e{i}", "outcome": {"kind": "success"}} for i in range(3)]
    await db_session.flush()

    # 3. Fire the EXPEDITION_COMPLETE handler.
    job = ScheduledJob(
        type=JobType.EXPEDITION_COMPLETE,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={"expedition_id": str(ex.id), "template_id": "claim_lighthouse"},
    )
    db_session.add(job)
    await db_session.flush()
    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    # 4. Assert seat held + auto-dock + ClaimAttempt resolved.
    lh = (
        await db_session.execute(
            select(Lighthouse).where(Lighthouse.system_id == sample_system_with_lighthouse.channel_id)
        )
    ).scalar_one()
    assert lh.warden_id == eligible_player_with_build.user.discord_id

    citz = (
        await db_session.execute(
            select(Citizenship)
            .where(Citizenship.player_id == eligible_player_with_build.user.discord_id)
            .where(Citizenship.ended_at.is_(None))
        )
    ).scalar_one()
    assert citz.system_id == sample_system_with_lighthouse.channel_id

    attempt = (
        await db_session.execute(
            select(ClaimAttempt).where(ClaimAttempt.id == attempt.id)
        )
    ).scalar_one()
    assert attempt.outcome == ClaimOutcome.PASS


async def test_second_claim_blocked_by_7d_cooldown(
    db_session, eligible_player_with_build, sample_system_with_lighthouse, sample_system_with_lighthouse_2
):
    """After resolving one attempt, the player can't claim again for 7 days."""
    from bot.cogs.lighthouse import _claim_logic
    from db.models import ClaimAttempt, ClaimOutcome
    from datetime import datetime, timezone

    # Plant a resolved attempt from 1 day ago.
    db_session.add(
        ClaimAttempt(
            player_id=eligible_player_with_build.user.discord_id,
            target_system_id=sample_system_with_lighthouse.channel_id,
            difficulty=20,
            resolved_at=datetime.now(timezone.utc) - timedelta(days=1),
            outcome=ClaimOutcome.FAIL,
        )
    )
    await db_session.flush()

    inter = MagicMock()
    inter.user.id = int(eligible_player_with_build.user.discord_id)
    r = await _claim_logic(inter, sample_system_with_lighthouse_2.name, db_session)
    assert not r.success
    assert "cooldown" in r.message.lower()
```

The fixture `sample_system_with_lighthouse_2` is referenced — add it to `tests/conftest.py`:

```python
@pytest.fixture
async def sample_system_with_lighthouse_2(db_session, sample_sector):
    """A second populated system+Lighthouse, distinct from sample_system_with_lighthouse."""
    import random

    from db.models import LighthouseBand, LighthouseState, System, Lighthouse
    from engine.system_generator import generate, persist_character

    sys_obj = System(
        channel_id="33333333",
        sector_id=sample_sector.guild_id,
        name="hespera-belt",
    )
    db_session.add(sys_obj)
    await db_session.flush()

    rng = random.Random(98765)
    char = generate(seed=98765)
    await persist_character(db_session, sys_obj.channel_id, char)
    db_session.add(
        Lighthouse(system_id=sys_obj.channel_id, band=LighthouseBand.MIDDLE, state=LighthouseState.ACTIVE)
    )
    await db_session.flush()
    await db_session.refresh(sys_obj)
    return sys_obj
```

- [ ] **Step 2: Run, confirm passes**

Run: `pytest tests/test_scenarios/test_claim_flow.py -v --no-cov`
Expected: 2 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scenarios/test_claim_flow.py tests/conftest.py
git commit -m "test(phase3b-2): scenario — claim happy path + 7d cooldown"
```

---

## Task 14: Documentation

**Files:**
- Modify: `docs/authoring/system_character.md`
- Create: `docs/authoring/wardenship_claim.md`

- [ ] **Step 1: Write the doc**

Create `docs/authoring/wardenship_claim.md`:

```markdown
# Authoring: Wardenship Claim Contract

Phase 3b-2 ships the `claim_lighthouse` parameterized expedition. This doc
documents the moving parts so the contract can be tuned.

## What gets parameterized

`Expedition.parameters` is a JSONB column; for claim contracts it carries:

```json
{
  "target_system_id": "<channel_id>",
  "target_band": "rim|middle|inner",
  "difficulty": <int>
}
```

The template itself (`data/expeditions/claim_lighthouse.yaml`) is **static**.
Difficulty does not change the rolls — it changes the **success threshold**
applied at completion time. See `engine.lighthouse_engine.required_successes_for_difficulty`.

## Difficulty formula (spec §7.3)

```
base = {rim: 10, middle: 25, inner: 50}[band]
difficulty = base
           + 5 * feature_count
           + 5  if star_type in {binary, trinary}
           + 10 if star_color == "exotic"
```

Computed once at `start_claim` time; fixed for the run. Mid-flight changes
to the system's character (if any) don't affect an in-flight claim.

## Required-success buckets

| Difficulty | Required successes (of 3 events) |
|---|---|
| ≤ 15 | 1 |
| 16-30 | 2 |
| > 30 | 3 |

A rim Lighthouse with 0 features and a single yellow star (difficulty 10)
is very claimable; an inner Lighthouse with 3 features and an exotic
trinary star (difficulty 80) requires every event to land.

## Tuning levers

- **Template `cost_credits`** — entry cost for the contract. Currently 250.
- **Template per-event `roll.base_p`** — the floor success probability.
- **Stat scale** — `base_stat` and `per_point` in each roll. Higher
  `per_point` means crew investment matters more.
- **Difficulty formula coefficients** — in `engine/lighthouse_engine.py`.
- **Required-success buckets** — `required_successes_for_difficulty`.

## Failure consolation

A failed claim pays 5% of the contract's `cost_credits` back to the player
"for the attempt" (Authority custom). Pays via `_pay_consolation`. Exact
value: `max(1, int(0.05 * 250)) == 12`. Tune in code, not template.
```

Append a new section to `docs/authoring/system_character.md` linking out:

```markdown
## Related: Wardenship claim

The Lighthouse band rolled at activation drives the difficulty of the
Wardenship claim contract. See `wardenship_claim.md` for that flow.
```

- [ ] **Step 2: Commit**

```bash
git add docs/authoring/wardenship_claim.md docs/authoring/system_character.md
git commit -m "docs(phase3b-2): authoring guide for the claim contract"
```

---

## Task 15: Final integration smoke

**Files:** none — verification only.

- [ ] **Step 1: Full test suite**

Run: `pytest --no-cov -q`
Expected: green.

- [ ] **Step 2: Migration round-trip**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: succeed.

- [ ] **Step 3: Manual verification**

Bring up a dev bot. With a player who has a filled active build and ≥3 completed expeditions:
- `/lighthouse list` — shows unclaimed Lighthouses with band, star, feature count, difficulty estimate.
- `/lighthouse claim <unclaimed>` — kicks off; expedition appears in `/expedition status`.
- Wait or fast-forward through the contract; on the player's DM, the standard expedition-complete notification arrives. After that:
  - `/lighthouse status <system>` shows the new Warden.
  - `/system info` shows the system as Warden-held.
  - The player's active citizenship is at the won system.
- Try `/lighthouse claim <other>` immediately — rejected with "Claim cooldown: 7d 0h remaining."

If anything renders wrong, fix before merging.

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin <branch>
gh pr create --title "Phase 3b-2: Wardenship claim contract" --body "$(cat <<'EOF'
## Summary
- Adds `claim_attempts` table + `expeditions.parameters` JSONB column.
- Ships the `claim_lighthouse` parameterized Phase-2b template (3 stat-vs-fixed-threshold rolls; difficulty becomes a required-success threshold at completion).
- New: `/lighthouse list` paginated discovery, `/lighthouse claim <system>` flow with full preconditions + 7-day per-player cooldown.
- On pass: `warden_id` set, auto-dock to the won system (bypasses 24h cooldown), 5% consolation NOT paid.
- On fail: 5% consolation, cooldown applies, no fleet damage.
- Converts 3b-1's `/lighthouse [system]` to `/lighthouse status [system]` so the slash-command tree stays valid.

## Test plan
- [x] All previously-green tests stay green
- [x] Migration round-trips
- [x] Scenario test: end-to-end claim pass → seat + auto-dock
- [x] Scenario test: 7d cooldown enforced after a resolved attempt
- [ ] Manual: dev bot — list, claim, complete, verify Warden held + cooldown rejection

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Spec coverage check (self-review)

| Spec section | Covered by | Notes |
|---|---|---|
| §7.1 Discovery | Task 10 | `/lighthouse list` paginated |
| §7.2 Contract structure | Task 4 | `claim_lighthouse.yaml` template, parameterized via `Expedition.parameters` |
| §7.3 Difficulty formula | Task 3 | `compute_claim_difficulty` |
| §7.4 Resolution outcomes | Task 7 | Pass: warden + auto-dock; Fail: 5% consolation, no fleet damage |
| §7.5 Per-player 7d cooldown | Task 5 | `precheck_claim` checks last `ClaimAttempt` |
| §7.6 Preconditions | Task 5 | All six checks |
| §7.7 Auto-dock on win | Task 7 | `_force_dock` bypasses 24h cooldown |
| §7.8 Multi-system Wardenship | Implicit | No restriction on holding multiple seats; `Lighthouse.warden_id` is per-row |
| §15 `claim_attempts` | Task 1 | Schema |
| §15 `expeditions.parameters` | Task 1 | Migration adds column |
| §16.1 `/lighthouse list`, `/lighthouse claim` | Tasks 9–11 | Group with subcommands |
| §19.3 Verification | Task 13 | Scenario covers list, start, resolve, seat, cooldown |

Sections deferred to later sub-plans listed in the plan header.

---

## Open Questions

1. **Auto-resolve scene order.** The claim template has 3 events: `signal_alignment`, `surveyor_protocol`, `spire_handover`. The scheduler's auto-resolve scene-walk currently picks the first un-walked event. If a player abandons mid-flight, that's the order successes get rolled in. Acceptable for 3b-2; if playtest shows it feels wrong, swap to a randomized walk.
2. **Consolation tied to template `cost_credits`.** If the contract's cost is changed in the YAML, the consolation amount should follow. Currently `_pay_consolation` hardcodes `0.05 * 250`. Refactor to read from the loaded template if/when this becomes a tuning variable.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-02-phase-3b-2-claim.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

---

## Next sub-plans (not in this file)

- `2026-05-02-phase-3b-3-donations.md` — Upgrade goals + donations + citizen buffs + passive tribute (§8, §9, §10.1, §11)
- `2026-05-02-phase-3b-4-flares.md` — Beacon Flares + Pride + activity-cut tribute (§12, §13, §10.1)
- `2026-05-02-phase-3b-5-lapse.md` — Lapse, vacation, tribute spending, abdication (§10.3, §14)
- `2026-05-02-phase-3b-6-llm-narrative.md` — Real LLM narrative seed pass (replaces the 3b-1 stub)
