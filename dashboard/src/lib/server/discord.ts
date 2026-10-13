import "server-only";
import { HttpError } from "./errors";
import { TtlCache } from "./ttl-cache";

const API = "https://discord.com/api/v10";
const MANAGE_GUILD = 0x20n;
const ADMINISTRATOR = 0x8n;

export interface DiscordUser {
  id: string;
  username: string;
  global_name?: string | null;
  avatar: string | null;
}

export interface UserGuild {
  id: string;
  name: string;
  icon: string | null;
  owner: boolean;
  permissions: string;
}

export async function exchangeCode(code: string, clientId: string, clientSecret: string, redirectUri: string) {
  const response = await fetch(`${API}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: clientId, client_secret: clientSecret, grant_type: "authorization_code",
                                code, redirect_uri: redirectUri }),
    cache: "no-store",
  });
  if (!response.ok) throw new HttpError(response.status === 400 ? 400 : 502, "token_exchange");
  return (await response.json()) as { access_token: string };
}

export async function fetchUser(accessToken: string): Promise<DiscordUser> {
  const response = await fetch(`${API}/users/@me`, { headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store" });
  if (!response.ok) throw new HttpError(502, "user_fetch");
  return (await response.json()) as DiscordUser;
}

// Discord rate-limits /users/@me/guilds hard: cache 15 minutes per token and share in-flight requests.
const guildCache = new TtlCache<UserGuild[]>(15 * 60_000, 1000);
const inflight = new Map<string, Promise<UserGuild[]>>();

export async function fetchUserGuilds(userId: string, accessToken: string, { fresh = false } = {}): Promise<UserGuild[]> {
  const cacheKey = `${userId}:${accessToken.slice(-8)}`;
  const cached = fresh ? undefined : guildCache.get(cacheKey);
  if (cached) return cached;
  const pending = inflight.get(cacheKey);
  if (pending) return pending;
  const request = (async () => {
    try {
      const response = await fetch(`${API}/users/@me/guilds`, {
        headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store",
      });
      if (response.status === 401) throw new HttpError(401, "La sesión de Discord expiró. Inicia sesión de nuevo.");
      if (response.status === 429) throw new HttpError(429, "Discord está limitando las solicitudes. Espera un minuto.");
      if (!response.ok) throw new HttpError(502, "No se pudieron obtener los servidores desde Discord");
      const guilds = (await response.json()) as UserGuild[];
      guildCache.set(cacheKey, guilds);
      return guilds;
    } finally {
      inflight.delete(cacheKey);
    }
  })();
  inflight.set(cacheKey, request);
  return request;
}

export function canManage(guild: UserGuild): boolean {
  const perms = BigInt(guild.permissions || "0");
  return guild.owner || (perms & MANAGE_GUILD) !== 0n || (perms & ADMINISTRATOR) !== 0n;
}

export function guildIcon(guild: { id: string; icon: string | null }, size = 96): string | null {
  return guild.icon ? `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=${size}` : null;
}
