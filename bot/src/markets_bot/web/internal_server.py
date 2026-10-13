"""HTTP server inside the bot process (127.0.0.1 only).

Used by peer bots (ban / warning / reputation sync, same protocol as v1) and by
the dashboard for anything that needs the live Discord connection (listing
channels, deploying panels, sending messages). Every request must carry the
shared ``x-internal-secret`` header.
"""

from __future__ import annotations

import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, default=str))


async def read_json(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HttpError(400, "Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HttpError(400, "Expected a JSON object")
    return body


def require(body: dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if not body.get(f)]
    if missing:
        raise HttpError(400, f"Missing required fields: {', '.join(missing)}")


class InternalServer:
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._routes: list[tuple[str, str, RouteHandler]] = []
        self._runner: web.AppRunner | None = None

    def route(self, method: str, path: str) -> Callable[[RouteHandler], RouteHandler]:
        def decorator(handler: RouteHandler) -> RouteHandler:
            self._routes.append((method.upper(), path, handler))
            return handler

        return decorator

    @web.middleware
    async def _auth(self, request: web.Request, handler: RouteHandler) -> web.StreamResponse:
        secret = self.bot.settings.api_secret
        if secret is None:
            log.error("[internal] API_SECRET not configured; rejecting %s", request.path)
            return json_response({"error": "Server misconfigured"}, 500)
        provided = request.headers.get("x-internal-secret", "")
        if not hmac.compare_digest(provided.encode(), secret.get_secret_value().encode()):
            log.warning("[internal] rejected %s from %s", request.path, request.remote)
            return json_response({"error": "Unauthorized"}, 401)
        try:
            return await handler(request)
        except HttpError as exc:
            return json_response({"error": exc.message}, exc.status)
        except web.HTTPException:
            raise
        except Exception:
            log.exception("[internal] handler error on %s", request.path)
            return json_response({"error": "Internal server error"}, 500)

    async def start(self, port: int) -> None:
        app = web.Application(middlewares=[self._auth], client_max_size=2 * 1024 * 1024)
        for method, path, handler in self._routes:
            app.router.add_route(method, path, handler)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", port).start()
        log.info("[internal] listening on 127.0.0.1:%s (%d routes)", port, len(self._routes))

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
