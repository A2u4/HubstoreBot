import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (request, { bot, guildId }) => {
  const status = request.nextUrl.searchParams.get("status");
  return db(bot.id).suggestion.findMany({
    where: { guildId, ...(status && status !== "all" ? { status } : {}) }, orderBy: { createdAt: "desc" }, take: 200,
  });
});
