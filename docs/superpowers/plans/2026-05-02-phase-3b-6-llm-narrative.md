# Phase 3b-6 — Runtime LLM Narrative Seed Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic templated paragraph from `engine/system_narrative.py::generate_flavor` (shipped in 3b-1) with a real LLM-generated paragraph that draws on the structured system character data, the canonical setting voice from `docs/lore/setting.md`, and per-system context. Activation enqueues a `system_narrative_seed` scheduler job; on success the system's `flavor_text` is replaced; on failure the deterministic stub remains in place. **Players never see a blank channel.** This is the final sub-plan in the Phase 3b arc; with 3b-1..6 shipped, the entire Phase 3b feature set is live.

**Architecture:**
- Add the Anthropic SDK (`anthropic`) and a single API key setting (`ANTHROPIC_API_KEY`) to `config/settings.py`. The model is `claude-haiku-4-5-20251001` — small/fast/cheap is the right shape for two-paragraph flavor text. Defer to a Sonnet/Opus tier only if playtest shows Haiku missing the voice.
- **Prompt caching is mandatory.** The setting voice (`docs/lore/setting.md`, ~206 lines / ~6-8k tokens) is the cacheable system block; the per-system data (star, planets, features, sector name) is the per-request user block. Cache breakpoint at the end of the system block; per-request block stays small (~200 tokens) and uncached. Hit rate target: >95% across the first day's activations of any given sector.
- One new column on `systems`: `flavor_text_status` (enum: `stub | generated | failed`). Tracks which version of the paragraph is currently stored. Activation writes `stub` (with the deterministic placeholder); the job flips to `generated` on success or `failed` on terminal failure (with the stub still in place). Migration `0011_phase3b_6_llm_narrative`.
- One new column on `systems`: `flavor_text_attempts` (int) — counts the LLM job's retry budget. Bounded at 3; the job retries with exponential backoff if it transiently fails (rate limit, network), but a 4xx response (e.g. policy block, malformed input) marks `failed` immediately.
- `engine/system_narrative.py` keeps `generate_flavor` as the deterministic stub fallback. A new `generate_flavor_llm(character, sector_name, *, anthropic_client) -> str` builds the prompt and returns the model output. Both functions are pure (no DB), so the scheduler job is the only DB writer.
- `scheduler/jobs/system_narrative_seed.py` is the new handler. Reads the system, builds the prompt from persisted star/planet/feature rows, calls Anthropic with prompt caching, writes the result + `flavor_text_status='generated'` on success, schedules a retry on transient failure, marks `failed` after 3 attempts. Idempotent — re-running on a system that already has `generated` is a no-op.
- `bot/cogs/admin.py::_system_enable_logic` keeps writing the stub *first* (so the system is immediately playable), then enqueues a `SYSTEM_NARRATIVE_SEED` job. The same enqueue is also called from a one-off backfill script (`scripts/backfill_llm_flavor.py`) to upgrade existing systems whose `flavor_text_status` is `stub`.
- `/system info` and `/lighthouse status` already render `flavor_text` verbatim — no UI changes needed. A single subtle indicator: when `flavor_text_status == 'stub'`, the embed footer notes "narrative pending" so players know the LLM pass is in flight.

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, Alembic, asyncpg, discord.py 2.x, pytest + pytest-asyncio, **NEW: `anthropic` SDK** (latest 1.x). Anthropic API key required at runtime.

