import { db } from "@/lib/server/db";
import { guildRoute, intParam } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const q = request.nextUrl.searchParams;
  const page = intParam(q.get("page"), 1, 1, 10_000);
  const take = intParam(q.get("limit"), 50, 1, 100);
  const where = {
    guildId,
    ...(q.get("status") ? { status: q.get("status")! } : {}),
    ...(q.get("panelId") ? { panelId: q.get("panelId")! } : {}),
    ...(q.get("userId") ? { userId: q.get("userId")! } : {}),
    ...(q.get("claimedBy") ? { claimedBy: q.get("claimedBy")! } : {}),
    ...(q.get("priority") ? { priority: q.get("priority")! } : {}),
  };
  const prisma = db(bot.id);
  const [tickets, total] = await Promise.all([
    prisma.ticket.findMany({ where, orderBy: { createdAt: "desc" }, take, skip: (page - 1) * take,
                             include: { panel: { select: { id: true, name: true, title: true } } } }),
    prisma.ticket.count({ where }),
  ]);
  return { tickets, total, page, pages: Math.max(1, Math.ceil(total / take)) };
});
