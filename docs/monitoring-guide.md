# Developer Monitoring Guide

This guide walks you through adding **logs**, **metrics**, and **alerts** to any new feature
you build in Dare2Drive. It is written for developers new to Python observability tooling.

---

## Table of Contents

1. [How the monitoring stack fits together](#1-how-the-monitoring-stack-fits-together)
2. [Starting the monitoring stack locally](#2-starting-the-monitoring-stack-locally)
3. [Structured logging](#3-structured-logging)
4. [Prometheus metrics](#4-prometheus-metrics)
5. [Adding metrics to a bot cog](#5-adding-metrics-to-a-bot-cog)
6. [Adding metrics to an API route](#6-adding-metrics-to-an-api-route)
7. [Adding an alerting rule](#7-adding-an-alerting-rule)
8. [End-to-end example — a new `/trade` feature](#8-end-to-end-example--a-new-trade-feature)
9. [Viewing your data](#9-viewing-your-data)
10. [Quick reference cheat sheet](#10-quick-reference-cheat-sheet)

---

## 1. How the monitoring stack fits together

```text
Your Code
  │
  ├─ log.info(...)         ──▶ stdout (JSON in prod)
  │                                 │
  │                         Railway Log Drain
  │                                 │
  │                              Loki  ◀──── Grafana (Explore → Logs)
  │
  └─ some_counter.inc()    ──▶ /metrics endpoint on the API
                                      │
                                   Prometheus (scrapes every 15 s)
                                      │
                               Grafana (dashboards + unified alerting)
                                      │
                               Discord webhook (#alerts channel)
```

**Key points:**

- **Logs** tell you *what happened* — use them for events, errors, and context.
- **Metrics** tell you *how much / how often* — use them for counts, durations, and rates you
  want to graph or alert on.
- **Alerts** fire when a metric crosses a threshold for long enough to be worth waking someone up.

All three live in your Python code. The infrastructure (Loki, Prometheus, Grafana) picks
them up automatically — you do not need to touch any config files when adding a new feature.

### Where things live

| Concern | Local dev | Production (Railway) |
| --- | --- | --- |
| Metrics storage | Prometheus container (`d2d up --monitoring`) | Railway Grafana Stack |
| Dashboards | Grafana container (`d2d up --monitoring`) | Railway Grafana Stack |
| Log storage | stdout / `docker compose logs` | Loki (via Railway Log Drain) |
| Alert rules | — (alerts are production-only) | `monitoring/railway/grafana/alerting/rules.yml` |
| Alert delivery | — | Discord webhook (Grafana contact point) |

---

## 2. Starting the monitoring stack locally

By default `d2d up` only starts the four core services (`bot`, `api`, `db`, `redis`). Add the
`--monitoring` flag to spin up Prometheus and Grafana for local metric testing:

```bash
# First run — build the Grafana image with the Prometheus datasource baked in
d2d up --monitoring --build

# Subsequent runs
d2d up --monitoring
```

This starts two additional containers: Prometheus (scrapes `api:8000/metrics`) and Grafana
(pre-configured with Prometheus as its default datasource).

Once running:

| UI | URL | Default login |
| --- | --- | --- |
| Grafana | <http://localhost:3000> | admin / dare2drive |
| Prometheus | <http://localhost:9090> | — |

> **Note:** There is no local Loki. Log aggregation only happens in production via Railway's Log
> Drain. Locally, use `docker compose logs -f bot api` to follow logs.

---

## 3. Structured logging

### 3.1 Getting a logger

Every module that needs logging should create its own logger at the top of the file:

```python
from config.logging import get_logger

log = get_logger(__name__)
```

`__name__` is a Python built-in that resolves to the module's fully qualified name
(e.g. `bot.cogs.race`, `api.routes.users`). This lets you filter logs by module in Grafana.

### 3.2 Log levels

Use the right level — it affects noise in production:

| Level | Method | When to use |
| --- | --- | --- |
| DEBUG | `log.debug(...)` | Detailed internal state — only useful while actively debugging. Off by default in prod. |
| INFO | `log.info(...)` | Normal notable events: a user registered, a race started, a pack was opened. |
| WARNING | `log.warning(...)` | Something unexpected happened but the system recovered: a card was not found in the DB. |
| ERROR | `log.error(...)` | An operation failed and the user was affected. Always include the exception. |
| CRITICAL | `log.critical(...)` | The service cannot continue — use sparingly. |

### 3.3 Basic usage

```python
# Simple message
log.info("Race started")

# Include variables using %s formatting (NOT f-strings — see note below)
log.info("Race started: race_id=%s, user_id=%s", race_id, user_id)

# Warning with context
log.warning("Starter card not found in DB: %s", card_name)

# Log an exception — always pass exc_info=True so the traceback is captured
try:
    result = await session.execute(query)
except Exception:
    log.error("Database query failed for user %s", user_id, exc_info=True)
```

> **Why `%s` and not f-strings?**
> Python's logging module only formats the message string if it actually needs to emit the log
> (based on the current log level). Using `%s` defers the formatting; f-strings evaluate
> *immediately* regardless of level, which wastes CPU in hot paths.

### 3.4 What makes a good log message

**Good:**
```python
log.info("Pack opened: user_id=%s pack_type=%s cards_granted=%d", user_id, pack_type, len(cards))
log.warning("Race result ambiguous: both players DNF. race_id=%s", race_id)
log.error("Failed to mint card for user %s: %s", user_id, exc, exc_info=True)
```

**Bad:**
```python
log.info("done")                  # No context
log.info("here")                  # Useless
log.debug("user: %s", user)       # May dump a huge ORM object as a string
log.info(f"user {user_id}")       # f-string — fine for short messages but defeats lazy formatting
```

**Rules of thumb:**
- Every INFO log should answer: *what happened, who it happened to, and what the outcome was.*
- Always include IDs (`user_id`, `race_id`, `card_id`) so you can search Loki for a specific user.
- Never log raw passwords, tokens, or Discord auth credentials.

### 3.5 How logs reach Loki

Logs are always written to stdout. In production, Railway's Log Drain picks them up and pushes
them to Loki automatically — you do not need to change your code for logs to appear in Grafana.

`LOG_FORMAT=json` (the production default) emits one JSON object per line, which Loki can parse
into searchable fields:

```json
{"ts": "2026-04-12T09:00:00Z", "level": "INFO", "logger": "bot.cogs.race", "msg": "Race completed"}
```

Locally there is no Loki — use `docker compose logs -f bot api` instead.

---

## 4. Prometheus metrics

### 4.1 What is a metric?

A metric is a number that Prometheus collects from your `/metrics` endpoint every 15 seconds
and stores as a time series. You can then graph it, compute rates over it, or fire alerts when it
crosses a threshold.

All metrics for the whole application live in one file: **`api/metrics.py`**.
You import them from there wherever you need to increment them.

### 4.2 The three types you will use

#### Counter

A number that only ever goes up. Use it for things you count:
races started, packs opened, errors thrown, commands invoked.

```python
from prometheus_client import Counter

# Define it (do this once, at the module level in api/metrics.py)
packs_opened = Counter(
    "dare2drive_packs_opened_total",   # metric name — must be unique
    "Total number of card packs opened.",
    ["pack_type"],                     # optional labels — see section 4.3
)

# Use it (anywhere in your code)
packs_opened.labels(pack_type="junkyard").inc()   # increment by 1
packs_opened.labels(pack_type="performance").inc(3)  # increment by 3
```

#### Histogram

Tracks the distribution of a value (e.g. how long something takes).
Prometheus automatically computes percentiles (p50, p95, p99) from it.

```python
from prometheus_client import Histogram

race_duration_seconds = Histogram(
    "dare2drive_race_duration_seconds",
    "Time in seconds to compute a race result.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# Usage — use the context manager to time a block of code automatically
with race_duration_seconds.time():
    result = compute_race(player_data, opponent_data)
```

#### Gauge

A number that can go up *and* down. Use it for current state: active connections,
queue depth, players currently in a race. We do not have many of these yet, but the
pattern is the same:

```python
from prometheus_client import Gauge

active_races = Gauge(
    "dare2drive_active_races",
    "Number of races currently in progress.",
)

active_races.inc()    # race started
active_races.dec()    # race ended
```

### 4.3 Labels

Labels slice a single metric into multiple series. For example, `packs_opened_total` has a
`pack_type` label so you can graph junkyard vs performance vs legend separately — without
defining three separate counters.

**Rules:**
- Keep the number of distinct label values small and bounded. Good: `pack_type` (3 values).
  Bad: `user_id` (thousands of values — this will crash Prometheus).
- Define all label names in the `Counter(...)` / `Histogram(...)` call.
- Always call `.labels(key=value)` before `.inc()` / `.observe()` / `.time()`.

```python
# With labels
races_completed.labels(race_type="open", outcome="win").inc()

# Without labels (metric has no label list)
daily_claimed.inc()
```

### 4.4 Naming conventions

All metrics follow this pattern: `dare2drive_<noun>_<verb>_<unit>`

| Part | Example | Rule |
| --- | --- | --- |
| Prefix | `dare2drive_` | Always start with this |
| Noun | `races`, `packs`, `users` | What is being measured |
| Verb / adjective | `started`, `opened`, `registered` | What happened |
| Unit suffix | `_total` for counters, `_seconds` for durations | Required by Prometheus convention |

Good names: `dare2drive_races_started_total`, `dare2drive_api_request_duration_seconds`
Bad names: `races`, `myCounter`, `dare2drive_thing`

### 4.5 Adding a new metric

1. Open `api/metrics.py`
2. Add your metric definition in the appropriate section (or create a new section with a comment)
3. Import it where you need it
4. Call `.inc()` / `.labels(...).inc()` / `.time()` at the right moment in your code

That is all. Prometheus picks it up automatically on the next scrape.

---

## 5. Adding metrics to a bot cog

Here is a complete, minimal example of a bot cog that uses both logging and metrics correctly.

```python
"""Example cog showing logging + metrics patterns."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

# Import the specific metrics you need
from api.metrics import bot_command_errors, bot_commands_invoked, packs_opened
from config.logging import get_logger
from db.session import async_session

log = get_logger(__name__)


class ExampleCog(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="openpack", description="Open a card pack")
    @app_commands.describe(pack_type="Type of pack to open")
    async def openpack(self, interaction: discord.Interaction, pack_type: str) -> None:
        user_id = str(interaction.user.id)
        log.info("Pack open requested: user_id=%s pack_type=%s", user_id, pack_type)

        # Always track that the command was invoked — useful for volume graphs
        bot_commands_invoked.labels(command="openpack").inc()

        try:
            async with async_session() as session:
                # ... your logic here ...
                cards = []  # replace with real logic

            # Track the business event with a label for the pack type
            packs_opened.labels(pack_type=pack_type).inc()

            log.info(
                "Pack opened: user_id=%s pack_type=%s cards_granted=%d",
                user_id, pack_type, len(cards),
            )
            await interaction.response.send_message(f"You opened a {pack_type}!", ephemeral=True)

        except Exception as exc:
            # Log the full traceback so it appears in Loki
            log.error("Pack open failed: user_id=%s pack_type=%s", user_id, pack_type, exc_info=True)

            # Track the error so we can alert on error rate spikes
            bot_command_errors.labels(command="openpack").inc()

            await interaction.response.send_message(
                "Something went wrong opening your pack. Try again.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExampleCog(bot))
```

**Key patterns to copy:**

- `log = get_logger(__name__)` at the top of every file
- `bot_commands_invoked.labels(command="...").inc()` at the start of every command
- `some_business_metric.labels(...).inc()` after the core logic succeeds
- `bot_command_errors.labels(command="...").inc()` in every `except` block
- `log.error(..., exc_info=True)` in every `except` block — `exc_info=True` captures the traceback

---

## 6. Adding metrics to an API route

API routes get HTTP-level metrics automatically from `prometheus_fastapi_instrumentator`
(registered in `api/main.py`) — you do not need to do anything for basic request count
and latency. Add metrics only for business events.

```python
"""Example API route with business metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import currency_spent, users_registered
from config.logging import get_logger
from db.session import get_db   # your DB dependency

log = get_logger(__name__)
router = APIRouter()


@router.post("/users/{user_id}/purchase")
async def purchase_item(
    user_id: str,
    item_type: str,
    cost: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    log.info("Purchase started: user_id=%s item_type=%s cost=%d", user_id, item_type, cost)

    try:
        # ... deduct currency, grant item ...

        # Track currency flow — label by what it was spent on
        currency_spent.labels(reason=item_type).inc(cost)

        log.info("Purchase complete: user_id=%s item_type=%s", user_id, item_type)
        return {"status": "ok"}

    except ValueError as exc:
        log.warning("Purchase rejected: user_id=%s reason=%s", user_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    except Exception:
        log.error("Purchase failed unexpectedly: user_id=%s item_type=%s", user_id, item_type, exc_info=True)
        raise HTTPException(status_code=500, detail="Purchase failed")
```

**Note:** HTTP status codes, latency, and request counts are already tracked automatically.
You only need to add metrics for things that matter to the *game* (currency flows, races,
registrations) not to the *HTTP layer*.

---

## 7. Adding an alerting rule

Alert rules live in **`monitoring/railway/grafana/alerting/rules.yml`** in the Grafana Stack
submodule. They use Grafana's unified alerting format and fire Discord notifications via the
pre-configured contact point.

> Alerting is production-only — there is no local Alertmanager or notification relay.
> Test your PromQL expression in the local Prometheus UI first, then add the rule.

### 7.1 Rule anatomy

Each rule has two data nodes: a Prometheus query (A) and a threshold expression (B).

```yaml
- uid: my-feature-alert          # unique string — use kebab-case, no spaces
  title: "Human-readable title"
  condition: B                   # B is the node that must be true to fire
  data:
    # Node A — the Prometheus query
    - refId: A
      relativeTimeRange: { from: 300, to: 0 }
      datasourceUid: grafana_prometheus
      model:
        expr: "<PromQL expression>"
        instant: true
        refId: A

    # Node B — the threshold condition evaluated against A
    - refId: B
      datasourceUid: "-100"
      model:
        type: classic_conditions
        refId: B
        conditions:
          - evaluator: { params: [<threshold>], type: gt }  # gt = greater than, lt = less than
            operator: { type: and }
            query: { params: [A] }
            reducer: { params: [], type: last }
            type: query

  noDataState: NoData    # NoData | Alerting — what to do when the query returns nothing
  execErrState: Error    # Error | Alerting — what to do on a query error
  for: 5m                # must stay true for this long before firing
  labels:
    severity: warning    # "warning" or "critical"
  annotations:
    summary: "One-line description shown in the Discord notification title"
    description: "Longer explanation — what does this mean and what should you look at?"
  isPaused: false
```

All rules go inside the existing group in `rules.yml`:

```yaml
groups:
  - orgId: 1
    name: dare2drive
    folder: Dare2Drive
    interval: 1m
    rules:
      - uid: d2d-api-down       # existing rule
        ...
      - uid: my-new-rule        # your rule goes here
        ...
```

### 7.2 Writing a PromQL expression

PromQL is the query language Prometheus uses. Here are the patterns you will use most often:

**Is a rate above a threshold?**
```promql
# Error rate: errors / total > 10 %
(
  rate(dare2drive_bot_command_errors_total[5m])
  /
  rate(dare2drive_bot_commands_total[5m])
) > 0.10
```

**Has a counter stopped increasing?**
```promql
# No packs opened in the last 30 minutes (could indicate the bot is stuck)
rate(dare2drive_packs_opened_total[30m]) == 0
```

**Is a value above a raw threshold?**
```promql
# More than 1000 parts destroyed in the last hour (economy sanity check)
increase(dare2drive_parts_destroyed_total[1h]) > 1000
```

**Filter by label:**
```promql
# Only "wreck" destructions, not "wear"
increase(dare2drive_parts_destroyed_total{reason="wreck"}[1h]) > 500
```

Test any expression in the local Prometheus UI at `http://localhost:9090/graph` before
adding it as a rule.

### 7.3 Adding a rule — step by step

1. Test the PromQL expression locally: `d2d up --monitoring`, open `http://localhost:9090/graph`
2. Open `monitoring/railway/grafana/alerting/rules.yml`
3. Add your rule to the `rules:` list following the template above
4. Commit and push the submodule:
   ```bash
   cd monitoring/railway
   git add alerting/rules.yml
   git commit -m "feat: add HighTradeFailureRate alert"
   git push
   ```
5. Redeploy the Grafana service on Railway (or wait for auto-deploy)
6. In Grafana → **Alerting** → **Alert rules**, verify your rule appears and its state is **Normal**

### 7.4 Example — alerting on a new feature

Say you added a `trade` feature and want to alert if trades are failing at a high rate:

```yaml
      - uid: d2d-high-trade-failure-rate
        title: "High Trade Failure Rate"
        condition: B
        data:
          - refId: A
            relativeTimeRange: { from: 300, to: 0 }
            datasourceUid: grafana_prometheus
            model:
              expr: >
                rate(dare2drive_trades_failed_total[5m])
                / rate(dare2drive_trades_initiated_total[5m])
                * 100
              instant: true
              refId: A
          - refId: B
            datasourceUid: "-100"
            model:
              type: classic_conditions
              refId: B
              conditions:
                - evaluator: { params: [15], type: gt }
                  operator: { type: and }
                  query: { params: [A] }
                  reducer: { params: [], type: last }
                  type: query
        noDataState: NoData
        execErrState: Error
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High trade failure rate (>15%)"
          description: "More than 15% of trade attempts are failing. Check bot logs for errors."
        isPaused: false
```

---

## 8. End-to-end example — a new `/trade` feature

This section walks through adding monitoring to a brand new feature from scratch.

### Step 1 — Define your metrics in `api/metrics.py`

Think about what you want to graph and alert on before you write any feature code.
For a trade feature you probably want to know:
- How many trades are being initiated?
- How many complete vs fail?

```python
# In api/metrics.py, add a new section:

# ---------------------------------------------------------------------------
# Trade metrics
# ---------------------------------------------------------------------------

trades_initiated = Counter(
    "dare2drive_trades_initiated_total",
    "Total number of trade offers sent.",
)

trades_completed = Counter(
    "dare2drive_trades_completed_total",
    "Total number of trades successfully completed.",
)

trades_failed = Counter(
    "dare2drive_trades_failed_total",
    "Total number of trades that failed or were declined.",
    ["reason"],  # "declined" | "expired" | "error" | "insufficient_funds"
)
```

### Step 2 — Add logging and metrics to your cog

```python
"""Trade cog — /trade command."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from api.metrics import bot_command_errors, bot_commands_invoked, trades_completed, trades_failed, trades_initiated
from config.logging import get_logger
from db.session import async_session

log = get_logger(__name__)


class TradeCog(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="trade", description="Offer a card trade to another player")
    @app_commands.describe(target="The user to trade with", card="The card you are offering")
    async def trade(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        card: str,
    ) -> None:
        sender_id = str(interaction.user.id)
        target_id = str(target.id)

        bot_commands_invoked.labels(command="trade").inc()
        log.info("Trade initiated: sender_id=%s target_id=%s card=%s", sender_id, target_id, card)
        trades_initiated.inc()

        try:
            async with async_session() as session:
                if sender_id == target_id:
                    log.warning("Trade self-attempt: user_id=%s", sender_id)
                    trades_failed.labels(reason="declined").inc()
                    await interaction.response.send_message(
                        "You can't trade with yourself.", ephemeral=True
                    )
                    return

                # ... look up card, check ownership, send offer to target_id ...

                trades_completed.inc()
                log.info(
                    "Trade completed: sender_id=%s target_id=%s card=%s",
                    sender_id, target_id, card,
                )
                await interaction.response.send_message("Trade offer sent!", ephemeral=True)

        except Exception:
            log.error(
                "Trade failed unexpectedly: sender_id=%s target_id=%s card=%s",
                sender_id, target_id, card,
                exc_info=True,
            )
            bot_command_errors.labels(command="trade").inc()
            trades_failed.labels(reason="error").inc()
            await interaction.response.send_message(
                "Something went wrong with the trade. Try again.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradeCog(bot))
```

### Step 3 — Add an alert rule

In `monitoring/railway/grafana/alerting/rules.yml`, add to the `rules:` list:

```yaml
      - uid: d2d-high-trade-failure-rate
        title: "High Trade Failure Rate"
        condition: B
        data:
          - refId: A
            relativeTimeRange: { from: 300, to: 0 }
            datasourceUid: grafana_prometheus
            model:
              expr: >
                rate(dare2drive_trades_failed_total[5m])
                / rate(dare2drive_trades_initiated_total[5m])
                * 100
              instant: true
              refId: A
          - refId: B
            datasourceUid: "-100"
            model:
              type: classic_conditions
              refId: B
              conditions:
                - evaluator: { params: [15], type: gt }
                  operator: { type: and }
                  query: { params: [A] }
                  reducer: { params: [], type: last }
                  type: query
        noDataState: NoData
        execErrState: Error
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High trade failure rate (>15%)"
          description: "More than 15% of trade attempts are failing. Check bot logs: logger=bot.cogs.trade"
        isPaused: false
```

### Step 4 — Verify end-to-end

```bash
# Start the local metrics stack
d2d up --monitoring

# In another terminal, tail bot logs
docker compose logs -f bot

# Trigger the /trade command in Discord

# Check the metric was recorded
curl -s http://localhost:8000/metrics | grep dare2drive_trades

# Check Prometheus has it
# Open http://localhost:9090/graph → query: dare2drive_trades_initiated_total

# Push the alert rule to the submodule, redeploy Grafana on Railway, then:
# Grafana → Alerting → Alert rules → verify HighTradeFailureRate shows Normal
```

---

## 9. Viewing your data

### 9.1 Logs — locally

There is no local Loki. Follow logs directly from Docker:

```bash
# Both services
docker compose logs -f bot api

# Bot only
docker compose logs -f bot

# Filter to errors (requires jq)
docker compose logs bot --no-log-prefix | jq 'select(.level == "ERROR")'
```

### 9.2 Logs — production (Loki in Grafana)

1. Open the Railway Grafana instance
2. Left sidebar → **Explore** (compass icon)
3. Top-left dropdown → select **Loki**
4. Use the **Label filters** builder or type a LogQL query directly

Useful LogQL queries:

```logql
# All app logs
{service_name=~"api|bot"}

# Filter to your module
{service_name="bot"} | json | logger=`bot.cogs.trade`

# All errors across all services
{service_name=~"api|bot"} | json | level=`ERROR`

# Logs for a specific user
{service_name="bot"} | json |= "user_id=123456789"
```

### 9.3 Metrics in Prometheus (local)

1. Open Prometheus: <http://localhost:9090>
2. Click **Graph**
3. Type a PromQL query in the expression box

Useful queries:

```promql
# Total packs opened (all time)
dare2drive_packs_opened_total

# Pack open rate per minute, broken down by pack type
rate(dare2drive_packs_opened_total[5m]) * 60

# Bot command error rate
rate(dare2drive_bot_command_errors_total[5m])
  /
rate(dare2drive_bot_commands_total[5m])
```

### 9.4 Metrics in Grafana (dashboards)

The **Dare2Drive** dashboard in the Railway Grafana instance shows:

- Request rate, 5xx error rate, P95 latency, API status (stat panels)
- Requests/sec by handler, response status codes (time series)
- Latency percentiles (p50/p95/p99), latency by handler (time series)
- App logs from Loki (logs panel)

Locally: Grafana at `http://localhost:3000` → Explore → Prometheus for ad-hoc queries.
To build a local dashboard: **+** → **New dashboard** → **Add visualization** → select Prometheus.

### 9.5 Checking alert rules

Alert rules are managed in Grafana, not Prometheus. To check their state:

1. Open the Railway Grafana instance
2. Left sidebar → **Alerting** → **Alert rules**
3. Rules show as **Normal** (condition not met), **Pending** (condition met but `for:` not elapsed),
   or **Firing** (alert is active and Discord notification has been sent)

---

## 10. Quick reference cheat sheet

### Logging

```python
from config.logging import get_logger
log = get_logger(__name__)

log.debug("msg: var=%s", var)       # development detail only
log.info("msg: user_id=%s", uid)    # notable events
log.warning("msg: reason=%s", r)    # unexpected but handled
log.error("msg: id=%s", id, exc_info=True)  # failure — always exc_info=True
```

### Metrics

```python
from api.metrics import (
    bot_commands_invoked,   # inc at top of every command
    bot_command_errors,     # inc in every except block
    races_started,          # inc when a race begins
    races_completed,        # inc when a race ends (label: outcome)
    packs_opened,           # inc when a pack is opened (label: pack_type)
    currency_spent,         # inc with the amount when currency is spent (label: reason)
    users_registered,       # inc when tutorial completes
    parts_destroyed,        # inc when a part is destroyed (label: reason)
)

# Counter — no labels
daily_claimed.inc()

# Counter — with labels
packs_opened.labels(pack_type="junkyard").inc()

# Counter — increment by more than 1
currency_spent.labels(reason="junkyard_pack").inc(100)

# Histogram — time a block of code
with api_request_duration_seconds.labels(route="/race").time():
    result = await do_work()
```

### Alert rule template

Add to `monitoring/railway/grafana/alerting/rules.yml` under `rules:`:

```yaml
      - uid: d2d-my-feature-alert    # unique kebab-case string
        title: "My Feature Alert"
        condition: B
        data:
          - refId: A
            relativeTimeRange: { from: 300, to: 0 }
            datasourceUid: grafana_prometheus
            model:
              expr: "rate(dare2drive_my_metric_total[5m]) > 0"
              instant: true
              refId: A
          - refId: B
            datasourceUid: "-100"
            model:
              type: classic_conditions
              refId: B
              conditions:
                - evaluator: { params: [0.10], type: gt }
                  operator: { type: and }
                  query: { params: [A] }
                  reducer: { params: [], type: last }
                  type: query
        noDataState: NoData
        execErrState: Error
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "My feature failing >10%"
          description: "Investigate: {service_name='bot'} | json | logger='bot.cogs.myfeature'"
        isPaused: false
```

### Useful `docker compose` shortcuts

```bash
# Watch bot and api logs live
docker compose logs -f bot api

# Watch all monitoring container logs
docker compose logs -f prometheus grafana

# Check the /metrics endpoint is responding
curl -s http://localhost:8000/metrics | grep dare2drive_
```
