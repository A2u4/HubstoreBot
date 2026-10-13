import "server-only";
import { botCall } from "./bot-api";
import type { BotInfo } from "./bots";
import { HttpError } from "./errors";
import { TtlCache } from "./ttl-cache";

const cache = new TtlCache<Set<string>>(30_000, 500);

async function guildChannelIds(bot: BotInfo, guildId: string): Promise<Set<string>> {
  const key = `${bot.id}:${guildId}`;
  const cached = cache.get(key);
  if (cached) return cached;
  const channels = await botCall<Array<{ id: string }>>(bot, `/internal/guilds/${guildId}/channels`, { timeoutMs: 5000 })
    .catch(() => { throw new HttpError(503, "El bot debe estar en línea para verificar los canales"); });
  const ids = new Set(channels.map((c) => c.id));
  cache.set(key, ids);
  return ids;
}

/**
 * Every channel the dashboard stores for the bot to post in must belong to this guild;
 * otherwise an admin of one server could make the bot write into another server's channel.
 */
export async function assertGuildChannels(bot: BotInfo, guildId: string, ids: Array<string | null | undefined>): Promise<void> {
  const wanted = ids.filter((id): id is string => Boolean(id));
  if (!wanted.length) return;
  let known = await guildChannelIds(bot, guildId);
  if (wanted.every((id) => known.has(id))) return;
  cache.delete(`${bot.id}:${guildId}`); // the channel may be brand new
  known = await guildChannelIds(bot, guildId);
  if (!wanted.every((id) => known.has(id))) throw new HttpError(400, "El canal no pertenece a este servidor");
}
