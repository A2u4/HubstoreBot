import { z } from "zod";
import { snowflake } from "@/lib/schemas/common";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Publish one category as its own synchronised message. */
export const POST = guildRoute(async (request, { bot, guildId }) => {
  const body = await readBody(request, z.object({ categoryId: z.string().regex(/^[a-z0-9_-]{1,40}$/), channelId: snowflake }));
  return botCall(bot, "/internal/shop/publish-category", { body: { ...body, guildId }, timeoutMs: 60_000 });
});