**Spec:** [docs/roadmap/2026-05-02-phase-3b-lighthouses-design.md](../../roadmap/2026-05-02-phase-3b-lighthouses-design.md) §4.4 (LLM narrative pass) and §4.6 (activation flow — "If the LLM job fails, a placeholder paragraph is stored and a retry is scheduled"). The decision to defer this to a follow-on sub-plan was made in 3b-1 ([Open Question §1, marked DECIDED](docs/superpowers/plans/2026-05-02-phase-3b-1-foundation.md#open-questions)).

**Depends on:** 3b-1 (system_narrative stub + activation hook + flavor_text column), 3b-5 (the most recent migration — `0010_phase3b_5_lapse`).

**Independent of:** 3b-2 (claim), 3b-3 (donations), 3b-4 (flares), 3b-5 (lapse). 3b-6 can ship in any order after 3b-1 lands; placing it last per the [3b-1 decision](docs/superpowers/plans/2026-05-02-phase-3b-1-foundation.md#open-questions) means the prompt can be informed by what flares/donations/Pride actually surface in-game.

**Dev loop:** Same as prior. Plus: `ANTHROPIC_API_KEY` must be set in `.env` for the live job tests; the unit tests use a mocked Anthropic client.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `db/migrations/versions/0011_phase3b_6_llm_narrative.py` | `flavor_text_status` enum + column; `flavor_text_attempts` int column; `JobType.SYSTEM_NARRATIVE_SEED` |
| `scheduler/jobs/system_narrative_seed.py` | Handler: build prompt, call Anthropic with caching, write result, retry on transient failure |
| `scripts/backfill_llm_flavor.py` | One-off: enqueue the job for every existing system with `flavor_text_status='stub'` |
| `tests/test_phase3b_6_migration.py` | Schema round-trip |
| `tests/test_engine_system_narrative_llm.py` | Prompt-builder shape tests + mocked-client roundtrip |
| `tests/test_handler_system_narrative_seed.py` | Success / transient retry / terminal failure paths |
| `tests/test_scenarios/test_activation_with_llm.py` | End-to-end: enable system → stub stored immediately → job runs → `generated` replaces stub |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Add `anthropic` dependency |
| `config/settings.py` | Add `ANTHROPIC_API_KEY` and `LLM_NARRATIVE_MODEL` (default `claude-haiku-4-5-20251001`) |
| `db/models.py` | Add `FlavorTextStatus` enum; extend `System` with `flavor_text_status` + `flavor_text_attempts`; extend `JobType` with `SYSTEM_NARRATIVE_SEED` |
| `engine/system_narrative.py` | Add `generate_flavor_llm` + `build_prompt`; keep `generate_flavor` as stub fallback |
| `bot/cogs/admin.py` | `_system_enable_logic` enqueues SYSTEM_NARRATIVE_SEED job after writing the stub; sets `flavor_text_status='stub'` |
| `bot/main.py` | Register the handler import side-effect; instantiate the Anthropic client at startup and stash on the bot for the handler to read |
| `bot/cogs/lighthouse.py` | When rendering Status, append "narrative pending" footer if `flavor_text_status == 'stub'` |
| `bot/cogs/admin.py` | Same footer note in `/system info` |

---

## Task 1: Migration 0011 — `flavor_text_status` column + enum

**Files:**
- Create: `db/migrations/versions/0011_phase3b_6_llm_narrative.py`
- Create: `tests/test_phase3b_6_migration.py`

- [ ] **Step 1: Write the failing test**

```python
"""Phase 3b-6 migration: flavor_text_status enum + column + retry counter + jobtype value."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def test_flavor_text_status_enum(db_session):
    rows = (
        await db_session.execute(
            text("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                 "WHERE t.typname = 'flavor_text_status' ORDER BY enumlabel")
        )
    ).scalars().all()
    assert set(rows) == {"stub", "generated", "failed"}


async def test_systems_flavor_text_columns(db_session):
    insp = await db_session.run_sync(lambda c: inspect(c.bind))
    cols = {c["name"] for c in insp.get_columns("systems")}
    assert "flavor_text_status" in cols
    assert "flavor_text_attempts" in cols


async def test_jobtype_has_system_narrative_seed(db_session):
    rows = (
        await db_session.execute(
            text("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                 "WHERE t.typname = 'jobtype'")
        )
    ).scalars().all()
    assert "system_narrative_seed" in set(rows)
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Write the migration**

Create `db/migrations/versions/0011_phase3b_6_llm_narrative.py`:

```python
"""Phase 3b-6 — Runtime LLM narrative seed.

Revision ID: 0011_phase3b_6_llm_narrative
Revises: 0010_phase3b_5_lapse
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_phase3b_6_llm_narrative"
down_revision = "0010_phase3b_5_lapse"
branch_labels = None
depends_on = None


FLAVOR_TEXT_STATUS = postgresql.ENUM(
    "stub", "generated", "failed", name="flavor_text_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    FLAVOR_TEXT_STATUS.create(bind, checkfirst=True)

    op.add_column(
        "systems",
        sa.Column(
            "flavor_text_status",
            postgresql.ENUM(name="flavor_text_status", create_type=False),
            nullable=False,
            server_default="stub",
        ),
    )
    op.add_column(
        "systems",
        sa.Column(
            "flavor_text_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'system_narrative_seed'")

    # Backfill: every existing system already has its 3b-1 deterministic
    # stub in flavor_text. Mark them all `stub` so the backfill script can
    # find them and enqueue LLM upgrades.
    op.execute(
        "UPDATE systems SET flavor_text_status = 'stub' WHERE flavor_text IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("systems", "flavor_text_attempts")
    op.drop_column("systems", "flavor_text_status")
    bind = op.get_bind()
    FLAVOR_TEXT_STATUS.drop(bind, checkfirst=True)
```

- [ ] **Step 4: Run, confirm passes + round-trip**

- [ ] **Step 5: Commit**

```bash
git add db/migrations/versions/0011_phase3b_6_llm_narrative.py tests/test_phase3b_6_migration.py
git commit -m "feat(phase3b-6): schema for LLM-narrative status + retry counter"
```

---

## Task 2: Add Anthropic SDK + settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to dependencies:

```toml
"anthropic>=0.40.0",
```

(Pin to the latest 0.x at plan-execution time — the SDK's prompt-caching API has been stable since mid-2024.)

Run: `uv sync` (or `pip install -e .`) to install.

- [ ] **Step 2: Add settings**

In `config/settings.py`, in `Settings`:

```python
    # Phase 3b-6 — LLM narrative seed
    ANTHROPIC_API_KEY: str = ""
    LLM_NARRATIVE_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_NARRATIVE_MAX_TOKENS: int = 600
    LLM_NARRATIVE_REQUEST_TIMEOUT_SECONDS: int = 30
    LLM_NARRATIVE_MAX_ATTEMPTS: int = 3
```

In `.env.example`:

```
# Phase 3b-6 — LLM narrative seed
ANTHROPIC_API_KEY=
# Optional overrides
# LLM_NARRATIVE_MODEL=claude-haiku-4-5-20251001
# LLM_NARRATIVE_MAX_TOKENS=600
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml config/settings.py .env.example
git commit -m "feat(phase3b-6): add anthropic SDK + LLM narrative settings"
```

---

## Task 3: ORM extensions

**Files:**
- Modify: `db/models.py`

- [ ] **Step 1: Add enum + columns**

```python
class FlavorTextStatus(str, enum.Enum):
    STUB = "stub"
    GENERATED = "generated"
    FAILED = "failed"
```

Extend `System`:

```python
    flavor_text_status: Mapped[FlavorTextStatus] = mapped_column(
        Enum(FlavorTextStatus, values_callable=lambda x: [e.value for e in x], name="flavor_text_status"),
        nullable=False,
        default=FlavorTextStatus.STUB,
        server_default=FlavorTextStatus.STUB.value,
    )
    flavor_text_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
```

Extend `JobType`:

```python
    SYSTEM_NARRATIVE_SEED = "system_narrative_seed"
```

- [ ] **Step 2: Commit**

```bash
git add db/models.py
git commit -m "feat(phase3b-6): ORM extensions for flavor_text_status + attempts"
```

---

## Task 4: Prompt builder + LLM call helper

**Files:**
- Modify: `engine/system_narrative.py`
- Create: `tests/test_engine_system_narrative_llm.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_system_narrative_llm.py`:

```python
"""Prompt builder + mocked Anthropic call."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def _sample_character(seed=42):
    from engine.system_generator import generate
    return generate(seed=seed)


def test_build_prompt_includes_setting_voice():
    from engine.system_narrative import build_prompt

    char = _sample_character()
    parts = build_prompt(char, sector_name="Marquee")
    # System block (cacheable) is the setting voice; user block (per-request)
    # is the structured character data.
    assert "encyclopedic" in parts.system_voice.lower() or "captain" in parts.system_voice.lower()
    assert char.star.color in parts.user_data
    for p in char.planets:
        assert p.name in parts.user_data
    assert "Marquee" in parts.user_data


def test_build_prompt_marks_system_block_for_cache():
    from engine.system_narrative import build_prompt

    parts = build_prompt(_sample_character(), sector_name="Marquee")
    # The shape we hand to anthropic.messages.create — the system block is
    # a list with `type: ephemeral` cache_control on the setting voice.
    msg = parts.to_anthropic_kwargs()
    assert isinstance(msg["system"], list)
    last_block = msg["system"][-1]
    assert last_block.get("cache_control", {}).get("type") == "ephemeral"


async def test_generate_flavor_llm_uses_mocked_client_and_returns_text():
    from engine.system_narrative import generate_flavor_llm

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="A wind-scoured rim system with three planets and a mood.")]
    fake_response.usage = MagicMock(
        input_tokens=2000, output_tokens=120, cache_read_input_tokens=1800, cache_creation_input_tokens=0
    )
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    text = await generate_flavor_llm(
        _sample_character(), sector_name="Marquee", anthropic_client=fake_client
    )
    assert text == "A wind-scoured rim system with three planets and a mood."
    fake_client.messages.create.assert_awaited_once()


async def test_generate_flavor_llm_strips_whitespace():
    from engine.system_narrative import generate_flavor_llm

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="\n   the body  \n  ")]
    fake_response.usage = MagicMock(
        input_tokens=2000, output_tokens=10, cache_read_input_tokens=1800, cache_creation_input_tokens=0
    )
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    text = await generate_flavor_llm(
        _sample_character(), sector_name="Marquee", anthropic_client=fake_client
    )
    assert text == "the body"
