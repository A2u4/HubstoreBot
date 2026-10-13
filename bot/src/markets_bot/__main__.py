"""Entry point: ``python -m markets_bot --bot vapiano``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import signal

import discord

from markets_bot.bot import MarketsBot
from markets_bot.core.config import KNOWN_IDENTITIES, load_settings
from markets_bot.core.logging import setup_logging

log = logging.getLogger("markets_bot")


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, discord.HTTPException):
        return exc.status == 429 or exc.status >= 500
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


async def run(identity: str | None) -> None:
    settings = load_settings(identity)
    setup_logging(settings.identity, settings.log_level, settings.log_dir)
    log.info("Starting %s bot", settings.display_name)

    if settings.startup_delay_seconds:
        # Bots share one outbound IP: stagger logins after a host restart.
        await asyncio.sleep(settings.startup_delay_seconds)

    for attempt in range(1, 11):
        bot = MarketsBot(settings)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda b=bot: asyncio.create_task(b.close()))
        try:
            async with bot:
                await bot.start(settings.token)
            return
        except discord.LoginFailure:
            log.critical("Discord rejected the token for %s", settings.identity)
            raise
        except Exception as exc:
            if not _retryable(exc) or attempt == 10:
                raise
            delay = min(60, 5 * 2 ** min(attempt - 1, 4)) + random.uniform(0, 2)
            log.warning("Login attempt %d failed (%s); retrying in %.0fs", attempt, exc, delay)
            await asyncio.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bot of the Markets cluster")
    parser.add_argument("--bot", choices=KNOWN_IDENTITIES, help="bot identity (default: $BOT_IDENTITY)")
    args = parser.parse_args()
    asyncio.run(run(args.bot))


if __name__ == "__main__":
    main()
