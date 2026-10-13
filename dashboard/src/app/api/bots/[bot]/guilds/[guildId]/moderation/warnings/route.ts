import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const userId = request.nextUrl.searchParams.get("userId");
  return db(bot.id).warning.findMany({ where: { guildId, ...(userId ? { userId } : {}) }, orderBy: { createdAt: "desc" }, take: 200 });
});
