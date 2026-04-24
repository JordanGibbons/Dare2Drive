"""Unit tests for engine.crew_xp — pure XP math."""

from __future__ import annotations

from unittest.mock import MagicMock

from engine.crew_xp import MAX_LEVEL, award_xp, xp_for_next


def _member(level: int = 1, xp: int = 0) -> MagicMock:
    m = MagicMock()
    m.level = level
    m.xp = xp
    return m


class TestXpForNext:
    def test_level_1_to_2_is_50(self):
        assert xp_for_next(1) == 50

    def test_level_2_to_3_is_200(self):
        assert xp_for_next(2) == 200

    def test_level_9_to_10_is_4050(self):
        assert xp_for_next(9) == 4050


class TestAwardXp:
    def test_below_threshold_no_level_up(self):
        m = _member(level=1, xp=0)
        leveled = award_xp(m, 30)
        assert m.xp == 30
        assert m.level == 1
        assert leveled is False

    def test_exact_threshold_levels_up(self):
        m = _member(level=1, xp=0)
        leveled = award_xp(m, 50)
        assert m.level == 2
        assert m.xp == 0  # consumed
        assert leveled is True

    def test_multi_level_in_one_grant(self):
        # 50 XP → L2, 200 XP → L3, 450 XP → L4. Total 700 jumps from L1 to L4.
        m = _member(level=1, xp=0)
        leveled = award_xp(m, 700)
        assert m.level == 4
        # After L4, xp remains 700 - 50 - 200 - 450 = 0
        assert m.xp == 0
        assert leveled is True

    def test_partial_xp_after_level_up_retained(self):
        m = _member(level=1, xp=0)
        award_xp(m, 75)
        assert m.level == 2
        assert m.xp == 25  # 75 - 50 = 25

    def test_level_cap_at_10(self):
        m = _member(level=10, xp=0)
        leveled = award_xp(m, 100_000)
        assert m.level == MAX_LEVEL
        assert m.xp == 0  # capped; excess discarded
        assert leveled is False

    def test_approaching_cap_caps_cleanly(self):
        m = _member(level=9, xp=0)
        # L9 → L10 needs 4050 XP; award 10_000 should land at L10 with 0 xp
        award_xp(m, 10_000)
        assert m.level == MAX_LEVEL
        assert m.xp == 0
