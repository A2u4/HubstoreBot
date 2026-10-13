"""Discord components for tickets: panel messages, ticket action rows, form modals."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import discord

from markets_bot.core.router import RoutedModal
from markets_bot.core.utils import INFO, parse_color
from markets_bot.db.models import Ticket, TicketPanel

BUTTON_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}
_CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")
CREATE_PREFIX = "ticket_create_"


def button_style(name: str | None) -> discord.ButtonStyle:
    return BUTTON_STYLES.get((name or "").lower(), discord.ButtonStyle.primary)


def parse_emoji(value: str | None) -> discord.PartialEmoji | None:
    if not value:
        return None
    if _CUSTOM_EMOJI_RE.match(value):
        return discord.PartialEmoji.from_str(value)
    return discord.PartialEmoji(name=value)


def pad(number: int) -> str:
    return str(number).zfill(4)


# ─── Panel messages (one Discord message can hold up to 5 panels) ────────────


def panel_order_from_components(components: Sequence[Any]) -> list[str]:
    """Panel IDs in the order their buttons currently appear in Discord."""
    order: list[str] = []
    for row in components:
        children = getattr(row, "children", None) or (row.get("components") if isinstance(row, dict) else None) or []
        for child in children:
            custom_id = getattr(child, "custom_id", None) or (child.get("custom_id") if isinstance(child, dict) else None)
            if isinstance(custom_id, str) and custom_id.startswith(CREATE_PREFIX):
                order.append(custom_id.removeprefix(CREATE_PREFIX))
    return order


def order_panels(panels: Sequence[TicketPanel], ordered_ids: Sequence[str]) -> list[TicketPanel]:
    if not ordered_ids or len(panels) <= 1:
        return list(panels)
    rank = {pid: i for i, pid in enumerate(ordered_ids)}
    return sorted(panels, key=lambda p: rank.get(p.id, len(rank) + 1_000))


def panel_message(
    panels: Sequence[TicketPanel], *, title: str | None = None, description: str | None = None,
    color: str | None = None, images: Sequence[str] | None = None, image_index: int = 0,
) -> tuple[discord.Embed, discord.ui.View]:
    """Embed + buttons for a group of panels sharing one message (single source of truth)."""
    if not panels:
        raise ValueError("panel_message requires at least one panel")
    first = panels[0]
    embed = discord.Embed(
        title=title if title is not None else first.group_embed_title or first.title or "Sistema de Tickets",
        description=description if description is not None
        else first.group_embed_description if first.group_embed_description is not None else first.description or "",
        color=parse_color(color or first.group_embed_color or first.embed_color, INFO),
    )
    if first.footer_text:
        embed.set_footer(text=first.footer_text)
    gallery = list(images) if images else list(first.group_embed_images or [])
    if gallery:
        embed.set_image(url=gallery[image_index % len(gallery)])
    view = discord.ui.View(timeout=None)
    for panel in panels[:5]:
        view.add_item(discord.ui.Button(
            custom_id=f"{CREATE_PREFIX}{panel.id}", label=(panel.button_label or panel.name)[:80],
            style=button_style(panel.button_color), emoji=parse_emoji(panel.button_emoji),
        ))
    return embed, view


# ─── Inside a ticket ─────────────────────────────────────────────────────────


def ticket_actions(panel: TicketPanel | None, ticket: Ticket | None = None) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    if panel is None or panel.show_close_button:
        view.add_item(discord.ui.Button(custom_id="ticket_close", label="Cerrar", emoji="🔒",
                                        style=discord.ButtonStyle.danger))
    if panel is None or (panel.show_claim_button and panel.claim_enabled):
        view.add_item(discord.ui.Button(custom_id="ticket_claim", label="Reclamar", emoji="🙋",
                                        style=discord.ButtonStyle.secondary))
    if panel is not None and panel.show_transcript_button and panel.transcript_enabled:
        view.add_item(discord.ui.Button(custom_id="ticket_transcript", label="Transcripción", emoji="📋",
                                        style=discord.ButtonStyle.secondary))
    if panel is not None and (panel.auto_close_hours or 0) > 0:
        disabled = bool(ticket and ticket.auto_close_disabled)
        view.add_item(discord.ui.Button(
            custom_id="ticket_autoclose_toggle",
            label="Activar cierre automático" if disabled else "Desactivar cierre automático",
            emoji="⏱️" if disabled else "⏸️",
            style=discord.ButtonStyle.success if disabled else discord.ButtonStyle.secondary,
        ))
    return view


def closed_actions() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(custom_id="ticket_reopen", label="Reabrir", emoji="🔓",
                                    style=discord.ButtonStyle.success))
    view.add_item(discord.ui.Button(custom_id="ticket_delete", label="Eliminar", emoji="🗑️",
                                    style=discord.ButtonStyle.danger))
    return view


def close_confirmation(requester_id: int, *, cancel_label: str = "Cancelar",
                       confirm_label: str = "Confirmar cierre") -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(custom_id=f"ticket_confirm_close_{requester_id}", label=confirm_label,
                                    emoji="🔒", style=discord.ButtonStyle.danger))
    view.add_item(discord.ui.Button(custom_id="ticket_cancel_close", label=cancel_label,
                                    style=discord.ButtonStyle.secondary))
    return view


def feedback_view(ticket_id: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for n in range(1, 6):
        style = discord.ButtonStyle.success if n >= 4 else discord.ButtonStyle.secondary if n >= 2 \
            else discord.ButtonStyle.danger
        view.add_item(discord.ui.Button(custom_id=f"ticket_feedback_{ticket_id}_{n}", label="⭐" * n, style=style))
    return view


def form_modal(custom_id: str, title: str | None, questions: list[dict[str, Any]]) -> RoutedModal | None:
    if not questions:
        return None
    inputs: list[discord.ui.TextInput[Any]] = []
    for index, question in enumerate(questions[:5]):
        inputs.append(discord.ui.TextInput(
            custom_id=f"question_{index}", label=str(question.get("label") or f"Pregunta {index + 1}")[:45],
            placeholder=str(question.get("placeholder") or "")[:100] or None,
            style=discord.TextStyle.paragraph if question.get("style") == "paragraph" else discord.TextStyle.short,
            required=question.get("required") is not False,
            min_length=question.get("minLength") or None, max_length=question.get("maxLength") or None,
        ))
    return RoutedModal(title=title or "Formulario de ticket", custom_id=custom_id, inputs=inputs)


PRIORITY_COLORS = {"low": 0x99AAB5, "normal": INFO, "high": 0xF47B67, "urgent": 0xED4245}
PRIORITY_EMOJI = {"low": "🟢", "normal": "🔵", "high": "🟠", "urgent": "🔴"}
