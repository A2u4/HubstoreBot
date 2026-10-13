"""Routing for persistent components (buttons, selects, modals) by ``custom_id``.

Panels posted months ago (tickets, shop, polls, reaction roles...) keep their
original custom IDs, so handlers are matched by exact ID or longest prefix and
keep working across restarts without registering views.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import discord

log = logging.getLogger(__name__)

Kind = Literal["button", "select", "modal"]
Handler = Callable[[discord.Interaction], Awaitable[Any]]


class ComponentRouter:
    def __init__(self) -> None:
        self._exact: dict[tuple[Kind, str], Handler] = {}
        self._prefix: dict[Kind, list[tuple[str, Handler]]] = {"button": [], "select": [], "modal": []}

    def exact(self, kind: Kind, custom_id: str, handler: Handler) -> None:
        self._exact[(kind, custom_id)] = handler

    def prefix(self, kind: Kind, prefix: str, handler: Handler) -> None:
        routes = self._prefix[kind]
        routes.append((prefix, handler))
        routes.sort(key=lambda item: len(item[0]), reverse=True)  # longest prefix wins

    def resolve(self, kind: Kind, custom_id: str) -> Handler | None:
        handler = self._exact.get((kind, custom_id))
        if handler:
            return handler
        return next((h for p, h in self._prefix[kind] if custom_id.startswith(p)), None)

    async def dispatch(self, interaction: discord.Interaction) -> bool:
        data: dict[str, Any] = interaction.data or {}  # type: ignore[assignment]
        custom_id = str(data.get("custom_id", ""))
        if interaction.type is discord.InteractionType.modal_submit:
            kind: Kind = "modal"
        elif interaction.type is discord.InteractionType.component:
            kind = "button" if data.get("component_type") == 2 else "select"
        else:
            return False
        handler = self.resolve(kind, custom_id)
        if handler is None:
            return False
        try:
            await handler(interaction)
        except discord.NotFound as exc:
            if exc.code == 10062:
                log.warning("Interaction %s expired before we answered", custom_id)
            else:
                log.exception("Error handling %s %s", kind, custom_id)
                await reply_error(interaction)
        except Exception:
            log.exception("Error handling %s %s", kind, custom_id)
            await reply_error(interaction)
        return True


async def reply_error(interaction: discord.Interaction, message: str = "Ocurrió un error.") -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


def modal_values(interaction: discord.Interaction) -> dict[str, str]:
    """Flatten submitted modal inputs (classic action rows or label-wrapped) into ``{custom_id: value}``."""
    values: dict[str, str] = {}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            if "custom_id" in node and "value" in node:
                values[str(node["custom_id"])] = str(node.get("value") or "")
            elif "custom_id" in node and "values" in node:
                values[str(node["custom_id"])] = ",".join(map(str, node.get("values") or []))
            visit(node.get("components"))
            visit(node.get("component"))

    visit((interaction.data or {}).get("components", []))
    return values


def select_values(interaction: discord.Interaction) -> list[str]:
    return [str(v) for v in (interaction.data or {}).get("values", [])]


class RoutedModal(discord.ui.Modal):
    """A modal whose submission is handled by :class:`ComponentRouter` (by custom_id).

    ``on_submit`` intentionally does nothing so the router stays the single handler.
    """

    def __init__(self, *, title: str, custom_id: str, inputs: list[discord.ui.TextInput[Any]]) -> None:
        super().__init__(title=title[:45], custom_id=custom_id[:100], timeout=900)
        for item in inputs[:5]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        return None
