"""Welcome / farewell card renderer (Pillow port of the old canvas renderer).

The layout JSON stored in ``GuildConfig.welcomeCardLayout`` is shared with the
dashboard editor, so field names stay camelCase.
"""

from __future__ import annotations

import io
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

CARD_WIDTH = 900
CARD_HEIGHT = 350

DEFAULT_LAYOUT: dict[str, Any] = {
    "width": CARD_WIDTH,
    "height": CARD_HEIGHT,
    "background": {"color": "#0d1117", "imageFit": "cover", "overlay": "rgba(0,0,0,0.35)"},
    "avatar": {
        "x": 175, "y": 175, "size": 180, "shape": "circle",
        "borderColor": "#ffffff", "borderWidth": 6, "visible": True,
    },
    "texts": [
        {"id": "title", "text": "¡Bienvenido a {server}!", "x": 340, "y": 90, "fontFamily": "Arial",
         "fontWeight": 800, "fontSize": 34, "color": "#ffffff", "align": "left",
         "shadowColor": "rgba(0,0,0,0.6)", "shadowBlur": 8, "visible": True},
        {"id": "username", "text": "{user}", "x": 340, "y": 145, "fontFamily": "Arial",
         "fontWeight": 700, "fontSize": 46, "color": "#ffffff", "align": "left", "visible": True},
        {"id": "member", "text": "Sos el miembro #{memberCount}", "x": 340, "y": 220, "fontFamily": "Arial",
         "fontWeight": 500, "fontSize": 20, "color": "rgba(255,255,255,0.8)", "align": "left", "visible": True},
        {"id": "inviter", "text": "Invitado por {inviter}", "x": 340, "y": 260, "fontFamily": "Arial",
         "fontWeight": 500, "fontSize": 18, "color": "rgba(255,255,255,0.55)", "align": "left", "visible": True},
    ],
}

_RGBA_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+%?)\s*)?\)", re.I)
_ANCHORS = {"left": "lm", "center": "mm", "right": "rm"}


def merge_layout(partial: dict[str, Any] | None) -> dict[str, Any]:
    if not partial:
        return DEFAULT_LAYOUT
    texts = partial.get("texts")
    return {
        "width": CARD_WIDTH,
        "height": CARD_HEIGHT,
        "background": {**DEFAULT_LAYOUT["background"], **(partial.get("background") or {})},
        "avatar": {**DEFAULT_LAYOUT["avatar"], **(partial.get("avatar") or {})},
        "texts": texts if isinstance(texts, list) and texts else DEFAULT_LAYOUT["texts"],
    }


def parse_rgba(value: str | None, default: tuple[int, int, int, int] = (255, 255, 255, 255)) -> tuple[int, int, int, int]:
    """CSS-ish color -> RGBA tuple. Supports hex (3/6/8), rgb()/rgba() with 0-1 alpha, and names."""
    if not value:
        return default
    text = value.strip()
    match = _RGBA_RE.fullmatch(text)
    if match:
        r, g, b = (max(0, min(255, round(float(c)))) for c in match.groups()[:3])
        raw_alpha = match.group(4)
        if raw_alpha is None:
            alpha = 255
        elif raw_alpha.endswith("%"):
            alpha = round(float(raw_alpha[:-1]) * 2.55)
        else:
            number = float(raw_alpha)
            alpha = round(number * 255) if number <= 1 else round(number)
        return r, g, b, max(0, min(255, alpha))
    try:
        rgb = ImageColor.getrgb(text)
    except ValueError:
        return default
    return (*rgb[:3], rgb[3] if len(rgb) == 4 else 255)  # type: ignore[return-value]


# ─── Fonts ───────────────────────────────────────────────────────────────────

_FONT_DIRS = [
    Path(os.environ.get("FONT_DIR", "")) if os.environ.get("FONT_DIR") else None,
    Path(__file__).resolve().parent.parent / "assets" / "fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
]
_FALLBACK_REGULAR = ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf")
_FALLBACK_BOLD = ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf", "Arial_Bold.ttf")


