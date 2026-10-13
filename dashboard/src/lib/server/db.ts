import "server-only";
import { PrismaClient } from "@prisma/client";
import { getBot } from "./bots";
import { HttpError } from "./errors";

// One client per bot database, reused across hot reloads in development.
const globalForPrisma = globalThis as unknown as { prismaClients?: Map<string, PrismaClient> };
const clients = (globalForPrisma.prismaClients ??= new Map());

export function db(botId: string): PrismaClient {
  const bot = getBot(botId);
  if (!bot?.databaseUrl) throw new HttpError(404, "Bot no configurado");
  let client = clients.get(bot.id);
  if (!client) {
    client = new PrismaClient({ datasourceUrl: bot.databaseUrl });
    clients.set(bot.id, client);
  }
  return client;
}

/** Make sure the guild's config row exists (v1 did this on every config read). */
export async function ensureGuildConfig(botId: string, guildId: string) {
  return db(botId).guildConfig.upsert({ where: { id: guildId }, create: { id: guildId }, update: {} });
}
