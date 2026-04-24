"""Tests for scripts/generate_card_image.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.generate_card_image import RARITY_PALETTE, _apply_ghost_shimmer, render_card


class TestRenderCard:
    def test_renders_common_card(self):
        card = {
            "name": "Test Reactor",
            "slot": "reactor",
            "rarity": "common",
            "stats": {
                "primary": {"power": 50, "acceleration": 40},
                "secondary": {"durability": 60},
            },
        }
        img = render_card(card)
        assert isinstance(img, Image.Image)
        assert img.size == (400, 560)
        assert img.mode == "RGBA"

    def test_renders_ghost_card_with_shimmer(self):
        card = {
            "name": "Ghost Reactor",
            "slot": "reactor",
            "rarity": "ghost",
            "stats": {
                "primary": {"power": 98},
                "secondary": {"durability": 96},
            },
            "print_max": 100,
        }
        img = render_card(card, print_number=42)
        assert isinstance(img, Image.Image)
        assert img.size == (400, 560)

    def test_renders_legendary_with_print_number(self):
        card = {
            "name": "Legendary Reactor",
            "slot": "reactor",
            "rarity": "legendary",
            "stats": {
                "primary": {"power": 94},
                "secondary": {"durability": 90},
            },
            "print_max": 500,
        }
        img = render_card(card, print_number=123)
        assert isinstance(img, Image.Image)

    def test_renders_with_nonexistent_art_path(self):
        card = {
            "name": "Art Test",
            "slot": "thrusters",
            "rarity": "rare",
            "stats": {"primary": {"grip": 50}, "secondary": {}},
        }
        img = render_card(card, art_path="/nonexistent/art.png")
        assert isinstance(img, Image.Image)

    @pytest.mark.parametrize("rarity", list(RARITY_PALETTE.keys()))
    def test_all_rarities_renderable(self, rarity):
        card = {
            "name": f"Test {rarity}",
            "slot": "reactor",
            "rarity": rarity,
            "stats": {"primary": {"power": 50}, "secondary": {"durability": 50}},
        }
        img = render_card(card)
        assert img.size == (400, 560)

    def test_renders_all_real_cards(self):
        """Render every card from the seed data."""
        cards_dir = Path(__file__).resolve().parent.parent / "data" / "cards"
        for json_file in cards_dir.glob("*.json"):
            with open(json_file) as f:
                cards = json.load(f)
            for card in cards:
                img = render_card(card)
                assert isinstance(img, Image.Image), f"Failed to render {card['name']}"


class TestGhostShimmer:
    def test_shimmer_preserves_size(self):
        img = Image.new("RGBA", (400, 560), (0, 0, 0, 255))
        result = _apply_ghost_shimmer(img)
        assert result.size == img.size
        assert result.mode == "RGBA"
