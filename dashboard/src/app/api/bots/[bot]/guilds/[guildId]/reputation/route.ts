import { botCall } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Leaderboard from the bot (includes reputation synced from peer servers), falling back to local counts. */
export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const prisma = db(bot.id);
  const [leaderboard, recent] = await Promise.all([
    botCall<Array<{ userId: string; rep: number }>>(bot, "/internal/reputation/leaderboard", { body: { guildId, limit: 50 } })
      .catch(async () => (await prisma.reputation.groupBy({ by: ["userId"], where: { guildId }, _count: true, orderBy: { _count: { userId: "desc" } }, take: 50 }))
        .map((r) => ({ userId: r.userId, rep: r._count }))),
    prisma.reputation.findMany({ where: { guildId }, orderBy: { createdAt: "desc" }, take: 50 }),
  ]);
  return { leaderboard, recent };
});
