import { randomBytes } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";
import { getBot, listBots } from "@/lib/server/bots";
import { env } from "@/lib/server/env";
import { rateLimit } from "@/lib/server/rate-limit";

export const dynamic = "force-dynamic";
const STATE_COOKIE = "mk_oauth_state";

/** Start Discord OAuth with the chosen bot's application (each bot keeps its own app, like v1). */
export async function GET(request: NextRequest) {
  const loginUrl = new URL("/login", env.dashboardUrl);
  if (!rateLimit(request, "login", 10)) {
    loginUrl.searchParams.set("error", "rate_limited");
    return NextResponse.redirect(loginUrl);
  }
  const requested = request.nextUrl.searchParams.get("bot");
  const bot = (requested && getBot(requested)) || listBots()[0];
  if (!bot?.clientId || !bot.clientSecret) {
    loginUrl.searchParams.set("error", "not_configured");
    return NextResponse.redirect(loginUrl);
  }
  const next = request.nextUrl.searchParams.get("next") || `/bots/${bot.id}`;
  const nonce = randomBytes(24).toString("hex");
  const state = `${nonce}.${bot.id}`;

  const authorize = new URL("https://discord.com/oauth2/authorize");
  authorize.search = new URLSearchParams({
    client_id: bot.clientId, response_type: "code", scope: "identify guilds", state, prompt: "none",
    redirect_uri: `${env.dashboardUrl}/api/auth/callback`,
  }).toString();

  const response = NextResponse.redirect(authorize);
  response.cookies.set(STATE_COOKIE, JSON.stringify({ state, next: next.startsWith("/") && !next.startsWith("//") ? next : "/" }), {
    httpOnly: true, secure: env.secure, sameSite: "lax", path: "/", maxAge: 600,
  });
  return response;
}
