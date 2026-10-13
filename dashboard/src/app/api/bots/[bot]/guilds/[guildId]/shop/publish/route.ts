import { z } from "zod";
import { snowflake } from "@/lib/schemas/common";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Publish (or edit in place) the main shop message. The bot checks the channel belongs to the guild. */
export const POST = guildRoute(async (request, { bot, guildId }) => {
  const { channelId } = await readBody(request, z.object({ channelId: snowflake }));
  return botCall(bot, "/internal/shop/publish", { body: { guildId, channelId }, timeoutMs: 60_000 });
});
