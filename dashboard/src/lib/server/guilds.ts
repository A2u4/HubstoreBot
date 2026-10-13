import "server-only";
import { redirect } from "next/navigation";
import { requireBot } from "./access";
import { botCall } from "./bot-api";
import type { BotInfo } from "./bots";
import { db } from "./db";
import { canManage, fetchUserGuilds, guildIcon, type UserGuild } from "./discord";
import { HttpError } from "./errors";
import { getSession, type Session } from "./session";

export interface ManageableGuild { id: string; name: string; icon: string | null; botPresent: boolean }

/** Session for a server-rendered page; unauthenticated users go to the login screen. */
export async function pageSession(bot: string, next: string): Promise<Session> {
  const session = await getSession();
  if (!session) redirect(`/login?bot=${bot}&next=${encodeURIComponent(next)}`);
  return session;
}

async function botGuildIds(bot: BotInfo): Promise<Set<string>> {
  try {
    const guilds = await botCall<Array<{ id: string }>>(bot, "/internal/guilds", { timeoutMs: 4000 });
    return new Set(guilds.map((g) => g.id));
  } catch {
    const rows = await db(bot.id).guildConfig.findMany({ select: { id: true } });
    return new Set(rows.map((r) => r.id));
  }
}

export async function manageableGuilds(botId: string, session: Session): Promise<ManageableGuild[]> {
  const bot = requireBot(botId);
  const present = await botGuildIds(bot);
  if (session.emergency) {
    return [...present].map((id) => ({ id, name: `Servidor ${id}`, icon: null, botPresent: true }));
  }
  const guilds = (await fetchUserGuilds(session.id, session.accessToken)).filter(canManage);
  return guilds
    .map((g: UserGuild) => ({ id: g.id, name: g.name, icon: guildIcon(g), botPresent: present.has(g.id) }))
    .sort((a, b) => Number(b.botPresent) - Number(a.botPresent) || a.name.localeCompare(b.name));
}

/** Resolve the guild for a dashboard page, or a reason it can't be opened. */
export async function pageGuild(botId: string, guildId: string, session: Session): Promise<{ name: string; icon: string | null }> {
  if (!/^\d{17,20}$/.test(guildId)) throw new HttpError(404, "Servidor no encontrado");
  if (session.emergency) return { name: `Servidor ${guildId}`, icon: null };
  const guild = (await fetchUserGuilds(session.id, session.accessToken)).find((g) => g.id === guildId);
  if (!guild) throw new HttpError(403, "No eres miembro de este servidor");
  if (!canManage(guild)) throw new HttpError(403, "No tienes permisos para administrar este servidor");
  return { name: guild.name, icon: guildIcon(guild) };
}
