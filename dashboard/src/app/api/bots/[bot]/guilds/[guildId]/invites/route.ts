import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Recent joins plus a per-inviter leaderboard (valid = not fake and still in the server). */
export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const prisma = db(bot.id);
  const [recent, grouped] = await Promise.all([
    prisma.invite.findMany({ where: { guildId }, orderBy: { createdAt: "desc" }, take: 100 }),
    prisma.invite.groupBy({ by: ["inviterId", "fake", "left"], where: { guildId }, _count: true }),
  ]);
  const board = new Map<string, { inviterId: string; valid: number; fake: number; left: number; total: number }>();
  for (const row of grouped) {
    const entry = board.get(row.inviterId) ?? { inviterId: row.inviterId, valid: 0, fake: 0, left: 0, total: 0 };
    entry.total += row._count;
    if (row.fake) entry.fake += row._count;
    else if (row.left) entry.left += row._count;
    else entry.valid += row._count;
    board.set(row.inviterId, entry);
  }
  const leaderboard = [...board.values()].sort((a, b) => b.valid - a.valid || b.total - a.total).slice(0, 50);
  return { recent, leaderboard };
});
