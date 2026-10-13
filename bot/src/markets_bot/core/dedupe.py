"""Protection against processing the same side effect twice.

Gateway resumes can replay dispatches, and historically a second deployment
running with the same token produced duplicate messages. These guards keep a
short, bounded memory of what this process already did.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import discord

from markets_bot.core.cache import TtlCache

log = logging.getLogger(__name__)

_side_effects: TtlCache[bool] = TtlCache(120, 20_000)
_recent_outputs: TtlCache[int] = TtlCache(5, 20_000)
_REP_REPLY_PREFIX = "dio **+1 rep** a"


def claim_side_effect(key: str) -> bool:
    """Return False when this exact side effect (welcome, ban log, ...) already ran recently."""
    return not key or _side_effects.claim(f"side:{key}")


def release_side_effect(key: str) -> None:
    """Forget a claim, e.g. when the opposite transition (leave after join) happens."""
    _side_effects.delete(f"side:{key}")


def _embed_payload(embed: discord.Embed, drop_footer: bool) -> dict[str, Any]:
    data = embed.to_dict()
    data.pop("timestamp", None)  # copies differ by milliseconds
    if drop_footer:
        data.pop("footer", None)
    return dict(data)


def output_fingerprint(message: discord.Message) -> str:
    embeds = message.embeds
    is_rep_reply = (
        message.reference is not None
        and len(embeds) == 1
        and _REP_REPLY_PREFIX in (embeds[0].description or "")
    )
    payload = {
        "channel": message.channel.id,
        "reference": message.reference.message_id if message.reference else None,
        "content": message.content,
        "embeds": [_embed_payload(e, is_rep_reply) for e in embeds],
        "components": [c.to_dict() for c in message.components],
        "attachments": [(a.id, a.filename, a.size) for a in message.attachments],
        "stickers": [s.id for s in message.stickers],
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def remove_duplicate_bot_output(message: discord.Message) -> bool:
    """Delete a copy of our own message posted within 5 seconds. Returns True if deleted."""
    me = message.guild.me if message.guild else None
    if me is None or message.author.id != me.id:
        return False
    key = output_fingerprint(message)
    previous_id = _recent_outputs.get(key)
    if previous_id is None or previous_id == message.id:
        _recent_outputs.set(key, message.id)
        return False
    try:
        await message.channel.fetch_message(previous_id)
    except discord.NotFound:
        # Sticky messages intentionally reappear after deleting the prior copy.
        _recent_outputs.set(key, message.id)
        return False
    except discord.HTTPException:
        return False  # a network failure is not proof the first copy is gone
    try:
        await message.delete()
    except discord.HTTPException:
        return False
    log.warning("Removed duplicate bot message %s in %s", message.id, message.channel.id)
    return True
