"""Shop catalog: category normalization, per-country prices and panel message builders.

Categories ("tiendas": Dealer, Mall, Dinero...) live as JSON in
``GuildConfig.shopCategories`` and are edited by the dashboard and ``/tienda``,
so field names inside that JSON stay camelCase.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from sqlalchemy import select, update

from markets_bot.core.utils import INFO, parse_color
from markets_bot.db.models import GuildConfig, ShopProduct

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

STYLES = {"Primary": discord.ButtonStyle.primary, "Secondary": discord.ButtonStyle.secondary,
          "Success": discord.ButtonStyle.success, "Danger": discord.ButtonStyle.danger}
MAX_BUTTONS = 25
MAX_CATEGORIES = 10
MAX_PAYMENT_OPTIONS = 25
OPTION_LIMITS = {"id": 80, "emoji": 20, "country": 60, "price": 100, "methods": 150, "stock": 60}
DEFAULT_FOOTER = ("────────────\nUsa **Comprar** para iniciar una compra o **Hacer un encargo** si buscas algo que "
                  "todavía no aparece en el catálogo.")
BULK_HEADER = "# bandera | país | precio | métodos de pago | stock (opcional) | oculto (opcional)"
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_SNOWFLAKE_RE = re.compile(r"^\d{16,22}$")


def safe_label(value: Any, fallback: str) -> str:
    label = re.sub(r"[\r\n]+", " ", str(value or fallback)).strip()
    return label[:80] or fallback


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "General"))
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]


# ─── Payment options (countries) ─────────────────────────────────────────────


@dataclass(slots=True)
class PaymentOption:
    id: str
    emoji: str
    country: str
    price: str
    methods: str = ""
    stock: str = ""
    hidden: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "emoji": self.emoji, "country": self.country, "price": self.price,
                "methods": self.methods, "stock": self.stock, "hidden": self.hidden}


def normalize_payment_options(value: Any) -> list[PaymentOption]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    options = []
    for index, item in enumerate(value[:MAX_PAYMENT_OPTIONS]):
        item = item if isinstance(item, dict) else {}
        oid = re.sub(r"[^a-zA-Z0-9_-]", "_", str(item.get("id") or f"payment-{index + 1}"))[:OPTION_LIMITS["id"]]
        country = _clean(item.get("country"), OPTION_LIMITS["country"])
        price = _clean(item.get("price"), OPTION_LIMITS["price"])
        if not oid or not country or not price or oid in seen:
            continue
        seen.add(oid)
        options.append(PaymentOption(oid, _clean(item.get("emoji"), OPTION_LIMITS["emoji"]), country, price,
                                     _clean(item.get("methods"), OPTION_LIMITS["methods"]),
                                     _clean(item.get("stock"), OPTION_LIMITS["stock"]), item.get("hidden") is True))
    return options


def country_slug(country: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(country)).strip("-")[:32] or "pais"


def unique_country_id(country: str, taken: list[str]) -> str:
    base = country_slug(country)
    if base not in taken:
        return base
    i = 2
    while f"{base[:28]}-{i}" in taken:
        i += 1
    return f"{base[:28]}-{i}"


def validate_country(data: dict[str, str], others: list[PaymentOption]) -> str | None:
    country, price = _clean(data.get("country"), 1000), _clean(data.get("price"), 1000)
    if not country:
        return "El nombre del país no puede estar vacío."
    if len(country) > OPTION_LIMITS["country"]:
        return f"El nombre del país admite hasta {OPTION_LIMITS['country']} caracteres."
    if not price:
        return "El precio no puede estar vacío."
    if len(price) > OPTION_LIMITS["price"]:
        return f"El precio admite hasta {OPTION_LIMITS['price']} caracteres."
    if len(_clean(data.get("methods"), 1000)) > OPTION_LIMITS["methods"]:
        return f"Los métodos de pago admiten hasta {OPTION_LIMITS['methods']} caracteres."
    if len(_clean(data.get("stock"), 1000)) > OPTION_LIMITS["stock"]:
        return f"El stock del país admite hasta {OPTION_LIMITS['stock']} caracteres."
    if len(_clean(data.get("emoji"), 1000)) > OPTION_LIMITS["emoji"]:
        return "La bandera/emoji es demasiado larga."
    if any(normalize(o.country) == normalize(country) for o in others):
        return f"Ya existe un país llamado **{country}**."
    return None


def build_country(oid: str, data: dict[str, str], hidden: bool = False) -> PaymentOption:
    return PaymentOption(oid, _clean(data.get("emoji"), OPTION_LIMITS["emoji"]),
                         _clean(data.get("country"), OPTION_LIMITS["country"]),
                         _clean(data.get("price"), OPTION_LIMITS["price"]),
                         _clean(data.get("methods"), OPTION_LIMITS["methods"]),
                         _clean(data.get("stock"), OPTION_LIMITS["stock"]), hidden)


def move_country(options: list[PaymentOption], oid: str, direction: int) -> list[PaymentOption]:
    index = next((i for i, o in enumerate(options) if o.id == oid), -1)
    target = index + direction
    if index < 0 or not 0 <= target < len(options):
        return options
    result = list(options)
    result[index], result[target] = result[target], result[index]
    return result


def format_bulk(options: list[PaymentOption]) -> str:
    lines = []
    for o in options:
        line = " | ".join([o.emoji, o.country, o.price, o.methods, o.stock, "oculto" if o.hidden else ""])
        lines.append(re.sub(r"(\s\|\s)+$", "", line))
    return "\n".join([BULK_HEADER, *lines])


def parse_bulk(text: str, existing: list[PaymentOption]) -> tuple[list[PaymentOption], list[str]]:
    errors: list[str] = []
    options: list[PaymentOption] = []
    by_name = {normalize(o.country): o for o in existing}
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    for number, line in enumerate(lines, 1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            errors.append(f"Línea {number}: usa el formato `bandera | país | precio | métodos`.")
            continue
        parts += [""] * (6 - len(parts))
        emoji, country, price, methods, stock, flag = parts[:6]
        data = {"emoji": emoji, "country": country, "price": price, "methods": methods, "stock": stock}
        problem = validate_country(data, options)
        if problem:
            errors.append(f"Línea {number}: {problem.replace('**', '')}")
            continue
        previous = by_name.get(normalize(country))
        oid = previous.id if previous else unique_country_id(country, [o.id for o in existing] + [o.id for o in options])
        options.append(build_country(oid, data, flag.lower() == "oculto"))
    if len(options) > MAX_PAYMENT_OPTIONS:
        errors.append(f"Máximo {MAX_PAYMENT_OPTIONS} países (escribiste {len(options)}).")
    if not options and not errors:
        errors.append("Escribe al menos un país.")
    return options, errors


def describe_changes(before: list[PaymentOption], after: list[PaymentOption]) -> list[str]:
    changes: list[str] = []
    before_by_id = {o.id: o for o in before}
    after_ids = {o.id for o in after}
    for o in after:
        name = f"{o.emoji} {o.country}".strip()
        prev = before_by_id.get(o.id)
        if prev is None:
            changes.append(f"➕ {name}: {o.price}")
            continue
        if prev.country != o.country:
            changes.append(f"✏️ {prev.country} → {o.country}")
        if prev.price != o.price:
            changes.append(f"💲 {name}: {prev.price} → {o.price}")
        if prev.methods != o.methods:
            changes.append(f"💳 {name}: {prev.methods or '—'} → {o.methods or '—'}")
        if prev.stock != o.stock:
            changes.append(f"📦 {name}: {prev.stock or '—'} → {o.stock or '—'}")
        if prev.emoji != o.emoji:
            changes.append(f"🏳️ {o.country}: {prev.emoji or '—'} → {o.emoji or '—'}")
        if prev.hidden != o.hidden:
            changes.append(f"{'🙈 Oculto' if o.hidden else '👁️ Visible'}: {name}")
    changes.extend(f"🗑️ {f'{o.emoji} {o.country}'.strip()}" for o in before if o.id not in after_ids)
    if [o.id for o in before if o.id in after_ids] != [o.id for o in after if o.id in before_by_id]:
        changes.append("↕️ Orden de países actualizado")
    return changes


# ─── Categories ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Category:
    id: str
    label: str
    emoji: str = "🛍️"
    style: str = "Primary"
    description: str = ""
    image: str | None = None
    images: list[str] = field(default_factory=list)
    effect: str = "normal"
    effect_images: list[str] = field(default_factory=list)
    image_interval: int = 3600
    playback_mode: str = "interval"
    playlist_image: str | None = None
    payment_options: list[PaymentOption] = field(default_factory=list)
    stock_amount: int | None = None
    stock_unit: str = ""
    availability_text: str = ""
    footer_text: str = ""
    channel_id: str | None = None
    message_id: str | None = None
    standalone: bool = False
    announcement_last_sent_at: str | None = None
    action_buttons: list[dict[str, Any]] | None = None

    @property
    def stock_text(self) -> str | None:
        if self.stock_amount is None:
            return None
        return f"{max(0, self.stock_amount)} {self.stock_unit or 'unidades disponibles'}"

    @property
    def display_images(self) -> list[str]:
        if self.playback_mode == "sequence" and self.playlist_image:
            return [self.playlist_image]
        if self.effect_images and len(self.effect_images) == len(self.images):
            return self.effect_images
        return self.images


def _defaults() -> list[Category]:
    return [
        Category("dealer", "Dealer", "🔫", "Danger", "Armas, cargadores y equipo disponible.", playback_mode="sequence"),
        Category("ropa", "Ropa", "👕", "Primary", "Prendas y conjuntos disponibles.", playback_mode="sequence"),
        Category("accesorios", "Accesorios", "💎", "Secondary", "Accesorios y artículos especiales.",
                 playback_mode="sequence"),
    ]


def _urls(value: Any, limit: int = 20) -> list[str]:
    result: list[str] = []
    for raw in value if isinstance(value, list) else []:
        url = str(raw or "").strip()
        if _URL_RE.match(url) and url not in result:
            result.append(url)
        if len(result) >= limit:
            break
    return result


def _actions(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    actions = []
    for item in value[:5]:
        item = item if isinstance(item, dict) else {}
        aid = re.sub(r"[^a-zA-Z0-9_-]", "_", str(item.get("id") or ""))[:80]
        if not aid or aid in seen:
            continue
        seen.add(aid)
        actions.append({"id": aid, "label": safe_label(item.get("label"), "Abrir ticket"),
                        "emoji": str(item.get("emoji") or "").strip()[:100] or None,
                        "style": item.get("style") if item.get("style") in STYLES else "Primary"})
    return actions


def _stock(item: dict[str, Any]) -> tuple[int | None, str]:
    amount = item.get("stockAmount")
    if amount not in (None, ""):
        try:
            number = int(amount)
        except (TypeError, ValueError):
            number = -1
        if 0 <= number <= 1_000_000:
            return number, str(item.get("stockUnit") or "unidades disponibles").strip()[:80] or "unidades disponibles"
    # Legacy free text such as "450 millones disponibles" becomes editable inventory.
    match = re.match(r"^([0-9][0-9.,]*)\s+(.+)$", str(item.get("availabilityText") or "").strip())
    if match:
        number = int(re.sub(r"[.,]", "", match.group(1)))
        if 0 <= number <= 1_000_000:
            return number, match.group(2).strip()[:80] or "unidades disponibles"
    return None, str(item.get("stockUnit") or "").strip()[:80]


def categories(config: GuildConfig | None) -> list[Category]:
    raw = config.shop_categories if config is not None and isinstance(config.shop_categories, list) else []
    if not raw:
        return _defaults()
    seen: set[str] = set()
    result: list[Category] = []
    for item in raw[:MAX_CATEGORIES]:
        item = item if isinstance(item, dict) else {}
        fallback = f"section{len(result) + 1}"
        cid = re.sub(r"[^a-z0-9_-]", "", str(item.get("id") or fallback).lower())[:40] or fallback
        if cid in seen:
            continue
        seen.add(cid)
        image = str(item.get("image") or "").strip()
        image = image if _URL_RE.match(image) else None
        images = _urls(item.get("images"))
        if not images and image:
            images.append(image)
        playlist = str(item.get("playlistImage") or "").strip()
        try:
            interval = min(2_592_000, max(60, round(float(item.get("imageInterval")))))
        except (TypeError, ValueError):
            interval = 3600
        amount, unit = _stock(item)
        sent = item.get("announcementLastSentAt")
        try:
            sent = datetime.fromisoformat(str(sent).replace("Z", "+00:00")).isoformat() if sent else None
        except ValueError:
            sent = None
        result.append(Category(
            id=cid, label=safe_label(item.get("label"), f"Sección {len(result) + 1}")[:50],
            emoji=str(item.get("emoji") or "🛍️").strip()[:100] or "🛍️",
            style=item.get("style") if item.get("style") in STYLES else "Primary",
            description=str(item.get("description") or "").strip()[:500], image=images[0] if images else image,
            images=images, effect=item.get("effect") if item.get("effect") in ("dark", "saturated", "soft", "mono")
            else "normal", effect_images=_urls(item.get("effectImages")), image_interval=interval,
            playback_mode="sequence" if item.get("playbackMode") == "sequence" else "interval",
            playlist_image=playlist if _URL_RE.match(playlist) else None,
            payment_options=normalize_payment_options(item.get("paymentOptions")), stock_amount=amount,
            stock_unit=unit, availability_text=str(item.get("availabilityText") or "").strip()[:100],
            footer_text=str(item.get("footerText") or "").strip()[:1000],
            channel_id=str(item["channelId"]) if _SNOWFLAKE_RE.match(str(item.get("channelId") or "")) else None,
            message_id=str(item["messageId"]) if _SNOWFLAKE_RE.match(str(item.get("messageId") or "")) else None,
            standalone=bool(item.get("standalone")), announcement_last_sent_at=sent,
            action_buttons=_actions(item.get("actionButtons")),
        ))
    return result or _defaults()


def primary_category(config: GuildConfig) -> Category | None:
    cats = categories(config)
    return (next((c for c in cats if c.id == "dealer"), None) or next((c for c in cats if not c.standalone), None)
            or (cats[0] if cats else None))


def in_category(products: list[ShopProduct], category: Category) -> list[ShopProduct]:
    key = normalize(category.label)
    return [p for p in products if normalize(p.category) == key]


def primary_products(config: GuildConfig, products: list[ShopProduct]) -> list[ShopProduct]:
    primary = primary_category(config)
    return in_category(products, primary) if primary else products


def primary_images(config: GuildConfig) -> list[str]:
    primary = primary_category(config)
    images = primary.display_images if primary else []
    return images or [i for i in (config.shop_images or []) if i]


# ─── Message builders ────────────────────────────────────────────────────────


def price_text(product: ShopProduct) -> str:
    return (product.price_label or "").strip() or f"${float(product.price or 0):.2f}"


def stock_text(product: ShopProduct) -> str:
    custom = (product.stock_label or "").strip()
    if custom:
        return custom
    return f"{product.stock} disponible{'' if product.stock == 1 else 's'}" if product.stock > 0 else "Agotado"


def parse_emoji(value: str | None) -> discord.PartialEmoji | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    if re.match(r"^<a?:[^:>]+:\d+>$", value):
        return discord.PartialEmoji.from_str(value)
    return discord.PartialEmoji(name=value[:100])


def _button(style: str, label: str, custom_id: str, emoji: str | None, disabled: bool = False) -> discord.ui.Button[Any]:
    return discord.ui.Button(style=STYLES.get(style, discord.ButtonStyle.primary), label=safe_label(label, "Comprar"),
                             custom_id=custom_id[:100], emoji=parse_emoji(emoji), disabled=disabled)


def _view(buttons: list[discord.ui.Button[Any]]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for index, button in enumerate(buttons[:MAX_BUTTONS]):
        button.row = index // 5
        view.add_item(button)
    return view


def custom_button_id(button: dict[str, Any]) -> str:
    return "shop_custom_" + re.sub(r"[^a-zA-Z0-9_-]", "_", str(button.get("id") or button.get("label") or "button"))


@dataclass(slots=True)
class Payload:
    embed: discord.Embed
    buttons: list[discord.ui.Button[Any]]
    content: str | None = None

    def kwargs(self) -> dict[str, Any]:
        result: dict[str, Any] = {"embed": self.embed, "view": _view(self.buttons)}
        if self.content:
            result["content"] = self.content[:2000]
            result["allowed_mentions"] = discord.AllowedMentions(everyone=True)
        return result


def shop_message(config: GuildConfig, products: list[ShopProduct], image_index: int = 0,
                 content: str | None = None) -> Payload:
    description = config.shop_description or "Bienvenido a nuestra tienda. ¡Elige un producto y abre un ticket de compra!"
    embed = discord.Embed(title=safe_label(config.shop_title, "🛍️ Tienda Oficial"),
                          color=parse_color(config.shop_color, INFO))
    primary = primary_category(config)
    images = primary.display_images if primary and primary.display_images else list(config.shop_images or [])
    image = images[image_index % len(images)] if images else config.shop_image
    if image:
        embed.set_image(url=image)
    if config.shop_thumbnail:
        embed.set_thumbnail(url=config.shop_thumbnail)
    active = [p for p in products if p.active]
    if active:
        description += "\n\n" + "\n\n".join("\n".join(filter(None, [
            f"**{safe_label(p.name, 'Producto')}**", (p.description or "").strip()[:500],
            f"Precio: {price_text(p)} · Stock: {stock_text(p)}"])) for p in active[:25])
    if primary and primary.footer_text.strip():
        description += f"\n\n{primary.footer_text.strip()}"
    embed.description = description[:4096]

    label = safe_label(config.shop_buy_button_label, "Comprar")
    style = config.shop_buy_button_style or "Primary"
    emoji = config.shop_buy_button_emoji or "🛒"
    buttons: list[discord.ui.Button[Any]] = []
    if config.shop_button_style == "single":
        buttons.append(_button(style, label, "shop_buy_menu", emoji))
    else:
        buttons.extend(_button(style, f"{label} · {p.name}", f"shop_buy_{p.id}", emoji, p.stock <= 0)
                       for p in active[:MAX_BUTTONS])
    customs = [b for b in (config.shop_custom_buttons or []) if isinstance(b, dict) and b.get("categoryOnly") is not True]
    for button in customs[:max(0, MAX_BUTTONS - len(buttons))]:
        buttons.append(_button(button.get("style") or "Primary", str(button.get("label") or ""),
                               custom_button_id(button), button.get("emoji")))
    return Payload(embed, buttons, content.strip() if content and content.strip() else None)


def category_preview(config: GuildConfig, products: list[ShopProduct]) -> Payload:
    cats = categories(config)
    active = [p for p in products if p.active]
    embed = discord.Embed(
        title=f"🛍️ {safe_label(config.shop_title, 'Tienda Oficial')}", color=parse_color(config.shop_color, INFO),
        description="**Bienvenido a la tienda de HubStore.** Tenemos varias categorías y stock actualizado para que "
                    "encuentres lo que necesitas.\n\nSelecciona la tienda que te interesa para explorar productos, "
                    "precios, disponibilidad y abrir tu ticket de compra.")
    for category in cats:
        count = len(in_category(active, category))
        copy = category.description or ("Stock disponible para compra." if count else "Próximamente")
        available = f"{count} producto{'' if count == 1 else 's'} disponible{'' if count == 1 else 's'}" if count \
            else "Próximamente"
        embed.add_field(name=f"{category.emoji} {category.label}", value=f"{copy}\n{available}", inline=True)
    overview = config.shop_image or (config.shop_images[0] if config.shop_images else None)
    if overview:
        embed.set_image(url=overview)
    if config.shop_thumbnail:
        embed.set_thumbnail(url=config.shop_thumbnail)
    return Payload(embed, [_button(c.style, c.label, f"shop_category_{c.id}", c.emoji) for c in cats])


def category_panel(config: GuildConfig, products: list[ShopProduct], category: Category, image_index: int = 0) -> Payload:
    actions = (category.action_buttons if category.action_buttons is not None else
               [b for b in (config.shop_custom_buttons or []) if isinstance(b, dict) and b.get("categoryOnly") is not True])
    has_purchase_action = any(re.search(r"(?:^|[_-])buy(?:$|[_-])|comprar|compra", f"{b.get('id')} {b.get('label')}",
                                        re.IGNORECASE) for b in actions)
    product_limit = 0 if has_purchase_action else max(0, MAX_BUTTONS - (0 if category.standalone else 1) - len(actions))
    style = config.shop_buy_button_style or "Primary"
    label = safe_label(config.shop_buy_button_label, "Comprar")
    emoji = config.shop_buy_button_emoji or "🛒"
    product_buttons = [_button(style, f"{label} · {p.name}", f"shop_buy_{p.id}", emoji, p.stock <= 0)
                       for p in [p for p in products if p.active][:product_limit]]

    lines = ["\n".join(filter(None, [f"**{safe_label(p.name, 'Producto')}**", (p.description or "").strip()[:180],
                                     f"Precio: {price_text(p)} · Stock: {stock_text(p)}"])) for p in products[:25]]
    visible = [o for o in category.payment_options if not o.hidden]
    payment = ""
    if visible:
        payment = "**Precios y métodos por país**\n\n" + "\n\n".join(
            f"**{f'{o.emoji} ' if o.emoji else ''}{o.country}**\n{o.price}{f' · {o.methods}' if o.methods else ''}"
            f"{f' · Stock: **{o.stock}**' if o.stock else ''}" for o in visible) + "\n\n"
    stock = category.stock_text or category.availability_text
    availability = f"# Stock\n## {stock}\n\n" if stock else ""
    details = "\n\n".join(lines) if lines else ("" if category.payment_options else
                                                "**Catálogo en preparación**\nPronto encontrarás aquí los productos disponibles.")
    footer = category.footer_text or DEFAULT_FOOTER
    title = (f"{category.label} · HubStore" if category.standalone
             else f"{category.label} · {safe_label(config.shop_title, 'HubStore')}")
    embed = discord.Embed(title=title, color=parse_color(config.shop_color, INFO), description=(
        f"**{category.description or f'Catálogo de {category.label}'}**\n\n{availability}{payment}{details}"
        f"{chr(10) * 2 if details else ''}{footer}")[:4096])
    images = category.display_images
    image = images[image_index % len(images)] if images else category.image
    if image:
        embed.set_image(url=image)
    elif category.id == "dealer" and config.shop_image:
        embed.set_image(url=config.shop_image)
    if config.shop_thumbnail:
        embed.set_thumbnail(url=config.shop_thumbnail)

    buttons: list[discord.ui.Button[Any]] = []
    if not category.standalone:
        buttons.append(_button("Secondary", "Ver categorías", "shop_category_home", "↩️"))
    buttons.extend(product_buttons)
    buttons.extend(_button(b.get("style") or "Primary", str(b.get("label") or ""), custom_button_id(b), b.get("emoji"))
                   for b in actions)
    return Payload(embed, buttons)


def announcement_content(message: str) -> str:
    text = message.strip()
    return text if "@everyone" in text else f"@everyone {text}"


# ─── Publishing ──────────────────────────────────────────────────────────────


class ShopPublisher:
    """Edits / reposts published shop messages from the current database state."""

    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    async def load(self, guild_id: str) -> tuple[GuildConfig | None, list[ShopProduct]]:
        async with self.bot.db.session() as session:
            config = await session.get(GuildConfig, guild_id)
            products = list((await session.execute(select(ShopProduct).where(
                ShopProduct.guild_id == guild_id, ShopProduct.active.is_(True)
            ).order_by(ShopProduct.created_at.desc()))).scalars().all())
        return config, products

    async def _messageable(self, channel_id: str) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(int(channel_id))
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def _edit(self, channel_id: str, message_id: str, payload: Payload) -> bool:
        channel = await self._messageable(channel_id)
        if channel is None:
            return False
        message = channel.get_partial_message(int(message_id))  # type: ignore[attr-defined]
        await message.edit(**payload.kwargs())
        return True

    async def refresh(self, guild_id: str, image_index: int | None = None,
                      category_indexes: dict[str, int] | None = None, *, only_due: bool = False) -> None:
        """Re-render the main shop message and every published category panel."""
        config, products = await self.load(guild_id)
        if config is None:
            return
        indexes = category_indexes or {}
        if config.shop_channel_id and config.shop_message_id and (not only_due or image_index is not None):
            try:
                await self._edit(config.shop_channel_id, config.shop_message_id,
                                 shop_message(config, primary_products(config, products), image_index or 0))
            except discord.NotFound:
                async with self.bot.db.session() as session:
                    await session.execute(update(GuildConfig).where(GuildConfig.id == guild_id).values(shop_message_id=None))
                self.bot.configs.invalidate(guild_id)
            except discord.HTTPException as exc:
                log.error("Failed to refresh shop message in %s: %s", guild_id, exc)
        for category in categories(config):
            if not category.channel_id or not category.message_id or (only_due and category.id not in indexes):
                continue
            try:
                await self._edit(category.channel_id, category.message_id,
                                 category_panel(config, in_category(products, category), category, indexes.get(category.id, 0)))
            except discord.HTTPException as exc:
                log.error("Failed to refresh %s shop message: %s", category.label, exc)

    async def publish(self, guild_id: str, channel_id: str) -> str:
        """Publish (or move) the main shop message. Returns the message ID."""
        config, products = await self.load(guild_id)
        if config is None:
            raise LookupError("No se encontró la configuración del servidor")
        if not products:
            raise ValueError("No hay productos activos para publicar")
        payload = shop_message(config, primary_products(config, products))
        channel = await self._messageable(channel_id)
        if channel is None:
            raise LookupError("Canal no encontrado")
        if config.shop_channel_id == channel_id and config.shop_message_id:
            try:
                await self._edit(channel_id, config.shop_message_id, payload)
                return config.shop_message_id
            except discord.HTTPException:
                pass
        if config.shop_channel_id and config.shop_message_id:
            old = await self._messageable(config.shop_channel_id)
            if old is not None:
                try:
                    await old.get_partial_message(int(config.shop_message_id)).delete()  # type: ignore[attr-defined]
                except discord.HTTPException:
                    pass
        message = await channel.send(**payload.kwargs())
        await self.bot.configs.update(guild_id, shop_channel_id=channel_id, shop_message_id=str(message.id))
        return str(message.id)

    async def repost_main(self, guild_id: str, content: str | None = None) -> str | None:
        """Repost the main shop at the bottom of its channel (sticky shop / announcements)."""
        config, products = await self.load(guild_id)
        if config is None or not config.shop_channel_id:
            return None
        channel = await self._messageable(config.shop_channel_id)
        if channel is None:
            return None
        try:
            message = await channel.send(**shop_message(config, primary_products(config, products), content=content).kwargs())
        except discord.HTTPException as exc:
            log.error("Failed to repost sticky shop message: %s", exc)
            return None
        previous = config.shop_message_id
        await self.bot.configs.update(guild_id, shop_message_id=str(message.id))
        if previous and previous != str(message.id):
            try:
                await channel.get_partial_message(int(previous)).delete()  # type: ignore[attr-defined]
            except discord.HTTPException:
                pass
        log.info("Reposted shop message in %s", config.shop_channel_id)
        return str(message.id)

    async def repost_category(self, guild_id: str, category_id: str, content: str | None = None) -> str | None:
        config, products = await self.load(guild_id)
        if config is None:
            return None
        category = next((c for c in categories(config) if c.id == category_id), None)
        if category is None or not category.channel_id:
            return None
        channel = await self._messageable(category.channel_id)
        if channel is None:
            return None
        payload = category_panel(config, in_category(products, category), category)
        payload.content = content.strip()[:2000] if content and content.strip() else None
        try:
            message = await channel.send(**payload.kwargs())
        except discord.HTTPException as exc:
            log.error("Failed to repost %s: %s", category.label, exc)
            return None
        await self.patch_category(guild_id, category.id, messageId=str(message.id))
        if category.message_id and category.message_id != str(message.id):
            try:
                await channel.get_partial_message(int(category.message_id)).delete()  # type: ignore[attr-defined]
            except discord.HTTPException:
                pass
        return str(message.id)

    async def publish_category(self, guild_id: str, category_id: str, channel_id: str) -> str:
        """Publish a category panel to a channel (replacing its previous message)."""
        config, products = await self.load(guild_id)
        category = next((c for c in categories(config) if c.id == category_id), None) if config else None
        if config is None or category is None:
            raise LookupError("Esa tienda ya no está configurada.")
        channel = await self._messageable(channel_id)
        if channel is None:
            raise LookupError("Canal no encontrado")
        payload = category_panel(config, in_category(products, category), category)
        if category.channel_id == channel_id and category.message_id:
            try:
                await self._edit(channel_id, category.message_id, payload)
                return category.message_id
            except discord.HTTPException:
                pass
        message = await channel.send(**payload.kwargs())
        await self.patch_category(guild_id, category_id, channelId=channel_id, messageId=str(message.id))
        return str(message.id)

    async def patch_category(self, guild_id: str, category_id: str, **values: Any) -> None:
        """Update keys of one category inside the ``shopCategories`` JSON."""
        async with self.bot.db.session() as session:
            config = await session.get(GuildConfig, guild_id, with_for_update=True)
            if config is None:
                return
            raw = [dict(c) if isinstance(c, dict) else c for c in (config.shop_categories or [])]
            for item in raw:
                if isinstance(item, dict) and str(item.get("id")) == category_id:
                    item.update(values)
            await session.execute(update(GuildConfig).where(GuildConfig.id == guild_id).values(shop_categories=raw))
        self.bot.configs.invalidate(guild_id)
