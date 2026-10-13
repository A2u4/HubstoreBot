import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const prisma = db(bot.id);
  const weekAgo = new Date(Date.now() - 7 * 86_400_000);
  const [open, closed, total, panels, transcripts, thisWeek, rating, responded] = await Promise.all([
    prisma.ticket.count({ where: { guildId, status: "open" } }),
    prisma.ticket.count({ where: { guildId, status: "closed" } }),
    prisma.ticket.count({ where: { guildId } }),
    prisma.ticketPanel.count({ where: { guildId } }),
    prisma.ticketTranscript.count({ where: { guildId } }),
    prisma.ticket.count({ where: { guildId, createdAt: { gte: weekAgo } } }),
    prisma.ticket.aggregate({ where: { guildId, rating: { not: null } }, _avg: { rating: true }, _count: { rating: true } }),
    prisma.ticket.findMany({ where: { guildId, firstResponse: { not: null }, createdAt: { gte: new Date(Date.now() - 30 * 86_400_000) } },
                             select: { createdAt: true, firstResponse: true }, take: 2000 }),
  ]);
  const waits = responded.map((t) => t.firstResponse!.getTime() - t.createdAt.getTime()).filter((ms) => ms >= 0).sort((a, b) => a - b);
  return {
    open, closed, total, panels, transcripts, thisWeek,
    avgRating: rating._avg.rating ? Math.round(rating._avg.rating * 10) / 10 : null, ratings: rating._count.rating,
    medianFirstResponseMinutes: waits.length ? Math.round(waits[Math.floor(waits.length / 2)] / 60_000) : null,
  };
});
