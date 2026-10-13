import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";
type Params = { bot: string; guildId: string; id: string };

/** Full backup JSON (download / inspect). */
export const GET = guildRoute<Params>(async (_request, { bot, guildId, params }) => {
  const backup = await db(bot.id).backup.findFirst({ where: { id: params.id, guildId } });
  if (!backup) throw new HttpError(404, "Respaldo no encontrado");
  return backup;
});

export const DELETE = guildRoute<Params>(async (_request, { bot, guildId, params }) => {
  const { count } = await db(bot.id).backup.deleteMany({ where: { id: params.id, guildId } });
  if (!count) throw new HttpError(404, "Respaldo no encontrado");
  return { success: true };
});
