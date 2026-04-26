# Phase 2a — Scheduler Foundation + Timers + Accrual

**Status:** Approved 2026-04-25
**Phase:** 2a of 6+ (see [salvage-pulp revamp roadmap](../../roadmap/2026-04-22-salvage-pulp-revamp.md))
**Owner:** Jordan
**Depends on:** [Phase 0 foundation](2026-04-22-phase-0-foundation-design.md) (shipped), [Phase 1 crew sector](2026-04-24-phase-1-crew-sector-design.md) (shipped)

---

## Context

Phase 0 pivoted to the salvage-pulp universe and added multi-tenant Sector/System tables. Phase 1 added persistent crew with archetypes, levels, and assignment to builds.

Phase 2a is the **bot heartbeat, simple-job edition** — the first time the bot does work in the background while players are away. It ships the durable scheduler infrastructure plus two engagement rhythms built on top of it:

- **Timers** (15 min – 2 hr): training routines for crew, research projects, and a ship-build recipe. Discrete, fire-and-resolve.
- **Accrual** (continuous): crew assigned to stations passively yield credits and XP, claimed via `/claim`.

Phase 2 was originally scoped as one shipping unit covering scheduler, timers, accrual, **and** multi-hour expeditions. During brainstorming we split it: simple "fire-and-resolve" jobs (this spec, 2a) ship first; **expeditions** (mid-flight choice points, response windows, narrative state — Phase 2b) ship after. Splitting lets the scheduler stress-test under high-volume simple jobs before expedition complexity stacks on top.

The scheduler infrastructure built here is load-bearing for Phase 2b expeditions, Phase 3 job-board / channel events / villains, and Phase 4 PvP tournaments.

No expeditions, no job board, no villains, no PvP, no Redis-backed wake-up signal (documented as a future upgrade pathway). Those are later phases.

---

## Locked decisions

These were settled during brainstorming. Re-litigation belongs in a follow-on spec.

### Phase decomposition: 2a → 2b

The original Phase 2 scope split into:

- **2a (this spec):** scheduler infrastructure + Training, Research, ShipBuild timers + Station accrual + notification pipeline.
- **2b (later):** Expeditions on top of the 2a scheduler.

Phase 3 is now blocked on Phase 2b. The roadmap is updated to reflect this split.

### Process topology

A new **`scheduler-worker`** Railway service runs alongside the existing bot and API. It connects to the same Postgres and Redis. It does **not** speak to Discord directly.

- **Bot** continues to run as today: handles slash commands, no scheduler logic, consumes notifications from a Redis stream and delivers DMs via `discord.py`.
- **API** unchanged.
- **Worker** is the only writer to `scheduled_jobs.state` transitions for `pending → claimed → completed/failed`. Cogs write the initial `pending` row, never touch state after.

Rationale: the worker's lifecycle is independent of the Discord client. Bot restarts (cog reloads, deploys) do not pause the scheduler. Scheduler restarts do not break command handling.

### Scheduler core: Postgres-only with `SELECT FOR UPDATE SKIP LOCKED`

Postgres is the single source of truth for `scheduled_jobs`. The worker tick polls (`SELECT … FOR UPDATE SKIP LOCKED`) every 5 seconds, claims due jobs into a `claimed` state, then dispatches each in its own transaction. Multi-worker is supported by SKIP LOCKED with no code changes; we deploy one worker in v1.

Redis is **not** used for the scheduling path in v1. Its only role is the worker→bot notification stream (see below).

#### Future Redis-fast-path upgrade pathway (locked)

When scale or latency demands it, we add a Redis sorted set as a sub-second wake-up signal alongside the existing tick. The `scheduled_jobs` schema and handler interface MUST remain stable when this is added — that is the architectural commitment. Concretely:

- `INSERT scheduled_jobs` will be followed by `ZADD d2d:job_wake {scheduled_for_unix} {job_id}`.
- A `wake_loop` coroutine in the worker does `BZPOPMIN`, sleeps until fire time, triggers `tick()`.
- The periodic tick stays as a reconciliation safety net at lower frequency (e.g., 60s).
- Handlers don't change.

Phase 2a does not implement this. The spec records it so future phases don't accidentally close the door (e.g., by leaning on tick-cadence semantics in handler code).

### Reward delivery: timers auto-credit, accrual via `/claim`

- **Timer completion:** rewards applied atomically inside the handler transaction (credits, XP, items). Notification fires after commit. No further user action required.
- **Accrual:** continuous yield accumulates in `pending_*` columns on `StationAssignment`. `/claim` zeroes them and credits the user in a single transaction. Notification only fires when pending yield crosses a per-user-tunable threshold (defaults below).

### Notification pipeline: Redis Streams + consumer group

Worker emits notification requests to Redis stream `d2d:notifications`. Bot reads them via `XREADGROUP` with consumer group `d2d-bot`, applies rate limit + batching, sends DMs.

