"""Card image renderer using Pillow."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import get_logger

log = get_logger(__name__)

# Card dimensions
CARD_WIDTH = 400
CARD_HEIGHT = 560
BORDER = 12
CORNER_RADIUS = 16

# Rarity color palette
RARITY_PALETTE = {
    "common": "#9CA3AF",
    "uncommon": "#22C55E",
    "rare": "#3B82F6",
    "epic": "#A855F7",
    "legendary": "#F59E0B",
    "ghost": "#FFFFFF",
}

RARITY_TEXT_COLOR = {
    "common": "#374151",
    "uncommon": "#FFFFFF",
    "rare": "#FFFFFF",
    "epic": "#FFFFFF",
    "legendary": "#1F2937",
    "ghost": "#6B7280",
}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try to load a system font; fall back to default."""
    font_names = [
        "arial.ttf",
        "Arial.ttf",
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: str,
) -> None:
    """Draw a rounded rectangle."""
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_stat_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    value: float,
    max_val: float,
    fill_color: str,
    bg_color: str = "#374151",
    font: ImageFont.FreeTypeFont | None = None,
    label: str = "",
) -> int:
    """Draw a labeled stat bar. Returns the y position after the bar."""
    bar_height = 14
    label_height = 16

    if font and label:
        draw.text((x, y), f"{label}: {value}", fill="#FFFFFF", font=font)
        y += label_height + 2

    draw.rounded_rectangle((x, y, x + width, y + bar_height), radius=4, fill=bg_color)

    if max_val > 0:
        fill_width = max(2, int((abs(value) / max_val) * width))
        fill_width = min(fill_width, width)
        draw.rounded_rectangle((x, y, x + fill_width, y + bar_height), radius=4, fill=fill_color)

    return y + bar_height + 4


def _apply_ghost_shimmer(img: Image.Image) -> Image.Image:
    """Apply a white shimmer overlay for Ghost Print cards."""
    shimmer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shimmer_draw = ImageDraw.Draw(shimmer)

    # Diagonal white stripes
    for offset in range(-img.height, img.width + img.height, 30):
        shimmer_draw.line(
            [(offset, 0), (offset + img.height, img.height)],
            fill=(255, 255, 255, 40),
            width=12,
        )

    return Image.alpha_composite(img, shimmer)


