import { panelDeploy } from "@/lib/schemas/tickets";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Publish up to 5 panels as one message (buttons side by side). The bot checks the channel belongs to the guild. */
export const POST = guildRoute(async (request, { bot, guildId }) =>
  botCall(bot, "/internal/tickets/deploy", { body: { ...(await readBody(request, panelDeploy)), guildId } }));
