import { botCall } from "@/lib/server/bot-api";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Member lookup through the bot's cache: ?q=search or ?ids=1,2,3 (for showing names next to user ids). */
export const GET = guildRoute(async (request, { bot, guildId }) => {
  const params = new URLSearchParams();
  const q = request.nextUrl.searchParams.get("q");
  const ids = request.nextUrl.searchParams.get("ids");
  if (q) params.set("q", q.slice(0, 64));
  if (ids) params.set("ids", ids.split(",").filter((id) => /^\d{17,20}$/.test(id)).slice(0, 100).join(","));
  params.set("limit", ids ? "100" : "25");
  return botCall(bot, `/internal/guilds/${guildId}/members?${params}`).catch(() => []);
});
