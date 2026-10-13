"""Social & fun (Nekotina style): anime roleplay GIFs with counters, marriage, 8ball, ship, dice, avatar."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.core.errors import UserError
from markets_bot.core.utils import ERROR, OK, discord_ts, module_color
from markets_bot.db.base import new_id
from markets_bot.db.models import Marriage, RoleplayStat

log = logging.getLogger(__name__)
COLOR = module_color("fun")
NEKOS_URL = "https://nekos.best/api/v2/{category}"


@dataclass(frozen=True, slots=True)
class Action:
    category: str  # nekos.best category
    text: str  # "{a}" actor, "{b}" target
    emoji: str
    noun: str = ""  # counter noun for targeted actions


TARGETED: dict[str, Action] = {
    "abrazar": Action("hug", "{a} abrazó a {b}", "🤗", "abrazos"),
    "besar": Action("kiss", "{a} besó a {b}", "💋", "besos"),
    "besito": Action("peck", "{a} le dio un besito a {b}", "😚", "besitos"),
    "acariciar": Action("pat", "{a} acarició a {b}", "🫳", "caricias"),
    "acurrucar": Action("cuddle", "{a} se acurrucó con {b}", "🥰", "acurrucadas"),
    "abofetear": Action("slap", "{a} le dio una bofetada a {b}", "🖐️", "bofetadas"),
    "golpear": Action("punch", "{a} golpeó a {b}", "👊", "golpes"),
    "patear": Action("kick", "{a} pateó a {b}", "🦶", "patadas"),
    "morder": Action("bite", "{a} mordió a {b}", "😬", "mordidas"),
    "picar": Action("poke", "{a} picó a {b}", "👉", "toques"),
    "cosquillas": Action("tickle", "{a} le hizo cosquillas a {b}", "🤭", "cosquillas"),
    "chocar-cinco": Action("highfive", "{a} chocó los cinco con {b}", "🙌", "choques"),
    "tomar-mano": Action("handhold", "{a} tomó la mano de {b}", "🫱", "veces"),
    "dar-mano": Action("handshake", "{a} le estrechó la mano a {b}", "🤝", "apretones"),
    "alimentar": Action("feed", "{a} le dio de comer a {b}", "🍙", "comidas"),
    "saludar": Action("wave", "{a} saludó a {b}", "👋", "saludos"),
    "mirar": Action("stare", "{a} se quedó mirando a {b}", "👀", "miradas"),
    "guiñar": Action("wink", "{a} le guiñó el ojo a {b}", "😉", "guiños"),
    "lanzar": Action("yeet", "{a} lanzó a {b} por los aires", "🚀", "lanzamientos"),
    "disparar": Action("shoot", "{a} le disparó a {b}", "🔫", "disparos"),
    "baka": Action("baka", "{a} le dijo baka a {b}", "😤", "bakas"),
    "pulgar": Action("thumbsup", "{a} le levantó el pulgar a {b}", "👍", "pulgares"),
}
SELF: dict[str, Action] = {
    "llorar": Action("cry", "{a} está llorando", "😭"),
    "bailar": Action("dance", "{a} está bailando", "💃"),
    "sonrojarse": Action("blush", "{a} se sonrojó", "😊"),
    "sonreir": Action("smile", "{a} está sonriendo", "😄"),
    "feliz": Action("happy", "{a} está feliz", "🥳"),
    "reir": Action("laugh", "{a} se está riendo", "🤣"),
    "dormir": Action("sleep", "{a} se fue a dormir", "😴"),
    "pensar": Action("think", "{a} está pensando", "🤔"),
    "encogerse": Action("shrug", "{a} se encogió de hombros", "🤷"),
    "facepalm": Action("facepalm", "{a} hizo facepalm", "🤦"),
    "puchero": Action("pout", "{a} está haciendo puchero", "😾"),
    "aburrido": Action("bored", "{a} está aburrido", "😑"),
    "bostezar": Action("yawn", "{a} bostezó", "🥱"),
    "nope": Action("nope", "{a} dice que nope", "🙅"),
    "presumir": Action("smug", "{a} está presumiendo", "😏"),
    "asentir": Action("nod", "{a} asintió", "🙂‍↕️"),
    "acechar": Action("lurk", "{a} está acechando", "🫣"),
    "comer": Action("nom", "{a} está comiendo", "😋"),
}
EIGHT_BALL = ["Sí.", "No.", "Definitivamente sí.", "Ni lo sueñes.", "Probablemente.", "Muy dudoso.",
              "Pregunta de nuevo más tarde.", "Las señales apuntan a que sí.", "Mis fuentes dicen que no.",
              "Sin duda alguna.", "Mejor no te lo digo ahora.", "Concéntrate y vuelve a preguntar.",
              "Cuenta con ello.", "No cuentes con ello.", "Es cierto.", "Las perspectivas no son buenas."]


def _stable_percent(*parts: str) -> int:
    digest = hashlib.sha256("|".join(sorted(parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big") % 101


def _choices(table: dict[str, Action], current: str) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [app_commands.Choice(name=f"{a.emoji} {name}", value=name)
            for name, a in table.items() if current in name][:25]


class Social(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.http: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6),
                                          headers={"User-Agent": "MarketsBot/2.0"})

    async def cog_unload(self) -> None:
        if self.http:
            await self.http.close()

    async def _gif(self, category: str) -> tuple[str | None, str | None]:
        """Return ``(gif_url, anime_name)`` from nekos.best; ``(None, None)`` when unreachable."""
        if self.http is None:
            return None, None
        try:
            async with self.http.get(NEKOS_URL.format(category=category)) as resp:
                if resp.status != 200:
                    return None, None
                result = (await resp.json())["results"][0]
                return result.get("url"), result.get("anime_name")
        except (aiohttp.ClientError, TimeoutError, KeyError, IndexError, ValueError):
            return None, None

    async def _bump(self, guild_id: str, action: str, user_id: str, target_id: str) -> int:
        async with self.bot.db.session() as session:
            return int(await session.scalar(
                insert(RoleplayStat).values(id=new_id(), guild_id=guild_id, action=action, user_id=user_id,
                                            target_id=target_id, count=1)
                .on_conflict_do_update(index_elements=["guildId", "action", "userId", "targetId"],
                                       set_={"count": RoleplayStat.count + 1})
                .returning(RoleplayStat.count)) or 1)

    async def _action_embed(self, guild: discord.Guild, name: str, actor: discord.abc.User,
                            target: discord.abc.User | None) -> discord.Embed:
        action = TARGETED.get(name) or SELF[name]
        description = action.emoji + " " + action.text.format(
            a=f"**{actor.display_name}**", b=f"**{target.display_name}**" if target else "")
        embed = discord.Embed(color=COLOR, description=description)
        if target is not None:
            count = await self._bump(str(guild.id), name, str(actor.id), str(target.id))
            embed.set_footer(text=f"{actor.display_name} → {target.display_name}: {count} {action.noun}")
        url, anime = await self._gif(action.category)
        if url:
            embed.set_image(url=url)
            if anime and target is None:
                embed.set_footer(text=f"Anime: {anime}")
        return embed

    # ── Roleplay ─────────────────────────────────────────────────────────

    async def _targeted_autocomplete(self, _: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _choices(TARGETED, current)

    async def _self_autocomplete(self, _: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _choices(SELF, current)

    @app_commands.command(name="accion", description="Interactuar con otro miembro (abrazar, besar, acariciar...)",
                          extras={"module": "fun", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(tipo="Acción a realizar", usuario="Miembro objetivo")
    @app_commands.autocomplete(tipo=_targeted_autocomplete)
    async def action(self, interaction: discord.Interaction, tipo: str, usuario: discord.Member) -> None:
        tipo = tipo.lower()
        if tipo not in TARGETED:
            raise UserError(f"Acción desconocida. Opciones: {', '.join(TARGETED)}")
        if usuario.id == interaction.user.id:
            raise UserError("Elige a otra persona 😅 (para acciones propias usa `/reaccion`).")
        assert interaction.guild is not None
        await interaction.response.defer()
        embed = await self._action_embed(interaction.guild, tipo, interaction.user, usuario)
        cog, actor = self, interaction.user

        class Return(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=90)

            @discord.ui.button(label="Devolver", emoji="🔁", style=discord.ButtonStyle.secondary)
            async def give_back(self, i: discord.Interaction, button: discord.ui.Button[Return]) -> None:
                if i.user.id != usuario.id:
                    await i.response.send_message("Solo la persona mencionada puede devolverlo.", ephemeral=True)
                    return
                button.disabled = True
                await i.response.edit_message(view=self)
                assert i.guild is not None
                await i.followup.send(embed=await cog._action_embed(i.guild, tipo, usuario, actor))
                self.stop()

        if usuario.bot:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(content=usuario.mention, embed=embed, view=Return(),
                                            allowed_mentions=discord.AllowedMentions(users=[usuario]))

    @app_commands.command(name="reaccion", description="Expresar una reacción (llorar, bailar, reír...)",
                          extras={"module": "fun", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(tipo="Reacción")
    @app_commands.autocomplete(tipo=_self_autocomplete)
    async def reaction(self, interaction: discord.Interaction, tipo: str) -> None:
        tipo = tipo.lower()
        if tipo not in SELF:
            raise UserError(f"Reacción desconocida. Opciones: {', '.join(SELF)}")
        assert interaction.guild is not None
        await interaction.response.defer()
        await interaction.followup.send(embed=await self._action_embed(interaction.guild, tipo, interaction.user, None))

    # ── Marriage ─────────────────────────────────────────────────────────

    marriage = app_commands.Group(name="matrimonio", description="Casarse, divorciarse y ver parejas", guild_only=True,
                                  extras={"module": "fun", "cooldown": 5, "public": True})

    async def _marriage_of(self, guild_id: str, user_id: str) -> Marriage | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(Marriage).where(
                Marriage.guild_id == guild_id, or_(Marriage.user1_id == user_id, Marriage.user2_id == user_id))
            )).scalar_one_or_none()

    @marriage.command(name="proponer", description="Proponer matrimonio a otro miembro")
    @app_commands.describe(usuario="Tu futura pareja")
    async def propose(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        gid, a, b = str(interaction.guild_id), str(interaction.user.id), str(usuario.id)
        if a == b or usuario.bot:
            raise UserError("Elige a otro miembro (no bots).")
        for uid, who in ((a, "Ya estás"), (b, f"{usuario.display_name} ya está")):
            if await self._marriage_of(gid, uid):
                raise UserError(f"{who} casado/a.")
        cog, proposer = self, interaction.user

        class Proposal(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=120)

            async def interaction_check(self, i: discord.Interaction) -> bool:
                if i.user.id != usuario.id:
                    await i.response.send_message("Esta propuesta no es para ti.", ephemeral=True)
                    return False
                return True

            @discord.ui.button(label="Aceptar", emoji="💍", style=discord.ButtonStyle.success)
            async def accept(self, i: discord.Interaction, _: discord.ui.Button[Proposal]) -> None:
                self.stop()
                ok = await cog._marry(gid, a, b)
                text = (f"💍 ¡{proposer.mention} y {usuario.mention} ahora están casados! Felicidades 🎉" if ok
                        else "Uno de los dos ya se casó con otra persona. 💔")
                await i.response.edit_message(embed=discord.Embed(color=OK if ok else ERROR, description=text), view=None)

            @discord.ui.button(label="Rechazar", emoji="💔", style=discord.ButtonStyle.secondary)
            async def reject(self, i: discord.Interaction, _: discord.ui.Button[Proposal]) -> None:
                self.stop()
                await i.response.edit_message(view=None, embed=discord.Embed(
                    color=ERROR, description=f"💔 {usuario.mention} rechazó la propuesta de {proposer.mention}."))

            async def on_timeout(self) -> None:
                try:
                    await interaction.edit_original_response(view=None, embed=discord.Embed(
                        color=ERROR, description="⌛ La propuesta expiró sin respuesta."))
                except discord.HTTPException:
                    pass

        embed = discord.Embed(color=COLOR, description=f"💍 {proposer.mention} le propone matrimonio a {usuario.mention}.\n"
                                                       f"{usuario.mention}, ¿aceptas?")
        await interaction.response.send_message(content=usuario.mention, embed=embed, view=Proposal(),
                                                allowed_mentions=discord.AllowedMentions(users=[usuario]))

    async def _marry(self, guild_id: str, a: str, b: str) -> bool:
        """Insert the marriage if neither member is married. A per-guild advisory lock serializes proposals."""
        user1, user2 = sorted((a, b))
        async with self.bot.db.session() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"marriage:{guild_id}"})
            taken = await session.scalar(select(func.count()).select_from(Marriage).where(
                Marriage.guild_id == guild_id, or_(Marriage.user1_id.in_([a, b]), Marriage.user2_id.in_([a, b]))))
            if taken:
                return False
            session.add(Marriage(guild_id=guild_id, user1_id=user1, user2_id=user2))
        return True

    @marriage.command(name="divorcio", description="Divorciarte de tu pareja")
    async def divorce(self, interaction: discord.Interaction) -> None:
        gid, uid = str(interaction.guild_id), str(interaction.user.id)
        current = await self._marriage_of(gid, uid)
        if current is None:
            raise UserError("No estás casado/a.")
        partner = current.user2_id if current.user1_id == uid else current.user1_id
        async with self.bot.db.session() as session:
            await session.execute(delete(Marriage).where(Marriage.id == current.id))
        await interaction.response.send_message(embed=discord.Embed(
            color=ERROR, description=f"💔 {interaction.user.mention} se divorció de <@{partner}>."))

    @marriage.command(name="ver", description="Ver la pareja de un miembro")
    @app_commands.describe(usuario="Miembro a consultar")
    async def partner(self, interaction: discord.Interaction, usuario: discord.Member | None = None) -> None:
        member = usuario or interaction.user
        current = await self._marriage_of(str(interaction.guild_id), str(member.id))
        if current is None:
            await interaction.response.send_message(f"💔 {member.display_name} está soltero/a.")
            return
        partner = current.user2_id if current.user1_id == str(member.id) else current.user1_id
        days = (discord.utils.utcnow().replace(tzinfo=None) - current.created_at).days
        await interaction.response.send_message(embed=discord.Embed(
            color=COLOR, description=f"💍 {member.mention} está casado/a con <@{partner}>\n"
                                     f"Desde {discord_ts(current.created_at, 'D')} · **{days}** días juntos"))

    # ── Fun ──────────────────────────────────────────────────────────────

    fun = app_commands.Group(name="diversion", description="Juegos y comandos divertidos", guild_only=True,
                             extras={"module": "fun", "cooldown": 3, "public": True})

    @fun.command(name="8ball", description="Hazle una pregunta a la bola mágica")
    @app_commands.describe(pregunta="Tu pregunta")
    async def eight_ball(self, interaction: discord.Interaction, pregunta: app_commands.Range[str, 1, 200]) -> None:
        embed = discord.Embed(color=COLOR, title="🎱 Bola mágica")
        embed.add_field(name="Pregunta", value=pregunta, inline=False)
        embed.add_field(name="Respuesta", value=EIGHT_BALL[secrets.randbelow(len(EIGHT_BALL))], inline=False)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="moneda", description="Lanzar una moneda")
    async def coin(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"🪙 ¡Salió **{'cara' if secrets.randbelow(2) else 'cruz'}**!")

    @fun.command(name="dado", description="Lanzar dados")
    @app_commands.describe(caras="Caras del dado", cantidad="Cuántos dados")
    async def dice(self, interaction: discord.Interaction, caras: app_commands.Range[int, 2, 1000] = 6,
                   cantidad: app_commands.Range[int, 1, 10] = 1) -> None:
        rolls = [secrets.randbelow(caras) + 1 for _ in range(cantidad)]
        extra = f" (total **{sum(rolls)}**)" if cantidad > 1 else ""
        await interaction.response.send_message(f"🎲 {' · '.join(f'**{r}**' for r in rolls)}{extra}")

    @fun.command(name="ship", description="Calcular la compatibilidad entre dos miembros")
    @app_commands.describe(usuario1="Primera persona", usuario2="Segunda persona (por defecto: tú)")
    async def ship(self, interaction: discord.Interaction, usuario1: discord.Member,
                   usuario2: discord.Member | None = None) -> None:
        other = usuario2 or interaction.user
        percent = _stable_percent(str(usuario1.id), str(other.id))
        a, b = usuario1.display_name, other.display_name
        name = a[: max(1, len(a) // 2)] + b[len(b) // 2:]
        bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
        verdict = ("💔 Mejor como amigos." if percent < 30 else "🙂 Hay algo ahí." if percent < 60
                   else "💕 ¡Muy buena pareja!" if percent < 85 else "💞 ¡Almas gemelas!")
        await interaction.response.send_message(embed=discord.Embed(
            color=COLOR, title=f"💘 {name}",
            description=f"{usuario1.mention} ❤️ {other.mention}\n\n`{bar}` **{percent}%**\n{verdict}"))

    @fun.command(name="elegir", description="Elegir al azar entre varias opciones")
    @app_commands.describe(opciones="Opciones separadas por coma o |")
    async def choose(self, interaction: discord.Interaction, opciones: str) -> None:
        items = [o.strip() for o in opciones.replace("|", ",").split(",") if o.strip()]
        if len(items) < 2:
            raise UserError("Dame al menos dos opciones separadas por coma.")
        await interaction.response.send_message(f"🤔 Elijo: **{discord.utils.escape_mentions(secrets.choice(items))}**")

    @fun.command(name="calificar", description="Calificar cualquier cosa del 0 al 10")
    @app_commands.describe(cosa="Lo que quieres calificar")
    async def rate(self, interaction: discord.Interaction, cosa: app_commands.Range[str, 1, 100]) -> None:
        score = _stable_percent(cosa.lower().strip()) // 10
        await interaction.response.send_message(
            f"⭐ Le doy a **{discord.utils.escape_mentions(cosa)}** un **{score}/10**.")

    # ── Avatar ───────────────────────────────────────────────────────────

    @app_commands.command(name="avatar", description="Ver el avatar (y banner) de un usuario en grande",
                          extras={"module": "utility", "cooldown": 3, "public": True})
    @app_commands.describe(usuario="Usuario", servidor="Mostrar el avatar de este servidor si tiene uno")
    async def avatar(self, interaction: discord.Interaction, usuario: discord.User | None = None,
                     servidor: bool = False) -> None:
        user = usuario or interaction.user
        member = interaction.guild.get_member(user.id) if interaction.guild else None
        asset = member.guild_avatar if servidor and member and member.guild_avatar else user.display_avatar
        formats = ["png", "jpg", "webp"] + (["gif"] if asset.is_animated() else [])
        links = " · ".join(f"[{f.upper()}]({asset.replace(format=f, size=4096).url})" for f in formats)  # type: ignore[arg-type]
        embed = discord.Embed(color=member.color.value if member and member.color.value else COLOR,
                              title=f"Avatar de {user.display_name}", description=links)
        embed.set_image(url=asset.with_size(1024).url)
        view = discord.ui.View()
        try:
            full = await self.bot.fetch_user(user.id)
            if full.banner:
                view.add_item(discord.ui.Button(label="Ver banner", url=full.banner.with_size(2048).url))
        except discord.HTTPException:
            pass
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Social(bot))
