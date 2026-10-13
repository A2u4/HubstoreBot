"""HTTP calls between the bots of the cluster (ban / warning / reputation sync).

Requests are signed with the shared ``API_SECRET`` header and never raise:
a peer being down must not break the local bot.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from markets_bot.core.config import Peer, Settings

log = logging.getLogger(__name__)

# Only these two bots share moderation history.
MODERATION_LINKED = frozenset({"vapiano", "hubstore"})


@dataclass(slots=True)
class PeerResult:
    peer: Peer
    ok: bool
    status: int
    data: Any = None
    error: str | None = None


class PeerClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        return self._session

    @property
    def remote_peers(self) -> list[Peer]:
        return self._settings.remote_peers()

    @property
    def moderation_peers(self) -> list[Peer]:
        if self._settings.identity not in MODERATION_LINKED:
            return []
        return [p for p in self.remote_peers if p.identity in MODERATION_LINKED]

    def find(self, key: str) -> Peer | None:
        return next((p for p in self._settings.peers() if key in (p.identity, p.guild_id)), None)

    async def call(self, peer: Peer, path: str, body: Any) -> PeerResult:
        secret = self._settings.api_secret
        if secret is None:
            return PeerResult(peer, False, 0, error="API_SECRET not configured")
        url = f"{peer.internal_url.rstrip('/')}/internal/{path.lstrip('/')}"
        try:
            async with self._http().post(
                url, json=body, headers={"x-internal-secret": secret.get_secret_value()}
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except ValueError:
                    data = await resp.text()
                return PeerResult(peer, resp.ok, resp.status, data)
        except (aiohttp.ClientError, TimeoutError) as exc:
            return PeerResult(peer, False, 0, error=str(exc) or type(exc).__name__)

    async def broadcast(self, path: str, body: Any, peers: list[Peer] | None = None) -> list[PeerResult]:
        targets = self.remote_peers if peers is None else peers
        results = await asyncio.gather(*(self.call(p, path, body) for p in targets))
        for result in results:
            if not result.ok:
                log.warning(
                    "[peer-sync] %s %s failed: status=%s err=%s",
                    result.peer.identity, path, result.status, result.error or "non-2xx",
                )
        return list(results)