```

- [ ] **Step 2: Run, confirm fails**

Run: `pytest tests/test_engine_system_narrative_llm.py -v --no-cov`
Expected: FAIL.

- [ ] **Step 3: Add the prompt builder + LLM call**

Append to `engine/system_narrative.py`:

```python
# ──────────── Phase 3b-6: runtime LLM narrative ────────────

from dataclasses import dataclass
from pathlib import Path

_SETTING_VOICE_PATH = Path(__file__).parent.parent / "docs" / "lore" / "setting.md"


def _load_setting_voice() -> str:
    return _SETTING_VOICE_PATH.read_text(encoding="utf-8")


# Loaded once at import — file lives in repo, not a hot path.
_SETTING_VOICE = _load_setting_voice()


@dataclass(frozen=True)
class _PromptParts:
    system_voice: str
    user_data: str

    def to_anthropic_kwargs(self) -> dict:
        """Return kwargs for `client.messages.create(...)`.

        The system block is a list of two parts:
          1. A short instruction prefix (uncached — small).
          2. The setting voice (cached — large, stable).

        Cache breakpoint goes on the setting voice block. The per-request
        user_data lands as a single user message.
        """
        return {
            "system": [
                {
                    "type": "text",
                    "text": (
                        "You write short flavor paragraphs (2-4 sentences) for newly-charted "
                        "star systems in the game Dare2Drive. Match the encyclopedic-yet-grounded "
                        "voice from the setting document below. Output the paragraph only — no "
                        "preamble, no headers, no quotes."
                    ),
                },
                {
                    "type": "text",
                    "text": self.system_voice,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {"role": "user", "content": self.user_data},
            ],
        }


def build_prompt(character: SystemCharacter, sector_name: str = "") -> _PromptParts:
    """Build the LLM prompt parts for a system character.

    The system block holds the cacheable setting voice. The user block holds
    the structured per-system data (small, per-request, not cached).
    """
    sector = sector_name.strip() or "an unnamed sector"
    lines = [
        f"Sector: {sector}",
        f"Star: {character.star.color} {character.star.type}-class, {character.star.age}",
        f"Planet count: {len(character.planets)}",
    ]
    for i, p in enumerate(character.planets):
        lines.append(
            f"  Planet {i+1}: {p.name} — {p.size} {p.planet_type}, "
            f"{p.richness} richness — {p.descriptor}"
        )
    if character.features:
        lines.append(f"Features ({len(character.features)}):")
        for f in character.features:
            lines.append(f"  {f.name} ({f.feature_type}) — {f.descriptor}")
    else:
        lines.append("Features: none charted")

    lines.append("")
    lines.append(
        "Write the flavor paragraph for this system. 2-4 sentences. "
        "Mention the system's signature detail. Encyclopedic tone, captain perspective."
    )

    return _PromptParts(system_voice=_SETTING_VOICE, user_data="\n".join(lines))


async def generate_flavor_llm(
    character: SystemCharacter,
    sector_name: str,
    *,
    anthropic_client,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Call Anthropic to generate a flavor paragraph. Pure (no DB writes).

    Raises whatever the SDK raises on transient or terminal failure — the
    handler in scheduler/jobs/system_narrative_seed.py decides retry policy.
    """
    from config.settings import settings as _settings

    parts = build_prompt(character, sector_name=sector_name)
    response = await anthropic_client.messages.create(
        model=model or _settings.LLM_NARRATIVE_MODEL,
        max_tokens=max_tokens or _settings.LLM_NARRATIVE_MAX_TOKENS,
        **parts.to_anthropic_kwargs(),
    )

    # Concatenate text blocks (Anthropic returns a list).
    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    return "".join(text_parts).strip()
```

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_engine_system_narrative_llm.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/system_narrative.py tests/test_engine_system_narrative_llm.py
git commit -m "feat(phase3b-6): LLM prompt builder + generate_flavor_llm with prompt caching"
```

---

## Task 5: Scheduler handler — `system_narrative_seed`

**Files:**
- Create: `scheduler/jobs/system_narrative_seed.py`
- Create: `tests/test_handler_system_narrative_seed.py`

- [ ] **Step 1: Write the failing test**

```python
"""system_narrative_seed handler — success / transient retry / terminal failure."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


async def test_handler_writes_generated_text_on_success(
    db_session, sample_system_with_lighthouse
):
    from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob, System
    from scheduler.jobs.system_narrative_seed import handle_system_narrative_seed
    from sqlalchemy import select

    # Set a stub flavor for the system to start.
    sys_obj = await db_session.get(System, sample_system_with_lighthouse.channel_id)
    sys_obj.flavor_text = "stub paragraph"
    sys_obj.flavor_text_status = FlavorTextStatus.STUB
    await db_session.flush()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="A wind-haunted rim system, three worlds, an old derelict.")]
    fake_response.usage = MagicMock(
        input_tokens=2200, output_tokens=140, cache_read_input_tokens=2000, cache_creation_input_tokens=0
    )
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    job = ScheduledJob(
        type=JobType.SYSTEM_NARRATIVE_SEED,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={"system_id": sample_system_with_lighthouse.channel_id},
    )
    db_session.add(job)
    await db_session.flush()

    await handle_system_narrative_seed(db_session, job, anthropic_client=fake_client)
    await db_session.flush()
    await db_session.refresh(sys_obj)

    assert sys_obj.flavor_text == "A wind-haunted rim system, three worlds, an old derelict."
    assert sys_obj.flavor_text_status == FlavorTextStatus.GENERATED
    assert sys_obj.flavor_text_attempts == 1


