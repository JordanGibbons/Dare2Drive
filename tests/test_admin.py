"""Tests for bot/cogs/admin.py — specifically deletion ordering in reset_player."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Delete, Update

from bot.cogs.admin import _delete_player_data
from db.models import Build, MarketListing, ShipTitle, UserCard, WreckLog


class TestDeletePlayerData:
    """
    _delete_player_data must handle the circular FK between builds and rig_titles:

      builds.rig_title_id → rig_titles.id   (fk_builds_rig_title_id)
      rig_titles.build_id → builds.id

    The only safe deletion sequence is:
      1. NULL out builds.rig_title_id  (breaks the builds→rig_titles reference)
      2. DELETE rig_titles
      3. DELETE builds

    Tests record (operation, entity) tuples so ordering constraints can be
    asserted precisely.
    """

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.delete = AsyncMock()
        return session

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.discord_id = "123456789"
        return user

    @pytest.fixture
    def ops_recorder(self, mock_session, mock_user):
        """Return (ops, session, user) where ops is filled after the call."""
        ops: list[tuple[str, type]] = []  # ("DELETE"|"UPDATE", EntityClass)

        async def record_execute(stmt):
            entity = stmt.entity_description["entity"]
            if isinstance(stmt, Delete):
                ops.append(("DELETE", entity))
            elif isinstance(stmt, Update):
                ops.append(("UPDATE", entity))

        async def record_user_delete(obj):
            ops.append(("DELETE", type(obj)))

        mock_session.execute.side_effect = record_execute
        mock_session.delete.side_effect = record_user_delete
        return ops, mock_session, mock_user

    @pytest.mark.asyncio
    async def test_builds_nulled_before_rig_titles_deleted(self, ops_recorder):
        """builds.rig_title_id must be NULLed before rig_titles is deleted (circular FK)."""
        ops, session, user = ops_recorder
        await _delete_player_data(session, "123456789", user)

        null_idx = ops.index(("UPDATE", Build))
        del_rig_idx = ops.index(("DELETE", ShipTitle))
        assert null_idx < del_rig_idx, (
            "builds.rig_title_id must be NULLed before DELETE rig_titles "
            "to break the circular FK"
        )

    @pytest.mark.asyncio
    async def test_rig_title_deleted_before_build(self, ops_recorder):
        """ShipTitle rows must be deleted before Build rows (FK: ship_titles.build_id)."""
        ops, session, user = ops_recorder
        await _delete_player_data(session, "123456789", user)

        rig_idx = ops.index(("DELETE", ShipTitle))
        build_idx = ops.index(("DELETE", Build))
        assert rig_idx < build_idx, (
            f"ShipTitle must be deleted before Build; "
            f"got ShipTitle at {rig_idx}, Build at {build_idx}"
        )

    @pytest.mark.asyncio
    async def test_rig_title_deleted_before_user(self, ops_recorder):
        """ShipTitle rows must be deleted before the user row (FK: rig_titles.owner_id → users)."""
        ops, session, user = ops_recorder
        await _delete_player_data(session, "123456789", user)

        rig_idx = ops.index(("DELETE", ShipTitle))
        # user is passed as an instance (MagicMock), not a class — find it by position
        user_idx = next(
            i
            for i, (op, _) in enumerate(ops)
            if op == "DELETE"
            and ops[i][1] is not ShipTitle
            and ops[i][1] not in (WreckLog, MarketListing, UserCard, Build)
        )  # noqa: E501
        assert rig_idx < user_idx

    @pytest.mark.asyncio
    async def test_all_tables_covered(self, ops_recorder):
        """Every owned table must appear in the wipe — nothing left behind."""
        ops, session, user = ops_recorder
        await _delete_player_data(session, "123456789", user)

        deleted = {entity for op, entity in ops if op == "DELETE"}
        updated = {entity for op, entity in ops if op == "UPDATE"}

        assert WreckLog in deleted
        assert MarketListing in deleted
        assert UserCard in deleted
        assert ShipTitle in deleted
        assert Build in deleted
        assert Build in updated  # rig_title_id nulled
        session.delete.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_full_operation_order(self, ops_recorder):
        """
        Exact sequence:
          DELETE WreckLog → DELETE MarketListing → DELETE UserCard
          → UPDATE Build (NULL rig_title_id) → DELETE ShipTitle → DELETE Build → DELETE user
        """
        ops, session, user = ops_recorder
        await _delete_player_data(session, "123456789", user)

        # ops[-1] is the session.delete(user) call recorded as ("DELETE", MagicMock type)
        entity_sequence = [entity for _, entity in ops]
        assert entity_sequence[0] is WreckLog
        assert entity_sequence[1] is MarketListing
        assert entity_sequence[2] is UserCard
        assert entity_sequence[3] is Build  # UPDATE — NULL rig_title_id
        assert entity_sequence[4] is ShipTitle
        assert entity_sequence[5] is Build  # DELETE
        # entity_sequence[6] is the user instance's type (MagicMock) — just confirm it ran
        session.delete.assert_awaited_once_with(user)
