import { botCall } from "@/lib/server/bot-api";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Publish (or update in place) the verification panel in the configured channel. */
export const POST = guildRoute(async (_request, { bot, guildId }) =>
  botCall(bot, "/internal/verification/panel", { body: { guildId } }));
