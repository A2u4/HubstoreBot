"""Helpers for periodic background jobs."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec

log = logging.getLogger(__name__)
P = ParamSpec("P")


def resilient[**P](func: Callable[P, Coroutine[Any, Any, None]]) -> Callable[P, Coroutine[Any, Any, None]]:
    """Log and swallow errors so a ``tasks.loop`` keeps running on the next tick.

    A failing iteration (database restart, Discord outage) must not kill the
    loop, and restarting it from an error handler would busy-spin instead.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Background job %s failed", func.__qualname__)

    return wrapper
