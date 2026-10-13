import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const DELETE = guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, { bot, guildId, params }) => {
  const { count } = await db(bot.id).starboardEntry.deleteMany({ where: { id: params.id, guildId } });
  if (!count) throw new HttpError(404, "Entrada no encontrada");
  return { success: true };
});
