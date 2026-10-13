import { z } from "zod";
import { snowflake } from "@/lib/schemas/common";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
const schema = z.object({ fromUserId: snowflake, toUserId: snowflake, razon: z.string().trim().max(200).optional() });

/** Move every rep of an old account to a new one (e.g. a member who lost access to their account). */
export const POST = guildRoute(async (request, { bot, guildId }) =>
  botCall(bot, "/internal/reputation/migrate", { body: { ...(await readBody(request, schema)), guildId } }));
