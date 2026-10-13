"""Image captcha for the verification module. CPU-bound: call through ``asyncio.to_thread``."""

from __future__ import annotations

import io
import secrets

from PIL import Image, ImageDraw, ImageFilter

from markets_bot.services.welcome_card import load_font

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I lookalikes


def new_code(length: int = 5) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def render_captcha(code: str) -> bytes:
    width, height = 320, 110
    image = Image.new("RGB", (width, height), (14, 14, 14))
    draw = ImageDraw.Draw(image)
    rand = secrets.SystemRandom()
    for _ in range(9):  # noise lines
        draw.line([(rand.randint(0, width), rand.randint(0, height)) for _ in range(2)],
                  fill=(rand.randint(60, 120),) * 3, width=rand.randint(1, 3))
    font = load_font("DejaVuSans", True, 54)
    step = (width - 40) // len(code)
    for index, char in enumerate(code):
        glyph = Image.new("RGBA", (70, 80), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text((10, 5), char, font=font, fill=(rand.randint(210, 255),) * 3 + (255,))
        glyph = glyph.rotate(rand.uniform(-28, 28), resample=Image.Resampling.BICUBIC, expand=True)
        image.paste(glyph, (20 + index * step + rand.randint(-4, 4), rand.randint(0, 22)), glyph)
    for _ in range(350):  # speckles
        draw.point((rand.randrange(width), rand.randrange(height)), fill=(rand.randint(80, 200),) * 3)
    image = image.filter(ImageFilter.SMOOTH)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