def render_card(
    card_data: dict[str, Any],
    art_path: str | None = None,
    print_number: int | None = None,
) -> Image.Image:
    """
    Render a trading card image.

    Parameters
    ----------
    card_data : dict with keys: name, slot, rarity, stats
    art_path : optional path to card art image
    print_number : optional print number for limited runs
    """
    rarity = card_data.get("rarity", "common")
    bg_color = RARITY_PALETTE.get(rarity, "#9CA3AF")
    RARITY_TEXT_COLOR.get(rarity, "#FFFFFF")

    img = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)

    # 1. Rarity background
    _draw_rounded_rect(draw, (0, 0, CARD_WIDTH, CARD_HEIGHT), CORNER_RADIUS, bg_color)

    # Inner panel
    inner_x = BORDER
    inner_y = BORDER
    inner_w = CARD_WIDTH - BORDER * 2
    inner_h = CARD_HEIGHT - BORDER * 2
    _draw_rounded_rect(
        draw,
        (inner_x, inner_y, inner_x + inner_w, inner_y + inner_h),
        CORNER_RADIUS - 4,
        "#1F2937",
    )

    # 2. Art image or placeholder
    art_area_y = inner_y + 50
    art_area_h = 160
    art_area_x = inner_x + 10
    art_area_w = inner_w - 20

    if art_path and Path(art_path).exists():
        try:
            art = Image.open(art_path).convert("RGBA")
            art = art.resize((art_area_w, art_area_h), Image.Resampling.LANCZOS)
            img.paste(art, (art_area_x, art_area_y), art)
        except Exception:
            draw.rounded_rectangle(
                (art_area_x, art_area_y, art_area_x + art_area_w, art_area_y + art_area_h),
                radius=8,
                fill="#374151",
            )
            placeholder_font = _get_font(18)
            slot_label = card_data.get("slot", "?").upper()
            draw.text(
                (art_area_x + art_area_w // 2, art_area_y + art_area_h // 2),
                slot_label,
                fill="#6B7280",
                font=placeholder_font,
                anchor="mm",
            )
    else:
        draw.rounded_rectangle(
            (art_area_x, art_area_y, art_area_x + art_area_w, art_area_y + art_area_h),
            radius=8,
            fill="#374151",
        )
        placeholder_font = _get_font(18)
        slot_label = card_data.get("slot", "?").upper()
        draw.text(
            (art_area_x + art_area_w // 2, art_area_y + art_area_h // 2),
            slot_label,
            fill="#6B7280",
            font=placeholder_font,
            anchor="mm",
        )

    # 3. Frame border overlay (draw border again for crispness)
    draw.rounded_rectangle(
        (0, 0, CARD_WIDTH - 1, CARD_HEIGHT - 1),
        radius=CORNER_RADIUS,
        outline=bg_color,
        width=BORDER,
    )

    # 4. Card name
    name_font = _get_font(20, bold=True)
    name = card_data.get("name", "Unknown")
    draw.text(
        (CARD_WIDTH // 2, inner_y + 25),
        name,
        fill="#FFFFFF",
        font=name_font,
        anchor="mm",
    )

    # 5. Slot label + rarity badge
    badge_font = _get_font(12)
    slot_text = card_data.get("slot", "?").upper()
    rarity_text = rarity.upper()
    badge_str = f"{slot_text} • {rarity_text}"
    draw.text(
        (CARD_WIDTH // 2, art_area_y + art_area_h + 15),
        badge_str,
        fill=bg_color,
        font=badge_font,
        anchor="mm",
    )

    # 6. Primary stat bars
    stat_font = _get_font(11)
    stats = card_data.get("stats", {})
    primary = stats.get("primary", {})
    y_cursor = art_area_y + art_area_h + 35
    stat_x = inner_x + 15
    stat_w = inner_w - 30

    for stat_name, value in primary.items():
        max_val = 100
        if "multiplier" in stat_name:
            max_val = 1.5
        elif "modifier" in stat_name or "height" in stat_name:
            max_val = 30
        y_cursor = _draw_stat_bar(
            draw,
            stat_x,
            y_cursor,
            stat_w,
            value,
            max_val,
            fill_color=bg_color,
            font=stat_font,
            label=stat_name,
        )

    # 7. Secondary stats (text-only, smaller font, dimmed color)
    secondary = stats.get("secondary", {})
    if secondary:
        sep_y = y_cursor + 4
        draw.line((stat_x, sep_y, stat_x + stat_w, sep_y), fill="#374151", width=1)
        y_cursor = sep_y + 8
        sec_font = _get_font(10)
        for stat_name, value in secondary.items():
            val_str = f"{value:.2f}" if isinstance(value, float) and abs(value) < 10 else str(value)
            draw.text((stat_x, y_cursor), f"{stat_name}: {val_str}", fill="#9CA3AF", font=sec_font)
            y_cursor += 15

    # 8. Print number badge
    print_max = card_data.get("print_max")
    if print_max and print_number:
        badge_text = f"{print_number:03d} / {print_max}"
        badge_font_lg = _get_font(14, bold=True)
        # Badge background
        bw = 120
        bh = 24
        bx = CARD_WIDTH - BORDER - bw - 5
        by = CARD_HEIGHT - BORDER - bh - 5
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=6, fill="#111827")
        draw.text(
            (bx + bw // 2, by + bh // 2),
            badge_text,
            fill="#F59E0B",
            font=badge_font_lg,
            anchor="mm",
        )

    # 8. Ghost Print shimmer
    if rarity == "ghost":
        img = _apply_ghost_shimmer(img)

    return img


def save_card_image(
    card_data: dict[str, Any],
    output_path: str,
    art_path: str | None = None,
    print_number: int | None = None,
) -> None:
    """Render and save a card image to disk."""
    img = render_card(card_data, art_path=art_path, print_number=print_number)
    img.save(output_path, "PNG")
    log.info("Saved card image: %s", output_path)


if __name__ == "__main__":
    # Demo — render one card from each rarity
    import json

    data_dir = Path(__file__).resolve().parent.parent / "data" / "cards"
    output_dir = Path(__file__).resolve().parent.parent / "art"
    output_dir.mkdir(exist_ok=True)

    for json_file in sorted(data_dir.glob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            cards = json.load(f)
        for card in cards:
            slot_dir = output_dir / card["slot"]
            slot_dir.mkdir(exist_ok=True)
            safe_name = card["name"].replace(" ", "_").lower()
            out = slot_dir / f"{safe_name}.png"
            save_card_image(card, str(out), print_number=42)
            print(f"Rendered: {out}")