- **Rate limit:** default 5 DMs/hour per user, configurable.
- **Batching window:** 30s — multiple notifications for the same user within the window get merged into one DM.
- **Per-user opt-out per category** via `users.notification_prefs` JSONB.
- **At-least-once with one accepted gap:** if the worker crashes between DB commit and `XADD`, the player gets credited but not notified. Acceptable v1 trade. Outbox-pattern hardening is a future enhancement.

### Polymorphic `timers` table (no per-type tables)

A single `timers` table with `timer_type` enum and `payload` JSONB. New timer types add an enum value + handler + content JSON file + cog logic; **no DB migration needed**. Type-specific validation lives in the handler layer.

### Crew busy-state model: hard mutual exclusion

A crew member has exactly one `current_activity` at a time: `idle | on_build | training | researching | on_station`. Putting Alice on a training timer pulls her off any build; she's unavailable for races until the timer completes. Implemented as a single enum + nullable polymorphic pointer on `CrewMember`.

When a player tries an action that conflicts with the rule (e.g., training a crew already on a station), the cog rejects with an explicit, actionable error. **No magical auto-recall** — players have to explicitly free the crew first.

### Concurrency limits

Limits derive from crew exclusivity + per-activity slots, not a global "max N timers" cap.

| Activity | Limit | Mechanism |
|---|---|---|
| Training | 1 per crew member | Crew exclusivity (`current_activity` enum) |
| Research | 1 active per user | Partial unique index on `timers` |
| Ship-build | 1 active per user | Partial unique index on `timers` |
| Station accrual | 1 crew per station type (3 types in v1) | Unique constraint on `(user_id, station_type)` where `recalled_at IS NULL` |

Future progression-gated capacity (e.g., unlock more research slots) is accommodated by relaxing the unique index or adding a capacity counter — out of scope for 2a.

### Cancel + refund policy

Mid-flight cancellation refunds **50% of the credit cost**, frees the crew (if any), marks Timer + ScheduledJob as `cancelled`, awards no XP/output. Tunable in `config/settings.py`. Station recall has no refund (assignment is free); pending yield stays claimable.

### Idempotency: handlers via `reward_ledger`

Every handler computes a deterministic `(source_type, source_id)` from job inputs and uses `INSERT ... ON CONFLICT DO NOTHING` against `reward_ledger`. A conflict means "already paid, no-op." This makes handlers exactly-once-effective without a separate idempotency table.

### v1 content scope: schema-rich, content-thin

- **3 training routines:** Combat Drills, Specialty Course, Field Exercise.
- **3 research projects:** stat-buff outputs (e.g., a temporary +2% fleet-wide stat).
- **1 ship-build recipe:** "Salvage Reconstruction" — turns N scrapped ships into a new hull. Distinct from `/build` (which equips parts). No conflict with the existing flow.
- **3 station types:** Cargo Run, Repair Bay, Watch Tower. Each yields a different resource mix.

Content lives entirely in `data/timers/*.json` and `data/stations/*.json`. Designers can deepen any timer type by editing data files — no schema changes.

---

## Architecture

### Process topology

```
  ┌─────────────────┐         ┌──────────────────┐         ┌─────────────────────┐
  │  Bot (existing) │         │  API (existing)  │         │  scheduler-worker   │
  │  discord.py     │         │  FastAPI         │         │  (NEW)              │
  │  port 8001      │         │  port 8000       │         │  port 8002          │
  └────────┬────────┘         └────────┬─────────┘         └──────────┬──────────┘
           │                           │                              │
           │      writes scheduled_jobs (state=pending)                │
           │      via cog handlers                                     │
           ├───────────────────────────┐                               │
           │                           ▼                               │
           │                  ┌────────────────┐                       │
           │                  │   Postgres     │◄──── reads/writes ────┤
           │                  │  (single SoT)  │      via worker tick  │
           │                  └────────────────┘                       │
           │                                                           │
           │   XREADGROUP d2d:notifications                            │
           │◄──────────────────────────────────────────────────────────┤ XADD
           ▼                                                           │
       Discord (DMs)                                                   │
                                              ┌────────────────┐       │
                                              │     Redis      │◄──────┘
                                              │ stream:        │
                                              │  d2d:notifs    │
                                              └────────────────┘
```

### Data flow: timer lifecycle (representative)

