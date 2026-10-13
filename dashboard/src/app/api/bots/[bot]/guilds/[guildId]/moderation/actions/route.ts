import { db } from "@/lib/server/db";
import { guildRoute, intParam } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const params = request.nextUrl.searchParams;
  const page = intParam(params.get("page"), 1, 1, 10_000);
  const take = 50;
  const where = {
    guildId,
    ...(params.get("action") ? { action: params.get("action")! } : {}),
    ...(params.get("userId") ? { userId: params.get("userId")! } : {}),
  };
  const [rows, total] = await Promise.all([
    db(bot.id).modAction.findMany({ where, orderBy: { createdAt: "desc" }, skip: (page - 1) * take, take }),
    db(bot.id).modAction.count({ where }),
  ]);
  return { rows, total, page, pages: Math.max(1, Math.ceil(total / take)) };
});
