"""In-memory moderation state shared between modules."""

from __future__ import annotations

from dataclasses import dataclass

from markets_bot.core.cache import TtlCache


@dataclass(slots=True)
class PendingBan:
    guild_id: str
    moderator_id: str
    reason: str
    delete_messages_applied: bool = False


# Bans issued by bot commands, so the ban event can credit the human moderator
# (the audit log only shows the bot). Entries are only useful for a minute.
pending_bans: TtlCache[PendingBan] = TtlCache(60, 5_000)


def remember_ban(user_id: int | str, ban: PendingBan) -> None:
    pending_bans.set(str(user_id), ban)


def pop_ban(user_id: int | str, guild_id: int | str) -> PendingBan | None:
    ban = pending_bans.get(str(user_id))
    if ban and ban.guild_id == str(guild_id):
        pending_bans.delete(str(user_id))
        return ban
    return None
