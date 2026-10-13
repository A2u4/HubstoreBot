import "server-only";
import { createHash } from "node:crypto";
import { EncryptJWT, jwtDecrypt } from "jose";
import { cookies } from "next/headers";
import { env } from "./env";

export const SESSION_COOKIE = "mk_session";
const MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

export interface Session {
  id: string;
  username: string;
  avatar: string | null;
  /** Discord OAuth token (only used server-side to list the user's guilds). */
  accessToken: string;
  /** Emergency sessions (CLI-issued) skip the Discord guild check. */
  emergency?: boolean;
}

function key(): Uint8Array {
  return createHash("sha256").update(`markets-dashboard-session:${env.sessionSecret}`).digest();
}

/** Encrypted (JWE), so the Discord token inside the cookie can't be read by the browser or a proxy log. */
export async function sealSession(session: Session, maxAgeSeconds = MAX_AGE_SECONDS): Promise<string> {
  return new EncryptJWT({ ...session })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(`${maxAgeSeconds}s`)
    .encrypt(key());
}

export async function openSession(token: string | undefined): Promise<Session | null> {
  if (!token) return null;
  try {
    const { payload } = await jwtDecrypt(token, key());
    if (typeof payload.id !== "string" || typeof payload.accessToken !== "string") return null;
    return payload as unknown as Session;
  } catch {
    return null;
  }
}

export async function getSession(): Promise<Session | null> {
  return openSession((await cookies()).get(SESSION_COOKIE)?.value);
}

export function sessionCookie(value: string, maxAge = MAX_AGE_SECONDS) {
  return { name: SESSION_COOKIE, value, httpOnly: true, secure: env.secure, sameSite: "lax" as const, path: "/", maxAge };
}

export function avatarUrl(session: Pick<Session, "id" | "avatar">): string {
  if (session.avatar) return `https://cdn.discordapp.com/avatars/${session.id}/${session.avatar}.png?size=64`;
  const index = Number((BigInt(session.id.replace(/\D/g, "") || "0") >> 22n) % 6n);
  return `https://cdn.discordapp.com/embed/avatars/${index}.png`;
}
