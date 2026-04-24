"""Durability system — per-part failure rolls, wreck mechanics, and part loss."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from config.logging import get_logger

log = get_logger(__name__)


class FailureSeverity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    DNF = "dnf"


@dataclass
class FailureEvent:
    slot: str
    severity: FailureSeverity
    narrative_fragment: str


@dataclass
class WreckPart:
    card_id: str
    slot: str
    card_name: str

    def to_dict(self) -> dict[str, str]:
        return {"card_id": self.card_id, "slot": self.slot, "card_name": self.card_name}


@dataclass
class DurabilityResult:
    failures: list[FailureEvent] = field(default_factory=list)
    dnf: bool = False
    score_multiplier: float = 1.0
    wrecked_parts: list[WreckPart] = field(default_factory=list)


def _determine_severity(excess: int) -> FailureSeverity:
    """Determine failure severity based on how far the roll exceeds durability."""
    if excess <= 20:
        return FailureSeverity.MINOR
    elif excess <= 40:
        return FailureSeverity.MAJOR
    else:
        return FailureSeverity.DNF


def _should_part_survive_wreck(rarity: str) -> bool:
    """Check wreck immunity based on card rarity."""
    if rarity == "ghost":
        return True  # Ghost Print cards never lost
    if rarity == "legendary":
        return random.random() < 0.5  # 50% chance to survive
    return False  # Common/Uncommon/Rare/Epic — no immunity


def check_durability(
    slot_durabilities: dict[str, float],
    equipped_cards: dict[str, dict[str, Any]],
    turbo_temp_increase: float = 0.0,
    engine_max_temp: float = 0.0,
) -> DurabilityResult:
    """
    Roll durability checks for each equipped part.

    Parameters
    ----------
    slot_durabilities : dict mapping slot → durability value (0-100)
    equipped_cards : dict mapping slot → card data dict (needs id, name, rarity, stats)
    turbo_temp_increase : overdrive engine_temp_increase stat
    engine_max_temp : reactor max_engine_temp stat
    """
    result = DurabilityResult()
    worst_multiplier = 1.0
    dnf_slot: str | None = None

    for slot, durability in slot_durabilities.items():
        if durability <= 0:
            continue

        roll = random.uniform(0, 100)

        # Special overdrive overheat check
        if (
            slot == "overdrive"
            and turbo_temp_increase > engine_max_temp * 0.8
            and engine_max_temp > 0
        ):
            # Additional failure chance — re-roll with penalty
            overheat_penalty = (turbo_temp_increase - engine_max_temp * 0.8) * 2
            roll = max(roll, random.uniform(0, 100) + overheat_penalty)
            log.debug(
                "Overdrive overheat penalty applied: temp_inc=%.1f, max_temp=%.1f, adj_roll=%.1f",
                turbo_temp_increase,
                engine_max_temp,
                roll,
            )

        if roll > durability:
            excess = roll - durability
            severity = _determine_severity(int(excess))
            card_data = equipped_cards.get(slot, {})
            card_name = card_data.get("name", slot.title())

            if severity == FailureSeverity.MINOR:
                worst_multiplier = min(worst_multiplier, 0.85)
                narrative = f"The {card_name} stuttered mid-race — minor hiccup, lost some pace."
            elif severity == FailureSeverity.MAJOR:
                worst_multiplier = min(worst_multiplier, 0.60)
                narrative = (
                    f"The {card_name} took heavy damage — limping through the final stretch."
                )
            else:  # DNF
                worst_multiplier = 0.0
                dnf_slot = slot
                narrative = f"The {card_name} catastrophically failed — race over."

            result.failures.append(
                FailureEvent(slot=slot, severity=severity, narrative_fragment=narrative)
            )
            log.info(
                "Durability failure: slot=%s, severity=%s, roll=%.1f, dur=%.1f",
                slot,
                severity.value,
                roll,
                durability,
            )

    result.score_multiplier = worst_multiplier
    result.dnf = worst_multiplier == 0.0

    # Wreck mechanic — only on DNF
    if result.dnf:
        result.wrecked_parts = _resolve_wreck(equipped_cards, dnf_slot)

    return result


def _resolve_wreck(
    equipped_cards: dict[str, dict[str, Any]],
    failed_slot: str | None,
) -> list[WreckPart]:
    """
    Determine which parts are destroyed in a wreck.
    Selects 1-3 parts, weighted toward the part that caused the DNF.
    """
    candidates: list[str] = [s for s in equipped_cards if equipped_cards[s]]
    if not candidates:
        return []

    num_lost = random.randint(1, min(3, len(candidates)))

    # Weight the failed slot more heavily
    weights = []
    for slot in candidates:
        if slot == failed_slot:
            weights.append(3.0)
        else:
            weights.append(1.0)

    selected_slots = []
    remaining = list(zip(candidates, weights))

    for _ in range(num_lost):
        if not remaining:
            break
        slots_list, wts = zip(*remaining)
        chosen = random.choices(list(slots_list), weights=list(wts), k=1)[0]
        selected_slots.append(chosen)
        remaining = [(s, w) for s, w in remaining if s != chosen]

    wrecked: list[WreckPart] = []
    for slot in selected_slots:
        card = equipped_cards[slot]
        rarity = card.get("rarity", "common")
        if _should_part_survive_wreck(rarity):
            log.info("Part survived wreck due to rarity immunity: slot=%s rarity=%s", slot, rarity)
            continue
        wrecked.append(
            WreckPart(
                card_id=str(card.get("id", "")),
                slot=slot,
                card_name=card.get("name", slot.title()),
            )
        )

    return wrecked
