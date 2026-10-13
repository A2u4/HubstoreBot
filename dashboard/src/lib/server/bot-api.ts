import "server-only";
import type { BotInfo } from "./bots";
import { env } from "./env";
import { HttpError } from "./errors";

interface CallOptions {
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs?: number;
}

/** Call the bot process's internal API (127.0.0.1 only, authenticated with API_SECRET). */
export async function botFetch(bot: BotInfo, path: string, options: CallOptions = {}): Promise<Response> {
  if (!bot.internalUrl) throw new HttpError(503, `${bot.name} no tiene configurado ${bot.id.toUpperCase()}_INTERNAL_PORT`);
  let response: Response;
  try {
    response = await fetch(`${bot.internalUrl}${path}`, {
      method: options.method ?? (options.body === undefined ? "GET" : "POST"),
      headers: { "x-internal-secret": env.apiSecret, "content-type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      signal: AbortSignal.timeout(options.timeoutMs ?? 20_000),
    });
  } catch {
    throw new HttpError(503, `${bot.name} no está en línea en este momento`);
  }
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new HttpError(response.status >= 500 ? 502 : response.status, data?.error || `El bot respondió ${response.status}`);
  }
  return response;
}

export async function botCall<T = Record<string, unknown>>(bot: BotInfo, path: string, options: CallOptions = {}): Promise<T> {
  return (await (await botFetch(bot, path, options)).json()) as T;
}

/**
 * Tell the bot a guild's settings changed so it drops its caches (and optionally
 * redeploys slash commands). A bot that is offline will read fresh data on start,
 * so failures here never fail the save.
 */
export async function invalidateBot(bot: BotInfo, guildId: string, resync = false): Promise<boolean> {
  try {
    await botFetch(bot, "/internal/cache/invalidate", { body: { guildId, resync }, timeoutMs: resync ? 30_000 : 5_000 });
    return true;
  } catch {
    return false;
  }
}
