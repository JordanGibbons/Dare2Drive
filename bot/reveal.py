"""Presentation adapters for the pack-reveal widget.

This module defines the ``RevealEntry`` protocol used by ``_PackRevealView``
in :mod:`bot.cogs.cards`, plus two concrete adapters:

* :class:`PartRevealEntry` — wraps a part-card mint (``Card`` + ``UserCard``).
* :class:`CrewRevealEntry` — wraps a crew dossier reveal.

Each adapter renders a fully-formed embed body for a single entry. The view
overlays a pagination footer afterward.

This module is intentionally a pure presentation layer — no DB or business
logic, just dataclasses + ``discord.Embed`` construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import discord

RARITY_COLORS = {
    "common": 0x9CA3AF,
    "uncommon": 0x22C55E,
    "rare": 0x3B82F6,
    "epic": 0xA855F7,
    "legendary": 0xF59E0B,
    "ghost": 0xFFFFFF,
}

RARITY_EMOJI = {
    "common": "⬜",
    "uncommon": "🟩",
    "rare": "🟦",
    "epic": "🟪",
    "legendary": "🟨",
    "ghost": "👻",
}


@runtime_checkable
class RevealEntry(Protocol):
    """Anything that can render itself as an embed inside ``_PackRevealView``."""

    name: str
    rarity: str

    def build_embed(self) -> discord.Embed:
        """Return a fully-formed embed for THIS entry.

        The caller (``_PackRevealView``) appends a position-counter footer
        afterward.
        """
        ...


@dataclass
class PartRevealEntry:
    """A part-card reveal entry — preserves the historical pack-reveal embed."""

    name: str
    rarity: str
    slot: str
    serial_number: int
    print_max: int | None = None
    primary_stats: dict[str, float] = field(default_factory=dict)
    secondary_stats: dict[str, float] = field(default_factory=dict)

    def build_embed(self) -> discord.Embed:
        color = RARITY_COLORS.get(self.rarity, 0x9CA3AF)
        emoji = RARITY_EMOJI.get(self.rarity, "")
        embed = discord.Embed(
            title=f"{emoji} {self.name} #{self.serial_number}",
            description=(f"**Slot:** {self.slot.title()}\n**Rarity:** {self.rarity.title()}"),
            color=color,
        )
        if self.primary_stats:
            embed.add_field(
                name="Primary Stats",
                value="\n".join(f"`{k}`: {v}" for k, v in self.primary_stats.items()),
                inline=True,
            )
        if self.secondary_stats:
            embed.add_field(
                name="Secondary Stats",
                value="\n".join(f"`{k}`: {v}" for k, v in self.secondary_stats.items()),
                inline=True,
            )
        if self.print_max:
            embed.set_footer(text=f"Limited Edition — {self.print_max} prints")
        return embed


@dataclass
class CrewRevealEntry:
    """A crew dossier reveal entry — Phase 1 crew sector."""

    name: str
    rarity: str
    archetype: str
    level: int
    primary_stat: str
    secondary_stat: str

    def build_embed(self) -> discord.Embed:
        color = RARITY_COLORS.get(self.rarity, 0x9CA3AF)
        emoji = RARITY_EMOJI.get(self.rarity, "")
        embed = discord.Embed(
            title=f"{emoji} {self.name}",
            description=(
                f"**Archetype:** {self.archetype.title()}\n" f"**Rarity:** {self.rarity.title()}"
            ),
            color=color,
        )
        embed.add_field(name="Level", value=str(self.level), inline=True)
        embed.add_field(
            name="Boosts",
            value=f"`{self.primary_stat}` / `{self.secondary_stat}`",
            inline=True,
        )
        return embed
