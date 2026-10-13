import { db } from "@/lib/server/db";
import { guildRoute, intParam } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const page = intParam(request.nextUrl.searchParams.get("page"), 1, 1, 1000);
  const take = 25;
  const where = { guildId, xp: { gt: 0 } };
  const [rows, total] = await Promise.all([
    db(bot.id).memberLevel.findMany({ where, orderBy: { xp: "desc" }, skip: (page - 1) * take, take }),
    db(bot.id).memberLevel.count({ where }),
  ]);
  return { rows, total, page, pages: Math.max(1, Math.ceil(total / take)) };
});
