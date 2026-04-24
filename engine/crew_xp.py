"""Pure XP / level-up math for crew members.

No DB access. Callers mutate `member.xp` and `member.level` in place and are
responsible for persisting.
"""

from __future__ import annotations

from typing import Any

MAX_LEVEL = 10


def xp_for_next(level: int) -> int:
    """XP required to advance FROM `level` TO `level + 1`. 50 * level^2."""
    return 50 * level * level


def award_xp(member: Any, amount: int) -> bool:
    """Add XP to a crew member, level up as long as thresholds are crossed.

    At `MAX_LEVEL`, any further XP is discarded (xp stays at 0; level does not rise).
    Returns True if the member gained at least one level.
    """
    if member.level >= MAX_LEVEL:
        member.xp = 0
        return False

    member.xp += amount
    leveled = False
    while member.level < MAX_LEVEL and member.xp >= xp_for_next(member.level):
        member.xp -= xp_for_next(member.level)
        member.level += 1
        leveled = True

    if member.level >= MAX_LEVEL:
        member.xp = 0  # cap cleanup

    return leveled
