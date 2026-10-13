"""Shop: public store panels, purchase tickets, ``/tienda`` staff panel, quotes and announcements."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import delete, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import send_audit
from markets_bot.core.cache import TtlCache
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.router import RoutedModal, modal_values, select_values
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import ERROR, INFO, OK, utcnow
from markets_bot.db.models import GuildConfig, ShopProduct, Ticket, TicketPanel
from markets_bot.services import shop as catalog
from markets_bot.services.market_quote import (
    calculate_quote,
    extract_usd_million_price,
    format_decimal,
    parse_ic_value,
)
from markets_bot.services.tickets.manager import CreateOptions, TicketService
from markets_bot.services.tickets.ui import form_modal
from markets_bot.web.internal_server import HttpError, json_response, read_json

log = logging.getLogger(__name__)

COUNTRY_PREFIX = "shopc:"
ANNOUNCE_STAGGER_SECONDS = 20 * 60
PREFERRED_ANNOUNCE_ORDER = ["dealer", "mall", "dinero", "cuentas"]
UUID_RE = r"[a-f0-9-]{36}"
CATEGORY_RE = r"[a-z0-9_-]{1,40}"

# /comprar (protected purchase) is specific to Hub Store's market.
HUBSTORE_GUILD_ID = "1107335281620820079"
ACCESS_PURCHASE_PANEL_NAME = "Compras Access"
VERIFIED_BUYER_ROLE_IDS = {"1540143035197689896", "1483835252375027943", "1483835218040197371"}
VERIFIED_SELLER_ROLE_IDS = {"1483835252375027943", "1483835218040197371"}


def _text(label: str, custom_id: str, *, value: str = "", placeholder: str = "", required: bool = True,
          max_length: int = 100, paragraph: bool = False) -> discord.ui.TextInput[Any]:
    return discord.ui.TextInput(label=label[:45], custom_id=custom_id, default=value[:max_length] or None,
                                placeholder=placeholder[:100] or None, required=required, max_length=max_length,
                                style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short)


def _positive_int(value: str) -> int | None:
    try:
        number = int(value.strip())
    except ValueError:
        return None
    return number if 0 < number <= 1_000_000 else None


def _numeric_price(label: str, fallback: float) -> float:
    match = re.search(r"\d+(?:\.\d+)?", label.replace(",", "."))
    return float(match.group(0)) if match else fallback


def _product_stock(product: ShopProduct) -> str:
    return (product.stock_label or "").strip() or f"{product.stock} unidad{'' if product.stock == 1 else 'es'}"


async def _ephemeral(interaction: discord.Interaction, content: str, **kwargs: Any) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=True, **kwargs)


class Shop(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.tickets = TicketService(bot)
        self.publisher = catalog.ShopPublisher(bot)
        self._sticky_timers: dict[int, asyncio.TimerHandle] = {}
        self._rotation_last: dict[str, float] = {}
        self._rotation_index: dict[str, int] = {}
        self._country_locks: dict[int, asyncio.Lock] = {}
        self._configs_cache: TtlCache[list[GuildConfig]] = TtlCache(60, 1)

        r = bot.router
        r.prefix("button", "shop_buy_", self.on_buy_button)
        r.exact("button", "shop_buy_menu", self.on_buy_menu)
        r.prefix("button", "shop_category_", self.on_category_button)
        r.prefix("button", "shop_custom_", self.on_custom_button)
        r.prefix("button", "shop_stock_", self.on_stock_button)
        r.prefix("button", COUNTRY_PREFIX, self.on_country)
        r.exact("select", "shop_buy_select", self.on_product_select)
        r.exact("select", "shop_category_select", self.on_product_select)
        r.exact("select", "shop_stock_category_select", self.on_stock_category_select)
        r.prefix("select", "shop_stock_select_", self.on_stock_select)
        r.prefix("select", COUNTRY_PREFIX, self.on_country)
        r.prefix("modal", "shop_product_form_", self.on_shop_form)
        r.prefix("modal", "shop_action_form_", self.on_shop_form)
        r.prefix("modal", "shop_stock_", self.on_stock_modal)
        r.prefix("modal", COUNTRY_PREFIX, self.on_country)

        bot.pipeline.register("shop_sticky", self.sticky_shop, MessagePipeline.SHOP_STICKY)
        route = bot.internal.route
        route("POST", "/internal/shop/publish")(self._publish_route)
        route("POST", "/internal/shop/refresh")(self._refresh_route)
        route("POST", "/internal/shop/publish-category")(self._publish_category_route)

    async def cog_load(self) -> None:
        self.rotate_images.start()
        self.announcements.start()

    async def cog_unload(self) -> None:
        self.rotate_images.cancel()
        self.announcements.cancel()
        for handle in self._sticky_timers.values():
            handle.cancel()

    def refresh_later(self, guild_id: int | str) -> None:
        self.bot.spawn(self.publisher.refresh(str(guild_id)), name=f"shop-refresh-{guild_id}")

    # ── Customer flows ───────────────────────────────────────────────────

    async def _panels(self, guild_id: int) -> list[TicketPanel]:
        async with self.bot.db.session() as session:
            return list((await session.execute(select(TicketPanel).where(
                TicketPanel.guild_id == str(guild_id)).order_by(TicketPanel.created_at))).scalars().all())

    @staticmethod
    def _find_panel(panels: list[TicketPanel], *ids: str | None) -> TicketPanel | None:
        target = next((i for i in ids if i), None)
        if target:
            return next((p for p in panels if p.id == target), None)
        return panels[0] if panels else None

    @staticmethod
    def _product_options(product: ShopProduct) -> CreateOptions:
        images = list(product.images or [])
        if product.image and product.image not in images:
            images.insert(0, product.image)
        details = [f"Hola {{user}}, gracias por tu interés en **{product.name}**.", "", "**Detalles del producto**",
                   f"• **Precio:** {catalog.price_text(product)}",
                   f"• **Disponibilidad:** {_product_stock(product)}"]
        if product.description:
            details.append(f"• **Descripción:** {product.description}")
        details += ["", "Abrir el ticket no modifica el stock. Un miembro del equipo confirmará contigo la "
                        "disponibilidad y el proceso de compra."]
        return CreateOptions(
            topic=f"Compra: {product.name}", welcome_title=f"🛒 Compra de {product.name}"[:256],
            welcome_message="\n".join(details), image_urls=images,
            reply_content="Tu solicitud de compra fue creada correctamente. Continúa en {channel}.",
            source_label=f"Tienda · {product.category or 'General'}")

    @staticmethod
    def _button_options(button: dict[str, Any]) -> CreateOptions:
        label = str(button.get("label") or "")
        return CreateOptions(
            category_id=button.get("categoryId") or None,
            staff_role_ids=[str(r) for r in button.get("staffRoleIds") or []],
            naming_pattern=button.get("namingPattern") or f"{label or 'ticket'}-{{number}}",
            topic=button.get("ticketTopic") or f"Tienda: {label}",
            welcome_title=f"{button.get('emoji') or '🎫'} Solicitud de {label}",
            welcome_message=button.get("welcomeMessage") or
            f"Hola {{user}}, abriste una solicitud para **{label}**.\n\nUn miembro del equipo te atenderá en breve.",
            reply_content="Tu solicitud fue creada correctamente. Continúa en {channel}.",
            source_label=f"Tienda · {label}")

    async def _buy(self, interaction: discord.Interaction, product_id: str) -> None:
        guild = interaction.guild
        if guild is None:
            return
        async with self.bot.db.session() as session:
            product = (await session.execute(select(ShopProduct).where(
                ShopProduct.id == product_id, ShopProduct.guild_id == str(guild.id)))).scalar_one_or_none()
        config = await self.bot.configs.get(guild.id)
        if product is None:
            await _ephemeral(interaction, "Este producto ya no existe.")
            return
        if product.stock <= 0:
            await _ephemeral(interaction, "Este producto está agotado por el momento.")
            return
        if not config.tickets_enabled:
            await _ephemeral(interaction, "El sistema de tickets está desactivado en este servidor. No se puede "
                                          "procesar la compra.")
            return
        panel = self._find_panel(await self._panels(guild.id), config.shop_panel_id)
        if panel is None:
            await _ephemeral(interaction, "La tienda todavía no tiene un panel de tickets vinculado. Un administrador "
                                          "debe configurarlo desde Tickets → Tiendas.")
            return
        if panel.form_enabled and panel.form_questions:
            modal = form_modal(f"shop_product_form_{product.id}", panel.form_title or f"Comprar {product.name}",
                               list(panel.form_questions))
            if modal is not None:
                await interaction.response.send_modal(modal)
                return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.tickets.create(interaction, panel, options=self._product_options(product))

    async def on_buy_button(self, interaction: discord.Interaction) -> None:
        await self._buy(interaction, str((interaction.data or {}).get("custom_id", "")).removeprefix("shop_buy_"))

    async def on_product_select(self, interaction: discord.Interaction) -> None:
        values = select_values(interaction)
        if values:
            await self._buy(interaction, values[0])

    async def on_buy_menu(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        config = await self.bot.configs.get(interaction.guild.id)
        async with self.bot.db.session() as session:
            products = list((await session.execute(select(ShopProduct).where(
                ShopProduct.guild_id == str(interaction.guild.id), ShopProduct.active.is_(True),
                ShopProduct.stock > 0))).scalars().all())
        products = catalog.primary_products(config, products)
        if not products:
            await interaction.edit_original_response(content="No hay productos disponibles en este momento.")
            return
        menu = discord.ui.Select(custom_id="shop_buy_select", placeholder="Selecciona un producto para comprar")
        for p in products[:25]:
            menu.add_option(label=p.name[:100], value=p.id, description=(
                f"Precio: {(p.price_label or '').strip() or f'${float(p.price):.2f}'} | "
                f"Stock: {(p.stock_label or '').strip() or p.stock}")[:100])
        view = discord.ui.View()
        view.add_item(menu)
        await interaction.edit_original_response(content="Por favor selecciona el producto que deseas comprar:", view=view)

    async def on_category_button(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        key = str((interaction.data or {}).get("custom_id", "")).removeprefix("shop_category_")
        config = await self.bot.configs.get(interaction.guild.id)
        # Catalog views are private so one member browsing never replaces the public store.
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db.session() as session:
            stmt = select(ShopProduct).where(ShopProduct.guild_id == str(interaction.guild.id))
            if key != "home":
                stmt = stmt.where(ShopProduct.active.is_(True))
            products = list((await session.execute(stmt.order_by(ShopProduct.created_at.desc()))).scalars().all())
        if key == "home":
            payload = catalog.category_preview(config, products)
        else:
            category = next((c for c in catalog.categories(config) if c.id == key), None)
            if category is None:
                await interaction.edit_original_response(content="Esta sección ya no está disponible.")
                return
            payload = catalog.category_panel(config, catalog.in_category(products, category), category)
        await interaction.edit_original_response(**payload.kwargs())

    async def on_custom_button(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        key = str((interaction.data or {}).get("custom_id", "")).removeprefix("shop_custom_")
        config = await self.bot.configs.get(guild.id)
        buttons = [b for b in config.shop_custom_buttons or [] if isinstance(b, dict)]
        # Category-specific actions are matched too (their IDs share the shop_custom_ prefix).
        for category in catalog.categories(config):
            buttons.extend(a for a in category.action_buttons or [] if a not in buttons)
        index, button = next(((i, b) for i, b in enumerate(buttons)
                              if catalog.custom_button_id(b).removeprefix("shop_custom_") == key
                              or b.get("id") == key or b.get("label") == key), (-1, None))
        if button is None:
            await _ephemeral(interaction, "Este botón no está configurado o ya no existe.")
            return
        if not config.tickets_enabled:
            await _ephemeral(interaction, "El sistema de tickets está desactivado en este servidor.")
            return
        panel = self._find_panel(await self._panels(guild.id), button.get("panelId"), config.shop_panel_id)
        if panel is None:
            await _ephemeral(interaction, "Este botón no tiene un panel de tickets válido. Un administrador debe "
                                          "vincularlo desde Tickets → Tiendas.")
            return
        if panel.form_enabled and panel.form_questions:
            modal = form_modal(f"shop_action_form_{index}", panel.form_title or str(button.get("label")),
                               list(panel.form_questions))
            if modal is not None:
                await interaction.response.send_modal(modal)
                return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.tickets.create(interaction, panel, options=self._button_options(button))

    async def on_shop_form(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        await interaction.response.defer(ephemeral=True, thinking=True)
        config = await self.bot.configs.get(guild.id)
        panels = await self._panels(guild.id)
        values = modal_values(interaction)

        def answers(panel: TicketPanel) -> list[dict[str, str]]:
            return [{"question": str(q.get("label", "")), "answer": values.get(f"question_{i}", "").strip()}
                    for i, q in enumerate(list(panel.form_questions or [])[:5])]

        if custom_id.startswith("shop_product_form_"):
            async with self.bot.db.session() as session:
                product = (await session.execute(select(ShopProduct).where(
                    ShopProduct.id == custom_id.removeprefix("shop_product_form_"),
                    ShopProduct.guild_id == str(guild.id)))).scalar_one_or_none()
            if product is None or product.stock <= 0:
                await interaction.edit_original_response(
                    content="Este producto ya no existe." if product is None else "Este producto está agotado por el momento.")
                return
            panel = self._find_panel(panels, config.shop_panel_id)
            if panel is None:
                await interaction.edit_original_response(content="La tienda no tiene un panel de tickets válido.")
                return
            await self.tickets.create(interaction, panel, answers(panel), self._product_options(product))
            return
        raw_index = custom_id.removeprefix("shop_action_form_")
        buttons = [b for b in config.shop_custom_buttons or [] if isinstance(b, dict)]
        button = buttons[int(raw_index)] if raw_index.isdigit() and int(raw_index) < len(buttons) else None
        if button is None:
            await interaction.edit_original_response(content="Este botón ya no existe.")
            return
        panel = self._find_panel(panels, button.get("panelId"), config.shop_panel_id)
        if panel is None:
            await interaction.edit_original_response(content="Este botón no tiene un panel de tickets válido.")
            return
        await self.tickets.create(interaction, panel, answers(panel), self._button_options(button))

    # ── /tienda staff panel ──────────────────────────────────────────────

    async def _admin_data(self, guild_id: int) -> tuple[list[catalog.Category | dict[str, Any]], list[ShopProduct]]:
        config = await self.bot.configs.get(guild_id)
        async with self.bot.db.session() as session:
            products = list((await session.execute(select(ShopProduct).where(
                ShopProduct.guild_id == str(guild_id)).order_by(ShopProduct.created_at.desc()))).scalars().all())
        cats: list[Any] = list(catalog.categories(config))
        for product in products:
            if any(catalog.normalize(c.label) == catalog.normalize(product.category) for c in cats):
                continue
            label = (product.category or "General").strip() or "General"
            safe = re.sub(r"[^a-z0-9_-]", "_", catalog.normalize(label))[:40] or "general"
            cats.append(catalog.Category(f"legacy_{safe}", label, "📦", description=f"Productos guardados en {label}."))
        return cats[:25], products

    @staticmethod
    def _find_admin_category(cats: list[Any], category_id: str, product_category: str | None = None) -> Any:
        return next((c for c in cats if c.id == category_id), None) or next(
            (c for c in cats if product_category and catalog.normalize(c.label) == catalog.normalize(product_category)),
            None)

    @staticmethod
    def _product_embed(product: ShopProduct) -> discord.Embed:
        embed = discord.Embed(color=OK if product.active else ERROR, title=f"📦 {product.name}",
                              description=product.description or "Sin descripción adicional.")
        embed.add_field(name="💳 Precio", value=catalog.price_text(product), inline=True)
        embed.add_field(name="📦 Stock real", value=str(product.stock), inline=True)
        embed.add_field(name="🏷️ Texto visible", value=_product_stock(product), inline=True)
        embed.add_field(name="Estado", value="🟢 Disponible" if product.active else "🔴 Oculto / desactivado", inline=True)
        embed.set_footer(text="Panel privado · Los cambios se publican automáticamente en la tienda.")
        if product.image:
            embed.set_image(url=product.image)
        return embed

    def _category_selector(self, cats: list[Any], products: list[ShopProduct]) -> discord.ui.Select[Any]:
        menu = discord.ui.Select(custom_id="shop_stock_category_select",
                                 placeholder="Selecciona Dealer, Mall, Dinero u otra tienda")
        for c in cats:
            count = len(catalog.in_category(products, c))
            plural = "" if count == 1 else "s"
            description = (f"Stock: {c.stock_text} · {count} producto{plural}" if c.stock_text
                           else f"{count} producto{plural} · Administrar catálogo y stock")
            menu.add_option(label=str(c.label)[:100], value=str(c.id)[:100], description=description[:100],
                            emoji=catalog.parse_emoji(c.emoji or "🛍️"))
        return menu

    def _home(self, cats: list[Any], products: list[ShopProduct]) -> dict[str, Any]:
        lines = []
        for c in cats:
            items = catalog.in_category(products, c)
            units = sum(max(0, p.stock) for p in items)
            plural = "" if len(items) == 1 else "s"
            lines.append(f"{c.emoji or '🛍️'} **{c.label}** · Stock general: **{c.stock_text}** · {len(items)} producto{plural}"
                         if c.stock_text else
                         f"{c.emoji or '🛍️'} **{c.label}** · {len(items)} producto{plural} · {units} unidad{'' if units == 1 else 'es'}")
        embed = discord.Embed(color=INFO, title="🛠️ Administración de tiendas", description=(
            "Selecciona la tienda que quieres administrar. Desde ahí podrás crear, eliminar y editar productos, además "
            f"de sumar o restar stock.\n\n{chr(10).join(lines) or 'No hay tiendas configuradas.'}")[:4096])
        embed.set_footer(text="Panel privado · Solo visible para ti.")
        view = discord.ui.View()
        if cats:
            view.add_item(self._category_selector(cats, products))
        return {"embed": embed, "view": view}

    def _category_admin(self, category: Any, products: list[ShopProduct], product: ShopProduct | None = None) -> dict[str, Any]:
        items = catalog.in_category(products, category)
        units = sum(max(0, p.stock) for p in items)
        if product is not None:
            embed = self._product_embed(product)
        else:
            if category.stock_text:
                extra = (f"\n\nTambién hay **{len(items)} producto{'' if len(items) == 1 else 's'}** "
                         f"individual{'' if len(items) == 1 else 'es'} para administrar." if items else "")
                text = (f"**Stock general: {category.stock_text}**\n\nEste inventario pertenece a toda la tienda y aparece "
                        "sobre los precios y métodos de pago. Puedes sumarlo, restarlo o reemplazarlo aquí." + extra)
            elif items:
                text = (f"Esta tienda tiene **{len(items)} producto{'' if len(items) == 1 else 's'}** y **{units} "
                        f"unidad{'' if units == 1 else 'es'}** en total. Selecciona un producto para administrarlo.")
            else:
                text = ("Esta tienda todavía no tiene productos. Usa **Agregar producto** para crear el primero "
                        "directamente desde Discord.")
            embed = discord.Embed(color=INFO, title=f"{category.emoji or '🛍️'} {category.label}", description=text)
            embed.set_footer(text="Panel privado · Los cambios se publican automáticamente.")
        view = discord.ui.View()
        row = 0
        if items:
            menu = discord.ui.Select(custom_id=f"shop_stock_select_{category.id}",
                                     placeholder="Elige un producto para administrarlo", row=row)
            for p in items[:25]:
                menu.add_option(label=p.name[:100], value=p.id,
                                description=f"Stock: {p.stock} · {'Activo' if p.active else 'Oculto'}"[:100])
            view.add_item(menu)
            row += 1
        if category.stock_text:
            for action, label, emoji, style in (("add", "Sumar stock", "➕", discord.ButtonStyle.success),
                                                ("sub", "Restar stock", "➖", discord.ButtonStyle.danger),
                                                ("edit", "Editar cantidad y texto", "✏️", discord.ButtonStyle.primary)):
                view.add_item(discord.ui.Button(custom_id=f"shop_stock_category_{action}_{category.id}", label=label,
                                                emoji=emoji, style=style, row=row))
            row += 1
        if product is not None:
            for action, label, emoji, style in (
                ("add", "Añadir stock", "➕", discord.ButtonStyle.success),
                ("sub", "Restar stock", "➖", discord.ButtonStyle.danger),
                ("edit", "Editar", "✏️", discord.ButtonStyle.primary),
                ("image", "Imagen", "🖼️", discord.ButtonStyle.secondary),
                ("toggle", "Ocultar" if product.active else "Activar", "🙈" if product.active else "👁️",
                 discord.ButtonStyle.secondary),
            ):
                view.add_item(discord.ui.Button(custom_id=f"shop_stock_{action}_{product.id}", label=label, emoji=emoji,
                                                style=style, row=row))
            row += 1
        view.add_item(discord.ui.Button(custom_id=f"shop_stock_create_{category.id}", label="Agregar producto",
                                        emoji="➕", style=discord.ButtonStyle.success, row=row))
        view.add_item(discord.ui.Button(custom_id="shop_stock_home", label="Cambiar tienda", emoji="🏪",
                                        style=discord.ButtonStyle.secondary, row=row))
        if not str(category.id).startswith("legacy_"):
            view.add_item(discord.ui.Button(custom_id=f"{COUNTRY_PREFIX}list:{category.id}", label="Países y precios",
                                            emoji="🌎", style=discord.ButtonStyle.primary, row=row))
        if product is not None:
            view.add_item(discord.ui.Button(custom_id=f"shop_stock_delete_{product.id}", label="Eliminar producto",
                                            emoji="🗑️", style=discord.ButtonStyle.danger, row=row))
        return {"embed": embed, "view": view}

    async def _admin_view(self, guild_id: int, category_id: str = "", product: ShopProduct | None = None,
                          product_category: str | None = None) -> dict[str, Any]:
        cats, products = await self._admin_data(guild_id)
        category = self._find_admin_category(cats, category_id, product_category or (product.category if product else None))
        return self._category_admin(category, products, product) if category else self._home(cats, products)

    @staticmethod
    def _can_manage(interaction: discord.Interaction) -> bool:
        return interaction.permissions.manage_guild

    @app_commands.command(name="tienda",
                          description="Administrar tiendas: productos, stock, países, precios y métodos de pago",
                          extras={"module": "shop", "cooldown": 3, "permissions": ["manage_guild"]})
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def tienda(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await _ephemeral(interaction, "Solo quien tenga **Gestionar servidor** puede administrar el stock.")
            return
        cats, products = await self._admin_data(interaction.guild_id or 0)
        await interaction.response.send_message(ephemeral=True, **self._home(cats, products))

    async def on_stock_category_select(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await _ephemeral(interaction, "No tienes permiso para administrar las tiendas.")
            return
        cats, products = await self._admin_data(interaction.guild_id or 0)
        category = self._find_admin_category(cats, (select_values(interaction) or [""])[0])
        if category is None:
            await interaction.response.edit_message(content="Esa tienda ya no está configurada.", embed=None,
                                                    view=self._home(cats, products)["view"])
            return
        await interaction.response.edit_message(content=None, **self._category_admin(category, products))

    async def _product(self, guild_id: int, product_id: str) -> ShopProduct | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(ShopProduct).where(
                ShopProduct.id == product_id, ShopProduct.guild_id == str(guild_id)))).scalar_one_or_none()

    async def on_stock_select(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await _ephemeral(interaction, "No tienes permiso para administrar el stock.")
            return
        guild_id = interaction.guild_id or 0
        category_id = str((interaction.data or {}).get("custom_id", "")).removeprefix("shop_stock_select_")
        product = await self._product(guild_id, (select_values(interaction) or [""])[0])
        cats, products = await self._admin_data(guild_id)
        category = self._find_admin_category(cats, category_id, product.category if product else None)
        if product is None or category is None:
            payload = self._category_admin(category, products) if category else self._home(cats, products)
            await interaction.response.edit_message(
                content="Ese producto ya no existe." if product is None else "No se pudo encontrar la tienda de ese producto.",
                embed=None, view=payload["view"])
            return
        await interaction.response.edit_message(content=None, **self._category_admin(category, products, product))

    async def on_stock_button(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await _ephemeral(interaction, "No tienes permiso para administrar el stock.")
            return
        guild_id = interaction.guild_id or 0
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        if custom_id == "shop_stock_home":
            cats, products = await self._admin_data(guild_id)
            await interaction.response.edit_message(content=None, **self._home(cats, products))
            return
        if match := re.fullmatch(rf"shop_stock_category_(add|sub|edit)_({CATEGORY_RE})", custom_id, re.I):
            action, category_id = match.groups()
            cats, _ = await self._admin_data(guild_id)
            category = self._find_admin_category(cats, category_id)
            if category is None or category.stock_amount is None:
                await _ephemeral(interaction, "Esta tienda no tiene un stock general configurado.")
                return
            if action == "edit":
                inputs = [_text("Cantidad real", "stockAmount", value=str(max(0, category.stock_amount)), max_length=7),
                          _text("Texto después de la cantidad", "stockUnit",
                                value=category.stock_unit or "unidades disponibles",
                                placeholder="Ej. millones disponibles", max_length=80)]
                title = f"Editar stock · {category.label}"
            else:
                inputs = [_text("Cantidad", "amount", placeholder="Ej. 10", max_length=7)]
                title = f"{'Sumar' if action == 'add' else 'Restar'} stock · {category.label}"
            await interaction.response.send_modal(RoutedModal(title=title, custom_id=custom_id, inputs=inputs))
            return
        if match := re.fullmatch(rf"shop_stock_create_({CATEGORY_RE})", custom_id, re.I):
            cats, _ = await self._admin_data(guild_id)
            category = self._find_admin_category(cats, match.group(1))
            if category is None:
                await _ephemeral(interaction, "Esa tienda ya no está configurada.")
                return
            await interaction.response.send_modal(RoutedModal(
                title=f"Crear producto · {category.label}", custom_id=f"shop_stock_create_{category.id}", inputs=[
                    _text("Nombre", "name", placeholder="Ej. Glock 17"),
                    _text("Precio visible", "priceLabel", placeholder="Ej. 3.50 USD", required=False),
                    _text("Cantidad inicial", "stock", placeholder="Ej. 10", max_length=7),
                    _text("Texto visible de stock", "stockLabel", placeholder="Ej. Disponible", required=False),
                    _text("Descripción (opcional)", "description", placeholder="Detalles del producto", required=False,
                          max_length=2000, paragraph=True)]))
            return
        if match := re.fullmatch(rf"shop_stock_delete_(confirm|cancel)_({UUID_RE})", custom_id, re.I):
            decision, product_id = match.groups()
            product = await self._product(guild_id, product_id)
            if product is None:
                cats, products = await self._admin_data(guild_id)
                await interaction.response.edit_message(content="Ese producto ya no existe.", embed=None,
                                                        view=self._home(cats, products)["view"])
                return
            if decision == "cancel":
                await interaction.response.edit_message(content=None, **await self._admin_view(guild_id, product=product))
                return
            async with self.bot.db.session() as session:
                await session.execute(delete(ShopProduct).where(ShopProduct.id == product.id))
            self.refresh_later(guild_id)
            await interaction.response.edit_message(
                content=f"✅ **{product.name}** fue eliminado de **{product.category or 'General'}**.",
                **await self._admin_view(guild_id, product_category=product.category))
            return
        match = re.fullmatch(rf"shop_stock_(add|sub|edit|image|toggle|delete)_({UUID_RE})", custom_id, re.I)
        if not match:
            return
        action, product_id = match.groups()
        product = await self._product(guild_id, product_id)
        if product is None:
            await _ephemeral(interaction, "Ese producto ya no existe.")
            return
        if action in ("add", "sub"):
            await interaction.response.send_modal(RoutedModal(
                title="Añadir unidades" if action == "add" else "Restar unidades", custom_id=f"shop_stock_{action}_{product.id}",
                inputs=[_text("Cantidad", "amount", placeholder="Ej. 10", max_length=7)]))
        elif action == "edit":
            await interaction.response.send_modal(RoutedModal(title="Editar producto", custom_id=f"shop_stock_edit_{product.id}", inputs=[
                _text("Nombre", "name", value=product.name, required=False),
                _text("Precio visible (ej. 3.50 USD)", "priceLabel", value=product.price_label or "", required=False),
                _text("Cantidad real de stock", "stock", value=str(product.stock), required=False, max_length=7),
                _text("Texto visible de stock", "stockLabel", value=product.stock_label or "", required=False),
                _text("Descripción (opcional)", "description", value=product.description or "", required=False,
                      max_length=2000, paragraph=True)]))
        elif action == "image":
            await interaction.response.send_modal(RoutedModal(title="Imagen del producto", custom_id=f"shop_stock_image_{product.id}",
                                                              inputs=[_text("URL de imagen (vacío para quitarla)", "image",
                                                                            value=product.image or "", required=False,
                                                                            max_length=1000)]))
        elif action == "delete":
            embed = discord.Embed(color=ERROR, title="⚠️ Confirmar eliminación", description=(
                f"¿Quieres eliminar definitivamente **{product.name}** de **{product.category or 'General'}**?\n\n"
                "Esta acción no se puede deshacer."))
            view = discord.ui.View()
            view.add_item(discord.ui.Button(custom_id=f"shop_stock_delete_confirm_{product.id}", label="Sí, eliminar",
                                            emoji="🗑️", style=discord.ButtonStyle.danger))
            view.add_item(discord.ui.Button(custom_id=f"shop_stock_delete_cancel_{product.id}", label="Cancelar",
                                            style=discord.ButtonStyle.secondary))
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            async with self.bot.db.session() as session:
                await session.execute(update(ShopProduct).where(ShopProduct.id == product.id).values(active=not product.active))
            product.active = not product.active
            self.refresh_later(guild_id)
            await interaction.response.edit_message(content=None, **await self._admin_view(guild_id, product=product))

    async def _update_category_stock(self, guild_id: int, category_id: str, action: str, values: dict[str, str]) -> str | None:
        """Returns an error message, or None on success."""
        config = await self.bot.configs.get(guild_id)
        category = next((c for c in catalog.categories(config) if c.id == category_id), None)
        if category is None or category.stock_amount is None:
            return "No se pudo actualizar el stock general de esta tienda."
        amount, unit = category.stock_amount, category.stock_unit or "unidades disponibles"
        if action in ("add", "sub"):
            delta = _positive_int(values.get("amount", ""))
            if not delta:
                return "Usa una cantidad entera entre 1 y 1.000.000."
            if action == "sub" and delta > amount:
                return "No puedes restar más cantidad de la que hay disponible."
            amount = amount + delta if action == "add" else amount - delta
        else:
            try:
                amount = int(values.get("stockAmount", "").strip())
            except ValueError:
                amount = -1
            unit = values.get("stockUnit", "").strip()[:80]
            if not 0 <= amount <= 1_000_000 or not unit:
                return "La cantidad debe ser un entero entre 0 y 1.000.000 y el texto no puede estar vacío."
        if not 0 <= amount <= 1_000_000:
            return "No se pudo actualizar el stock general de esta tienda."
        await self.publisher.patch_category(str(guild_id), category_id, stockAmount=amount, stockUnit=unit,
                                            availabilityText=f"{amount} {unit}"[:100])
        return None

    async def on_stock_modal(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await _ephemeral(interaction, "No tienes permiso para administrar el stock.")
            return
        guild_id = interaction.guild_id or 0
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        values = modal_values(interaction)

        if match := re.fullmatch(rf"shop_stock_category_(add|sub|edit)_({CATEGORY_RE})", custom_id, re.I):
            action, category_id = match.groups()
            error = await self._update_category_stock(guild_id, category_id, action, values)
            if error:
                await _ephemeral(interaction, error)
                return
            self.refresh_later(guild_id)
            cats, products = await self._admin_data(guild_id)
            category = self._find_admin_category(cats, category_id)
            payload = self._category_admin(category, products) if category else self._home(cats, products)
            await _ephemeral(interaction, f"✅ Stock general actualizado: **{category.stock_text if category else 'guardado'}**.",
                             **payload)
            return

        if match := re.fullmatch(rf"shop_stock_create_({CATEGORY_RE})", custom_id, re.I):
            cats, _ = await self._admin_data(guild_id)
            category = self._find_admin_category(cats, match.group(1))
            if category is None:
                await _ephemeral(interaction, "Esa tienda ya no está configurada.")
                return
            name = values.get("name", "").strip()
            try:
                stock = int(values.get("stock", "").strip())
            except ValueError:
                stock = -1
            if not name or len(name) > 100 or not 0 <= stock <= 1_000_000:
                await _ephemeral(interaction, "Revisa nombre y cantidad: el stock debe ser un entero entre 0 y 1.000.000.")
                return
            price_label = values.get("priceLabel", "").strip()
            product = ShopProduct(guild_id=str(guild_id), name=name, category=category.label,
                                  price=_numeric_price(price_label, 0), price_label=price_label or None, stock=stock,
                                  stock_label=values.get("stockLabel", "").strip() or None,
                                  description=values.get("description", "").strip()[:2000])
            async with self.bot.db.session() as session:
                session.add(product)
            self.refresh_later(guild_id)
            await _ephemeral(interaction, f"✅ Producto creado en **{category.label}**.",
                             **await self._admin_view(guild_id, category.id, product))
            return

        match = re.fullmatch(rf"shop_stock_(add|sub|edit|image)_({UUID_RE})", custom_id, re.I)
        if not match:
            return
        action, product_id = match.groups()
        product = await self._product(guild_id, product_id)
        if product is None:
            await _ephemeral(interaction, "Ese producto ya no existe.")
            return
        changes: dict[str, Any] = {}
        if action in ("add", "sub"):
            amount = _positive_int(values.get("amount", ""))
            if not amount:
                await _ephemeral(interaction, "Usa una cantidad entera entre 1 y 1.000.000.")
                return
            async with self.bot.db.session() as session:
                stmt = update(ShopProduct).where(ShopProduct.id == product.id)
                if action == "sub":
                    stmt = stmt.where(ShopProduct.stock >= amount)
                result = await session.execute(stmt.values(
                    stock=ShopProduct.stock + amount if action == "add" else ShopProduct.stock - amount))
            if result.rowcount != 1:
                await _ephemeral(interaction, f"No puedes restar {amount}: el producto solo tiene {product.stock} unidades.")
                return
        elif action == "image":
            image = values.get("image", "").strip()
            if image and not re.match(r"^https?://", image, re.I):
                await _ephemeral(interaction, "La imagen debe comenzar con http:// o https://.")
                return
            changes["image"] = image or None
        else:
            name = values.get("name", "").strip()
            try:
                stock = int(values.get("stock", "").strip())
            except ValueError:
                stock = -1
            if not name or len(name) > 100 or not 0 <= stock <= 1_000_000:
                await _ephemeral(interaction, "Revisa nombre y cantidad: el stock debe ser un entero entre 0 y 1.000.000.")
                return
            price_label = values.get("priceLabel", "").strip()
            changes.update(name=name, price=_numeric_price(price_label, product.price), price_label=price_label or None,
                           stock=stock, stock_label=values.get("stockLabel", "").strip() or None,
                           description=values.get("description", "").strip()[:2000])
        if changes:
            async with self.bot.db.session() as session:
                await session.execute(update(ShopProduct).where(ShopProduct.id == product.id).values(**changes))
        updated = await self._product(guild_id, product.id)
        self.refresh_later(guild_id)
        await _ephemeral(interaction, "✅ Producto actualizado.", **await self._admin_view(guild_id, product=updated))

    # ── Countries & prices (shopc:<action>:<category>[:<country>]) ───────

    async def _country_category(self, guild_id: int, category_id: str) -> catalog.Category | None:
        self.bot.configs.invalidate(guild_id)
        return next((c for c in catalog.categories(await self.bot.configs.get(guild_id)) if c.id == category_id), None)

    async def _mutate_countries(self, guild_id: int, category_id: str, change: Any) -> tuple[list[catalog.PaymentOption], list[catalog.PaymentOption]]:
        lock = self._country_locks.setdefault(guild_id, asyncio.Lock())
        async with lock, self.bot.db.session() as session:
            config = await session.get(GuildConfig, str(guild_id), with_for_update=True)
            raw = [dict(c) if isinstance(c, dict) else c for c in (config.shop_categories or [])] if config else []
            index = next((i for i, c in enumerate(raw) if isinstance(c, dict) and str(c.get("id")) == category_id), -1)
            if index < 0:
                raise ValueError("Esa tienda ya no está configurada.")
            before = catalog.normalize_payment_options(raw[index].get("paymentOptions"))
            after = change(before)
            if len(after) > catalog.MAX_PAYMENT_OPTIONS:
                raise ValueError(f"Máximo {catalog.MAX_PAYMENT_OPTIONS} países por tienda.")
            raw[index]["paymentOptions"] = [o.to_json() for o in after]
            await session.execute(update(GuildConfig).where(GuildConfig.id == str(guild_id)).values(shop_categories=raw))
        self.bot.configs.invalidate(guild_id)
        return before, after

    async def _after_country_change(self, interaction: discord.Interaction, label: str,
                                    before: list[catalog.PaymentOption], after: list[catalog.PaymentOption]) -> None:
        self.refresh_later(interaction.guild_id or 0)
        changes = catalog.describe_changes(before, after)
        if changes and interaction.guild:
            embed = discord.Embed(color=INFO, title=f"🌎 Tienda {label}: precios actualizados",
                                  description="\n".join(changes)[:4000], timestamp=discord.utils.utcnow())
            embed.add_field(name="Editado por", value=f"{interaction.user.mention} `{interaction.user.name}`")
            await send_audit(self.bot, interaction.guild, embed)

    @staticmethod
    def _cid(*parts: str) -> str:
        return (COUNTRY_PREFIX + ":".join(parts))[:100]

    def _country_list(self, category: catalog.Category, note: str = "") -> dict[str, Any]:
        options = category.payment_options
        hidden = sum(1 for o in options if o.hidden)
        lines = []
        for i, o in enumerate(options):
            extras = " · ".join(filter(None, [o.methods, f"Stock: **{o.stock}**" if o.stock else ""]))
            lines.append(f"`{str(i + 1).rjust(2)}` {'🙈 ~~' if o.hidden else ''}{f'{o.emoji} ' if o.emoji else ''}"
                         f"**{o.country}**{'~~' if o.hidden else ''} — {o.price}{f' · {extras}' if extras else ''}")
        body = "\n".join(lines) if lines else "Esta tienda todavía no tiene países. Usa **Agregar país** o **Edición rápida**."
        hidden_text = f" · {hidden} oculto{'' if hidden == 1 else 's'}" if hidden else ""
        embed = discord.Embed(color=INFO, title=f"🌎 {category.label}: países y precios",
                              description=f"{body}\n\n**{len(options)}/{catalog.MAX_PAYMENT_OPTIONS}** países{hidden_text}"[:4096])
        embed.set_footer(text="Elige un país para editarlo · Los cambios se publican al instante")
        view = discord.ui.View()
        if options:
            menu = discord.ui.Select(custom_id=self._cid("pick", category.id),
                                     placeholder="Elige un país para editar precio, stock o métodos", row=0)
            for o in options[:25]:
                emoji = o.emoji if o.emoji and len(o.emoji) <= 4 else None
                menu.add_option(label=f"{o.country}{' (oculto)' if o.hidden else ''}"[:100], value=o.id, emoji=emoji,
                                description=" · ".join(filter(None, [o.price, f"Stock: {o.stock}" if o.stock else ""]))[:100])
            view.add_item(menu)
        for action, label, emoji, style, disabled in (
            ("add", "Agregar país", "➕", discord.ButtonStyle.success, len(options) >= catalog.MAX_PAYMENT_OPTIONS),
            ("bulk", "Edición rápida", "📝", discord.ButtonStyle.primary, False),
            ("preview", "Vista previa", "👁️", discord.ButtonStyle.secondary, False),
            ("back", "Volver", "↩️", discord.ButtonStyle.secondary, False),
        ):
            view.add_item(discord.ui.Button(custom_id=self._cid(action, category.id), label=label, emoji=emoji,
                                            style=style, disabled=disabled, row=1))
        return {"content": note or None, "embed": embed, "view": view}

    def _country_view(self, category: catalog.Category, option: catalog.PaymentOption, note: str = "") -> dict[str, Any]:
        position = next((i for i, o in enumerate(category.payment_options) if o.id == option.id), 0)
        embed = discord.Embed(color=0x99AAB5 if option.hidden else OK,
                              title=f"{f'{option.emoji} ' if option.emoji else ''}{option.country}")
        embed.add_field(name="💲 Precio", value=option.price, inline=True)
        embed.add_field(name="💳 Métodos de pago", value=option.methods or "—", inline=True)
        embed.add_field(name="📦 Stock del país", value=option.stock or "— (usa el stock general)", inline=True)
        embed.add_field(name="Estado", value="🙈 Oculto en la tienda" if option.hidden else "👁️ Visible en la tienda",
                        inline=True)
        embed.add_field(name="Posición", value=f"{position + 1} de {len(category.payment_options)}", inline=True)
        embed.set_footer(text=f"Tienda {category.label} · Los cambios se publican al instante")
        view = discord.ui.View()
        total = len(category.payment_options)
        for action, label, emoji, style, disabled in (
            ("edit", "Editar", "✏️", discord.ButtonStyle.primary, False),
            ("toggle", "Mostrar" if option.hidden else "Ocultar", "👁️" if option.hidden else "🙈",
             discord.ButtonStyle.secondary, False),
            ("up", None, "⬆️", discord.ButtonStyle.secondary, position <= 0),
            ("down", None, "⬇️", discord.ButtonStyle.secondary, position >= total - 1),
            ("del", "Eliminar", "🗑️", discord.ButtonStyle.danger, False),
        ):
            view.add_item(discord.ui.Button(custom_id=self._cid(action, category.id, option.id), label=label, emoji=emoji,
                                            style=style, disabled=disabled, row=0))
        view.add_item(discord.ui.Button(custom_id=self._cid("list", category.id), label="Todos los países", emoji="🌎",
                                        style=discord.ButtonStyle.secondary, row=1))
        return {"content": note or None, "embed": embed, "view": view}

    def _country_modal(self, custom_id: str, title: str, option: catalog.PaymentOption | None = None) -> RoutedModal:
        o = option
        return RoutedModal(title=title, custom_id=custom_id, inputs=[
            _text("País", "country", value=o.country if o else "", placeholder="Ej: Venezuela", max_length=60),
            _text("Bandera o emoji", "emoji", value=o.emoji if o else "", placeholder="Ej: 🇻🇪", required=False, max_length=20),
            _text("Precio", "price", value=o.price if o else "", placeholder="Ej: 25 USD C/U por millón"),
            _text("Métodos de pago", "methods", value=o.methods if o else "", placeholder="Ej: Pago Móvil / Binance",
                  required=False, max_length=150),
            _text("Stock de este país (opcional)", "stock", value=o.stock if o else "",
                  placeholder="Ej: 200 millones · Agotado · vacío = stock general", required=False, max_length=60),
        ])

    async def _show(self, interaction: discord.Interaction, payload: dict[str, Any]) -> None:
        message = interaction.message
        if interaction.type is discord.InteractionType.modal_submit and message is None:
            await interaction.response.send_message(ephemeral=True, **payload)
        else:
            await interaction.response.edit_message(**payload)

    async def on_country(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or not self._can_manage(interaction):
            await _ephemeral(interaction, "Solo quien tenga **Gestionar servidor** puede editar los precios.")
            return
        guild_id = interaction.guild_id
        parts = str((interaction.data or {}).get("custom_id", "")).removeprefix(COUNTRY_PREFIX).split(":")
        action, category_id, country_id = ([*parts, "", "", ""])[:3]
        if interaction.type is discord.InteractionType.component and (interaction.data or {}).get("component_type") == 3:
            country_id = (select_values(interaction) or [""])[0]
        category = await self._country_category(guild_id, category_id)
        if category is None:
            await _ephemeral(interaction, "Esa tienda ya no está configurada.")
            return
        option = next((o for o in category.payment_options if o.id == country_id), None)
        try:
            await self._country_action(interaction, guild_id, action, category, option, country_id)
        except ValueError as exc:
            await _ephemeral(interaction, f"❌ {exc}")

    async def _country_action(self, interaction: discord.Interaction, guild_id: int, action: str,
                              category: catalog.Category, option: catalog.PaymentOption | None, country_id: str) -> None:
        missing = {**self._country_list(category), "content": "Ese país ya no existe."}
        if action == "list":
            await self._show(interaction, self._country_list(category))
        elif action == "back":
            await self._show(interaction, {"content": None, **await self._admin_view(guild_id, category.id)})
        elif action == "pick":
            await self._show(interaction, self._country_view(category, option) if option else missing)
        elif action == "preview":
            config = await self.bot.configs.get(guild_id)
            async with self.bot.db.session() as session:
                products = list((await session.execute(select(ShopProduct).where(
                    ShopProduct.guild_id == str(guild_id), ShopProduct.active.is_(True)))).scalars().all())
            payload = catalog.category_panel(config, catalog.in_category(products, category), category)
            await interaction.response.send_message("👁️ **Vista previa** — así se ve el panel público ahora mismo:",
                                                    embed=payload.embed, ephemeral=True)
        elif action == "add":
            if len(category.payment_options) >= catalog.MAX_PAYMENT_OPTIONS:
                await _ephemeral(interaction, f"Ya tienes el máximo de {catalog.MAX_PAYMENT_OPTIONS} países.")
                return
            await interaction.response.send_modal(self._country_modal(self._cid("addm", category.id),
                                                                      f"Agregar país · {category.label}"))
        elif action == "edit":
            if option is None:
                await self._show(interaction, missing)
                return
            await interaction.response.send_modal(self._country_modal(self._cid("editm", category.id, option.id),
                                                                      f"Editar {option.country}", option))
        elif action == "bulk":
            value = catalog.format_bulk(category.payment_options)
            if len(value) > 4000:
                await _ephemeral(interaction, "La lista es demasiado larga para la edición rápida (límite de Discord: "
                                              "4000 caracteres). Edita los países uno por uno.")
                return
            await interaction.response.send_modal(RoutedModal(
                title=f"Edición rápida · {category.label}", custom_id=self._cid("bulkm", category.id),
                inputs=[_text("Un país por línea (separa con | )", "countries", value=value, max_length=4000, paragraph=True)]))
        elif action in ("addm", "editm"):
            values = modal_values(interaction)
            data = {k: values.get(k, "") for k in ("country", "emoji", "price", "methods", "stock")}
            saved_id = country_id

            def change(options: list[catalog.PaymentOption]) -> list[catalog.PaymentOption]:
                nonlocal saved_id
                problem = catalog.validate_country(data, [o for o in options if o.id != country_id])
                if problem:
                    raise ValueError(problem)
                if action == "addm":
                    saved_id = catalog.unique_country_id(data["country"], [o.id for o in options])
                    return [*options, catalog.build_country(saved_id, data)]
                if not any(o.id == country_id for o in options):
                    raise ValueError("Ese país ya no existe.")
                return [catalog.build_country(o.id, data, o.hidden) if o.id == country_id else o for o in options]

            before, after = await self._mutate_countries(guild_id, category.id, change)
            await self._after_country_change(interaction, category.label, before, after)
            updated = await self._country_category(guild_id, category.id)
            saved = next((o for o in updated.payment_options if o.id == saved_id), None) if updated else None
            if updated is None or saved is None:
                await self._show(interaction, {"content": "✅ Guardado.", "embed": None, "view": None})
                return
            note = f"✅ **{saved.country}** agregado y publicado." if action == "addm" else "✅ Cambios guardados y publicados."
            await self._show(interaction, self._country_view(updated, saved, note))
        elif action == "bulkm":
            text = modal_values(interaction).get("countries", "")
            problems: list[str] = []

            def change_bulk(options: list[catalog.PaymentOption]) -> list[catalog.PaymentOption]:
                parsed, errors = catalog.parse_bulk(text, options)
                problems.extend(errors)
                if errors:
                    raise LookupError
                return parsed

            try:
                before, after = await self._mutate_countries(guild_id, category.id, change_bulk)
            except LookupError:
                await _ephemeral(interaction, ("❌ No se guardó nada. Corrige estas líneas:\n"
                                               + "\n".join(f"• {p}" for p in problems[:15]))[:2000])
                return
            await self._after_country_change(interaction, category.label, before, after)
            updated = await self._country_category(guild_id, category.id)
            count = len(catalog.describe_changes(before, after))
            plural = "" if count == 1 else "s"
            await self._show(interaction, self._country_list(
                updated or category, f"✅ Edición rápida guardada · {count} cambio{plural} publicado{plural}."))
        elif action in ("toggle", "up", "down"):
            if option is None:
                await self._show(interaction, missing)
                return

            def change_one(options: list[catalog.PaymentOption]) -> list[catalog.PaymentOption]:
                if action == "toggle":
                    return [catalog.PaymentOption(o.id, o.emoji, o.country, o.price, o.methods, o.stock, not o.hidden)
                            if o.id == option.id else o for o in options]
                return catalog.move_country(options, option.id, -1 if action == "up" else 1)

            before, after = await self._mutate_countries(guild_id, category.id, change_one)
            await self._after_country_change(interaction, category.label, before, after)
            updated = await self._country_category(guild_id, category.id)
            saved = next((o for o in updated.payment_options if o.id == option.id), option) if updated else option
            await self._show(interaction, self._country_view(updated or category, saved))
        elif action == "del":
            if option is None:
                await self._show(interaction, missing)
                return
            embed = discord.Embed(color=ERROR, title="⚠️ Eliminar país", description=(
                f"¿Eliminar **{f'{option.emoji} ' if option.emoji else ''}{option.country}** ({option.price}) de "
                f"**{category.label}**?\n\nSi solo quieres quitarlo por un tiempo, usa **Ocultar**."))
            view = discord.ui.View()
            view.add_item(discord.ui.Button(custom_id=self._cid("delok", category.id, option.id), label="Sí, eliminar",
                                            emoji="🗑️", style=discord.ButtonStyle.danger))
            view.add_item(discord.ui.Button(custom_id=self._cid("pick", category.id, option.id), label="Cancelar",
                                            style=discord.ButtonStyle.secondary))
            await self._show(interaction, {"content": None, "embed": embed, "view": view})
        elif action == "delok":
            before, after = await self._mutate_countries(
                guild_id, category.id, lambda options: [o for o in options if o.id != country_id])
            await self._after_country_change(interaction, category.label, before, after)
            updated = await self._country_category(guild_id, category.id)
            await self._show(interaction, self._country_list(
                updated or category, f"🗑️ **{option.country}** eliminado." if option else ""))

    # ── /cotizacion & /comprar ───────────────────────────────────────────

    @app_commands.command(name="cotizacion", description="Calcular el precio de venta de un objeto según su valor IC",
                          extras={"module": "utility", "cooldown": 3, "public": True})
    @app_commands.guild_only()
    @app_commands.rename(valor_ic="valor-ic")
    @app_commands.describe(objeto="Nombre del objeto", valor_ic="Valor IC en K o M, por ejemplo: 450K, 2.5M o 120.5M",
                           depuracion="Mostrar el cálculo interno (solo administradores)")
    async def cotizacion(self, interaction: discord.Interaction, objeto: app_commands.Range[str, 1, 100],
                         valor_ic: app_commands.Range[str, 1, 30], depuracion: bool = False) -> None:
        name = re.sub(r"[\r\n]+", " ", objeto).strip()
        parsed = parse_ic_value(valor_ic)
        if not name or parsed is None:
            await _ephemeral(interaction, "El valor IC no es válido. Usa formatos como `200K`, `450K`, `1M`, `2.5M` o `120.5M`.")
            return
        config = await self.bot.configs.get(interaction.guild_id or 0)
        base = extract_usd_million_price(config.shop_categories)
        if not base:
            await _ephemeral(interaction, "No se pudo obtener el precio actual del millón. Un administrador debe revisar "
                                          "el precio en la tienda Dinero.")
            return
        quote = calculate_quote(parsed.millions, base)
        await interaction.response.send_message(f"📦 Objeto: {name}\n💰 Precio: ${quote.final_price:.2f} USD",
                                                allowed_mentions=discord.AllowedMentions.none())
        perms = interaction.permissions
        if not (perms.administrator or perms.manage_guild):
            return
        lines = ["━━ INFORMACIÓN INTERNA ━━", "", f"• Valor IC: {parsed.original}",
                 f"• Equivalencia en millones: {format_decimal(quote.millions)}M",
                 f"• Precio actual del millón: ${quote.base_price_per_million:.2f} USD/M",
                 f"• Descuento aplicado por volumen: -${quote.discount_per_million:.2f} USD/M",
                 f"• Precio por millón utilizado: ${quote.quote_price_per_million:.2f} USD/M",
                 f"• Valor al precio actual: ${quote.reference_price:.2f} USD",
                 f"• Precio final: ${quote.final_price:.2f} USD", f"• Reducción total aplicada: ${quote.reduction:.2f} USD"]
        if depuracion:
            lines += ["", "Depuración solicitada manualmente."]
        await interaction.followup.send("\n".join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="comprar", description="Abrir una compra protegida dentro del Market",
                          extras={"module": "tickets", "cooldown": 10, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(vendedor="Usuario al que deseas comprarle")
    async def comprar(self, interaction: discord.Interaction, vendedor: discord.User) -> None:
        guild = interaction.guild
        if guild is None or str(guild.id) != HUBSTORE_GUILD_ID:
            await _ephemeral(interaction, "Este flujo de compra no está configurado en este servidor.")
            return
        buyer = interaction.user
        if not isinstance(buyer, discord.Member) or not ({str(r.id) for r in buyer.roles} & VERIFIED_BUYER_ROLE_IDS):
            await _ephemeral(interaction, "Necesitas el rango **Shopper**, **Access** o **Vip** para comprar dentro del "
                                          "Market. Abre un ticket de rangos para solicitarlo.")
            return
        if vendedor.id == buyer.id:
            await _ephemeral(interaction, "No puedes abrir una compra contigo mismo.")
            return
        if vendedor.bot:
            await _ephemeral(interaction, "El vendedor debe ser una persona, no un bot.")
            return
        seller = guild.get_member(vendedor.id)
        if seller is None:
            await _ephemeral(interaction, "El vendedor debe estar dentro de HubStore para abrir una compra protegida.")
            return
        if not ({str(r.id) for r in seller.roles} & VERIFIED_SELLER_ROLE_IDS):
            await _ephemeral(interaction, "Ese usuario no tiene un rango **Access** o **Vip** verificado para vender "
                                          "dentro del Market.")
            return
        async with self.bot.db.session() as session:
            panel = (await session.execute(select(TicketPanel).where(
                TicketPanel.guild_id == str(guild.id), TicketPanel.name == ACCESS_PURCHASE_PANEL_NAME).limit(1)
            )).scalar_one_or_none()
            existing = None
            if panel is not None:
                existing = (await session.execute(select(Ticket).where(
                    Ticket.guild_id == str(guild.id), Ticket.panel_id == panel.id, Ticket.user_id == str(buyer.id),
                    Ticket.status == "open", Ticket.added_users.any(str(seller.id)),
                ).order_by(Ticket.created_at.desc()).limit(1))).scalar_one_or_none()
        if panel is None:
            await _ephemeral(interaction, "El sistema de compras protegidas todavía no está configurado. Avísale a un "
                                          "administrador.")
            return
        if existing is not None:
            await _ephemeral(interaction, f"Ya tienes una compra abierta con ese vendedor: <#{existing.channel_id}>.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = [{"question": "Comprador", "answer": buyer.mention}, {"question": "Vendedor", "answer": seller.mention},
                   {"question": "Canal de origen", "answer": f"<#{interaction.channel_id}>"}]
        await self.tickets.create(interaction, panel, answers, CreateOptions(
            participant_user_ids=[str(seller.id)], mention_user_ids=[str(seller.id)],
            naming_pattern="compra-{number}-{username}",
            topic=f"Compra protegida | Comprador: {buyer.id} | Vendedor: {seller.id} | Origen: {interaction.channel_id}",
            welcome_title="Compra protegida #{number}", welcome_color="#5865F2",
            welcome_message=(
                f"**Comprador:** {buyer.mention}\n**Vendedor:** {seller.mention}\n\nEste canal es privado y fue creado "
                "para realizar la compra dentro de HubStore. Confirmen aquí el producto, la cantidad, el precio, el "
                "método de pago y cualquier condición antes de completar la operación.\n\nGuarden todos los "
                "comprobantes en este ticket y no trasladen la negociación a mensajes privados. El staff podrá "
                "intervenir y la conversación quedará disponible para generar una transcripción."),
            reply_content="Tu compra protegida fue creada: {channel}", source_label="Access"))

    # ── Sticky shop, rotation and announcements ──────────────────────────

    async def sticky_shop(self, message: discord.Message, config: GuildConfig) -> None:
        """Debounced repost so the shop stays the last message of its channel."""
        if not config.shop_sticky_enabled or config.shop_channel_id != str(message.channel.id):
            return
        handle = self._sticky_timers.pop(message.channel.id, None)
        if handle:
            handle.cancel()
        delay = max(5, min(3600, config.shop_sticky_cooldown or 10))
        guild_id = str(message.guild.id) if message.guild else ""

        def fire() -> None:
            self._sticky_timers.pop(message.channel.id, None)
            self.bot.spawn(self.publisher.repost_main(guild_id), name=f"shop-sticky-{guild_id}")

        self._sticky_timers[message.channel.id] = asyncio.get_running_loop().call_later(delay, fire)

    async def _shop_configs(self) -> list[GuildConfig]:
        cached = self._configs_cache.get("all")
        if cached is not None:
            return cached
        guild_ids = [str(g.id) for g in self.bot.guilds]
        async with self.bot.db.session() as session:
            rows = list((await session.execute(select(GuildConfig).where(GuildConfig.id.in_(guild_ids)))).scalars().all())
        self._configs_cache.set("all", rows)
        return rows

    @tasks.loop(minutes=1)
    @resilient
    async def rotate_images(self) -> None:
        now = time.monotonic()
        for config in await self._shop_configs():
            main_index: int | None = None
            primary = catalog.primary_category(config)
            images = catalog.primary_images(config)
            if config.shop_channel_id and config.shop_message_id and primary and primary.playback_mode == "interval" \
                    and len(images) > 1:
                interval = max(60, primary.image_interval or config.shop_image_interval or 60)
                key = config.id
                self._rotation_last.setdefault(key, now)
                if now - self._rotation_last[key] >= interval:
                    self._rotation_last[key] = now
                    main_index = (self._rotation_index.get(key, 0) + 1) % len(images)
                    self._rotation_index[key] = main_index
            due: dict[str, int] = {}
            for category in catalog.categories(config):
                display = category.display_images
                if not (category.channel_id and category.message_id and category.playback_mode == "interval"
                        and len(display) > 1):
                    continue
                key = f"{config.id}:{category.id}"
                self._rotation_last.setdefault(key, now)
                if now - self._rotation_last[key] >= max(60, category.image_interval):
                    self._rotation_last[key] = now
                    due[category.id] = (self._rotation_index.get(key, 0) + 1) % len(display)
                    self._rotation_index[key] = due[category.id]
            if main_index is not None or due:
                await self.publisher.refresh(config.id, main_index, due, only_due=True)

    @tasks.loop(minutes=1)
    @resilient
    async def announcements(self) -> None:
        """Scheduled @everyone shop announcements, rotating between stores with a 20-minute stagger."""
        for config in await self._shop_configs():
            fresh = await self.bot.configs.get(config.id)
            if not fresh.shop_announcement_enabled or not (fresh.shop_announcement_message or "").strip():
                continue
            await self._announce(fresh)

    def _targets(self, config: GuildConfig) -> list[dict[str, Any]]:
        def stamp(value: str | None) -> float:
            try:
                return datetime.fromisoformat(value).timestamp() if value else 0.0
            except ValueError:
                return 0.0

        cats = catalog.categories(config)
        primary = catalog.primary_category(config)
        published = [c for c in cats if c.channel_id and c.message_id]
        if config.shop_announcement_channel_id:
            category = next((c for c in published if c.channel_id == config.shop_announcement_channel_id), None)
            is_primary = config.shop_announcement_channel_id == config.shop_channel_id
            source = category or (primary if is_primary else None)
            return [{"channel": config.shop_announcement_channel_id,
                     "category": category.id if category else (primary.id if is_primary and primary else None),
                     "primary": is_primary, "last": stamp(source.announcement_last_sent_at if source else None)}]
        targets = []
        if config.shop_channel_id and primary:
            targets.append({"channel": config.shop_channel_id, "category": primary.id, "primary": True,
                            "last": stamp(primary.announcement_last_sent_at)})
        targets += [{"channel": c.channel_id, "category": c.id, "primary": False, "last": stamp(c.announcement_last_sent_at)}
                    for c in published if c.channel_id != config.shop_channel_id]

        def order(target: dict[str, Any]) -> int:
            category = target["category"]
            return PREFERRED_ANNOUNCE_ORDER.index(category) if category in PREFERRED_ANNOUNCE_ORDER \
                else len(PREFERRED_ANNOUNCE_ORDER)

        return sorted(targets, key=order)

    async def _announce(self, config: GuildConfig) -> None:
        interval = max(300, config.shop_announcement_interval or 86400)
        targets = self._targets(config)
        if not targets:
            return
        now = time.time()
        latest = max((t for t in targets if t["last"]), key=lambda t: t["last"], default=None)
        if latest is None:
            legacy = config.shop_announcement_last_sent_at.replace(tzinfo=UTC).timestamp() \
                if config.shop_announcement_last_sent_at else 0
            if legacy and now - legacy < interval:
                return
            target = targets[0]
        else:
            if now - latest["last"] < ANNOUNCE_STAGGER_SECONDS:
                return
            target = targets[(targets.index(latest) + 1) % len(targets)]
            if target["last"] and now - target["last"] < interval:
                return
        channel = self.bot.get_channel(int(target["channel"]))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning("Shop announcement channel %s unavailable for %s", target["channel"], config.id)
            return
        perms = channel.permissions_for(channel.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.mention_everyone):
            log.warning("Missing Send Messages or Mention Everyone permission in %s", channel.id)
            return
        content = catalog.announcement_content(config.shop_announcement_message or "")
        if target["primary"]:
            sent = bool(await self.publisher.repost_main(config.id, content))
        elif target["category"]:
            sent = bool(await self.publisher.repost_category(config.id, target["category"], content))
        else:
            await channel.send(content, allowed_mentions=discord.AllowedMentions(everyone=True))
            sent = True
        if not sent:
            return
        sent_at = utcnow()
        if target["category"]:
            await self.publisher.patch_category(config.id, target["category"],
                                                announcementLastSentAt=sent_at.isoformat() + "Z")
        await self.bot.configs.update(config.id, shop_announcement_last_sent_at=sent_at)
        log.info("Sent shop announcement for %s; next store eligible in 20 minutes", target["category"] or target["channel"])

    @rotate_images.before_loop
    @announcements.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    # ── Dashboard actions ────────────────────────────────────────────────

    async def _publish_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        try:
            message_id = await self.publisher.publish(str(body.get("guildId")), str(body.get("channelId")))
        except ValueError as exc:
            raise HttpError(400, str(exc)) from exc
        except LookupError as exc:
            raise HttpError(404, str(exc)) from exc
        except discord.HTTPException as exc:
            raise HttpError(502, f"No se pudo publicar: {exc}") from exc
        return json_response({"success": True, "messageId": message_id, "message": "Tienda publicada exitosamente"})

    async def _refresh_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        self.bot.configs.invalidate(str(body.get("guildId")))
        self._configs_cache.clear()
        await self.publisher.refresh(str(body.get("guildId")))
        return json_response({"success": True})

    async def _publish_category_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        try:
            message_id = await self.publisher.publish_category(str(body.get("guildId")), str(body.get("categoryId")),
                                                               str(body.get("channelId")))
        except LookupError as exc:
            raise HttpError(404, str(exc)) from exc
        except discord.HTTPException as exc:
            raise HttpError(502, f"No se pudo publicar: {exc}") from exc
        return json_response({"success": True, "messageId": message_id})


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Shop(bot))