```
Player runs /training start <crew> <routine>
  └─► bot/cogs/fleet.py: TrainingCommand
       ├─► system_gating check (existing)
       ├─► validate: crew owned, idle, routine exists, can afford cost
       ├─► single transaction:
       │     UPDATE crew_members SET current_activity='training' …
       │     INSERT timers (timer_type='training', state='active', …)
       │     INSERT scheduled_jobs (job_type='timer_complete', scheduled_for=…, state='pending')
       │     UPDATE users SET credits = credits - cost
       └─► reply embed: "Training started. Alice will return in 30 minutes."

scheduler-worker (every 5s):
  └─► SELECT … FROM scheduled_jobs WHERE state='pending' AND scheduled_for <= now()
       FOR UPDATE SKIP LOCKED LIMIT 100
       UPDATE state='claimed'
  └─► For each claimed job, in its own transaction:
       handle_timer_complete(session, job):
         ├─► load timers row (id from job.payload)
         ├─► compute rewards from data/timers/training_routines.json[recipe_id]
         ├─► INSERT reward_ledger (source_type='timer', source_id=timer.id, delta=…)
         │     ON CONFLICT DO NOTHING        # idempotency guard
         ├─► UPDATE crew_members SET current_activity='idle', xp += routine.rewards.xp
         │     (level-up logic reuses engine.crew_xp.award_xp)
         ├─► UPDATE timers SET state='completed', completed_at=now()
         ├─► UPDATE scheduled_jobs SET state='completed', completed_at=now()
         └─► append NotificationRequest to handler_result
  └─► After commit: redis.xadd("d2d:notifications", payload, maxlen=10000)

bot consumer (long-running asyncio task):
  └─► XREADGROUP fetches notification entry
       ├─► load user.notification_prefs; if "off" → XACK + skip
       ├─► rate-limit check (in-memory, 5/hr default)
       ├─► batching window (30s) — merge consecutive notifications
       └─► after window: send DM via discord.py
            ├─► 200 OK → XACK
            ├─► 403 Forbidden (DMs closed) → log + XACK (no retry)
            └─► transient error → don't XACK; redelivers via XPENDING
```

### Data flow: accrual lifecycle (representative)

```
Player runs /stations assign <crew> <station_type>
  └─► bot/cogs/fleet.py: StationsAssignCommand
       ├─► validate: crew owned + idle, station_type slot empty for user
       ├─► single transaction:
       │     UPDATE crew_members SET current_activity='on_station', current_activity_id=…
       │     INSERT station_assignments (…, last_yield_tick_at=now(), pending_credits=0, …)
       │     IF no pending accrual_tick job exists for this user:
       │       INSERT scheduled_jobs (job_type='accrual_tick', scheduled_for=now()+30min, state='pending')
       └─► reply embed.

scheduler-worker tick (every 30 min for accrual_tick jobs):
  └─► handle_accrual_tick(session, job):
       ├─► load all StationAssignments for job.user_id where recalled_at IS NULL
       ├─► for each: compute incremental yield from (now - last_yield_tick_at)
       │     using rates from data/stations/station_types.json
       ├─► UPDATE station_assignments SET pending_credits += …, pending_xp += …, last_yield_tick_at = now()
       ├─► IF total pending crosses threshold and not notified recently:
       │     append NotificationRequest("Your stations have N pending credits — /claim")
       ├─► UPDATE scheduled_jobs SET state='completed'
       └─► INSERT next scheduled_jobs (job_type='accrual_tick', scheduled_for=now()+30min)
              (self-rescheduling — runs forever as long as user has at least one assignment)

Player runs /claim
  └─► bot/cogs/fleet.py: ClaimCommand
       ├─► single transaction:
       │     SELECT pending_credits, pending_xp FROM station_assignments WHERE user_id=…
       │     UPDATE users SET credits += SUM(pending_credits)
       │     UPDATE crew_members SET xp += pending_xp (per assignment)
       │     INSERT reward_ledger (source_type='accrual_claim', source_id=<deterministic claim_id>, delta=…)
       │     UPDATE station_assignments SET pending_credits=0, pending_xp=0
       │     hard-delete recalled_at-set rows whose pending fields are now zero
       └─► reply embed with totals.
```

---

## Data model

### `scheduled_jobs` (new)

The durable job ledger. Single source of truth for "what should fire when." Generic enough to support Phase 2b expedition events and Phase 3 villain spawns without schema changes.

```
id              UUID         PRIMARY KEY
user_id         varchar(20)  NOT NULL  FK users.discord_id
job_type        ENUM(timer_complete, accrual_tick)
payload         JSONB        NOT NULL  -- handler-interpreted
scheduled_for   timestamptz  NOT NULL
state           ENUM(pending, claimed, completed, failed, cancelled)  NOT NULL
claimed_at      timestamptz  NULL
completed_at    timestamptz  NULL
attempts        int          NOT NULL DEFAULT 0
last_error      text         NULL
created_at      timestamptz  NOT NULL DEFAULT now()
updated_at      timestamptz  NOT NULL DEFAULT now()

INDEX ix_scheduled_jobs_pending_due ON (state, scheduled_for) WHERE state IN ('pending', 'claimed')
INDEX ix_scheduled_jobs_user_id ON (user_id)
```

The composite partial index is the worker tick's hot path.

### `timers` (new)

Polymorphic table for all finite-duration tasks.

