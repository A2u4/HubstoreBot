import { ticketPanelUpdate } from "@/lib/schemas/tickets";
import { botCall, invalidateBot } from "@/lib/server/bot-api";
import { assertGuildChannels } from "@/lib/server/channels";
import { itemRoutes } from "@/lib/server/crud";
import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
type Params = { bot: string; guildId: string; id: string };

export const { GET, DELETE } = itemRoutes({ model: "ticketPanel", notify: "invalidate" });

/** Save the panel, then refresh its published Discord message (v1 did this automatically too). */
export const PATCH = guildRoute<Params>(async (request, { bot, guildId, params }) => {
  const data = await readBody(request, ticketPanelUpdate);
  await assertGuildChannels(bot, guildId, [data.channelId, data.transcriptChannelId, data.logChannelId]);
  const prisma = db(bot.id);
  const { count } = await prisma.ticketPanel.updateMany({ where: { id: params.id, guildId }, data: data as object });
  if (!count) throw new HttpError(404, "Panel no encontrado");
  const panel = await prisma.ticketPanel.findUniqueOrThrow({ where: { id: params.id } });
  await invalidateBot(bot, guildId);
  let synced = false;
  if (panel.messageId && panel.channelId && panel.channelId !== "0") {
    synced = await botCall(bot, "/internal/tickets/sync", { body: { guildId, panelId: panel.id } }).then(() => true, () => false);
  }
  return { ...panel, synced };
});
