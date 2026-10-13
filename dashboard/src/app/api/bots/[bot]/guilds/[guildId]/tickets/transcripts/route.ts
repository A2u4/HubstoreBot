import { db } from "@/lib/server/db";
import { guildRoute, intParam } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const q = request.nextUrl.searchParams;
  const page = intParam(q.get("page"), 1, 1, 10_000);
  const take = 50;
  const where = { guildId, ...(q.get("userId") ? { userId: q.get("userId")! } : {}) };
  const prisma = db(bot.id);
  const [transcripts, total] = await Promise.all([
    prisma.ticketTranscript.findMany({
      where, orderBy: { createdAt: "desc" }, take, skip: (page - 1) * take,
      select: { id: true, ticketId: true, userId: true, closedBy: true, messageCount: true, createdAt: true,
                ticket: { select: { number: true, status: true, userId: true } } },
    }),
    prisma.ticketTranscript.count({ where }),
  ]);
  return { transcripts, total, page, pages: Math.max(1, Math.ceil(total / take)) };
});
