import { botCall } from "@/lib/server/bot-api";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const POST = guildRoute(async (_request, { bot, guildId }) =>
  botCall(bot, `/internal/guilds/${guildId}/commands/sync`, { body: {}, timeoutMs: 60_000 }));
