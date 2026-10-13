import { botCall } from "@/lib/server/bot-api";
import { listBots, publicBot } from "@/lib/server/bots";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Channels, roles and emojis come from the live bot; an offline bot yields empty lists (pages still work). */
export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const base = `/internal/guilds/${guildId}`;
  const [channels, roles, emojis] = await Promise.allSettled([
    botCall<unknown[]>(bot, `${base}/channels`),
    botCall<unknown[]>(bot, `${base}/roles`),
    botCall<unknown[]>(bot, `${base}/emojis`),
  ]);
  const value = (r: PromiseSettledResult<unknown[]>) => (r.status === "fulfilled" ? r.value : []);
  return {
    channels: value(channels),
    roles: value(roles),
    emojis: value(emojis),
    botOnline: channels.status === "fulfilled",
    peers: listBots().map(publicBot),
  };
});