@lru_cache(maxsize=1)
def _font_files() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for directory in _FONT_DIRS:
        if directory is None or not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() in {".ttf", ".otf"}:
                found.setdefault(path.name.lower(), path)
    return found


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@lru_cache(maxsize=128)
def _font(family: str, bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    files = _font_files()
    wanted = _norm(family or "")
    candidates = []
    for name, path in files.items():
        stem = _norm(Path(name).stem)
        if wanted and stem.startswith(wanted):
            is_bold = "bold" in stem or "black" in stem or "heavy" in stem
            candidates.append((is_bold == bold, -len(stem), path))
    if candidates:
        candidates.sort(reverse=True)
        return ImageFont.truetype(str(candidates[0][2]), size)
    for name in _FALLBACK_BOLD if bold else _FALLBACK_REGULAR:
        path = files.get(name.lower())
        if path:
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


# ─── Rendering ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class CardInput:
    layout: dict[str, Any] | None
    variables: dict[str, str]
    avatar_png: bytes | None
    background_image: bytes | None = None


def _draw_background(card: Image.Image, bg: dict[str, Any], image_bytes: bytes | None) -> None:
    width, height = card.size
    card.paste(parse_rgba(bg.get("color"), (13, 17, 23, 255)), (0, 0, width, height))
    if image_bytes:
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            fit = bg.get("imageFit") or "cover"
            if fit == "fill":
                card.alpha_composite(img.resize((width, height)))
            else:
                scale = (max if fit == "cover" else min)(width / img.width, height / img.height)
                resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
                if fit == "cover":
                    left = (resized.width - width) // 2
                    top = (resized.height - height) // 2
                    card.alpha_composite(resized.crop((left, top, left + width, top + height)))
                else:
                    card.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
        except Exception as exc:  # corrupt / unsupported image: keep the solid color
            log.warning("Welcome card background failed: %s", exc)
    if bg.get("overlay"):
        overlay = Image.new("RGBA", card.size, parse_rgba(bg["overlay"], (0, 0, 0, 0)))
        card.alpha_composite(overlay)


def _shape_mask(size: int, shape: str) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    if shape == "circle":
        draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    elif shape == "rounded":
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=min(24, size // 2), fill=255)
    else:
        draw.rectangle((0, 0, size - 1, size - 1), fill=255)
    return mask


def _draw_avatar(card: Image.Image, avatar: dict[str, Any], png: bytes | None) -> None:
    if not avatar.get("visible", True):
        return
    size = int(avatar.get("size", 180))
    cx, cy = int(avatar.get("x", 175)), int(avatar.get("y", 175))
    left, top = cx - size // 2, cy - size // 2
    shape = avatar.get("shape", "circle")
    border = int(avatar.get("borderWidth", 0))
    if border > 0:
        draw = ImageDraw.Draw(card)
        box = (left - border // 2, top - border // 2, left + size + border // 2, top + size + border // 2)
        color = parse_rgba(avatar.get("borderColor"), (255, 255, 255, 255))
        if shape == "circle":
            draw.ellipse(box, outline=color, width=border)
        elif shape == "rounded":
            draw.rounded_rectangle(box, radius=min(24, size // 2), outline=color, width=border)
        else:
            draw.rectangle(box, outline=color, width=border)
    if not png:
        return
    try:
        img = Image.open(io.BytesIO(png)).convert("RGBA").resize((size, size))
        card.paste(img, (left, top), _shape_mask(size, shape))
    except Exception as exc:
        log.warning("Welcome card avatar failed: %s", exc)


def _resolve(template: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        template = template.replace(key, value)
    return template


def _draw_text(card: Image.Image, spec: dict[str, Any], variables: dict[str, str]) -> None:
    if not spec.get("visible", True):
        return
    text = _resolve(str(spec.get("text", "")), variables)
    if not text:
        return
    font = _font(str(spec.get("fontFamily") or "Arial"), int(spec.get("fontWeight") or 400) >= 600,
                 max(6, int(spec.get("fontSize") or 16)))
    anchor = _ANCHORS.get(spec.get("align") or "left", "lm")
    position = (float(spec.get("x", 0)), float(spec.get("y", 0)))

    blur = float(spec.get("shadowBlur") or 0)
    if spec.get("shadowColor") and blur:
        shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text(position, text, font=font, anchor=anchor, fill=parse_rgba(spec["shadowColor"]))
        card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur / 2)))

    layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
    stroke_width = int(spec.get("strokeWidth") or 0) if spec.get("strokeColor") else 0
    ImageDraw.Draw(layer).text(
        position, text, font=font, anchor=anchor, fill=parse_rgba(spec.get("color")),
        stroke_width=stroke_width, stroke_fill=parse_rgba(spec.get("strokeColor")) if stroke_width else None,
    )
    card.alpha_composite(layer)


def render_card(data: CardInput) -> bytes:
    """Render a PNG. CPU-bound: call through ``asyncio.to_thread``."""
    layout = merge_layout(data.layout)
    card = Image.new("RGBA", (int(layout["width"]), int(layout["height"])), (0, 0, 0, 255))
    _draw_background(card, layout["background"], data.background_image)
    _draw_avatar(card, layout["avatar"], data.avatar_png)
    for spec in layout["texts"]:
        _draw_text(card, spec, data.variables)
    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def card_variables(
    *, display_name: str, username: str, server: str, member_count: int, inviter: str | None
) -> dict[str, str]:
    return {
        "{user}": display_name,
        "{username}": username,
        "{displayName}": display_name,
        "{server}": server,
        "{memberCount}": str(member_count),
        "{inviter}": inviter or "Desconocido",
    }


def load_font(family: str, bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Public font lookup shared with other card renderers (rank card)."""
    return _font(family, bold, size)
