import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Wipe every member's XP in the guild (role rewards already given are kept). */
export const POST = guildRoute(async (_request, { bot, guildId }) => {
  const { count } = await db(bot.id).memberLevel.deleteMany({ where: { guildId } });
  return { success: true, count };
});
