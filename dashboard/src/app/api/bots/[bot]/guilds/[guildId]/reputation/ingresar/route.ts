import { z } from "zod";
import { snowflake } from "@/lib/schemas/common";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
const schema = z.object({ userId: snowflake, cantidad: z.number().int().min(1).max(1000), razon: z.string().trim().min(1).max(200) });

export const POST = guildRoute(async (request, { bot, guildId, session }) =>
  botCall(bot, "/internal/reputation/add", { body: { ...(await readBody(request, schema)), guildId, giverId: session.emergency ? "dashboard" : session.id } }));
