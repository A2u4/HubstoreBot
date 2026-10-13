"""Runtime settings, loaded from environment variables / the repo-root ``.env``.

One process runs one bot identity (``vapiano``, ``hubstore`` or ``tradezone``).
Per-bot values are read from ``<IDENTITY>_*`` variables, so a single ``.env``
can describe the whole cluster without copying secrets around.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KNOWN_IDENTITIES: tuple[str, ...] = ("vapiano", "hubstore", "tradezone")
DISPLAY_NAMES = {"vapiano": "Vapiano", "hubstore": "Hub Store", "tradezone": "Trade Zone"}


def _env_files() -> tuple[Path, ...]:
    """Look for ``.env`` in the working directory and the repo root."""
    explicit = os.environ.get("ENV_FILE")
    if explicit:
        return (Path(explicit),)
    repo_root = Path(__file__).resolve().parents[4]
    return (repo_root / ".env", Path.cwd() / ".env")


def to_asyncpg_url(url: str) -> str:
    """Convert a Prisma-style ``postgresql://...?...schema=public`` URL for SQLAlchemy+asyncpg."""
    parts = urlsplit(url)
    scheme = "postgresql+asyncpg"
    # asyncpg rejects Prisma-only query params such as `schema` or `connection_limit`.
    allowed = {"sslmode", "ssl"}
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in allowed]
    if query and query[0][0] == "sslmode":
        query = [("ssl", v) for _, v in query]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True, slots=True)
class Peer:
    identity: str
    guild_id: str
    internal_url: str

    @property
    def display_name(self) -> str:
        return DISPLAY_NAMES.get(self.identity, self.identity)


class Settings(BaseSettings):
    """Shared settings (not prefixed)."""

    model_config = SettingsConfigDict(env_file=_env_files(), extra="ignore", env_file_encoding="utf-8")

    bot_identity: str = Field(default="vapiano")
    api_secret: SecretStr | None = None
    market_ip_hash_secret: SecretStr | None = None
    ipinfo_token: SecretStr | None = None
    dashboard_url: str = "http://localhost:3100"
    market_registration_url: str | None = None
    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    discord_cooldown_file: Path = Path("/tmp/markets-bot-discord-cooldown")

    # ── Per-identity values (resolved from <IDENTITY>_* variables) ──────────

    def _ident(self, key: str, default: str | None = None) -> str | None:
        return self._lookup(f"{self.bot_identity.upper()}_{key}", default)

    def _lookup(self, name: str, default: str | None = None) -> str | None:
        value = os.environ.get(name)
        if value is None:
            value = self._dotenv.get(name)
        return value if value not in (None, "") else default

    @cached_property
    def _dotenv(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for path in _env_files():
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return values

    @property
    def identity(self) -> str:
        return self.bot_identity.lower()

    @property
    def display_name(self) -> str:
        return self._ident("DISPLAY_NAME") or DISPLAY_NAMES.get(self.identity, self.identity)

    @property
    def token(self) -> str:
        value = self._ident("BOT_TOKEN")
        if not value:
            raise RuntimeError(f"Missing {self.identity.upper()}_BOT_TOKEN")
        return value

    @property
    def client_id(self) -> int | None:
        value = self._ident("CLIENT_ID")
        return int(value) if value else None

    @property
    def guild_id(self) -> str:
        """Primary guild of this bot (used by cross-bot sync)."""
        return self._ident("GUILD_ID", "") or ""

    @property
    def database_url(self) -> str:
        value = self._ident("DATABASE_URL") or self._lookup("DATABASE_URL")
        if not value:
            raise RuntimeError(f"Missing {self.identity.upper()}_DATABASE_URL")
        return to_asyncpg_url(value)

    @property
    def internal_port(self) -> int | None:
        value = self._ident("INTERNAL_PORT")
        return int(value) if value else None

    @property
    def startup_delay_seconds(self) -> int:
        """Stagger gateway logins so bots sharing one IP don't burst Discord."""
        return {"hubstore": 8, "tradezone": 16}.get(self.identity, 0)

    def peers(self) -> list[Peer]:
        """Every configured bot of the cluster (including self)."""
        result = []
        for identity in KNOWN_IDENTITIES:
            guild_id = self._lookup(f"{identity.upper()}_GUILD_ID")
            port = self._lookup(f"{identity.upper()}_INTERNAL_PORT")
            if guild_id and port:
                result.append(Peer(identity, guild_id, f"http://127.0.0.1:{port}"))
        return result

    def remote_peers(self) -> list[Peer]:
        return [peer for peer in self.peers() if peer.identity != self.identity]


def load_settings(identity: str | None = None) -> Settings:
    if identity:
        os.environ["BOT_IDENTITY"] = identity
    settings = Settings()
    if settings.identity not in KNOWN_IDENTITIES:
        raise RuntimeError(f"Invalid BOT_IDENTITY {settings.identity!r}; expected one of {KNOWN_IDENTITIES}")
    return settings
