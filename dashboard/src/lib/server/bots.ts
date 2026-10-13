import "server-only";

/** Bots of the cluster. Each one has its own database and internal HTTP port, all set in the root .env. */
export interface BotInfo {
  id: string;
  name: string;
  guildId: string | null;
  clientId: string | null;
  clientSecret: string | null;
  databaseUrl: string | null;
  internalUrl: string | null;
}

const DEFAULT_IDS = ["vapiano", "hubstore", "tradezone"];
const DISPLAY_NAMES: Record<string, string> = { vapiano: "Vapiano", hubstore: "Hub Store", tradezone: "Trade Zone" };

function read(id: string, key: string): string | null {
  return process.env[`${id.toUpperCase()}_${key}`] || null;
}

export function botIds(): string[] {
  const configured = (process.env.BOTS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  return configured.length ? configured : DEFAULT_IDS;
}

export function getBot(id: string): BotInfo | null {
  const key = id.toLowerCase();
  if (!botIds().includes(key)) return null;
  const port = read(key, "INTERNAL_PORT");
  return {
    id: key,
    name: read(key, "DISPLAY_NAME") || DISPLAY_NAMES[key] || key,
    guildId: read(key, "GUILD_ID"),
    clientId: read(key, "CLIENT_ID") || process.env.CLIENT_ID || null,
    clientSecret: read(key, "CLIENT_SECRET") || process.env.CLIENT_SECRET || null,
    databaseUrl: read(key, "DATABASE_URL") || process.env.DATABASE_URL || null,
    internalUrl: port ? `http://127.0.0.1:${port}` : null,
  };
}

/** Bots with a database configured (the ones the dashboard can manage). */
export function listBots(): BotInfo[] {
  return botIds().map(getBot).filter((b): b is BotInfo => Boolean(b?.databaseUrl));
}

/** Public, secret-free description for the client. */
export function publicBot(bot: BotInfo) {
  return { id: bot.id, name: bot.name, guildId: bot.guildId, online: Boolean(bot.internalUrl) };
}
