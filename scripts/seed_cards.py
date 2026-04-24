"""Seed card data from JSON files into the database."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from config.logging import get_logger, setup_logging
from db.models import Card
from db.session import async_session

setup_logging()
log = get_logger(__name__)

CARDS_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"

SLOT_FILE_MAP = {
    "reactors.json": "reactor",
    "drives.json": "drive",
    "thrusters.json": "thrusters",
    "stabilizers.json": "stabilizers",
    "hulls.json": "hull",
    "overdrives.json": "overdrive",
    "retros.json": "retros",
}


async def seed_cards() -> None:
    """Load all card JSON files and upsert into the database."""
    total = 0

    async with async_session() as session:
        for filename, expected_slot in SLOT_FILE_MAP.items():
            filepath = CARDS_DIR / filename
            if not filepath.exists():
                log.warning("Missing card file: %s", filepath)
                continue

            with open(filepath, "r", encoding="utf-8") as f:
                card_list = json.load(f)

            for card_data in card_list:
                name = card_data["name"]
                # Check if card already exists
                result = await session.execute(select(Card).where(Card.name == name))
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing card
                    existing.slot = card_data.get("slot", expected_slot)
                    existing.rarity = card_data["rarity"]
                    existing.stats = card_data["stats"]
                    existing.print_max = card_data.get("print_max")
                    log.debug("Updated card: %s", name)
                else:
                    card = Card(
                        name=name,
                        slot=card_data.get("slot", expected_slot),
                        rarity=card_data["rarity"],
                        stats=card_data["stats"],
                        print_max=card_data.get("print_max"),
                    )
                    session.add(card)
                    log.debug("Added card: %s", name)

                total += 1

        await session.commit()

    log.info("Seeded %d cards total", total)


async def main() -> None:
    log.info("Seeding cards...")
    await seed_cards()
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
