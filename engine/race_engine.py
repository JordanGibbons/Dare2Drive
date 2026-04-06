"""Core race computation engine."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from config.logging import get_logger
from engine.durability import DurabilityResult, WreckPart, check_durability
from engine.environment import EnvironmentCondition, apply_environment_weights, roll_environment
from engine.stat_resolver import BuildStats, aggregate_build

log = get_logger(__name__)


@dataclass
class Placement:
    user_id: str
    score: float
    position: int
    dnf: bool
    narrative: str
    wrecked_parts: list[WreckPart] = field(default_factory=list)
    distance_pct: float = 1.0  # 0.0–1.0; only meaningful when dnf=True
    is_tie: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "score": round(self.score, 2),
            "position": self.position,
            "dnf": self.dnf,
            "narrative": self.narrative,
            "distance_pct": round(self.distance_pct, 3),
            "wrecked_parts": [wp.to_dict() for wp in self.wrecked_parts],
            "is_tie": self.is_tie,
        }


@dataclass
class RaceResult:
    placements: list[Placement]
    environment: EnvironmentCondition
    all_dnf: bool = False
    wrecks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "placements": [p.to_dict() for p in self.placements],
            "environment": self.environment.to_dict(),
            "all_dnf": self.all_dnf,
            "wrecks": self.wrecks,
        }


def _build_stats_to_flat(bs: BuildStats) -> dict[str, float]:
    """Convert BuildStats dataclass to flat dict for environment weighting."""
    return {
        "power": bs.effective_power,
        "handling": bs.effective_handling,
        "top_speed": bs.effective_top_speed,
        "grip": bs.effective_grip,
        "braking": bs.effective_braking,
        "durability": bs.effective_durability,
        "acceleration": bs.effective_acceleration,
        "stability": bs.effective_stability,
        "weather_performance": bs.effective_weather_performance,
    }


def _compute_base_score(weighted_stats: dict[str, float]) -> float:
    """Sum all weighted stats into a single score."""
    return sum(weighted_stats.values())


def _generate_narrative(
    user_id: str,
    equipped_cards: dict[str, dict[str, Any]],
    durability_result: DurabilityResult,
    score: float,
    position: int,
    environment: EnvironmentCondition,
    distance_pct: float = 1.0,
) -> str:
    """Generate a race narrative referencing actual part names."""
    parts_mentioned = []
    for slot in ["engine", "turbo", "tires", "chassis"]:
        card = equipped_cards.get(slot, {})
        if card:
            parts_mentioned.append(card.get("name", slot.title()))

    intro = f"Racing on the {environment.display_name}. "

    if durability_result.dnf:
        fail_frags = [f.narrative_fragment for f in durability_result.failures]
        wreck_names = [wp.card_name for wp in durability_result.wrecked_parts]
        dist_str = f"{distance_pct * 100:.0f}%"
        narrative = intro + " ".join(fail_frags)
        narrative += f" Made it {dist_str} through before it all fell apart."
        if wreck_names:
            narrative += f" Wreck on the course. Lost: {', '.join(wreck_names)}."
        else:
            narrative += " All parts survived the crash somehow."
        return narrative

    if durability_result.failures:
        fail_frags = [f.narrative_fragment for f in durability_result.failures]
        narrative = intro + " ".join(fail_frags)
        narrative += f" Finished P{position} with a score of {score:.1f}."
        return narrative

    # Clean race
    if position == 1:
        narrative = intro + f"A dominant run powered by the {parts_mentioned[0] if parts_mentioned else 'build'}."
        narrative += f" First place with a score of {score:.1f}!"
    elif position <= 3:
        narrative = intro + f"Solid performance. P{position} finish — {score:.1f} points."
    else:
        narrative = intro + f"P{position} finish with {score:.1f} points. Room for improvement."

    return narrative


def compute_race(
    builds: list[dict[str, Any]],
    environment: EnvironmentCondition | None = None,
) -> RaceResult:
    """
    Run a full race computation.

    Parameters
    ----------
    builds : list of dicts, each with:
        - user_id: str
        - slots: dict[slot_name → card_id | None]
        - cards: dict[card_id → card_data dict]
    environment : optional EnvironmentCondition; rolled randomly if not provided
    """
    if environment is None:
        environment = roll_environment()

    raw_results: list[dict[str, Any]] = []

    for build in builds:
        user_id = build["user_id"]
        slots = build["slots"]
        cards = build["cards"]

        # Build equipped_cards lookup: slot → card_data
        equipped_cards: dict[str, dict[str, Any]] = {}
        for slot_name, card_id in slots.items():
            if card_id and card_id in cards:
                equipped_cards[slot_name] = cards[card_id]

        # 1. Aggregate build stats
        body_type = build.get("body_type")
        build_stats = aggregate_build(slots, cards, body_type=body_type)

        # 2. Convert to flat dict and apply environment weights
        flat = _build_stats_to_flat(build_stats)
        weighted = apply_environment_weights(flat, environment)

        # 3. Durability checks
        dur_result = check_durability(
            slot_durabilities=build_stats.slot_durabilities,
            equipped_cards=equipped_cards,
            turbo_temp_increase=build_stats.turbo_engine_temp_increase,
            engine_max_temp=build_stats.engine_max_temp,
        )

        # 4. Compute base score
        base_score = _compute_base_score(weighted)

        # 5. Apply durability multiplier
        score = base_score * dur_result.score_multiplier

        # 6. Apply variance (±5%, scaled by environment variance multiplier)
        if not dur_result.dnf:
            variance_pct = 0.05 * environment.variance_multiplier
            variance = random.uniform(-variance_pct, variance_pct)
            score *= 1 + variance

        # 7. Compute distance_pct for DNF — how far they got before breaking down.
        #    Better builds (higher base_score) get further. Reference of 500 is
        #    roughly what a mid-tier full build scores; tune as card power scales.
        if dur_result.dnf:
            reference = 500.0
            raw_dist = (base_score / reference) * random.uniform(0.5, 1.1)
            distance_pct = round(min(0.97, max(0.03, raw_dist)), 3)
        else:
            distance_pct = 1.0

        raw_results.append({
            "user_id": user_id,
            "score": max(score, 0),
            "dnf": dur_result.dnf,
            "distance_pct": distance_pct,
            "durability_result": dur_result,
            "equipped_cards": equipped_cards,
        })

    # Sort: finishers first (by score desc), DNFs last (by distance desc)
    raw_results.sort(key=lambda r: (r["dnf"], -r["distance_pct"] if r["dnf"] else -r["score"]))

    # Determine if every racer DNF'd — affects display in the embed
    all_dnf = all(r["dnf"] for r in raw_results)

    # Assign positions — detect ties (same score for finishers, same distance for DNFs)
    placements: list[Placement] = []
    wrecks: list[dict[str, Any]] = []

    for i, r in enumerate(raw_results):
        if i == 0:
            position = 1
        else:
            prev = raw_results[i - 1]
            if r["dnf"] and prev["dnf"] and abs(r["distance_pct"] - prev["distance_pct"]) < 0.001:
                # DNF tie — same position
                position = placements[-1].position
                r["is_tie"] = True
                # Mark previous placement as tie too
                placements[-1].is_tie = True
            elif not r["dnf"] and not prev["dnf"] and abs(r["score"] - prev["score"]) < 0.01:
                position = placements[-1].position
                r["is_tie"] = True
                placements[-1].is_tie = True
            else:
                position = i + 1
        narrative = _generate_narrative(
            user_id=r["user_id"],
            equipped_cards=r["equipped_cards"],
            durability_result=r["durability_result"],
            score=r["score"],
            position=position,
            environment=environment,
            distance_pct=r["distance_pct"],
        )
        placement = Placement(
            user_id=r["user_id"],
            score=r["score"],
            position=position,
            dnf=r["dnf"],
            narrative=narrative,
            wrecked_parts=r["durability_result"].wrecked_parts,
            distance_pct=r["distance_pct"],
            is_tie=r.get("is_tie", False),
        )
        placements.append(placement)

        if r["durability_result"].wrecked_parts:
            wrecks.append({
                "user_id": r["user_id"],
                "lost_parts": [wp.to_dict() for wp in r["durability_result"].wrecked_parts],
            })

    log.info(
        "Race complete: %d participants, environment=%s, %d wrecks",
        len(placements), environment.name, len(wrecks),
    )

    return RaceResult(placements=placements, environment=environment, all_dnf=all_dnf, wrecks=wrecks)
