import { panelCrossDeploy } from "@/lib/schemas/tickets";
import { assertGuildAccess } from "@/lib/server/access";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Copy panels to another server of this bot and publish them there (user must manage both servers). */
export const POST = guildRoute(async (request, { bot, guildId, session }) => {
  const body = await readBody(request, panelCrossDeploy);
  await assertGuildAccess(session, body.targetGuildId);
  return botCall(bot, "/internal/tickets/cross-deploy", { body: { ...body, guildId } });
});
