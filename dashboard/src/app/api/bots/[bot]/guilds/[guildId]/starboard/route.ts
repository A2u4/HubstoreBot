import { db } from "@/lib/server/db";
import { guildRoute, intParam } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const page = intParam(request.nextUrl.searchParams.get("page"), 1, 1, 10_000);
  const take = 20;
  const [rows, total] = await Promise.all([
    db(bot.id).starboardEntry.findMany({ where: { guildId }, orderBy: { stars: "desc" }, skip: (page - 1) * take, take }),
    db(bot.id).starboardEntry.count({ where: { guildId } }),
  ]);
  return { rows, total, page, pages: Math.max(1, Math.ceil(total / take)) };
});
