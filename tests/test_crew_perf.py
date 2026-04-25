"""Perf sanity: apply_crew_boosts at 100 crew/build stays fast."""

from __future__ import annotations

import time
from statistics import quantiles
from unittest.mock import MagicMock

import pytest

from engine.stat_resolver import BuildStats, apply_crew_boosts


def _crew(arch, rarity, lvl):
    m = MagicMock()
    m.archetype = MagicMock(value=arch)
    m.rarity = MagicMock(value=rarity)
    m.level = lvl
    return m


@pytest.mark.perf
def test_apply_crew_boosts_p99_under_50ms_with_100_crew():
    """Called 100 times (10 races × 10 participants) with 100 crew each."""
    archetypes = ["pilot", "engineer", "gunner", "navigator", "medic"]
    rarities = ["common", "uncommon", "rare", "epic", "legendary", "ghost"]

    crew_list = []
    for i in range(100):
        crew_list.append(_crew(archetypes[i % 5], rarities[i % 6], (i % 10) + 1))

    timings: list[float] = []
    for _ in range(100):
        bs = BuildStats(
            effective_power=200.0,
            effective_handling=200.0,
            effective_top_speed=200.0,
            effective_grip=100.0,
            effective_braking=100.0,
            effective_durability=100.0,
            effective_acceleration=200.0,
            effective_stability=100.0,
            effective_weather_performance=100.0,
        )
        t0 = time.perf_counter()
        apply_crew_boosts(bs, crew_list)
        timings.append((time.perf_counter() - t0) * 1000)  # ms

    # `quantiles(data, n=100)` returns 99 cut points dividing the data into 100 equal-frequency
    # groups. Index 49 is roughly p50, 89 is roughly p90, 98 is roughly p99.
    p50 = quantiles(timings, n=100)[49]
    p90 = quantiles(timings, n=100)[89]
    p99 = quantiles(timings, n=100)[98]
    print(f"apply_crew_boosts p50={p50:.2f}ms p90={p90:.2f}ms p99={p99:.2f}ms")
    assert p99 < 50.0, f"p99 {p99:.2f}ms exceeds 50ms budget"