async def test_handler_retries_on_transient_failure(
    db_session, sample_system_with_lighthouse
):
    from anthropic import APIConnectionError
    from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob, System
    from scheduler.jobs.system_narrative_seed import handle_system_narrative_seed

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=APIConnectionError(request=MagicMock()))

    job = ScheduledJob(
        type=JobType.SYSTEM_NARRATIVE_SEED,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={"system_id": sample_system_with_lighthouse.channel_id},
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_system_narrative_seed(db_session, job, anthropic_client=fake_client)
    await db_session.flush()

    sys_obj = await db_session.get(System, sample_system_with_lighthouse.channel_id)
    # Stub still in place; status NOT set to failed; attempts incremented.
    assert sys_obj.flavor_text_status == FlavorTextStatus.STUB
    assert sys_obj.flavor_text_attempts == 1
    # Handler asked for a retry (returned a new ScheduledJob in result).
    assert any(
        j.type == JobType.SYSTEM_NARRATIVE_SEED for j in result.scheduled_jobs
    )


async def test_handler_marks_failed_after_max_attempts(
    db_session, sample_system_with_lighthouse
):
    from anthropic import APIConnectionError
    from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob, System
    from scheduler.jobs.system_narrative_seed import handle_system_narrative_seed

    sys_obj = await db_session.get(System, sample_system_with_lighthouse.channel_id)
    sys_obj.flavor_text_attempts = 3  # already tried max times
    await db_session.flush()

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=APIConnectionError(request=MagicMock()))

    job = ScheduledJob(
        type=JobType.SYSTEM_NARRATIVE_SEED,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={"system_id": sample_system_with_lighthouse.channel_id},
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_system_narrative_seed(db_session, job, anthropic_client=fake_client)
    await db_session.flush()
    await db_session.refresh(sys_obj)

    assert sys_obj.flavor_text_status == FlavorTextStatus.FAILED
    # No retry scheduled.
    assert not any(j.type == JobType.SYSTEM_NARRATIVE_SEED for j in (result.scheduled_jobs or []))


async def test_handler_marks_failed_on_terminal_4xx(
    db_session, sample_system_with_lighthouse
):
    from anthropic import BadRequestError
    from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob, System
    from scheduler.jobs.system_narrative_seed import handle_system_narrative_seed

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(
        side_effect=BadRequestError(message="bad", response=MagicMock(), body=None)
    )

    job = ScheduledJob(
        type=JobType.SYSTEM_NARRATIVE_SEED,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={"system_id": sample_system_with_lighthouse.channel_id},
    )
    db_session.add(job)
    await db_session.flush()

    await handle_system_narrative_seed(db_session, job, anthropic_client=fake_client)
    await db_session.flush()

    sys_obj = await db_session.get(System, sample_system_with_lighthouse.channel_id)
    # 4xx is terminal — no retry.
    assert sys_obj.flavor_text_status == FlavorTextStatus.FAILED


async def test_handler_skips_already_generated_idempotent(
    db_session, sample_system_with_lighthouse
):
    """If a system already has GENERATED status, the handler is a no-op."""
    from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob, System
    from scheduler.jobs.system_narrative_seed import handle_system_narrative_seed

    sys_obj = await db_session.get(System, sample_system_with_lighthouse.channel_id)
    sys_obj.flavor_text = "already generated paragraph"
    sys_obj.flavor_text_status = FlavorTextStatus.GENERATED
    await db_session.flush()

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock()

    job = ScheduledJob(
        type=JobType.SYSTEM_NARRATIVE_SEED,
        run_at=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        payload={"system_id": sample_system_with_lighthouse.channel_id},
    )
    db_session.add(job)
    await db_session.flush()

    await handle_system_narrative_seed(db_session, job, anthropic_client=fake_client)
    fake_client.messages.create.assert_not_awaited()
    await db_session.refresh(sys_obj)
    assert sys_obj.flavor_text == "already generated paragraph"
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Implement the handler**

Create `scheduler/jobs/system_narrative_seed.py`:

```python
"""SYSTEM_NARRATIVE_SEED handler — runtime LLM narrative seed.

Reads the system's persisted character data, builds the prompt, calls
Anthropic with prompt caching, writes the result. Retries transient
failures up to LLM_NARRATIVE_MAX_ATTEMPTS times with exponential backoff;
4xx responses are terminal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config.logging import get_logger
from config.settings import settings
from db.models import (
    FlavorTextStatus,
    JobState,
    JobType,
    ScheduledJob,
    System,
    SystemFeature,
    SystemPlanet,
)
from engine.system_generator import Feature, Planet, Star, SystemCharacter
from engine.system_narrative import generate_flavor_llm
from scheduler.dispatch import HandlerResult, register

log = get_logger(__name__)

_BACKOFF_BASE_SECONDS = 30


async def handle_system_narrative_seed(
    session,
    job: ScheduledJob,
    *,
    anthropic_client=None,  # injected; falls back to bot's client
) -> HandlerResult:
    """Generate a flavor paragraph via Anthropic and write it to the system.

    The Anthropic client is passed in so tests can mock it. Production code
    grabs the client from the bot instance at registration time.
    """
    if anthropic_client is None:
        anthropic_client = _get_default_client()

    system_id = job.payload["system_id"]
    sys_obj = await session.get(System, system_id, with_for_update=True)
    if sys_obj is None:
        log.warning("system_narrative_seed: %s not found", system_id)
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    if sys_obj.flavor_text_status == FlavorTextStatus.GENERATED:
        log.info("system_narrative_seed: %s already generated, skipping", system_id)
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    sys_obj.flavor_text_attempts = (sys_obj.flavor_text_attempts or 0) + 1
    attempts = sys_obj.flavor_text_attempts

    character = await _hydrate_character(session, sys_obj)
    sector_name = await _sector_name(session, sys_obj.sector_id)

    try:
        text = await generate_flavor_llm(
            character,
            sector_name=sector_name,
            anthropic_client=anthropic_client,
        )
    except Exception as e:
        return await _handle_failure(session, job, sys_obj, e, attempts)

    sys_obj.flavor_text = text
    sys_obj.flavor_text_status = FlavorTextStatus.GENERATED
    log.info(
        "system_narrative_seed: %s succeeded (attempt %d, %d chars)",
        system_id, attempts, len(text),
    )
    job.state = JobState.COMPLETED
    job.completed_at = func.now()
    return HandlerResult()


def _is_transient(exc: Exception) -> bool:
    """Network blips, rate limits, and 5xx are transient. 4xx is terminal."""
    try:
        from anthropic import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )
    except Exception:
        return True  # if SDK can't be imported, assume retry

    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)):
        return True
    if isinstance(exc, APIStatusError):
        # 5xx transient, 4xx terminal.
        try:
            return 500 <= exc.status_code < 600
        except Exception:
            return False
    return False


async def _handle_failure(
    session, job: ScheduledJob, sys_obj: System, exc: Exception, attempts: int
) -> HandlerResult:
    transient = _is_transient(exc)
    log.warning(
        "system_narrative_seed: %s failed (attempt %d, transient=%s): %s",
        sys_obj.channel_id, attempts, transient, exc,
    )

    if not transient or attempts >= settings.LLM_NARRATIVE_MAX_ATTEMPTS:
        sys_obj.flavor_text_status = FlavorTextStatus.FAILED
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    # Schedule retry with exponential backoff.
    backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
    retry = ScheduledJob(
        type=JobType.SYSTEM_NARRATIVE_SEED,
        run_at=datetime.now(timezone.utc) + timedelta(seconds=backoff),
        state=JobState.PENDING,
        payload=dict(job.payload),
    )
    job.state = JobState.COMPLETED
    job.completed_at = func.now()
    return HandlerResult(scheduled_jobs=[retry])


async def _hydrate_character(session, sys_obj: System) -> SystemCharacter:
    """Reconstruct a SystemCharacter from persisted rows for prompt building."""
    seed = (sys_obj.config or {}).get("generator_seed", 0)
    star = Star(
        type=(sys_obj.star_type.value if sys_obj.star_type else "single"),
        color=(sys_obj.star_color.value if sys_obj.star_color else "yellow"),
        age=(sys_obj.star_age.value if sys_obj.star_age else "mature"),
    )
    planet_rows = (
        await session.execute(
            select(SystemPlanet)
            .where(SystemPlanet.system_id == sys_obj.channel_id)
            .order_by(SystemPlanet.slot_index.asc())
        )
    ).scalars().all()
    feature_rows = (
        await session.execute(
            select(SystemFeature)
            .where(SystemFeature.system_id == sys_obj.channel_id)
            .order_by(SystemFeature.slot_index.asc())
        )
    ).scalars().all()
    planets = tuple(
        Planet(
            slot_index=p.slot_index,
            name=p.name,
            planet_type=p.planet_type.value,
            size=p.size.value,
            richness=p.richness.value,
            descriptor=p.descriptor,
        )
        for p in planet_rows
    )
    features = tuple(
        Feature(
            slot_index=f.slot_index,
            name=f.name,
            feature_type=f.feature_type.value,
            descriptor=f.descriptor,
        )
        for f in feature_rows
    )
    return SystemCharacter(seed=seed, star=star, planets=planets, features=features)


async def _sector_name(session, sector_id: str) -> str:
    from db.models import Sector

    sector = await session.get(Sector, sector_id)
    return sector.name if sector else ""


def _get_default_client():
    """Construct a client from settings. Used only at runtime; tests inject."""
    import anthropic

    return anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=settings.LLM_NARRATIVE_REQUEST_TIMEOUT_SECONDS,
    )


register(JobType.SYSTEM_NARRATIVE_SEED, handle_system_narrative_seed)
```

(Note: the `register` call passes `handle_system_narrative_seed` directly. The dispatcher invokes it with `(session, job)` — the keyword `anthropic_client` keeps its default `None`, which then falls back to `_get_default_client()`. Tests pass the mock explicitly.)

- [ ] **Step 4: Run, confirm passes**

Run: `pytest tests/test_handler_system_narrative_seed.py -v --no-cov`
Expected: 5 PASS.

- [ ] **Step 5: Register handler import**

In `bot/main.py::setup_hook`:

```python
        import scheduler.jobs.system_narrative_seed as _system_narrative_seed_module  # noqa: F401
```

- [ ] **Step 6: Commit**

```bash
git add scheduler/jobs/system_narrative_seed.py bot/main.py tests/test_handler_system_narrative_seed.py
git commit -m "feat(phase3b-6): system_narrative_seed handler — generate, retry, fallback"
```

---

## Task 6: Activation hook enqueues the LLM job

**Files:**
- Modify: `bot/cogs/admin.py`
- Modify: `tests/test_systems_sectors.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_systems_sectors.py`:

```python
async def test_system_enable_enqueues_llm_narrative_job(db_session, sample_sector):
    from unittest.mock import MagicMock

    from bot.cogs.admin import _system_enable_logic
    from db.models import FlavorTextStatus, JobType, ScheduledJob, System
    from sqlalchemy import select

    interaction = MagicMock()
    interaction.user.guild_permissions = MagicMock()
    interaction.user.guild_permissions.manage_channels = True
    interaction.guild_id = int(sample_sector.guild_id)
    interaction.channel_id = 76767676
    interaction.channel = MagicMock()
    interaction.channel.name = "veyra-belt"

    r = await _system_enable_logic(interaction, db_session)
    assert r.success
    await db_session.flush()

    sys_obj = (
        await db_session.execute(select(System).where(System.channel_id == "76767676"))
    ).scalar_one()
    assert sys_obj.flavor_text_status == FlavorTextStatus.STUB
    # Stub paragraph is in flavor_text immediately.
    assert sys_obj.flavor_text and len(sys_obj.flavor_text) > 50

    jobs = (
        await db_session.execute(
            select(ScheduledJob).where(ScheduledJob.type == JobType.SYSTEM_NARRATIVE_SEED)
        )
    ).scalars().all()
    assert any(j.payload.get("system_id") == "76767676" for j in jobs)
```

- [ ] **Step 2: Run, confirm fails**

- [ ] **Step 3: Modify `_system_enable_logic`**

In `bot/cogs/admin.py`, after the existing stub-write, add:

```python
    # Phase 3b-6: enqueue an LLM narrative job to replace the stub.
    from datetime import datetime, timezone

    from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob

    sys_obj.flavor_text_status = FlavorTextStatus.STUB
    session.add(
        ScheduledJob(
            type=JobType.SYSTEM_NARRATIVE_SEED,
            run_at=datetime.now(timezone.utc),
            state=JobState.PENDING,
            payload={"system_id": sys_obj.channel_id},
        )
    )
```

(`flavor_text` itself is unchanged from 3b-1 — the stub is still written first so the channel has *something* to show. The job upgrades it asynchronously.)

- [ ] **Step 4: Run, confirm passes**

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/admin.py tests/test_systems_sectors.py
git commit -m "feat(phase3b-6): /system enable enqueues LLM narrative job"
```

---

## Task 7: "narrative pending" footer when status=stub

**Files:**
- Modify: `bot/cogs/lighthouse.py`
- Modify: `bot/cogs/admin.py`

- [ ] **Step 1: Add the footer**

In `bot/cogs/lighthouse.py::_lighthouse_logic`, after composing the message:

```python
    if sys_obj.flavor_text_status.value == "stub":
        msg += "\n_(narrative pending — LLM seed pass in flight)_"
```

Same in `_sector_info_logic` per-system row.

- [ ] **Step 2: Tests**

Add a small test that asserts the footer appears for stub status and not for generated.

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/lighthouse.py bot/cogs/admin.py tests/test_cog_lighthouse.py tests/test_systems_sectors.py
git commit -m "feat(phase3b-6): show 'narrative pending' footer when flavor is the stub"
```

---

## Task 8: Backfill script — upgrade existing systems

**Files:**
- Create: `scripts/backfill_llm_flavor.py`

- [ ] **Step 1: Write the script**

```python
"""Enqueue SYSTEM_NARRATIVE_SEED jobs for every system whose flavor_text_status is STUB.

Idempotent — re-running on a partially-completed backfill simply tops up
the queue. A system that already has GENERATED is skipped at handler time.

Usage:
    DATABASE_URL=... python -m scripts.backfill_llm_flavor
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from config.logging import get_logger, setup_logging
from db.models import FlavorTextStatus, JobState, JobType, ScheduledJob, System
from db.session import async_session

log = get_logger(__name__)


async def main() -> None:
    setup_logging()
    async with async_session() as session, session.begin():
        rows = (
            await session.execute(
                select(System).where(System.flavor_text_status == FlavorTextStatus.STUB)
            )
        ).scalars().all()
        log.info("backfill_llm_flavor: enqueueing %d jobs", len(rows))
        for sys_obj in rows:
            session.add(
                ScheduledJob(
                    type=JobType.SYSTEM_NARRATIVE_SEED,
                    run_at=datetime.now(timezone.utc),
                    state=JobState.PENDING,
                    payload={"system_id": sys_obj.channel_id},
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add scripts/backfill_llm_flavor.py
git commit -m "feat(phase3b-6): backfill script for existing systems"
```

---

## Task 9: End-to-end scenario — activation upgrade path

**Files:**
- Create: `tests/test_scenarios/test_activation_with_llm.py`

- [ ] **Step 1: Write the scenario**

```python
"""Enable a system → stub stored immediately + LLM job enqueued → handler upgrades to generated."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


async def test_activation_then_llm_upgrade_path(db_session, sample_sector):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock as MM

    from bot.cogs.admin import _system_enable_logic
    from db.models import FlavorTextStatus, JobType, ScheduledJob, System
    from scheduler.jobs.system_narrative_seed import handle_system_narrative_seed
    from sqlalchemy import select

    # 1. Enable.
    inter = MM()
    inter.user.guild_permissions = MM()
    inter.user.guild_permissions.manage_channels = True
    inter.guild_id = int(sample_sector.guild_id)
    inter.channel_id = 67676767
    inter.channel = MM()
    inter.channel.name = "tarsus-belt"

    r = await _system_enable_logic(inter, db_session)
    assert r.success
    await db_session.flush()

    sys_obj = (
        await db_session.execute(select(System).where(System.channel_id == "67676767"))
    ).scalar_one()
    stub_text = sys_obj.flavor_text
    assert sys_obj.flavor_text_status == FlavorTextStatus.STUB

    # 2. Find the enqueued job + run it through the handler with a mock client.
    job = (
        await db_session.execute(
            select(ScheduledJob).where(
                ScheduledJob.type == JobType.SYSTEM_NARRATIVE_SEED,
                ScheduledJob.payload.contains({"system_id": "67676767"}),
            )
        )
    ).scalar_one()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="A handsome new paragraph from the LLM.")]
    fake_response.usage = MagicMock(
        input_tokens=2200, output_tokens=20, cache_read_input_tokens=2000, cache_creation_input_tokens=0
    )
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    await handle_system_narrative_seed(db_session, job, anthropic_client=fake_client)
    await db_session.flush()
    await db_session.refresh(sys_obj)

    assert sys_obj.flavor_text == "A handsome new paragraph from the LLM."
    assert sys_obj.flavor_text != stub_text
    assert sys_obj.flavor_text_status == FlavorTextStatus.GENERATED
```

- [ ] **Step 2: Run, confirm passes**

- [ ] **Step 3: Commit**

```bash
git add tests/test_scenarios/test_activation_with_llm.py
git commit -m "test(phase3b-6): scenario — activation enqueues + handler upgrades flavor"
```

---

## Task 10: Documentation

**Files:**
- Modify: `docs/authoring/system_character.md` (update the LLM-stub section)
- Create: `docs/authoring/llm_narrative.md`

- [ ] **Step 1: Update the existing section in `system_character.md`**

Replace the "## The narrative paragraph" section with a pointer:

```markdown
## The narrative paragraph

`engine.system_narrative.generate_flavor` is the deterministic stub
fallback used at activation time, before the LLM job runs and on terminal
LLM failures.

`engine.system_narrative.generate_flavor_llm` is the runtime LLM call.
It runs asynchronously via `scheduler/jobs/system_narrative_seed.py`. See
`docs/authoring/llm_narrative.md` for prompt + retry details.
```

- [ ] **Step 2: Write the LLM doc**

Create `docs/authoring/llm_narrative.md`:

```markdown
# Authoring: LLM Narrative Seed

Phase 3b-6 added a runtime LLM call that replaces the deterministic
template stub for system flavor paragraphs.

## Lifecycle

1. `/system enable` writes the deterministic stub and enqueues a
   `SYSTEM_NARRATIVE_SEED` job.
2. The scheduler dispatches the job to
   `scheduler/jobs/system_narrative_seed.py::handle_system_narrative_seed`.
3. The handler hydrates a `SystemCharacter` from the persisted rows,
   builds the prompt via `engine.system_narrative.build_prompt`, and
   calls `engine.system_narrative.generate_flavor_llm`.
4. On success: writes the result to `system.flavor_text`, sets status to
   `generated`. The "narrative pending" footer disappears from
   `/lighthouse status` and `/system info`.
5. On transient failure (5xx, rate limit, timeout, connection): retries
   with exponential backoff (30s, 60s, 120s) up to
   `LLM_NARRATIVE_MAX_ATTEMPTS` (default 3).
6. On terminal failure (4xx, max attempts hit): sets status to `failed`.
   The stub stays in place — players see flavor either way.

## Prompt structure

`build_prompt` returns a `_PromptParts` dataclass with two pieces:

- **System block (cached):** the full `docs/lore/setting.md` voice, with
  `cache_control: ephemeral` on the trailing block. ~6-8k tokens.
- **User block (uncached):** structured per-system data — star, planets,
  features, sector name. ~200 tokens.

Cache hit rate target: > 95% across same-sector activations within the 5-
minute Anthropic cache TTL. Below that, investigate whether the setting
voice is being mutated between calls (it shouldn't be — load happens at
module import).

## Tuning

`config/settings.py`:

| Setting | Default | Notes |
|---|---|---|
| `LLM_NARRATIVE_MODEL` | `claude-haiku-4-5-20251001` | Haiku is the right size for 2-4 sentence flavor |
| `LLM_NARRATIVE_MAX_TOKENS` | 600 | enough for 4 sentences with slack |
| `LLM_NARRATIVE_REQUEST_TIMEOUT_SECONDS` | 30 | scheduler retries on timeout |
| `LLM_NARRATIVE_MAX_ATTEMPTS` | 3 | per-system retry budget |

To bump to a different model (e.g. Sonnet 4.6 or Opus 4.7) without
shipping a migration, set `LLM_NARRATIVE_MODEL` in env. Prompt caching
works identically across the Claude 4.x family.

## Editing the prompt

`engine/system_narrative.py::build_prompt` builds the per-system user
block. The instruction prefix in the system block is short and lives
inline; edit it there if the output drifts from the desired tone.

The cached portion is `docs/lore/setting.md` — editing it invalidates
the cache for ~5 minutes (one TTL window) before activations resume
hitting the cache. Don't edit `setting.md` casually during a busy
activation period.

## Manual reseed

If a system's `flavor_text` reads poorly and you want to retry:

```sql
UPDATE systems
SET flavor_text_status = 'stub', flavor_text_attempts = 0
WHERE channel_id = '<id>';
```

Then run `python -m scripts.backfill_llm_flavor` to enqueue.
```

- [ ] **Step 3: Commit**

```bash
git add docs/authoring/system_character.md docs/authoring/llm_narrative.md
git commit -m "docs(phase3b-6): LLM narrative authoring guide"
```

---

## Task 11: Final integration smoke

- [ ] **Step 1: Full suite + migration round-trip**

Run: `pytest --no-cov -q` then `alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 2: Live LLM smoke (requires ANTHROPIC_API_KEY in dev .env)**

Bring up the dev bot. Set `ANTHROPIC_API_KEY` in `.env`. Run `/system enable` in a fresh channel.

- Within seconds: `/lighthouse status` shows the deterministic stub paragraph + "narrative pending" footer.
- Within ~10 seconds (job dispatch + LLM call): `/lighthouse status` shows the LLM paragraph + footer is gone.
- `flavor_text_status` in DB reads `generated`.
- Hit it again with `/system enable` in another fresh channel — the second call should be a cache hit on the system block; check Anthropic dashboard for cache_read_input_tokens > 0.

- [ ] **Step 3: Push and PR**

```bash
gh pr create --title "Phase 3b-6: Runtime LLM narrative seed pass" --body "$(cat <<'EOF'
## Summary
- Adds the `anthropic` SDK and `ANTHROPIC_API_KEY` setting.
- New `SYSTEM_NARRATIVE_SEED` scheduler job: hydrates a SystemCharacter from persisted rows, builds a prompt-cached request (setting voice cached, per-system data uncached), calls Anthropic, writes the result to `system.flavor_text`.
- Retry policy: transient failures (5xx, rate limit, timeout) retry with exponential backoff up to 3 attempts; 4xx is terminal.
- The deterministic stub from 3b-1 stays as the fallback — on terminal failure or while the job is in flight, players see the stub. `flavor_text_status` (stub/generated/failed) tracks state.
- "narrative pending" footer in `/lighthouse status` and `/system info` while status=stub.
- `scripts/backfill_llm_flavor.py` enqueues jobs for every existing system.

## Cache strategy
- System block (~6-8k tokens, `docs/lore/setting.md`) gets `cache_control: ephemeral`.
- User block (~200 tokens) is per-request.
- Hit-rate target: >95% across same-sector activations within the 5-minute TTL.

## Test plan
- [x] Unit: prompt builder, mocked client roundtrip, retry/terminal/idempotency paths
- [x] Migration round-trips
- [x] Scenario: enable → stub stored immediately → handler upgrades to generated
- [ ] Live: dev bot with ANTHROPIC_API_KEY set; verify cache_read tokens on second activation

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Spec coverage check (self-review)

| Spec section | Covered by | Notes |
|---|---|---|
| §4.4 Narrative — LLM pass | Tasks 4, 5 | generate_flavor_llm + handler |
| §4.6 Activation flow — placeholder + retry | Tasks 1, 5, 6 | stub stored first; handler retries on transient |

The single remaining piece of §4 not in 3b-6: §4.4 says "output is stored verbatim" — implemented via `sys_obj.flavor_text = text` with `.strip()` only.

---

## Open Questions

1. **Cache breakpoint placement.** Putting the cache breakpoint after the setting voice means every request reads ~6-8k cached tokens + writes ~200 fresh tokens. If the setting voice grows beyond ~10k tokens, we may want to split it across two cache breakpoints. Anthropic supports up to 4 breakpoints per request; today one is plenty.
2. **Retry on rate-limit specifically.** Rate-limit errors come back as 429s — Anthropic's SDK exposes them as `RateLimitError`. The current `_is_transient` treats them as retryable, but does NOT honor the `Retry-After` header. For a low-volume use case (system activation isn't bursty), the exponential backoff (30s, 60s, 120s) easily clears any normal rate-limit window. Worth revisiting if this ever becomes hot-path.
3. **Single vs streaming completion.** 3b-6 uses `messages.create` (single response). For 600 max-tokens responses, streaming has no UX benefit (the player isn't watching the channel for live tokens — the post lands when the job finishes). Stay non-streaming.
4. **Seasonal voice override.** Future feature: allow the prompt's instruction prefix to be tagged per-event (e.g. "during the Cult Whisper event, lean ominous"). Out of scope for 3b-6 — flagged for whichever phase introduces seasonal events (3e or later).

---

## Execution Handoff

Plan complete. Two execution options as in prior sub-plans.

**With 3b-6 shipped, the entire Phase 3b arc is live:** system character + claim + donations + flares + lapse + LLM-generated flavor. Time to shift focus to 3c (resource extraction, planet/feature exploitation) and 3d (home base UI consolidation).
