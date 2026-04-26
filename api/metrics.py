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
    ["reason"],  # "salvage_crate" | "gear_crate" | "legend_crate" | "new_build" | ...
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

# ---------------------------------------------------------------------------
# Crew metrics
# ---------------------------------------------------------------------------

crew_recruited = Counter(
    "dare2drive_crew_recruited_total",
    "Total number of crew recruited.",
    ["source", "tier", "archetype", "rarity"],
    # source: dossier | daily_lead
    # tier: recruit_lead | dossier | elite_dossier | daily_lead (sentinel)
)

dossier_purchased = Counter(
    "dare2drive_dossier_purchased_total",
    "Total number of dossiers purchased.",
    ["tier"],
)

crew_assignment = Counter(
    "dare2drive_crew_assignment_total",
    "Crew assignment actions.",
    ["action"],  # assign | unassign | auto_unassign
)

crew_level_up = Counter(
    "dare2drive_crew_level_up_total",
    "Crew level-up events.",
    ["archetype", "from_level", "to_level"],
)

crew_boost_apply = Counter(
    "dare2drive_crew_boost_apply_total",
    "Crew boost applications during stat resolution.",
    ["archetype", "rarity"],
)

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
