import "server-only";
import { botFetch } from "./bot-api";
import type { BotInfo } from "./bots";

/** Re-render the published shop message after catalog changes (silently skipped if the bot is offline). */
export async function refreshShop(bot: BotInfo, guildId: string): Promise<boolean> {
  return botFetch(bot, "/internal/shop/refresh", { body: { guildId }, timeoutMs: 30_000 }).then(() => true, () => false);
}
