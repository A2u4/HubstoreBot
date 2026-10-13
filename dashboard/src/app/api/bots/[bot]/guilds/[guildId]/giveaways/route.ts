import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const status = request.nextUrl.searchParams.get("status");
  const where = { guildId, ...(status === "active" ? { ended: false } : status === "ended" ? { ended: true } : {}) };
  return db(bot.id).giveaway.findMany({ where, orderBy: { createdAt: "desc" }, take: 100 });
});
