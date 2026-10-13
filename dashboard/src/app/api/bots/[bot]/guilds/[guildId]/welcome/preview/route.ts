import { z } from "zod";
import { botFetch } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

const schema = z.object({ layout: z.record(z.unknown()).nullable().optional(), inviterName: z.string().max(64).optional() });

/** Render the welcome/farewell card with the bot's own renderer (pixel-identical to what members see). */
export const POST = guildRoute(async (request, { bot, guildId, session }) => {
  const { layout, inviterName } = await readBody(request, schema);
  const response = await botFetch(bot, "/internal/welcome/preview", {
    body: { guildId, userId: session.emergency ? null : session.id, layout, inviterName }, timeoutMs: 15_000,
  });
  return new Response(await response.arrayBuffer(), { headers: { "content-type": "image/png", "cache-control": "no-store" } });
});
