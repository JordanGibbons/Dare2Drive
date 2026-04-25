"""Tests for the _PackRevealView widget in bot/cogs/cards.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.cogs.cards import _PackRevealView
from bot.reveal import PartRevealEntry


def _make_entry(
    name: str = "Ironforge V8",
    slot: str = "engine",
    rarity: str = "rare",
    serial: int = 1,
    primary: dict | None = None,
    secondary: dict | None = None,
    print_max: int | None = None,
) -> PartRevealEntry:
    return PartRevealEntry(
        name=name,
        rarity=rarity,
        slot=slot,
        serial_number=serial,
        print_max=print_max,
        primary_stats=primary if primary is not None else {"power": 65},
        secondary_stats=secondary if secondary is not None else {"durability": 60},
    )


def _make_entries(count: int = 3) -> list[PartRevealEntry]:
    return [_make_entry(name=f"Card {i}", serial=i) for i in range(1, count + 1)]


def _make_interaction(user_id: int = 42) -> MagicMock:
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    return interaction


# ---------------------------------------------------------------------------
# build_embed
# ---------------------------------------------------------------------------


class TestBuildEmbed:
    async def test_shows_first_card_on_init(self):
        entries = _make_entries(3)
        view = _PackRevealView(entries, display_name="Junkyard Pack", owner_id=42)
        embed = view.build_embed()
        assert "Card 1" in embed.title

    async def test_footer_contains_card_counter(self):
        entries = _make_entries(3)
        view = _PackRevealView(entries, display_name="Junkyard Pack", owner_id=42)
        embed = view.build_embed()
        assert "1 of 3" in embed.footer.text
        assert "Junkyard Pack" in embed.footer.text

    async def test_footer_shows_limited_edition_for_print_max(self):
        entry = _make_entry(print_max=500)
        view = _PackRevealView([entry], display_name="Legend Crate", owner_id=42)
        embed = view.build_embed()
        assert "Limited Edition" in embed.footer.text

    async def test_primary_stats_field_present(self):
        entry = _make_entry(primary={"power": 80, "torque": 70})
        view = _PackRevealView([entry], display_name="Pack", owner_id=42)
        embed = view.build_embed()
        field_names = [f.name for f in embed.fields]
        assert "Primary Stats" in field_names

    async def test_secondary_stats_field_present(self):
        entry = _make_entry(secondary={"durability": 55})
        view = _PackRevealView([entry], display_name="Pack", owner_id=42)
        embed = view.build_embed()
        field_names = [f.name for f in embed.fields]
        assert "Secondary Stats" in field_names

    async def test_no_secondary_field_when_empty(self):
        entry = _make_entry(secondary={})
        view = _PackRevealView([entry], display_name="Pack", owner_id=42)
        embed = view.build_embed()
        field_names = [f.name for f in embed.fields]
        assert "Secondary Stats" not in field_names

    @pytest.mark.parametrize("rarity", ["common", "uncommon", "rare", "epic", "legendary", "ghost"])
    async def test_all_rarities_produce_embed(self, rarity):
        entry = _make_entry(rarity=rarity)
        view = _PackRevealView([entry], display_name="Pack", owner_id=42)
        embed = view.build_embed()
        assert embed.title is not None


# ---------------------------------------------------------------------------
# Button state
# ---------------------------------------------------------------------------


class TestButtonState:
    async def test_prev_disabled_on_first_card(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        assert view.prev_card.disabled is True
        assert view.next_card.disabled is False

    async def test_next_disabled_on_last_card(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        view.index = 2
        view._update_buttons()
        assert view.next_card.disabled is True
        assert view.prev_card.disabled is False

    async def test_both_enabled_on_middle_card(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        view.index = 1
        view._update_buttons()
        assert view.prev_card.disabled is False
        assert view.next_card.disabled is False

    async def test_single_card_both_buttons_disabled(self):
        view = _PackRevealView(_make_entries(1), display_name="Pack", owner_id=42)
        assert view.prev_card.disabled is True
        assert view.next_card.disabled is True


# ---------------------------------------------------------------------------
# Navigation callbacks
# ---------------------------------------------------------------------------


class TestNavigation:
    # @discord.ui.button replaces the method with a Button object at class level.
    # The original coroutine is stored at button.callback and takes (self, interaction, button).

    async def test_next_advances_index(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        interaction = _make_interaction(user_id=42)
        await view.next_card.callback(interaction)
        assert view.index == 1
        interaction.response.edit_message.assert_awaited_once()

    async def test_prev_decrements_index(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        view.index = 2
        interaction = _make_interaction(user_id=42)
        await view.prev_card.callback(interaction)
        assert view.index == 1
        interaction.response.edit_message.assert_awaited_once()

    async def test_wrong_user_blocked_on_next(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        interaction = _make_interaction(user_id=99)
        await view.next_card.callback(interaction)
        assert view.index == 0  # unchanged
        interaction.response.send_message.assert_awaited_once_with(
            "This isn't your pack.", ephemeral=True
        )

    async def test_wrong_user_blocked_on_prev(self):
        view = _PackRevealView(_make_entries(3), display_name="Pack", owner_id=42)
        view.index = 1
        interaction = _make_interaction(user_id=99)
        await view.prev_card.callback(interaction)
        assert view.index == 1  # unchanged
        interaction.response.send_message.assert_awaited_once_with(
            "This isn't your pack.", ephemeral=True
        )

    async def test_embed_reflects_new_index_after_next(self):
        entries = _make_entries(3)
        view = _PackRevealView(entries, display_name="Pack", owner_id=42)
        interaction = _make_interaction(user_id=42)
        await view.next_card.callback(interaction)
        embed = view.build_embed()
        assert "2 of 3" in embed.footer.text


# ---------------------------------------------------------------------------
# CrewRevealEntry — Phase 1 crew sector
# ---------------------------------------------------------------------------


class TestCrewRevealEntry:
    async def test_crew_reveal_builds_embed(self):
        from bot.reveal import CrewRevealEntry

        entry = CrewRevealEntry(
            name='Jax "Blackjack" Krell',
            rarity="rare",
            archetype="pilot",
            level=1,
            primary_stat="handling",
            secondary_stat="stability",
        )
        embed = entry.build_embed()
        flat = (embed.description or "") + " ".join(f.value for f in embed.fields)
        assert "pilot" in flat.lower()
        assert "handling" in flat.lower()
        assert "stability" in flat.lower()


class TestPackRevealViewWithCrew:
    async def test_single_crew_reveal_in_view(self):
        from bot.cogs.cards import _PackRevealView
        from bot.reveal import CrewRevealEntry

        entry = CrewRevealEntry(
            name='Mira "Sixgun" Voss',
            rarity="epic",
            archetype="engineer",
            level=1,
            primary_stat="power",
            secondary_stat="acceleration",
        )
        view = _PackRevealView(entries=[entry], display_name="Dossier", owner_id=42)
        embed = view.build_embed()
        flat = (
            (embed.title or "")
            + (embed.description or "")
            + " ".join(f.value for f in embed.fields)
        )
        assert "Mira" in flat
        # Single-entry navigation: both buttons disabled
        assert view.prev_card.disabled is True
        assert view.next_card.disabled is True