```
id                       UUID         PRIMARY KEY
user_id                  varchar(20)  NOT NULL  FK users.discord_id
timer_type               ENUM(training, research, ship_build)  NOT NULL
recipe_id                varchar(64)  NOT NULL  -- key into the type's content JSON
payload                  JSONB        NOT NULL DEFAULT '{}'
started_at               timestamptz  NOT NULL DEFAULT now()
completes_at             timestamptz  NOT NULL
state                    ENUM(active, completed, cancelled)  NOT NULL
linked_scheduled_job_id  UUID         NOT NULL  FK scheduled_jobs.id
created_at               timestamptz  NOT NULL DEFAULT now()
updated_at               timestamptz  NOT NULL DEFAULT now()

INDEX ix_timers_user_id ON (user_id)
UNIQUE INDEX ux_timers_one_research_active   ON (user_id) WHERE timer_type='research' AND state='active'
UNIQUE INDEX ux_timers_one_ship_build_active ON (user_id) WHERE timer_type='ship_build' AND state='active'
```

`payload` shape, by `timer_type`:

- **training:** `{"crew_id": "<uuid>"}` — the crew member being trained.
- **research:** `{}` (room for future fields like target stat, tier).
- **ship_build:** `{"input_ship_ids": ["<uuid>", …]}` — scrapped ships consumed.

### `station_assignments` (new)

```
id                  UUID         PRIMARY KEY
user_id             varchar(20)  NOT NULL  FK users.discord_id
station_type        ENUM(cargo_run, repair_bay, watch_tower)  NOT NULL
crew_id             UUID         NOT NULL  FK crew_members.id
assigned_at         timestamptz  NOT NULL DEFAULT now()
last_yield_tick_at  timestamptz  NOT NULL DEFAULT now()
pending_credits     int          NOT NULL DEFAULT 0
pending_xp          int          NOT NULL DEFAULT 0
recalled_at         timestamptz  NULL
created_at          timestamptz  NOT NULL DEFAULT now()
updated_at          timestamptz  NOT NULL DEFAULT now()

UNIQUE INDEX ux_station_assignments_user_type_active
  ON (user_id, station_type) WHERE recalled_at IS NULL
INDEX ix_station_assignments_user_id ON (user_id)
```

Soft-recall (`recalled_at` set, row retained) lets unclaimed yield remain collectible. Row is hard-deleted after `/claim` zeroes the pending fields.

### `reward_ledger` (new)

Doubles as the **idempotency record** for handler-fired sources.

```
id            UUID         PRIMARY KEY
user_id       varchar(20)  NOT NULL  FK users.discord_id
source_type   ENUM(timer_complete, accrual_tick, accrual_claim, timer_cancel_refund)  NOT NULL
source_id     varchar(128) NOT NULL  -- see source_id conventions below
delta         JSONB        NOT NULL  -- {"credits": 100, "xp": 50, "items": [...]}
applied_at    timestamptz  NOT NULL DEFAULT now()

UNIQUE INDEX ux_reward_ledger_source ON (source_type, source_id)
INDEX ix_reward_ledger_user_id ON (user_id)
```

`source_id` conventions per source_type:

| source_type | source_id format | purpose |
|---|---|---|
| `timer_complete` | `timer:<timer_uuid>` | idempotency: handler retry → `ON CONFLICT DO NOTHING` skips re-credit |
| `accrual_tick` | `accrual_tick:<scheduled_jobs_uuid>` | idempotency: re-fire of same accrual_tick → no double-increment of `pending_*` |
| `accrual_claim` | `accrual_claim:<claim_uuid>` (generated per `/claim`) | audit only; `/claim` is user-initiated and not retried by scheduler |
| `timer_cancel_refund` | `timer_cancel_refund:<timer_uuid>` | idempotency + audit |

Handler pattern:

```python
ledger = RewardLedger(source_type=..., source_id=..., user_id=..., delta=...)
session.add(ledger)
try:
    await session.flush()  # raises IntegrityError on conflict
except IntegrityError:
    await session.rollback()
    return  # already applied; treat as success
# downstream effects (credits, XP, etc.) only apply on first flush
```

### `crew_members` extension

```
+ current_activity      ENUM(idle, on_build, training, researching, on_station)  NOT NULL DEFAULT 'idle'
+ current_activity_id   UUID  NULL  -- polymorphic pointer to Build/Timer/StationAssignment
```

`current_activity_id` is **not** a DB-level FK because the target table varies. Validity is handler-enforced. Acceptable trade for simplicity at this stage; can be replaced with typed columns later if soundness becomes an issue.

