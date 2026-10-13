"""HTML transcripts for ticket channels."""

from __future__ import annotations

import base64
import html
import re
from datetime import UTC, datetime
from typing import Any

import aiohttp
import discord

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_EMBEDDED_IMAGE_BYTES = 4 * 1024 * 1024  # aggregate budget per transcript
IMAGE_TYPE_RE = re.compile(r"^image/(png|jpe?g|gif|webp)$", re.IGNORECASE)
IMAGE_NAME_RE = re.compile(r"\.(png|jpe?g|gif|webp)$", re.IGNORECASE)


async def _data_uri(http: aiohttp.ClientSession, attachment: discord.Attachment) -> str | None:
    if attachment.size and attachment.size > MAX_IMAGE_BYTES:
        return None
    try:
        async with http.get(attachment.url) as resp:
            if resp.status != 200:
                return None
            content_type = (resp.headers.get("content-type") or attachment.content_type or "").split(";")[0].strip()
            if not IMAGE_TYPE_RE.match(content_type):
                return None
            data = await resp.content.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                return None
            return f"data:{content_type};base64,{base64.b64encode(data).decode()}"
    except (aiohttp.ClientError, TimeoutError):
        return None


async def fetch_messages(channel: discord.abc.Messageable, limit: int = 1000) -> list[dict[str, Any]]:
    """Channel history (oldest first) as transcript records; embeds small images inline."""
    messages = [m async for m in channel.history(limit=limit, oldest_first=False)]
    messages.reverse()
    budget = MAX_EMBEDDED_IMAGE_BYTES
    records: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        for message in messages:
            attachments = []
            for att in message.attachments:
                item: dict[str, Any] = {"url": att.url, "name": att.filename, "contentType": att.content_type,
                                        "size": att.size, "dataUri": None}
                is_image = IMAGE_TYPE_RE.match(att.content_type or "") or IMAGE_NAME_RE.search(att.filename)
                if is_image and budget > 0 and (not att.size or att.size <= budget):
                    item["dataUri"] = await _data_uri(http, att)
                    if item["dataUri"]:
                        budget = max(0, budget - len(item["dataUri"]) * 3 // 4)
                attachments.append(item)
            records.append({
                "author": message.author.display_name,
                "authorId": str(message.author.id),
                "avatarUrl": message.author.display_avatar.with_size(64).url,
                "content": message.content or "",
                "embeds": len(message.embeds),
                "attachments": attachments,
                "timestamp": message.created_at.isoformat(),
                "isBot": message.author.bot,
            })
    return records


def _format(content: str) -> str:
    text = html.escape(content, quote=True)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"```(\w+)?\n?([\s\S]*?)```", r"<pre><code>\2</code></pre>", text)
    text = re.sub(r"`(.+?)`", r'<code class="inline">\1</code>', text)
    text = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
    text = text.replace("\n", "<br>")
    text = re.sub(r"&lt;@!?(\d+)&gt;", r'<span class="mention">@\1</span>', text)
    text = re.sub(r"&lt;@&amp;(\d+)&gt;", r'<span class="mention role">@Role:\1</span>', text)
    return re.sub(r"&lt;#(\d+)&gt;", r'<span class="mention channel">#\1</span>', text)


def _when(value: str | datetime) -> str:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.strftime("%d/%m/%Y %H:%M:%S UTC")


_STYLE = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0b0b0c;color:#e5e5e5;font-family:Inter,'Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.45}
.header{background:#111113;padding:24px;border-bottom:1px solid #262628}.header h1{color:#fff;font-size:22px;margin-bottom:8px}
.meta{color:#a3a3a3;font-size:13px}.meta span{margin-right:16px}.messages{padding:16px}
.message{display:flex;gap:16px;padding:6px 16px;border-radius:6px}.message:hover{background:#141416}
.avatar img{width:40px;height:40px;border-radius:50%}.msg-body{flex:1;min-width:0}
.msg-header{display:flex;align-items:baseline;gap:8px;margin-bottom:2px}.author{color:#fff;font-weight:600}
.timestamp{color:#737373;font-size:11px}.bot-badge{background:#e5e5e5;color:#0b0b0c;font-size:10px;padding:1px 4px;border-radius:3px;font-weight:700}
.content{word-wrap:break-word}.content a{color:#d4d4d4;text-decoration:underline}.content strong{color:#fff}
.content code.inline{background:#1c1c1e;padding:2px 4px;border-radius:3px;font-size:13px}
.content pre{background:#1c1c1e;padding:8px;border-radius:4px;margin:4px 0;overflow-x:auto}
.mention{background:#262628;color:#fafafa;padding:0 2px;border-radius:3px}
.embed-badge{background:#262628;color:#a3a3a3;font-size:11px;padding:2px 6px;border-radius:3px;margin-top:4px;display:inline-block}
.attachment{margin:4px 0}.attachment img{max-width:400px;max-height:300px;border-radius:4px}.attachment a{color:#d4d4d4}
.footer{background:#111113;padding:16px 24px;border-top:1px solid #262628;text-align:center;color:#737373;font-size:12px}
"""


def render_html(messages: list[dict[str, Any]], *, number: int, guild_name: str, channel_name: str,
                created_at: datetime, closed_at: datetime | None) -> str:
    esc = html.escape
    rows = []
    for m in messages:
        parts = []
        for att in m.get("attachments", []):
            url = att["url"] if isinstance(att, dict) else str(att)
            source = (att.get("dataUri") if isinstance(att, dict) else None) or url
            name = (att.get("name") if isinstance(att, dict) else None) or "Adjunto"
            ctype = (att.get("contentType") if isinstance(att, dict) else None) or ""
            if source.startswith("data:image/") or ctype.startswith("image/") or IMAGE_NAME_RE.search(url):
                parts.append(f'<div class="attachment"><img src="{esc(source)}" alt="{esc(name)}" loading="lazy"></div>')
            else:
                parts.append(f'<div class="attachment"><a href="{esc(url)}" target="_blank" rel="noopener">{esc(name)}</a></div>')
        rows.append(
            f'<div class="message"><div class="avatar"><img src="{esc(m.get("avatarUrl") or "https://cdn.discordapp.com/embed/avatars/0.png")}" alt=""></div>'
            f'<div class="msg-body"><div class="msg-header"><span class="author">{esc(m.get("author", ""))}</span>'
            f'{"<span class=bot-badge>BOT</span>" if m.get("isBot") else ""}'
            f'<span class="timestamp">{_when(m["timestamp"])}</span></div>'
            f'{f"<div class=content>{_format(m.get("content", ""))}</div>" if m.get("content") else ""}'
            f'{f"<span class=embed-badge>{m["embeds"]} embed(s)</span>" if m.get("embeds") else ""}'
            f'{"".join(parts)}</div></div>'
        )
    return (
        f'<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>Transcripción - Ticket #{number}</title><style>{_STYLE}</style></head><body>"
        f'<div class="header"><h1>Ticket #{str(number).zfill(4)}</h1><div class="meta">'
        f"<span>Servidor: {esc(guild_name)}</span><span>Canal: {esc(channel_name)}</span>"
        f"<span>Creado: {_when(created_at)}</span>"
        f"<span>Cerrado: {_when(closed_at) if closed_at else 'Sigue abierto'}</span>"
        f"<span>Mensajes: {len(messages)}</span></div></div>"
        f'<div class="messages">{"".join(rows)}</div>'
        f'<div class="footer">Generado por Markets Bot &bull; {_when(datetime.now(UTC))}</div></body></html>'
    )
