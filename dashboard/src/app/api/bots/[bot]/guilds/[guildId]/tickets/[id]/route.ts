import { ticketUpdate } from "@/lib/schemas/tickets";
import { botCall } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
type Params = { bot: string; guildId: string; id: string };

const include = {
  panel: { select: { id: true, name: true, title: true } },
  transcripts: { select: { id: true, messageCount: true, closedBy: true, createdAt: true }, orderBy: { createdAt: "desc" as const } },
};

export const GET = guildRoute<Params>(async (_request, { bot, guildId, params }) => {
  const ticket = await db(bot.id).ticket.findFirst({ where: { id: params.id, guildId }, include });
  if (!ticket) throw new HttpError(404, "Ticket no encontrado");
  return ticket;
});

/**
 * Closing an open ticket goes through the bot (transcript, DMs, channel removal).
 * If the bot is offline, only the database row is updated (v1 behaviour).
 */
export const PATCH = guildRoute<Params>(async (request, { bot, guildId, params, session }) => {
  const data = await readBody(request, ticketUpdate);
  const prisma = db(bot.id);
  const ticket = await prisma.ticket.findFirst({ where: { id: params.id, guildId } });
  if (!ticket) throw new HttpError(404, "Ticket no encontrado");
  const { status, ...rest } = data;
  if (Object.keys(rest).length) await prisma.ticket.update({ where: { id: ticket.id }, data: rest });
  if (status === "closed" && ticket.status === "open") {
    const closed = await botCall<{ success: boolean }>(bot, "/internal/tickets/close", {
      body: { guildId, channelId: ticket.channelId, closedBy: session.id, reason: "Cerrado desde el dashboard" }, timeoutMs: 60_000,
    }).then((r) => r.success, () => false);
    if (!closed) await prisma.ticket.update({ where: { id: ticket.id }, data: { status: "closed", closedAt: new Date(), closedBy: session.id } });
  } else if (status && status !== ticket.status) {
    await prisma.ticket.update({ where: { id: ticket.id }, data: { status, ...(status === "open" ? { closedAt: null } : {}) } });
  }
  return prisma.ticket.findFirst({ where: { id: ticket.id }, include });
});
