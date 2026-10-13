"""Ordered ``on_message`` pipeline.

Separate cog listeners would run concurrently in arbitrary order. Features that
depend on order (automod must run first and can stop the rest; sticky messages
must repost last) register here with an explicit priority instead.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from markets_bot.db.models import GuildConfig

log = logging.getLogger(__name__)

# Return True to stop the pipeline (e.g. the message was deleted by automod).
MessageHandler = Callable[[discord.Message, GuildConfig], Awaitable[bool | None]]


@dataclass(order=True, slots=True)
class _Entry:
    priority: int
    name: str
    handler: MessageHandler
    include_bots: bool


class MessagePipeline:
    """Priorities used by the built-in modules (lower runs first)."""

    AUTOMOD = 10
    AFK = 20
    AUTORESPONSES = 30
    REPUTATION = 40
    LEVELING = 45
    TICKET_ACTIVITY = 50
    PANEL_REPOST = 60
    STICKY = 70
    SHOP_STICKY = 80

    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def register(self, name: str, handler: MessageHandler, priority: int, *, include_bots: bool = False) -> None:
        self._entries = sorted([*[e for e in self._entries if e.name != name], _Entry(priority, name, handler, include_bots)])

    def unregister(self, name: str) -> None:
        self._entries = [e for e in self._entries if e.name != name]

    async def run(self, message: discord.Message, config: GuildConfig) -> None:
        for entry in self._entries:
            if message.author.bot and not entry.include_bots:
                continue
            try:
                if await entry.handler(message, config):
                    return
            except Exception:
                log.exception("[on_message:%s] handler failed", entry.name)
