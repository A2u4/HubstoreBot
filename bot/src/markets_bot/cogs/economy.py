"""Economy (Nekotina / UnbelievaBoat style): wallet + bank, daily/weekly, work, crime, rob,
transfers, gambling, an item shop with role items and an admin toolbox."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.utils import ERROR, OK, crypto_sample, format_duration, module_color
from markets_bot.db.models import EconomyAccount, EconomyItem, GuildConfig
from markets_bot.services.economy import MAX_BALANCE, EconomyError, EconomyService, parse_amount, remaining

log = logging.getLogger(__name__)
COLOR = module_color("economy")
PAGE = 10

WORK_LINES = [
    "Trabajaste como repartidor y ganaste {amount}.", "Programaste un bot de Discord y te pagaron {amount}.",
    "Atendiste la caja del supermercado y recibiste {amount}.", "Diseñaste un logo para un cliente: {amount}.",
    "Paseaste perros todo el día y ganaste {amount}.", "Hiciste de streamer y tus subs donaron {amount}.",
    "Vendiste limonada en la esquina y juntaste {amount}.", "Reparaste una PC y cobraste {amount}.",
    "Moderaste un servidor enorme y te dieron {amount}.", "Hiciste horas extra en la oficina: {amount}.",
]
CRIME_WIN = ["Hackeaste un cajero y sacaste {amount}.", "Robaste una joyería y vendiste el botín por {amount}.",
             "Ganaste una carrera ilegal y cobraste {amount}.", "Contrabandeaste mercancía y ganaste {amount}."]
CRIME_LOSE = ["La policía te atrapó y pagaste una multa de {amount}.", "Tu cómplice te traicionó y perdiste {amount}.",
              "Te resbalaste huyendo y perdiste {amount}.", "El plan salió mal: pagaste {amount} en sobornos."]
SLOTS = ["🍒", "🍋", "🍇", "🔔", "⭐", "💎"]
SLOT_MULTIPLIER = {"💎": 10, "⭐": 7, "🔔": 5, "🍇": 4, "🍋": 3, "🍒": 2}


def _randint(low: int, high: int) -> int:
    low, high = min(low, high), max(low, high)
    return low + secrets.randbelow(high - low + 1)


def _chance(percent: int) -> bool:
    return secrets.randbelow(100) < max(0, min(100, percent))


class Economy(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.eco = EconomyService(bot.db)

    @staticmethod
    def fmt(config: GuildConfig, amount: int) -> str:
        return f"{config.currency_symbol} **{amount:,}** {config.currency_name}"

    async def _reply(self, interaction: discord.Interaction, text: str, *, color: int = COLOR,
                     ephemeral: bool = False, title: str | None = None) -> None:
        embed = discord.Embed(color=color, description=text, title=title)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    async def _config(self, interaction: discord.Interaction) -> GuildConfig:
        return await self.bot.configs.get(interaction.guild_id or 0)

    # ── Balance ──────────────────────────────────────────────────────────

    @app_commands.command(name="saldo", description="Ver tu cartera y banco (o los de otro miembro)",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(usuario="Miembro a consultar")
    async def balance(self, interaction: discord.Interaction, usuario: discord.Member | None = None) -> None:
        member = usuario or interaction.user
        config = await self._config(interaction)
        account = await self.eco.get(str(interaction.guild_id), str(member.id))
        wallet = account.wallet if account else config.economy_start_balance
        bank = account.bank if account else 0
        position = await self.eco.rank(str(interaction.guild_id), wallet + bank)
        embed = discord.Embed(color=COLOR, timestamp=discord.utils.utcnow())
        embed.set_author(name=f"Saldo de {member.display_name}", icon_url=member.display_avatar.url)
        embed.add_field(name="👛 Cartera", value=self.fmt(config, wallet), inline=True)
        embed.add_field(name="🏦 Banco", value=self.fmt(config, bank), inline=True)
        embed.add_field(name="💰 Total", value=self.fmt(config, wallet + bank), inline=True)
        if account and account.daily_streak:
            embed.add_field(name="🔥 Racha diaria", value=f"{account.daily_streak} días", inline=True)
        embed.set_footer(text=f"Puesto #{position} en el servidor")
        await interaction.response.send_message(embed=embed)

    # ── Income ───────────────────────────────────────────────────────────

    async def _timed_reward(self, interaction: discord.Interaction, column: str, cooldown: int,
                            amount_for: Any) -> tuple[int, EconomyAccount] | None:
        """Credit a cooldown-gated reward atomically. ``amount_for(account)`` returns the amount."""
        config = await self._config(interaction)
        gid, uid = str(interaction.guild_id), str(interaction.user.id)
        now = self.eco.now()
        async with self.eco.locked(gid, uid, start_balance=config.economy_start_balance) as (_, accounts):
            account = accounts[uid]
            wait = remaining(getattr(account, column), cooldown, now)
            if wait:
                raise EconomyError(f"Debes esperar **{format_duration(wait)}** para volver a usar este comando.")
            amount = int(amount_for(account, now))
            account.wallet = min(MAX_BALANCE, account.wallet + amount)
            setattr(account, column, now)
            return amount, account

    @app_commands.command(name="diario", description="Reclamar tu recompensa diaria (con racha)",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        config = await self._config(interaction)

        def amount(account: EconomyAccount, now: Any) -> int:
            kept = account.last_daily is not None and now - account.last_daily < timedelta(hours=48)
            account.daily_streak = account.daily_streak + 1 if kept else 1
            bonus = min(account.daily_streak - 1, 10) * 0.1  # +10% per day, max +100%
            return round(config.daily_amount * (1 + bonus))

        result = await self._timed_reward(interaction, "last_daily", 86400, amount)
        if result:
            gained, account = result
            await self._reply(interaction, f"🎁 Reclamaste {self.fmt(config, gained)}.\n🔥 Racha: **{account.daily_streak}** "
                                           f"día(s) · Cartera: {self.fmt(config, account.wallet)}", color=OK)

    @app_commands.command(name="semanal", description="Reclamar tu recompensa semanal",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    async def weekly(self, interaction: discord.Interaction) -> None:
        config = await self._config(interaction)
        result = await self._timed_reward(interaction, "last_weekly", 7 * 86400, lambda *_: config.weekly_amount)
        if result:
            await self._reply(interaction, f"📦 Reclamaste tu semanal: {self.fmt(config, result[0])}.", color=OK)

    @app_commands.command(name="trabajar", description="Trabajar para ganar dinero",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction) -> None:
        config = await self._config(interaction)
        result = await self._timed_reward(interaction, "last_work", config.work_cooldown_seconds,
                                          lambda *_: _randint(config.work_min, config.work_max))
        if result:
            line = crypto_sample(WORK_LINES, 1)[0]
            await self._reply(interaction, "💼 " + line.format(amount=self.fmt(config, result[0])), color=OK)

    @app_commands.command(name="crimen", description="Cometer un crimen: alto riesgo, alta recompensa",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    async def crime(self, interaction: discord.Interaction) -> None:
        config = await self._config(interaction)
        success = _chance(config.crime_success_rate)
        gain = _randint(config.crime_min, config.crime_max)
        fine = 0

        def amount(account: EconomyAccount, _now: Any) -> int:
            nonlocal fine
            if success:
                return gain
            # Fines come out of the wallet first, then the bank, and never push the total below zero.
            fine = min(account.wallet + account.bank, gain // 2)
            from_wallet = min(account.wallet, fine)
            account.wallet -= from_wallet
            account.bank -= fine - from_wallet
            return 0

        if await self._timed_reward(interaction, "last_crime", config.crime_cooldown_seconds, amount):
            lines, value = (CRIME_WIN, gain) if success else (CRIME_LOSE, fine)
            await self._reply(interaction, "🦹 " + crypto_sample(lines, 1)[0].format(amount=self.fmt(config, value)),
                              color=OK if success else ERROR)

    @app_commands.command(name="robar", description="Intentar robar la cartera de otro miembro",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(usuario="Víctima")
    async def rob(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        config = await self._config(interaction)
        if not config.rob_enabled:
            raise EconomyError("Los robos están desactivados en este servidor.")
        if usuario.id == interaction.user.id or usuario.bot:
            raise EconomyError("No puedes robarte a ti mismo ni a un bot.")
        gid, uid, vid = str(interaction.guild_id), str(interaction.user.id), str(usuario.id)
        now = self.eco.now()
        async with self.eco.locked(gid, uid, vid, start_balance=config.economy_start_balance) as (_, accounts):
            thief, victim = accounts[uid], accounts[vid]
            wait = remaining(thief.last_rob, config.rob_cooldown_seconds, now)
            if wait:
                raise EconomyError(f"Debes esperar **{format_duration(wait)}** para volver a robar.")
            if victim.wallet < 100:
                raise EconomyError(f"{usuario.display_name} no tiene suficiente en la cartera para robarle.")
            if thief.wallet < 100:
                raise EconomyError("Necesitas al menos 100 en la cartera para intentar un robo.")
            thief.last_rob = now
            if _chance(40):
                stolen = _randint(1, max(1, victim.wallet * 30 // 100))
                victim.wallet -= stolen
                thief.wallet = min(MAX_BALANCE, thief.wallet + stolen)
                text, color = f"🥷 Le robaste {self.fmt(config, stolen)} a {usuario.mention}.", OK
            else:
                fine = max(1, thief.wallet * 20 // 100)
                thief.wallet -= fine
                victim.wallet = min(MAX_BALANCE, victim.wallet + fine)
                text, color = f"🚓 Te atraparon y tuviste que pagarle {self.fmt(config, fine)} a {usuario.mention}.", ERROR
        await self._reply(interaction, text, color=color)

    # ── Bank & transfers ─────────────────────────────────────────────────

    @app_commands.command(name="depositar", description="Mover dinero de la cartera al banco (a salvo de robos)",
                          extras={"module": "economy", "cooldown": 2, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(cantidad="Cantidad, `todo` o `mitad`")
    async def deposit(self, interaction: discord.Interaction, cantidad: str) -> None:
        await self._move(interaction, cantidad, to_bank=True)

    @app_commands.command(name="retirar", description="Mover dinero del banco a la cartera",
                          extras={"module": "economy", "cooldown": 2, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(cantidad="Cantidad, `todo` o `mitad`")
    async def withdraw(self, interaction: discord.Interaction, cantidad: str) -> None:
        await self._move(interaction, cantidad, to_bank=False)

    async def _move(self, interaction: discord.Interaction, text: str, *, to_bank: bool) -> None:
        config = await self._config(interaction)
        uid = str(interaction.user.id)
        async with self.eco.locked(str(interaction.guild_id), uid, start_balance=config.economy_start_balance) as (_, a):
            account = a[uid]
            source = account.wallet if to_bank else account.bank
            amount = parse_amount(text, source)
            if amount <= 0 or amount > source:
                raise EconomyError(f"No tienes suficiente en {'la cartera' if to_bank else 'el banco'} "
                                   f"(disponible: {source:,}).")
            if to_bank:
                account.wallet -= amount
                account.bank += amount
            else:
                account.bank -= amount
                account.wallet += amount
        verb = "Depositaste" if to_bank else "Retiraste"
        await self._reply(interaction, f"🏦 {verb} {self.fmt(config, amount)}.\n👛 Cartera: **{account.wallet:,}** · "
                                       f"🏦 Banco: **{account.bank:,}**", color=OK)

    @app_commands.command(name="pagar", description="Transferir dinero de tu cartera a otro miembro",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(usuario="Destinatario", cantidad="Cantidad, `todo` o `mitad`")
    async def pay(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: str) -> None:
        if usuario.id == interaction.user.id or usuario.bot:
            raise EconomyError("Elige a otro miembro (no bots).")
        config = await self._config(interaction)
        uid, tid = str(interaction.user.id), str(usuario.id)
        async with self.eco.locked(str(interaction.guild_id), uid, tid,
                                   start_balance=config.economy_start_balance) as (_, accounts):
            sender, receiver = accounts[uid], accounts[tid]
            amount = parse_amount(cantidad, sender.wallet)
            if amount <= 0 or amount > sender.wallet:
                raise EconomyError(f"No tienes suficiente en la cartera (disponible: {sender.wallet:,}).")
            if receiver.wallet + amount > MAX_BALANCE:
                raise EconomyError("El destinatario superaría el máximo permitido.")
            sender.wallet -= amount
            receiver.wallet += amount
        await self._reply(interaction, f"💸 Le enviaste {self.fmt(config, amount)} a {usuario.mention}.", color=OK)

    # ── Gambling ─────────────────────────────────────────────────────────

    async def _bet(self, interaction: discord.Interaction, text: str, resolve: Any) -> tuple[int, int, Any]:
        """Lock, take the bet, apply ``resolve() -> (multiplier, detail)`` and pay out. Returns (bet, payout, detail)."""
        config = await self._config(interaction)
        uid = str(interaction.user.id)
        async with self.eco.locked(str(interaction.guild_id), uid, start_balance=config.economy_start_balance) as (_, a):
            account = a[uid]
            bet = parse_amount(text, account.wallet)
            if bet <= 0 or bet > account.wallet:
                raise EconomyError(f"No tienes suficiente en la cartera (disponible: {account.wallet:,}).")
            multiplier, detail = resolve()
            payout = int(bet * multiplier)
            account.wallet = min(MAX_BALANCE, account.wallet - bet + payout)
        return bet, payout, detail

    @app_commands.command(name="apostar", description="Apostar a cara o cruz (x2)",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(cantidad="Cantidad, `todo` o `mitad`", lado="Cara o cruz")
    @app_commands.choices(lado=[app_commands.Choice(name="Cara", value="cara"),
                                app_commands.Choice(name="Cruz", value="cruz")])
    async def coinflip(self, interaction: discord.Interaction, cantidad: str, lado: str) -> None:
        config = await self._config(interaction)

        def resolve() -> tuple[float, str]:
            side = "cara" if secrets.randbelow(2) == 0 else "cruz"
            return (2.0 if side == lado else 0.0), side

        bet, payout, side = await self._bet(interaction, cantidad, resolve)
        won = payout > 0
        await self._reply(interaction, f"🪙 Salió **{side}**. " + (
            f"¡Ganaste {self.fmt(config, payout - bet)}!" if won else f"Perdiste {self.fmt(config, bet)}."),
            color=OK if won else ERROR)

    @app_commands.command(name="tragamonedas", description="Jugar a la tragamonedas (hasta x10)",
                          extras={"module": "economy", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(cantidad="Cantidad, `todo` o `mitad`")
    async def slots(self, interaction: discord.Interaction, cantidad: str) -> None:
        config = await self._config(interaction)

        def resolve() -> tuple[float, list[str]]:
            reels = [SLOTS[secrets.randbelow(len(SLOTS))] for _ in range(3)]
            if reels[0] == reels[1] == reels[2]:
                return float(SLOT_MULTIPLIER[reels[0]]), reels
            if len(set(reels)) == 2:
                return 1.5, reels
            return 0.0, reels

        bet, payout, reels = await self._bet(interaction, cantidad, resolve)
        net = payout - bet
        result = (f"¡Ganaste {self.fmt(config, net)}!" if net > 0 else f"Perdiste {self.fmt(config, -net)}."
                  if net < 0 else "Recuperaste tu apuesta.")
        await self._reply(interaction, f"🎰 **[ {' | '.join(reels)} ]**\n{result}", color=OK if net >= 0 else ERROR)

    # ── Leaderboard ──────────────────────────────────────────────────────

    @app_commands.command(name="top-economia", description="Los miembros más ricos del servidor",
                          extras={"module": "economy", "cooldown": 5, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(pagina="Página del ranking")
    async def leaderboard(self, interaction: discord.Interaction, pagina: app_commands.Range[int, 1, 500] = 1) -> None:
        config = await self._config(interaction)
        rows, total = await self.eco.leaderboard(str(interaction.guild_id), (pagina - 1) * PAGE, PAGE)
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        lines = [f"{medals.get((pagina - 1) * PAGE + i, f'`#{(pagina - 1) * PAGE + i + 1}`')} <@{r.user_id}> — "
                 f"{config.currency_symbol} **{r.wallet + r.bank:,}**" for i, r in enumerate(rows)]
        embed = discord.Embed(color=COLOR, title=f"💰 Ranking de {config.currency_name}",
                              description="\n".join(lines) or "_Nadie tiene dinero todavía._")
        embed.set_footer(text=f"Página {pagina} de {max(1, -(-total // PAGE))} • {total} cuentas")
        await interaction.response.send_message(embed=embed)

    # ── Item shop ────────────────────────────────────────────────────────

    items_group = app_commands.Group(name="items", description="Tienda de artículos de la economía", guild_only=True,
                                     extras={"module": "economy", "cooldown": 3, "public": True})

    @items_group.command(name="tienda", description="Ver los artículos a la venta")
    async def item_shop(self, interaction: discord.Interaction) -> None:
        config = await self._config(interaction)
        items = await self.eco.items(str(interaction.guild_id))
        embed = discord.Embed(color=COLOR, title="🛒 Tienda de artículos")
        for item in items[:25]:
            stock = "∞" if item.stock is None else str(item.stock)
            role = f"\n🎭 Otorga <@&{item.role_id}>" if item.role_id else ""
            embed.add_field(name=f"{item.emoji or '📦'} {item.name} — {config.currency_symbol} {item.price:,}",
                            value=f"{item.description or '_Sin descripción_'}{role}\nStock: {stock}", inline=False)
        if not items:
            embed.description = "_No hay artículos a la venta._ Los administradores pueden crearlos con `/economia-admin`."
        else:
            embed.set_footer(text="Compra con /items comprar")
        await interaction.response.send_message(embed=embed)

    async def _item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        items = await self.eco.items(str(interaction.guild_id), only_active=False)
        return [app_commands.Choice(name=f"{i.name} ({i.price:,}){'' if i.active else ' [inactivo]'}"[:100], value=i.id)
                for i in items if current.lower() in i.name.lower()][:25]

    @items_group.command(name="comprar", description="Comprar un artículo")
    @app_commands.describe(articulo="Artículo a comprar", cantidad="Cantidad")
    @app_commands.autocomplete(articulo=_item_autocomplete)
    async def item_buy(self, interaction: discord.Interaction, articulo: str,
                       cantidad: app_commands.Range[int, 1, 100] = 1) -> None:
        config = await self._config(interaction)
        gid, uid = str(interaction.guild_id), str(interaction.user.id)
        item, wallet = await self.eco.buy(gid, uid, articulo, cantidad, config.economy_start_balance)
        note = ""
        if item.role_id and isinstance(interaction.user, discord.Member) and interaction.guild:
            role = interaction.guild.get_role(int(item.role_id))
            try:
                if role is None:
                    raise LookupError(item.role_id)
                await interaction.user.add_roles(role, reason=f"Compra en la tienda: {item.name}")
                note = f"\n🎭 Recibiste el rol {role.mention}."
            except (discord.HTTPException, LookupError):
                async with self.eco.locked(gid, uid) as (_, accounts):  # refund: the role is the product
                    accounts[uid].wallet += item.price * cantidad
                raise EconomyError("No pude darte el rol de este artículo; se te devolvió el dinero.") from None
        await self._reply(interaction, f"🛍️ Compraste **{cantidad}× {item.emoji or ''} {item.name}** por "
                                       f"{self.fmt(config, item.price * cantidad)}.{note}\n👛 Cartera: **{wallet:,}**",
                          color=OK)

    @items_group.command(name="inventario", description="Ver tu inventario (o el de otro miembro)")
    @app_commands.describe(usuario="Miembro a consultar")
    async def item_inventory(self, interaction: discord.Interaction, usuario: discord.Member | None = None) -> None:
        member = usuario or interaction.user
        rows = await self.eco.inventory(str(interaction.guild_id), str(member.id))
        embed = discord.Embed(color=COLOR, title=f"🎒 Inventario de {member.display_name}", description="\n".join(
            f"{r.item.emoji or '📦'} **{r.item.name}** × {r.quantity}" for r in rows) or "_Inventario vacío._")
        await interaction.response.send_message(embed=embed)

    # ── Admin ────────────────────────────────────────────────────────────

    admin = app_commands.Group(name="economia-admin", description="Administrar la economía del servidor",
                               guild_only=True, default_permissions=discord.Permissions(manage_guild=True),
                               extras={"module": "economy", "cooldown": 2, "permissions": ["manage_guild"]})

    @admin.command(name="dar", description="Añadir dinero a un miembro")
    @app_commands.describe(usuario="Miembro", cantidad="Cantidad", destino="Cartera o banco")
    @app_commands.choices(destino=[app_commands.Choice(name="Cartera", value="wallet"),
                                   app_commands.Choice(name="Banco", value="bank")])
    async def admin_give(self, interaction: discord.Interaction, usuario: discord.Member,
                         cantidad: app_commands.Range[int, 1, MAX_BALANCE], destino: str = "wallet") -> None:
        await self._admin_adjust(interaction, usuario, cantidad, destino)

    @admin.command(name="quitar", description="Quitar dinero a un miembro")
    @app_commands.describe(usuario="Miembro", cantidad="Cantidad", destino="Cartera o banco")
    @app_commands.choices(destino=[app_commands.Choice(name="Cartera", value="wallet"),
                                   app_commands.Choice(name="Banco", value="bank")])
    async def admin_take(self, interaction: discord.Interaction, usuario: discord.Member,
                         cantidad: app_commands.Range[int, 1, MAX_BALANCE], destino: str = "wallet") -> None:
        await self._admin_adjust(interaction, usuario, -cantidad, destino)

    async def _admin_adjust(self, interaction: discord.Interaction, member: discord.Member, delta: int, column: str) -> None:
        config = await self._config(interaction)
        uid = str(member.id)
        async with self.eco.locked(str(interaction.guild_id), uid, start_balance=config.economy_start_balance) as (_, a):
            account = a[uid]
            setattr(account, column, max(0, min(MAX_BALANCE, getattr(account, column) + delta)))
        verb = "Añadiste" if delta > 0 else "Quitaste"
        await self._reply(interaction, f"✅ {verb} {self.fmt(config, abs(delta))} a {member.mention} "
                                       f"({'banco' if column == 'bank' else 'cartera'}).", ephemeral=True, color=OK)

    @admin.command(name="reiniciar", description="Reiniciar la cuenta de un miembro (o de todos)")
    @app_commands.describe(usuario="Miembro (vacío = TODO el servidor)")
    async def admin_reset(self, interaction: discord.Interaction, usuario: discord.Member | None = None) -> None:
        config = await self._config(interaction)
        query = update(EconomyAccount).where(EconomyAccount.guild_id == str(interaction.guild_id))
        if usuario:
            query = query.where(EconomyAccount.user_id == str(usuario.id))
        elif not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            raise EconomyError("Solo un administrador puede reiniciar la economía de todo el servidor.")
        async with self.bot.db.session() as session:
            count = (await session.execute(query.values(
                wallet=config.economy_start_balance, bank=0, daily_streak=0, last_daily=None, last_weekly=None,
                last_work=None, last_crime=None, last_rob=None))).rowcount  # type: ignore[attr-defined]
        await self._reply(interaction, f"✅ {count} cuenta(s) reiniciada(s).", ephemeral=True, color=OK)

    @admin.command(name="item-crear", description="Crear o actualizar un artículo de la tienda")
    @app_commands.describe(nombre="Nombre", precio="Precio", descripcion="Descripción", emoji="Emoji",
                           rol="Rol que otorga al comprarlo", stock="Stock (vacío = ilimitado)")
    async def item_create(self, interaction: discord.Interaction, nombre: app_commands.Range[str, 1, 60],
                          precio: app_commands.Range[int, 0, MAX_BALANCE], descripcion: str | None = None,
                          emoji: str | None = None, rol: discord.Role | None = None,
                          stock: app_commands.Range[int, 0, 1_000_000] | None = None) -> None:
        gid = str(interaction.guild_id)
        async with self.bot.db.session() as session:
            item = (await session.execute(select(EconomyItem).where(
                EconomyItem.guild_id == gid, EconomyItem.name == nombre))).scalar_one_or_none()
            if item is None:
                item = EconomyItem(guild_id=gid, name=nombre, price=precio)
                session.add(item)
            item.price, item.active = precio, True
            item.description = descripcion or item.description or ""
            item.emoji = emoji or item.emoji
            item.role_id = str(rol.id) if rol else item.role_id
            item.stock = stock
        await self._reply(interaction, f"✅ Artículo **{nombre}** guardado ({precio:,}).", ephemeral=True, color=OK)

    @admin.command(name="item-eliminar", description="Eliminar un artículo de la tienda")
    @app_commands.describe(articulo="Artículo")
    @app_commands.autocomplete(articulo=_item_autocomplete)
    async def item_delete(self, interaction: discord.Interaction, articulo: str) -> None:
        async with self.bot.db.session() as session:
            removed = (await session.execute(delete(EconomyItem).where(
                EconomyItem.id == articulo, EconomyItem.guild_id == str(interaction.guild_id)))).rowcount  # type: ignore[attr-defined]
        await self._reply(interaction, "✅ Artículo eliminado." if removed else "❌ No encontré ese artículo.",
                          ephemeral=True, color=OK if removed else ERROR)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Economy(bot))
