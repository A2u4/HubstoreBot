import { timingSafeEqual } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";
import { getBot } from "@/lib/server/bots";
import { exchangeCode, fetchUser } from "@/lib/server/discord";
import { env } from "@/lib/server/env";
import { HttpError } from "@/lib/server/errors";
import { rateLimit } from "@/lib/server/rate-limit";
import { sealSession, sessionCookie } from "@/lib/server/session";

export const dynamic = "force-dynamic";
const STATE_COOKIE = "mk_oauth_state";

function safeEqual(a: string, b: string): boolean {
  return a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

function fail(error: string) {
  const url = new URL("/login", env.dashboardUrl);
  url.searchParams.set("error", error);
  const response = NextResponse.redirect(url);
  response.cookies.delete(STATE_COOKIE);
  return response;
}

export async function GET(request: NextRequest) {
  if (!rateLimit(request, "callback", 10)) return fail("rate_limited");
  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state") || "";
  if (!code) return fail(request.nextUrl.searchParams.get("error") === "access_denied" ? "denied" : "no_code");

  let stored: { state: string; next: string };
  try {
    stored = JSON.parse(request.cookies.get(STATE_COOKIE)?.value || "");
  } catch {
    return fail("invalid_state");
  }
  // CSRF: the state echoed by Discord must match the one we set in this browser.
  if (!stored?.state || !safeEqual(stored.state, state)) return fail("invalid_state");

  const bot = getBot(state.split(".")[1] || "");
  if (!bot?.clientId || !bot.clientSecret) return fail("not_configured");
  try {
    const tokens = await exchangeCode(code, bot.clientId, bot.clientSecret, `${env.dashboardUrl}/api/auth/callback`);
    const user = await fetchUser(tokens.access_token);
    const sealed = await sealSession({
      id: user.id, username: user.global_name || user.username, avatar: user.avatar, accessToken: tokens.access_token,
    });
    const response = NextResponse.redirect(new URL(stored.next || "/", env.dashboardUrl));
    response.cookies.set(sessionCookie(sealed));
    response.cookies.delete(STATE_COOKIE);
    return response;
  } catch (error) {
    if (error instanceof HttpError) return fail(error.status === 400 ? "oauth_code_invalid" : error.message);
    console.error("[auth] callback failed", error);
    return fail("unknown");
  }
}
