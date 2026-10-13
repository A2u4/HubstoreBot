import "server-only";
import { type BotInfo, getBot } from "./bots";
import { canManage, fetchUserGuilds } from "./discord";
import { HttpError } from "./errors";
import { getSession, type Session } from "./session";

export const SNOWFLAKE = /^\d{17,20}$/;

export async function requireSession(): Promise<Session> {
  const session = await getSession();
  if (!session) throw new HttpError(401, "Debes iniciar sesión");
  return session;
}

export function requireBot(botId: string): BotInfo {
  const bot = getBot(botId);
  if (!bot?.databaseUrl) throw new HttpError(404, "Bot no encontrado");
  return bot;
}

/** The user must own the guild or have Manage Server / Administrator in it (same rule as v1). */
export async function assertGuildAccess(session: Session, guildId: string): Promise<void> {
  if (!SNOWFLAKE.test(guildId)) throw new HttpError(400, "ID de servidor inválido");
  if (session.emergency) return;
  const guild = (await fetchUserGuilds(session.id, session.accessToken)).find((g) => g.id === guildId);
  if (!guild) throw new HttpError(403, "No eres miembro de este servidor");
  if (!canManage(guild)) throw new HttpError(403, "No tienes permisos para administrar este servidor");
}

export async function requireGuildAccess(botId: string, guildId: string): Promise<{ bot: BotInfo; session: Session }> {
  const bot = requireBot(botId);
  const session = await requireSession();
  await assertGuildAccess(session, guildId);
  return { bot, session };
}
