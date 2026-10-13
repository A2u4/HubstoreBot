import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const prisma = db(bot.id);
  const [marriages, topActions, totals] = await Promise.all([
    prisma.marriage.findMany({ where: { guildId }, orderBy: { createdAt: "asc" }, take: 100 }),
    prisma.roleplayStat.findMany({ where: { guildId }, orderBy: { count: "desc" }, take: 15 }),
    prisma.roleplayStat.groupBy({ by: ["action"], where: { guildId }, _sum: { count: true }, orderBy: { _sum: { count: "desc" } }, take: 10 }),
  ]);
  return { marriages, topActions, totals: totals.map((t) => ({ action: t.action, count: t._sum.count ?? 0 })) };
});
