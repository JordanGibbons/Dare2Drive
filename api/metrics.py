"""Application-level Prometheus metrics for Dare2Drive.

Import and call these counters/histograms from anywhere in the app to track
key business events.  The ``/metrics`` endpoint (registered in ``api/main.py``)
exposes them for Prometheus to scrape.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Race metrics
# ---------------------------------------------------------------------------

races_started = Counter(
    "dare2drive_races_started_total",
    "Total number of races started.",
    ["race_type"],  # "tutorial" | "open" | "street" | ...
)

races_completed = Counter(
    "dare2drive_races_completed_total",
    "Total number of races completed.",
    ["race_type", "outcome"],  # outcome: "win" | "loss" | "wreck"
)

# ---------------------------------------------------------------------------
# Economy / pack metrics
# ---------------------------------------------------------------------------

packs_opened = Counter(
    "dare2drive_packs_opened_total",
    "Total number of card packs opened.",
    ["pack_type"],  # "junkyard" | "performance" | "legend"
)

daily_claimed = Counter(
    "dare2drive_daily_claimed_total",
    "Total number of /daily claims.",
)

currency_spent = Counter(
    "dare2drive_currency_spent_total",
    "Total amount of in-game currency spent.",
    ["reason"],  # "junkyard_pack" | "performance_pack" | "legend_crate" | "new_build" | ...
)

# ---------------------------------------------------------------------------
# User metrics
# ---------------------------------------------------------------------------

users_registered = Gauge(
    "dare2drive_users_registered_total",
    "Total number of users who completed registration / tutorial.",
)

# ---------------------------------------------------------------------------
# Part / inventory metrics
# ---------------------------------------------------------------------------

parts_destroyed = Counter(
    "dare2drive_parts_destroyed_total",
    "Total number of parts destroyed (wear-out or wreck).",
    ["reason"],  # "wear" | "wreck"
)

# ---------------------------------------------------------------------------
# Discord bot command metrics
# ---------------------------------------------------------------------------

bot_commands_invoked = Counter(
    "dare2drive_bot_commands_total",
    "Total number of Discord slash-commands invoked.",
    ["command"],
)

bot_command_errors = Counter(
    "dare2drive_bot_command_errors_total",
    "Total number of Discord slash-command errors.",
    ["command"],
)

# ---------------------------------------------------------------------------
# API latency histogram (supplementary — FastAPI instrumentator adds its own)
# ---------------------------------------------------------------------------

api_request_duration_seconds = Histogram(
    "dare2drive_api_request_duration_seconds",
    "HTTP request duration in seconds (custom, per-business-route).",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
