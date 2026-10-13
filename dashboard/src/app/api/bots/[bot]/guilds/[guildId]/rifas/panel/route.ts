import { z } from "zod";
import { snowflake } from "@/lib/schemas/common";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
const schema = z.object({
  channelId: snowflake, title: z.string().max(256).optional(), description: z.string().max(4000).optional(),
  buttonLabel: z.string().max(80).optional(), buttonColor: z.number().int().min(1).max(4).optional(), // discord ButtonStyle: 1 primary, 2 secondary, 3 success, 4 danger
});

export const POST = guildRoute(async (request, { bot, guildId }) =>
  botCall(bot, "/internal/rifas/deploy-panel", { body: { ...(await readBody(request, schema)), guildId } }));