**Backfill** (in a script under `scripts/backfills/`, per the roadmap's migration discipline rule):

```sql
UPDATE crew_members
SET current_activity = 'on_build',
    current_activity_id = ca.build_id
FROM crew_assignments ca
WHERE ca.crew_id = crew_members.id;
```

### `users` extension

```
+ notification_prefs    JSONB  NOT NULL DEFAULT '{"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1}'
```

Schema (versioned for future migration):

```json
{
  "_version": 1,
  "timer_completion": "dm" | "off",
  "accrual_threshold": "dm" | "off"
}
```

---

## Scheduler engine

### Tick loop (`scheduler/engine.py`)

```python
async def run_forever() -> None:
    while not shutdown_requested:
        try:
            n = await tick()
        except Exception:
            log.exception("tick failed")
            n = 0
        if n < SCHEDULER_BATCH_SIZE:
            await asyncio.sleep(SCHEDULER_TICK_INTERVAL_SECONDS)
        # else loop immediately to drain backlog

async def tick() -> int:
    async with async_session() as session, session.begin():
        rows = (await session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.state == JobState.PENDING)
            .where(ScheduledJob.scheduled_for <= func.now())
            .order_by(ScheduledJob.scheduled_for)
            .limit(SCHEDULER_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for job in rows:
            job.state = JobState.CLAIMED
            job.claimed_at = func.now()
            job.attempts += 1
    # claim transaction committed; jobs are durably claimed.

    for job in rows:
        await dispatch(job)
    return len(rows)
```

### Dispatcher contract (`scheduler/dispatch.py`)

```python
HANDLERS: dict[JobType, Callable[[AsyncSession, ScheduledJob], Awaitable[HandlerResult]]] = {
    JobType.TIMER_COMPLETE: handle_timer_complete,
    JobType.ACCRUAL_TICK: handle_accrual_tick,
}

@dataclass
class HandlerResult:
    notifications: list[NotificationRequest] = field(default_factory=list)

async def dispatch(job: ScheduledJob) -> None:
    handler = HANDLERS[job.job_type]
    with tracer.start_as_current_span(f"scheduler.{job.job_type.value}") as span:
        span.set_attributes({
            "d2d.job_id": str(job.id),
            "d2d.job_type": job.job_type.value,
            "d2d.user_id": job.user_id,
            "d2d.attempts": job.attempts,
        })
        try:
            async with async_session() as session, session.begin():
                # Re-load the row with FOR UPDATE to refresh and lock.
                fresh = await session.get(ScheduledJob, job.id, with_for_update=True)
                result = await handler(session, fresh)
            for n in result.notifications:
                await redis_client.xadd("d2d:notifications", n.to_dict(),
                                        maxlen=NOTIFICATION_STREAM_MAXLEN, approximate=True)
            scheduler_jobs_total.labels(job_type=job.job_type.value, result="success").inc()
        except Exception as e:
            await mark_failed(job, e)
            scheduler_jobs_total.labels(job_type=job.job_type.value, result="failure").inc()
            span.record_exception(e)
            log.exception("handler failed: job_id=%s", job.id)
```

### Handler contract

Every handler is a coroutine `async def handler(session, job) -> HandlerResult` that MUST:

1. Be **idempotent** (re-execution produces same domain effect; achieved via `reward_ledger` ON CONFLICT pattern).
2. Run inside the dispatcher's transaction (no nested transactions).
3. Mark the job complete: `job.state = JobState.COMPLETED; job.completed_at = func.now()` before returning.
4. Return notifications via `HandlerResult.notifications` rather than emitting them directly. The dispatcher handles the post-commit `XADD`.

### Retry & recovery

The worker runs a second coroutine alongside the tick loop — `recovery_sweep()` — that runs every `SCHEDULER_RECOVERY_INTERVAL_SECS` and handles two cases:

- **Failed jobs** (handler raised): row has `state='failed'`, `last_error=<traceback>`. The sweep resets them to `state='pending'` for retry, up to `SCHEDULER_MAX_ATTEMPTS = 3`. After max attempts: stays `failed` permanently; alert fires.
- **Stuck claimed jobs** (worker died after claim, before commit): the sweep resets `state='claimed' AND claimed_at < now() - SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS` back to `pending`, capped by `attempts`.

`recovery_sweep` is **not** itself a `scheduled_jobs` row — it's a worker-internal periodic task, mirroring the main `tick()` loop. This avoids a self-rescheduling bootstrap edge case (what happens if recovery_sweep itself gets stuck?).

**Cancelled jobs** transition to `state='cancelled'`; the tick query's `state='pending'` filter naturally skips them.

### Tunables (`config/settings.py`)

```
SCHEDULER_TICK_INTERVAL_SECONDS    = 5
SCHEDULER_BATCH_SIZE               = 100
SCHEDULER_MAX_ATTEMPTS             = 3
SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS = 300
SCHEDULER_RECOVERY_INTERVAL_SECS   = 60
ACCRUAL_TICK_INTERVAL_MINUTES      = 30
ACCRUAL_NOTIFICATION_THRESHOLD     = 1000  # credits — below this, no DM
TIMER_CANCEL_REFUND_PCT            = 50
NOTIFICATION_RATE_LIMIT_PER_HOUR   = 5
NOTIFICATION_BATCH_WINDOW_SECONDS  = 30
NOTIFICATION_STREAM_MAXLEN         = 10000
```

---

## Notification pipeline

### Stream layout

- Stream key: `d2d:notifications`
- Consumer group: `d2d-bot`
- Trim policy: `XADD ... MAXLEN ~ 10000` (approximate trim).

### Message shape

```json
{
  "user_id": "discord_id_string",
  "category": "timer_completion" | "accrual_threshold",
  "title": "Training complete",
  "body": "Alice gained 200 XP and is now level 4.",
  "correlation_id": "<scheduled_jobs.id>",
  "dedupe_key": "timer:<uuid>",
  "created_at": "iso8601"
}
```

### Worker → Stream

The worker emits `XADD` **after** the DB commit, never inside the transaction. Worker crashes between commit and XADD result in a missed DM but no double-credit. Outbox-pattern hardening is a future enhancement (out of v1 scope).

### Bot consumer (`bot/notifications.py`)

```python
async def notification_consumer():
    await ensure_consumer_group("d2d:notifications", "d2d-bot")
    while not shutdown_requested:
        try:
            msgs = await redis.xreadgroup(
                "d2d-bot", consumer_id, {"d2d:notifications": ">"},
                count=50, block=5000,
            )
            for stream, entries in msgs:
                for entry_id, payload in entries:
                    await handle_notification(entry_id, payload)
        except Exception:
            log.exception("consumer loop error")
            await asyncio.sleep(1)
```

`handle_notification`:

1. Load `User.notification_prefs[category]`. If `"off"` → `XACK` + skip + increment `notifications_total{result="opted_out"}`.
2. Rate-limit check (in-memory `(user_id, hour_bucket) → count`, default cap 5/hr). Over cap → drop with `XACK` + `result="rate_limited"`.
3. Batching window: if another notification for the same user is queued within `NOTIFICATION_BATCH_WINDOW_SECONDS`, merge into pending batch instead of sending immediately.
4. After window expires: send one DM via `discord.py` with merged content.
5. On `200` → `XACK` + `result="delivered"`.
6. On `discord.errors.Forbidden` (DMs closed) → log + `XACK` + `result="dm_closed"` (no retry).
7. On transient error → no `XACK`; redelivers via `XPENDING` reclaim + `result="failed"`.

The consumer runs as an `asyncio.create_task` started in the bot's `setup_hook()` and cancelled cleanly on shutdown.

### Tracing

Each notification carries `correlation_id` (the originating `scheduled_jobs.id`). The bot wraps `handle_notification` in a span that links to the worker's span via `correlation_id`. A single Tempo trace shows worker → DB commit → Redis stream → bot → DM.

---

## Commands surface

All commands live in a new cog **`bot/cogs/fleet.py`**. All except `/notifications` are system-gated (per `feedback_system_gating_universal` memory).

```
/training start <crew> <routine>      Start a training routine on a crew member.
/training status                      List your active and recently completed training.
/training cancel <crew>               Cancel an active training (50% refund, no XP).

/research start <project>             Start a research project (one active per user).
/research status
/research cancel

/build construct <recipe>             Start a ship-build recipe (one active per user).
/build status
/build cancel

/stations list                        See your station roster + pending yield.
/stations assign <crew> <station>     Assign a crew to a station type.
/stations recall <crew>               Recall a crew (yield stays claimable).

/claim                                Collect all pending station yield in one transaction.

/notifications                        Show / edit your notification preferences.
```

### Cancel / refund detail

Cancel is offered for all three timer types via the same handler shape:

1. Validate timer is `state='active'`.
2. Show confirmation embed: *"Cancel will refund X of Y credits and free \<crew\>. Continue?"* (Reuse the ephemeral confirmation pattern from `bot/cogs/hangar.py`.)
3. On confirm, single transaction:
   - `UPDATE timers SET state='cancelled'`
   - `UPDATE scheduled_jobs SET state='cancelled' WHERE id=timer.linked_scheduled_job_id AND state='pending'`
     (Race with the worker is handled by the `WHERE state='pending'` clause — if the worker already claimed it, cancel fails gracefully and the user is told the timer just completed.)
   - `UPDATE crew_members SET current_activity='idle', current_activity_id=NULL` (where applicable)
   - `UPDATE users SET credits = credits + (cost * TIMER_CANCEL_REFUND_PCT / 100)`
   - `INSERT reward_ledger (source_type='timer_cancel_refund', source_id='timer_cancel_refund:<timer_uuid>', …)` for audit + idempotency (per the source_id conventions table above)

### Content data files

```
data/timers/training_routines.json     # 3 routines for v1
data/timers/research_projects.json     # 3 projects for v1
data/timers/ship_build_recipes.json    # 1 recipe ("salvage_reconstruction") for v1
data/stations/station_types.json       # 3 station types for v1
```

Schema for a training routine (representative):

```json
{
  "id": "combat_drills",
  "name": "Combat Drills",
  "duration_minutes": 30,
  "cost_credits": 50,
  "min_crew_level": 1,
  "rewards": {
    "xp": 200,
    "archetype_perk": null
  },
  "flavor": "Standard sim runs in the gunnery pod. Reliable progress."
}
```

Schema for a station type:

```json
{
  "id": "cargo_run",
  "name": "Cargo Run",
  "yields_per_tick": {
    "credits": 50,
    "xp": 10
  },
  "preferred_archetype": "navigator",
  "archetype_bonus_pct": 25,
  "flavor": "Standard freight runs. Reliable, modest pay."
}
```

Loaded at startup into an in-memory registry (`engine/timer_recipes.py`, `engine/station_types.py`); cog validates `recipe_id` / `station_type` against the registry; handler reads from it for reward computation. No DB rows for content.

---

## Observability

### Tracing

- Worker initialises tracing via `init_tracing("Dare2Drive-Worker")` at startup, mirroring the bot pattern.
- Every `tick()` is a span; every dispatched job is a child span named `scheduler.<job_type>`.
- Standard attributes per job span: `d2d.job_id`, `d2d.job_type`, `d2d.user_id`, `d2d.attempts`, `d2d.scheduled_for` plus type-specific (e.g., `d2d.timer_id`, `d2d.station_type`).
- SQLAlchemy auto-instrumented in the worker via `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)`.
- Notification spans on the bot side carry `d2d.correlation_id` linking to the originating job span.

### Metrics

New counters/histograms in `api/metrics.py` (keep the registry consolidated):

```
dare2drive_scheduler_jobs_total{job_type, result}              # counter — success | failure | retry
dare2drive_scheduler_job_duration_seconds{job_type}            # histogram
dare2drive_scheduler_jobs_in_flight                            # gauge — claimed but not done
dare2drive_scheduler_jobs_pending                              # gauge — periodic snapshot
dare2drive_scheduler_tick_duration_seconds                     # histogram
dare2drive_notifications_total{category, result}               # counter — delivered | rate_limited | opted_out | dm_closed | failed
dare2drive_notification_stream_lag                             # gauge — XLEN d2d:notifications
dare2drive_timers_started_total{timer_type}                    # counter
dare2drive_timers_completed_total{timer_type, outcome}         # counter — success | cancelled
dare2drive_station_yield_credits_total                         # counter
dare2drive_claim_total{result}                                 # counter — success | empty
```

All counters expose Prometheus exemplars linked to the active span via the existing `trace_exemplar()` helper.

### Logs

Worker uses `setup_logging()` with `LOG_FORMAT=json` in production. Per-job log entries carry `job_id`, `user_id`, `trace_id`, `span_id`.

### Grafana

New dashboard **`dare2drive-scheduler`** in the `grafana-stack` submodule (same upgrade pattern Phases 0/1 used):

- Tick rate, tick duration, jobs-pending gauge, jobs-in-flight gauge.
- Job throughput by `job_type`, success/failure ratio.
- Stuck-claim count (claimed jobs older than threshold).
- Notification stream lag.
- Per-timer-type completion counts.

Tile added to existing `dare2drive-overview`: scheduler health summary.

### Alerts

Tier-aware (matching Phase 1's precedent), in `grafana-stack`:

- **`SchedulerJobsBacklog`** — `dare2drive_scheduler_jobs_pending > 1000 for 10m` warning; `> 5000 for 5m` critical.
- **`SchedulerJobsFailureRate`** — `rate(jobs_total{result="failure"}[5m]) / rate(jobs_total[5m]) > 0.05 for 10m` warning.
- **`SchedulerStuckClaims`** — count of `state='claimed' AND claimed_at < now() - 5min` exposed as a metric, alert if `> 10`.
- **`NotificationStreamBuildup`** — `dare2drive_notification_stream_lag > 1000 for 10m` warning.
- **`NotificationFailureRate`** — `rate(notifications_total{result="failed"}[15m]) > 0.1` warning.
- **`WorkerDown`** — `up{job="scheduler-worker"} == 0 for 2m` critical.

---

## Files likely touched

### New

- `scheduler/__init__.py`
- `scheduler/worker.py` — entry point: tracing, metrics server, run_forever loop
- `scheduler/engine.py` — tick loop + claim transaction
- `scheduler/dispatch.py` — handler registry + per-job transaction wrapper
- `scheduler/jobs/__init__.py`
- `scheduler/jobs/timer_complete.py` — handler for `timer_complete` job_type (delegates by `timer_type`)
- `scheduler/jobs/accrual_tick.py` — handler for accrual yield computation, threshold-notification emission, and self-rescheduling of the next tick
- `scheduler/recovery.py` — worker-internal `recovery_sweep()` coroutine for stuck claims + capped failures
- `scheduler/notifications.py` — `NotificationRequest` dataclass + `xadd` helper
- `bot/cogs/fleet.py` — all Phase 2a slash commands
- `bot/notifications.py` — Redis stream consumer + DM rate-limit/batching
- `engine/timer_recipes.py` — JSON loader + lookup for training/research/ship-build recipes
- `engine/station_types.py` — JSON loader + lookup for station types
- `data/timers/training_routines.json`
- `data/timers/research_projects.json`
- `data/timers/ship_build_recipes.json`
- `data/stations/station_types.json`
- `db/migrations/versions/0003_phase2a_scheduler.py` — adds the five new tables + two existing-table extensions
- `scripts/backfills/0003_crew_current_activity.py` — backfills `crew_members.current_activity` from existing `crew_assignments`

### Touched

- `db/models.py` — new models, enum extensions
- `config/settings.py` — scheduler/notification tunables
- `api/metrics.py` — new counters/gauges/histograms
- `bot/main.py` — start `notification_consumer` task in `setup_hook`, load `fleet` cog
- `pyproject.toml` — add `scheduler*` to `[tool.setuptools.packages.find].include`; also add `scheduler` to `[tool.coverage.run].source` and the omit list as appropriate. No new dependencies (`redis` already present).
- `railway.toml` — add `scheduler-worker` service definition

---

## Reuse pointers

- **System gating** — `bot/system_gating.py` (`get_active_system`, `system_required_message`) is reused unchanged for all gated commands.
- **Crew XP / level-up** — `engine.crew_xp.award_xp` from Phase 1 handles XP application and level-up side effects. Timer handlers call it directly.
- **Crew lookup by name** — pattern from `bot/cogs/hiring.py` and `bot/cogs/hangar.py` for resolving a crew member from a slash-command argument.
- **Embed style** — established status/list embed pattern from existing cogs.
- **Tracing init** — copy the `init_tracing("Dare2Drive")` + `SQLAlchemyInstrumentor` pattern from `bot/main.py` into `scheduler/worker.py`.
- **Metrics module location** — keep new metrics in `api/metrics.py` (already imported by both bot and API; worker imports it too).

---

## Scope boundary (OUT of Phase 2a)

- **Expeditions** — Phase 2b. All multi-hour-with-mid-flight-events behaviour belongs there.
- **Job board / channel events / villains** — Phase 3.
- **PvP** — Phase 4.
- **Redis-backed wake-up signal** — future fast-path upgrade; pathway documented above.
- **Outbox pattern for notifications** — accepted v1 trade-off; can add later if missed-DM complaints arise.
- **Multi-worker deployment** — supported by `SKIP LOCKED` but not deployed in v1; one worker until load demands more.
- **Progression-gated capacity** (e.g., unlock a 4th station type) — schema supports it; v1 ships fixed slots.
- **Ship-build recipes beyond "Salvage Reconstruction"** — content can grow via JSON edits.

---

## Verification

Per the `feedback_feature_checklist` memory, every feature ships with tests, monitoring, dashboards, alerts, and docs. Phase 2a's verification:

| Layer | Test | How |
|---|---|---|
| Unit | tick claim semantics under concurrency | Two simulated workers tick simultaneously against a real Postgres fixture; only one claims each row. |
| Unit | handler idempotency | Run the same `timer_complete` job twice; `reward_ledger` has one row, balances updated once. |
| Unit | each handler in isolation | Standard `pytest` against in-memory session, asserting state transitions and reward shape. |
| Unit | recipe loader / station-type loader | Loaders parse the v1 JSON files without error; missing IDs produce clear errors. |
| Unit | cancel + 50% refund math | Verify rounding, ledger row, crew freed, `scheduled_jobs` race handled. |
| Unit | DM rate-limit + batching | Mock Redis stream + `discord.py` client; assert merged DM after window. |
| Integration | full timer lifecycle | `start training → wait → handler fires → DM delivered → reward applied`. End-to-end test in `tests/scenarios/`, mirroring Phase 1's crew-flow scenario. |
| Integration | station accrual | Assign crew → simulate 2 ticks → `pending_credits` accumulates → `/claim` → balance updated, pending zeroed. |
| Integration | concurrency rules | Attempt second concurrent research timer → rejected by partial unique index. |
| Integration | crew busy-state | Train a crew on a build → `current_activity` flips, build assignment cleared. |
| Chaos | kill worker mid-job | Kill worker after `state='claimed'` but before commit; restart; recovery picks up stuck claim and reprocesses. No double-credit. |
| Chaos | bot offline during notification | Stop bot, fire timer, restart bot; pending DMs drain from stream and deliver. |
| Load | 1000 concurrent jobs | Synthetic workload — schedule 1000 jobs all firing within 60s. Verify all complete, no deadlocks, p99 latency under SLO. |
| Migration | existing tests pass | Apply migration, run all existing Phase 0/1 tests, verify no regressions. |
| Migration | crew backfill correctness | Existing `CrewAssignment` rows produce `current_activity='on_build'` for matching crew. |
| Manual | tutorial walkthrough still works | Phase 1's tutorial scenario test passes end-to-end. |
| Manual | grafana dashboards render | Eyeball each panel post-deploy with synthetic load. |
| Manual | alerts fire under simulated failures | Force a handler exception, confirm `SchedulerJobsFailureRate` fires within window. |

---

## Deliverable

Players can start training routines, research projects, and ship-build recipes; assign crew to stations and `/claim` accrued yield. The bot DMs them when work completes, respecting per-user opt-out and rate limits. The scheduler-worker survives bot deploys without missing or duplicating job fires. Phase 2b expeditions can be built directly on top.
