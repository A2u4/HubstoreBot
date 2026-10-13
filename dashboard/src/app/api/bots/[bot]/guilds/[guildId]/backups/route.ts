import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) =>
  db(bot.id).backup.findMany({
    where: { guildId }, orderBy: { createdAt: "desc" },
    select: { id: true, name: true, creatorId: true, size: true, createdAt: true },
  }));
