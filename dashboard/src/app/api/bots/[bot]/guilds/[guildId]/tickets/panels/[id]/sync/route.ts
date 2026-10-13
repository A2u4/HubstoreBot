import { botCall } from "@/lib/server/bot-api";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const POST = guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, { bot, guildId, params }) =>
  botCall(bot, "/internal/tickets/sync", { body: { guildId, panelId: params.id } }));
