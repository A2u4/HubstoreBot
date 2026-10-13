"""ORM models mirroring ``prisma/schema.prisma``.

Keep this file in sync with the Prisma schema: Prisma owns migrations, this
module only describes the tables so the bot can query them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from markets_bot.db.base import Base, new_id, utcnow

GUILD_FK = "guild_configs.id"


def _pk() -> Mapped[str]:
    return mapped_column(String, primary_key=True, default=new_id)


def _guild_fk() -> Mapped[str]:
    return mapped_column(String, ForeignKey(GUILD_FK, ondelete="CASCADE"), index=False)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime, default=utcnow)


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime, default=utcnow, onupdate=utcnow)


def _str_list() -> Mapped[list[str]]:
    return mapped_column(ARRAY(String), default=list)


# ─── Guild configuration ─────────────────────────────────────────────────────


class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Discord guild ID
    prefix: Mapped[str] = mapped_column(String, default="!")
    language: Mapped[str] = mapped_column(String, default="en")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    # Module toggles
    invites_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    moderation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    automod_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tickets_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    farewell_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reputation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    giveaway_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rifa_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rifa_category_id: Mapped[str | None] = mapped_column(String, default="1489245171953434805")
    rifa_panel_channel_id: Mapped[str | None] = mapped_column(String)
    rifa_panel_message_id: Mapped[str | None] = mapped_column(String)
    rifa_log_channel_id: Mapped[str | None] = mapped_column(String)
    rifa_staff_role_ids: Mapped[list[str]] = _str_list()
    suggestions_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    starboard_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    afk_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    backup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sticky_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    logging_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # {"moderation": ["roleId", ...], ...}
    module_allowed_roles: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Welcome / farewell
    welcome_channel_id: Mapped[str | None] = mapped_column(String)
    welcome_message: Mapped[str | None] = mapped_column(String, default="Bienvenido {user} !")
    welcome_image_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_embed_title: Mapped[str | None] = mapped_column(String, default="¡Bienvenido!")
    welcome_embed_color: Mapped[str | None] = mapped_column(String)
    welcome_embed_footer: Mapped[str | None] = mapped_column(String)
    welcome_embed_description: Mapped[str | None] = mapped_column(String)
    welcome_embed_image: Mapped[str | None] = mapped_column(String)
    welcome_embed_thumbnail: Mapped[str | None] = mapped_column(String)
    welcome_image_bg_color: Mapped[str | None] = mapped_column(String, default="#0d1117")
    welcome_image_accent1: Mapped[str | None] = mapped_column(String, default="#dc3250")
    welcome_image_accent2: Mapped[str | None] = mapped_column(String, default="#3282dc")
    welcome_image_pill_text: Mapped[str | None] = mapped_column(String, default="BIENVENID@")
    welcome_image_brand: Mapped[str | None] = mapped_column(String, default="")
    welcome_image_subtitle: Mapped[str | None] = mapped_column(String, default="a {server}")
    welcome_image_member_label: Mapped[str | None] = mapped_column(String, default="Miembro #{memberCount}")
    welcome_image_font: Mapped[str | None] = mapped_column(String, default="Arial")
    welcome_image_font_weight: Mapped[int | None] = mapped_column(Integer, default=700)
    welcome_card_layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    farewell_channel_id: Mapped[str | None] = mapped_column(String)
    farewell_message: Mapped[str | None] = mapped_column(String, default="Goodbye {user}, we'll miss you!")
    farewell_image_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    farewell_card_layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    farewell_embed_title: Mapped[str | None] = mapped_column(String, default="¡Adiós!")
    farewell_embed_color: Mapped[str | None] = mapped_column(String)
    farewell_embed_footer: Mapped[str | None] = mapped_column(String)
    farewell_embed_description: Mapped[str | None] = mapped_column(String)
    farewell_embed_image: Mapped[str | None] = mapped_column(String)
    farewell_embed_thumbnail: Mapped[str | None] = mapped_column(String)

    # Moderation / logging channels
    mod_log_channel_id: Mapped[str | None] = mapped_column(String)
    warn_log_channel_id: Mapped[str | None] = mapped_column(String)
    message_log_channel_id: Mapped[str | None] = mapped_column(String)
    join_leave_log_channel_id: Mapped[str | None] = mapped_column(String)
    audit_log_channel_id: Mapped[str | None] = mapped_column(String)
    voice_log_channel_id: Mapped[str | None] = mapped_column(String)
    verification_log_channel_id: Mapped[str | None] = mapped_column(String)
    dar_rango_images_channel_id: Mapped[str | None] = mapped_column(String)
    dar_rango_roles: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    # Cross-bot sync
    ban_log_channel_id: Mapped[str | None] = mapped_column(String)
    ban_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rep_sync_guild_ids: Mapped[list[str]] = _str_list()

    stats_channels: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    mute_role_id: Mapped[str | None] = mapped_column(String)

    # Tickets (guild-wide defaults)
    ticket_category_id: Mapped[str | None] = mapped_column(String)
    ticket_log_channel_id: Mapped[str | None] = mapped_column(String)
    ticket_staff_role_ids: Mapped[list[str]] = _str_list()
    ticket_counter: Mapped[int] = mapped_column(Integer, default=0)
    ticket_transcript_channel_id: Mapped[str | None] = mapped_column(String)
    ticket_close_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    ticket_dm_transcript: Mapped[bool] = mapped_column("ticketDMTranscript", Boolean, default=True)

    join_role_ids: Mapped[list[str]] = _str_list()

    # AutoMod
    anti_spam_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_spam_threshold: Mapped[int] = mapped_column(Integer, default=5)
    anti_spam_interval: Mapped[int] = mapped_column(Integer, default=5)
    anti_flood_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_caps_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_caps_threshold: Mapped[int] = mapped_column(Integer, default=70)
    anti_links_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_links_whitelist: Mapped[list[str]] = _str_list()
    blacklist_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklisted_words: Mapped[list[str]] = _str_list()
    anti_caps_min_length: Mapped[int] = mapped_column(Integer, default=10)
    automod_exempt_role_ids: Mapped[list[str]] = _str_list()
    automod_exempt_channel_ids: Mapped[list[str]] = _str_list()

    # Reputation
    rep_cooldown: Mapped[int] = mapped_column(Integer, default=86400)  # unused, kept for compat
    rep_channel_id: Mapped[str | None] = mapped_column(String)

    # Starboard
    starboard_channel_id: Mapped[str | None] = mapped_column(String)
    starboard_emoji: Mapped[str] = mapped_column(String, default="⭐")
    starboard_threshold: Mapped[int] = mapped_column(Integer, default=3)

    # Suggestions
    suggestions_channel_id: Mapped[str | None] = mapped_column(String)
    suggestions_log_channel_id: Mapped[str | None] = mapped_column(String)

    # Shop
    shop_channel_id: Mapped[str | None] = mapped_column(String)
    shop_message_id: Mapped[str | None] = mapped_column(String)
    shop_title: Mapped[str | None] = mapped_column(String, default="🛍️ Tienda Oficial")
    shop_description: Mapped[str | None] = mapped_column(
        String,
        default="Bienvenido a nuestra tienda. ¡Elige un producto y haz clic en Comprar para abrir un ticket!",
    )
    shop_color: Mapped[str | None] = mapped_column(String, default="#5865F2")
    shop_image: Mapped[str | None] = mapped_column(String)
    shop_images: Mapped[list[str]] = _str_list()
    shop_image_interval: Mapped[int] = mapped_column(Integer, default=10)
    shop_thumbnail: Mapped[str | None] = mapped_column(String)
    shop_button_style: Mapped[str | None] = mapped_column(String, default="multiple")
    shop_custom_buttons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    shop_categories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    shop_buy_button_label: Mapped[str | None] = mapped_column(String, default="Comprar")
    shop_buy_button_emoji: Mapped[str | None] = mapped_column(String, default="🛒")
    shop_buy_button_style: Mapped[str | None] = mapped_column(String, default="Primary")
    shop_panel_id: Mapped[str | None] = mapped_column(String)
    shop_sticky_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    shop_sticky_cooldown: Mapped[int] = mapped_column(Integer, default=10)
    shop_announcement_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    shop_announcement_channel_id: Mapped[str | None] = mapped_column(String)
    shop_announcement_interval: Mapped[int] = mapped_column(Integer, default=3600)
    shop_announcement_message: Mapped[str | None] = mapped_column(String)
    shop_announcement_last_sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Market verification (only keyed HMAC identifiers are stored, never IPs)
    market_verification_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    market_verification_role_id: Mapped[str | None] = mapped_column(String)
    market_verification_log_channel_id: Mapped[str | None] = mapped_column(String)
    market_verification_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    market_vpn_check_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    market_vpn_policy: Mapped[str] = mapped_column(String, default="review")
    market_blocked_network_action: Mapped[str] = mapped_column(String, default="deny")

    # Leveling (v2)
    leveling_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    level_up_channel_id: Mapped[str | None] = mapped_column(String)
    level_up_message: Mapped[str] = mapped_column(String, default="🎉 {user} subió a **nivel {level}**")
    xp_per_message_min: Mapped[int] = mapped_column(Integer, default=15)
    xp_per_message_max: Mapped[int] = mapped_column(Integer, default=25)
    xp_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    leveling_ignored_channel_ids: Mapped[list[str]] = _str_list()
    leveling_ignored_role_ids: Mapped[list[str]] = _str_list()
    level_rewards_stack: Mapped[bool] = mapped_column(Boolean, default=True)

    # Economy (v2)
    economy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    currency_name: Mapped[str] = mapped_column(String, default="monedas")
    currency_symbol: Mapped[str] = mapped_column(String, default="🪙")
    economy_start_balance: Mapped[int] = mapped_column(Integer, default=0)
    daily_amount: Mapped[int] = mapped_column(Integer, default=250)
    weekly_amount: Mapped[int] = mapped_column(Integer, default=1500)
    work_min: Mapped[int] = mapped_column(Integer, default=50)
    work_max: Mapped[int] = mapped_column(Integer, default=300)
    work_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    crime_min: Mapped[int] = mapped_column(Integer, default=100)
    crime_max: Mapped[int] = mapped_column(Integer, default=700)
    crime_success_rate: Mapped[int] = mapped_column(Integer, default=45)
    crime_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=7200)
    rob_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rob_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=14400)

    # Fun / roleplay (v2)
    fun_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Captcha verification (v2)
    verification_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_mode: Mapped[str] = mapped_column(String, default="button")
    verification_channel_id: Mapped[str | None] = mapped_column(String)
    verification_role_id: Mapped[str | None] = mapped_column(String)
    verification_remove_role_id: Mapped[str | None] = mapped_column(String)
    verification_panel_title: Mapped[str] = mapped_column(String, default="Verificación")
    verification_panel_message: Mapped[str] = mapped_column(
        String, default="Pulsa el botón para verificarte y acceder al servidor."
    )
    verification_panel_msg_id: Mapped[str | None] = mapped_column(String)

    # Temporary voice channels (v2)
    temp_voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_voice_hub_channel_id: Mapped[str | None] = mapped_column(String)
    temp_voice_category_id: Mapped[str | None] = mapped_column(String)
    temp_voice_name_template: Mapped[str] = mapped_column(String, default="🔊 {user}")
    temp_voice_user_limit: Mapped[int] = mapped_column(Integer, default=0)

    bot_join_role_ids: Mapped[list[str]] = _str_list()


# ─── Invites / backups ───────────────────────────────────────────────────────


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    inviter_id: Mapped[str] = mapped_column(String)
    invited_id: Mapped[str] = mapped_column(String)
    code: Mapped[str] = mapped_column(String)
    fake: Mapped[bool] = mapped_column(Boolean, default=False)
    left: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Backup(Base):
    __tablename__ = "backups"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    creator_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


# ─── Moderation ──────────────────────────────────────────────────────────────


class Warning(Base):
    __tablename__ = "warnings"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    moderator_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, default="No reason provided")
    synced_from_guild_id: Mapped[str | None] = mapped_column(String)
    synced_from_bot: Mapped[str | None] = mapped_column(String)
    synced_from_guild_name: Mapped[str | None] = mapped_column(String)
    source_warning_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()


class ModAction(Base):
    __tablename__ = "mod_actions"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    moderator_id: Mapped[str] = mapped_column(String)
    # warn, mute, kick, ban, tempmute, tempban, unmute, unban, timeout...
    action: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, default="No reason provided")
    duration: Mapped[int | None] = mapped_column(Integer)  # seconds
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_from_guild_id: Mapped[str | None] = mapped_column(String)
    synced_from_bot: Mapped[str | None] = mapped_column(String)
    synced_from_guild_name: Mapped[str | None] = mapped_column(String)
    source_action_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()


class PendingAdminAction(Base):
    """Durable confirmation state for destructive admin flows (survives restarts)."""

    __tablename__ = "pending_admin_actions"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = mapped_column(String)
    moderator_id: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    # pending, running, completed, cancelled, replaced, expired, failed
    status: Mapped[str] = mapped_column(String, default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ReactionRole(Base):
    __tablename__ = "reaction_roles"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String)
    message_id: Mapped[str] = mapped_column(String)
    emoji: Mapped[str] = mapped_column(String)
    role_id: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="toggle")  # toggle, give, remove


# ─── Automation ──────────────────────────────────────────────────────────────


class AutoResponse(Base):
    __tablename__ = "auto_responses"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    trigger: Mapped[str] = mapped_column(String)
    response: Mapped[str] = mapped_column(String)
    match_type: Mapped[str] = mapped_column(String, default="contains")  # exact, contains, startsWith, regex
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class ScheduledMessage(Base):
    __tablename__ = "scheduled_messages"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    cron: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class CustomTextCommand(Base):
    __tablename__ = "custom_text_commands"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    name: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    embed_color: Mapped[str] = mapped_column(String, default="#ffffff")
    title: Mapped[str | None] = mapped_column(String)
    thumbnail_url: Mapped[str | None] = mapped_column(String)
    show_author: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class RankMoneyEntry(Base):
    __tablename__ = "rank_money_entries"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    rank_type: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer)
    adrian_share: Mapped[int] = mapped_column(Integer)
    keng_share: Mapped[int] = mapped_column(Integer)
    buyer_id: Mapped[str | None] = mapped_column(String)
    recorded_by_id: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_by_id: Mapped[str | None] = mapped_column(String)
    withdrawal_note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String)
    message_id: Mapped[str | None] = mapped_column(String)
    question: Mapped[str] = mapped_column(String)
    options: Mapped[list[str]] = _str_list()
    votes: Mapped[dict[str, list[str]]] = mapped_column(JSONB, default=dict)  # {"0": [userId]}
    creator_id: Mapped[str] = mapped_column(String)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    allowed_role_ids: Mapped[list[str]] = _str_list()
    ended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


# ─── Tickets ─────────────────────────────────────────────────────────────────


class TicketPanel(Base):
    __tablename__ = "ticket_panels"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    name: Mapped[str] = mapped_column(String, default="Default")

    channel_id: Mapped[str] = mapped_column(String)
    message_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, default="Support Tickets")
    description: Mapped[str] = mapped_column(String, default="Click the button below to create a ticket.")
    embed_color: Mapped[str] = mapped_column(String, default="#5865F2")
    footer_text: Mapped[str | None] = mapped_column(String)
    embed_images: Mapped[list[str]] = _str_list()
    embed_image_interval: Mapped[int] = mapped_column(Integer, default=10)
    group_embed_title: Mapped[str | None] = mapped_column(String)
    group_embed_description: Mapped[str | None] = mapped_column(String)
    group_embed_color: Mapped[str | None] = mapped_column(String)
    group_embed_images: Mapped[list[str]] = _str_list()

    button_label: Mapped[str] = mapped_column(String, default="Create Ticket")
    button_emoji: Mapped[str | None] = mapped_column(String, default="🎫")
    button_color: Mapped[str] = mapped_column(String, default="Primary")
    style: Mapped[str] = mapped_column(String, default="button")  # button, dropdown, command

    category_id: Mapped[str | None] = mapped_column(String)
    closed_category_id: Mapped[str | None] = mapped_column(String)
    naming_pattern: Mapped[str] = mapped_column(String, default="ticket-{number}")

    staff_role_ids: Mapped[list[str]] = _str_list()
    admin_role_ids: Mapped[list[str]] = _str_list()

    ticket_limit: Mapped[int] = mapped_column(Integer, default=1)
    mention_staff: Mapped[bool] = mapped_column(Boolean, default=True)
    mention_creator: Mapped[bool] = mapped_column(Boolean, default=True)

    welcome_title: Mapped[str | None] = mapped_column(String, default="Ticket Opened")
    welcome_message: Mapped[str | None] = mapped_column(
        String, default="Welcome! Please describe your issue.\nA staff member will assist you shortly."
    )
    welcome_color: Mapped[str] = mapped_column(String, default="#5865F2")

    close_request_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    close_request_message: Mapped[str | None] = mapped_column(
        String, default="Are you sure you want to close this ticket?"
    )

    claim_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    claim_lock_others: Mapped[bool] = mapped_column(Boolean, default=False)

    transcript_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    transcript_channel_id: Mapped[str | None] = mapped_column(String)
    transcript_dm_user: Mapped[bool] = mapped_column("transcriptDMUser", Boolean, default=True)
    transcript_dm_staff: Mapped[bool] = mapped_column("transcriptDMStaff", Boolean, default=False)

    log_channel_id: Mapped[str | None] = mapped_column(String)

    show_close_button: Mapped[bool] = mapped_column(Boolean, default=True)
    show_claim_button: Mapped[bool] = mapped_column(Boolean, default=True)
    show_transcript_button: Mapped[bool] = mapped_column(Boolean, default=True)

    form_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    form_title: Mapped[str | None] = mapped_column(String, default="Ticket Form")
    form_questions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    escalate_panel_id: Mapped[str | None] = mapped_column(String)

    feedback_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback_message: Mapped[str | None] = mapped_column(
        String, default="How would you rate the support you received?"
    )

    panel_auto_repost: Mapped[bool] = mapped_column(Boolean, default=False)
    panel_auto_repost_cooldown: Mapped[int] = mapped_column(Integer, default=5)
    panel_auto_repost_ignore_bots: Mapped[bool] = mapped_column(Boolean, default=True)

    auto_close_hours: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    panel_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("ticket_panels.id", ondelete="SET NULL")
    )
    channel_id: Mapped[str] = mapped_column(String, unique=True)
    user_id: Mapped[str] = mapped_column(String)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="open")  # open, closed, deleted
    topic: Mapped[str | None] = mapped_column(String)
    claimed_by: Mapped[str | None] = mapped_column(String)
    closed_by: Mapped[str | None] = mapped_column(String)
    close_reason: Mapped[str | None] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String, default="normal")  # low, normal, high, urgent
    rating: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[str | None] = mapped_column(String)
    added_users: Mapped[list[str]] = _str_list()
    form_answers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    auto_close_disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_response: Mapped[datetime | None] = mapped_column(DateTime)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = _created()


class TicketTranscript(Base):
    __tablename__ = "ticket_transcripts"

    id: Mapped[str] = _pk()
    ticket_id: Mapped[str] = mapped_column(String, ForeignKey("tickets.id", ondelete="CASCADE"))
    panel_id: Mapped[str | None] = mapped_column(String, ForeignKey("ticket_panels.id"))
    guild_id: Mapped[str] = mapped_column(String)
    channel_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    closed_by: Mapped[str | None] = mapped_column(String)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    html_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


# ─── Community ───────────────────────────────────────────────────────────────


class Reputation(Base):
    """One row is one +1 rep (there is no points column)."""

    __tablename__ = "reputations"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)  # receiver
    giver_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()


class Giveaway(Base):
    __tablename__ = "giveaways"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String)
    message_id: Mapped[str | None] = mapped_column(String)
    host_id: Mapped[str] = mapped_column(String)
    prize: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    winners: Mapped[int] = mapped_column(Integer, default=1)
    entries: Mapped[list[str]] = _str_list()
    winner_ids: Mapped[list[str]] = _str_list()
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    ended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String)
    message_id: Mapped[str | None] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, approved, denied, implemented
    upvotes: Mapped[list[str]] = _str_list()
    downvotes: Mapped[list[str]] = _str_list()
    staff_note: Mapped[str | None] = mapped_column(String)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class StarboardEntry(Base):
    __tablename__ = "starboard_entries"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    original_msg_id: Mapped[str] = mapped_column(String)
    original_ch_id: Mapped[str] = mapped_column(String)
    starboard_msg_id: Mapped[str | None] = mapped_column(String)
    author_id: Mapped[str] = mapped_column(String)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str | None] = mapped_column(String)
    attachment_url: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _created()


class AfkStatus(Base):
    __tablename__ = "afk_statuses"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, default="AFK")
    created_at: Mapped[datetime] = _created()


class StickyMessage(Base):
    __tablename__ = "sticky_messages"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String, unique=True)
    message_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    color: Mapped[str] = mapped_column(String, default="#5865F2")
    plain_text: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_urls: Mapped[list[str]] = _str_list()
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    channel_id: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    remind_at: Mapped[datetime] = mapped_column(DateTime)
    fired: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class Rifa(Base):
    __tablename__ = "rifas"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String)
    message_id: Mapped[str | None] = mapped_column(String)
    host_id: Mapped[str] = mapped_column(String)
    prize: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    max_slots: Mapped[int] = mapped_column(Integer)
    participants: Mapped[list[str]] = _str_list()
    winner_ids: Mapped[list[str]] = _str_list()
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_draw_on_full: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_self_join: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class CommandPermission(Base):
    __tablename__ = "command_permissions"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    command: Mapped[str] = mapped_column(String)  # "cmd" or "cmd sub"
    role_ids: Mapped[list[str]] = _str_list()
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = _updated()


# ─── Shop & market security ──────────────────────────────────────────────────


class ShopProduct(Base):
    __tablename__ = "shop_products"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String(50), default="General")
    description: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    price_label: Mapped[str | None] = mapped_column(String(100))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    stock_label: Mapped[str | None] = mapped_column(String(100))
    image: Mapped[str | None] = mapped_column(String)
    images: Mapped[list[str]] = _str_list()
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class MarketVerificationSession(Base):
    __tablename__ = "market_verification_sessions"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class MarketRegistration(Base):
    __tablename__ = "market_registrations"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    accepted_privacy_at: Mapped[datetime] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class MarketNetworkSignal(Base):
    __tablename__ = "market_network_signals"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    registration_id: Mapped[str] = mapped_column(
        String, ForeignKey("market_registrations.id", ondelete="CASCADE")
    )
    ip_hash: Mapped[str] = mapped_column(String(64))
    ip_version: Mapped[int] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    vpn_detected: Mapped[bool | None] = mapped_column(Boolean)
    proxy_detected: Mapped[bool | None] = mapped_column(Boolean)
    tor_detected: Mapped[bool | None] = mapped_column(Boolean)
    relay_detected: Mapped[bool | None] = mapped_column(Boolean)
    hosting_detected: Mapped[bool | None] = mapped_column(Boolean)
    privacy_service: Mapped[str | None] = mapped_column(String(100))
    privacy_provider: Mapped[str | None] = mapped_column(String(30))
    privacy_checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class MarketNetworkBlock(Base):
    __tablename__ = "market_network_blocks"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    ip_hash: Mapped[str] = mapped_column(String(64))
    source_user_id: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# ─── v2: leveling ────────────────────────────────────────────────────────────


class MemberLevel(Base):
    __tablename__ = "member_levels"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    messages: Mapped[int] = mapped_column(Integer, default=0)
    last_xp_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class LevelReward(Base):
    __tablename__ = "level_rewards"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    level: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[str] = mapped_column(String)


# ─── v2: economy ─────────────────────────────────────────────────────────────


class EconomyAccount(Base):
    __tablename__ = "economy_accounts"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user_id: Mapped[str] = mapped_column(String)
    wallet: Mapped[int] = mapped_column(Integer, default=0)
    bank: Mapped[int] = mapped_column(Integer, default=0)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_daily: Mapped[datetime | None] = mapped_column(DateTime)
    last_weekly: Mapped[datetime | None] = mapped_column(DateTime)
    last_work: Mapped[datetime | None] = mapped_column(DateTime)
    last_crime: Mapped[datetime | None] = mapped_column(DateTime)
    last_rob: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class EconomyItem(Base):
    __tablename__ = "economy_items"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String, default="")
    emoji: Mapped[str | None] = mapped_column(String)
    price: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[str | None] = mapped_column(String)
    stock: Mapped[int | None] = mapped_column(Integer)  # None = unlimited
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class EconomyInventory(Base):
    __tablename__ = "economy_inventory"

    id: Mapped[str] = _pk()
    account_id: Mapped[str] = mapped_column(String, ForeignKey("economy_accounts.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(String, ForeignKey("economy_items.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    item: Mapped[EconomyItem] = relationship(lazy="joined")


# ─── v2: social ──────────────────────────────────────────────────────────────


class Marriage(Base):
    __tablename__ = "marriages"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    user1_id: Mapped[str] = mapped_column("user1Id", String)
    user2_id: Mapped[str] = mapped_column("user2Id", String)
    created_at: Mapped[datetime] = _created()


class RoleplayStat(Base):
    __tablename__ = "roleplay_stats"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    action: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String)
    count: Mapped[int] = mapped_column(Integer, default=0)


class TempVoiceChannel(Base):
    __tablename__ = "temp_voice_channels"

    id: Mapped[str] = _pk()
    guild_id: Mapped[str] = _guild_fk()
    channel_id: Mapped[str] = mapped_column(String, unique=True)
    owner_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = _created()
