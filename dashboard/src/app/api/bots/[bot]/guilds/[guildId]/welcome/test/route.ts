import { z } from "zod";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Post a real welcome/farewell message in the configured channel, using the requesting user as the member. */
export const POST = guildRoute(async (request, { bot, guildId, session }) => {
  const { kind } = await readBody(request, z.object({ kind: z.enum(["welcome", "farewell"]) }));
  return botCall(bot, `/internal/guilds/${guildId}/welcome/test`, { body: { kind, userId: session.emergency ? null : session.id } });
});
