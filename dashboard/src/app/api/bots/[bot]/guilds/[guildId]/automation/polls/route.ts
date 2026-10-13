import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) =>
  db(bot.id).poll.findMany({ where: { guildId }, orderBy: { createdAt: "desc" }, take: 100 }));
