"""Monochrome rank card (Pillow). CPU-bound: call ``render_rank_card`` through ``asyncio.to_thread``."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageOps

from markets_bot.services.welcome_card import load_font

WIDTH, HEIGHT = 934, 282
BG, PANEL, TRACK = (10, 10, 10, 255), (24, 24, 24, 255), (52, 52, 52, 255)
WHITE, GREY, DIM = (255, 255, 255, 255), (170, 170, 170, 255), (110, 110, 110, 255)


@dataclass(slots=True)
class RankCardInput:
    avatar_png: bytes | None
    name: str
    level: int
    rank: int
    current: int
    needed: int
    total_xp: int


def _short(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def render_rank_card(data: RankCardInput) -> bytes:
    card = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((16, 16, WIDTH - 16, HEIGHT - 16), radius=24, fill=PANEL)

    size = 180
    if data.avatar_png:
        try:
            avatar = Image.open(io.BytesIO(data.avatar_png)).convert("RGBA")
            avatar = ImageOps.fit(avatar, (size, size))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            card.paste(avatar, (50, (HEIGHT - size) // 2), mask)
        except OSError:
            pass
    draw.ellipse((46, (HEIGHT - size) // 2 - 4, 54 + size, (HEIGHT + size) // 2 + 4), outline=WHITE, width=4)

    left, right = 270, WIDTH - 50
    label, value = load_font("DejaVuSans", False, 22), load_font("DejaVuSans", True, 48)
    x = right
    for caption, number in (("NIVEL", str(data.level)), ("RANK", f"#{data.rank}")):
        width = draw.textlength(number, font=value)
        draw.text((x - width, 50), number, font=value, fill=WHITE)
        cap_w = draw.textlength(caption, font=label)
        draw.text((x - width - cap_w - 10, 72), caption, font=label, fill=GREY)
        x -= width + cap_w + 40

    name_font, name = load_font("DejaVuSans", True, 40), data.name
    while name and draw.textlength(name, font=name_font) > x - left:
        name = name[:-2] + "…" if len(name) > 1 else ""
    draw.text((left, 70), name, font=name_font, fill=WHITE)

    progress = f"{_short(data.current)} / {_short(data.needed)} XP"
    small = load_font("DejaVuSans", False, 24)
    draw.text((right - draw.textlength(progress, font=small), 150), progress, font=small, fill=GREY)
    draw.text((left, 150), f"Total: {_short(data.total_xp)} XP", font=small, fill=DIM)

    bar_top, bar_h = 192, 36
    draw.rounded_rectangle((left, bar_top, right, bar_top + bar_h), radius=bar_h // 2, fill=TRACK)
    ratio = max(0.0, min(1.0, data.current / data.needed if data.needed else 0))
    if ratio > 0:
        filled = left + max(bar_h, int((right - left) * ratio))
        draw.rounded_rectangle((left, bar_top, filled, bar_top + bar_h), radius=bar_h // 2, fill=WHITE)

    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
