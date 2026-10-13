"""Load every feature module without connecting to Discord and validate the slash command tree."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import discord
import pytest
from discord import app_commands

from markets_bot.bot import EXTENSIONS, MarketsBot
from markets_bot.core.config import Settings
from markets_bot.core.guild_config import MODULE_TOGGLES
from markets_bot.core.tree import command_extras

NAME_RE = re.compile(r"^[-_\w]{1,32}$")
GUILD_COMMAND_LIMIT = 100
RESERVED_FOR_CUSTOM_COMMANDS = 10


@pytest.fixture
async def bot(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[MarketsBot]:
    monkeypatch.setenv("ENV_FILE", "/nonexistent/.env")  # never read a real .env in tests
    monkeypatch.setenv("VAPIANO_DATABASE_URL", "postgresql://test@127.0.0.1:1/test")
    instance = MarketsBot(Settings(bot_identity="vapiano"))
    await instance._async_setup_hook()  # what login() does: lets background loops wait for "ready"
    for extension in EXTENSIONS:
        await instance.load_extension(extension)
    yield instance
    for extension in list(instance.extensions):
        await instance.unload_extension(extension)
    await instance.db.close()
    await instance.peers.close()


def _walk(payload: dict[str, Any], path: str) -> list[str]:
    problems = []
    name, description = payload.get("name", ""), payload.get("description", "")
    if not NAME_RE.match(name) or name != name.lower():
        problems.append(f"{path}: invalid name {name!r}")
    if payload.get("type", 1) in (1, 2, 3, None) and not 1 <= len(description) <= 100:
        problems.append(f"{path}: description must be 1-100 chars ({len(description)})")
    options = payload.get("options") or []
    if len(options) > 25:
        problems.append(f"{path}: more than 25 options")
    required_seen_optional = False
    for option in options:
        problems += _walk(option, f"{path} {option['name']}")
        if option.get("type") not in (1, 2):
            if not option.get("required"):
                required_seen_optional = True
            elif required_seen_optional:
                problems.append(f"{path}: required option {option['name']} after an optional one")
        if len(option.get("choices") or []) > 25:
            problems.append(f"{path} {option['name']}: more than 25 choices")
    return problems


async def test_all_extensions_load(bot: MarketsBot) -> None:
    assert set(EXTENSIONS) <= set(bot.extensions)


async def test_command_tree_is_valid(bot: MarketsBot) -> None:
    commands = bot.tree.get_commands(type=discord.AppCommandType.chat_input)
    names = [c.name for c in commands]
    assert len(names) == len(set(names)), "duplicate top-level command names"
    assert len(commands) <= GUILD_COMMAND_LIMIT - RESERVED_FOR_CUSTOM_COMMANDS, len(commands)

    problems: list[str] = []
    for command in commands:
        problems += _walk(command.to_dict(bot.tree), f"/{command.name}")
        module = command_extras(command).get("module")
        if module is None:
            problems.append(f"/{command.name}: missing extras['module']")
        elif module not in MODULE_TOGGLES and module not in {"config", "utility", "shop", "market"}:
            problems.append(f"/{command.name}: unknown module {module!r}")
    assert not problems, "\n".join(problems)


async def test_component_routes_do_not_collide(bot: MarketsBot) -> None:
    for kind, routes in bot.router._prefix.items():
        prefixes = [p for p, _ in routes]
        assert len(prefixes) == len(set(prefixes)), f"duplicate {kind} prefixes"
    assert isinstance(bot.tree.get_command("ayuda"), app_commands.Command)
