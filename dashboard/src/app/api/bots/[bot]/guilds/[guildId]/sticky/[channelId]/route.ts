import { stickyUpdate } from "@/lib/schemas/content";
import { botCall, botFetch, invalidateBot } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
type Params = { bot: string; guildId: string; channelId: string };

export const PATCH = guildRoute<Params>(async (request, { bot, guildId, params }) => {
  const data = await readBody(request, stickyUpdate);
  const { count } = await db(bot.id).stickyMessage.updateMany({ where: { guildId, channelId: params.channelId }, data });
  if (!count) throw new HttpError(404, "Mensaje fijo no encontrado");
  await invalidateBot(bot, guildId);
  await botFetch(bot, "/internal/sticky/resend", { body: { guildId, channelId: params.channelId } }).catch(() => undefined);
  return db(bot.id).stickyMessage.findUnique({ where: { channelId: params.channelId } });
});

/** The bot deletes both the row and the posted message; if it is offline, only the row is removed. */
export const DELETE = guildRoute<Params>(async (_request, { bot, guildId, params }) => {
  const row = await db(bot.id).stickyMessage.findFirst({ where: { guildId, channelId: params.channelId } });
  if (!row) throw new HttpError(404, "Mensaje fijo no encontrado");
  const removed = await botCall<{ success: boolean }>(bot, "/internal/sticky/remove", { body: { channelId: params.channelId } })
    .then((r) => r.success, () => false);
  if (!removed) await db(bot.id).stickyMessage.deleteMany({ where: { guildId, channelId: params.channelId } });
  await invalidateBot(bot, guildId);
  return { success: true };
});
