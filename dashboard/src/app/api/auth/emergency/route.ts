import { createHmac, timingSafeEqual } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/server/env";
import { sealSession, sessionCookie } from "@/lib/server/session";

export const dynamic = "force-dynamic";

/**
 * Emergency access (replaces v1's /auth/magic). Disabled unless
 * DASHBOARD_EMERGENCY_LOGIN=true. A one-time link is printed by
 * `npm run emergency-link` on the server, so only someone with shell access
 * and the secrets can create it; it expires after 10 minutes and the session after 2 hours.
 */
export async function GET(request: NextRequest) {
  const notFound = NextResponse.json({ error: "Ruta no encontrada" }, { status: 404 });
  if (process.env.DASHBOARD_EMERGENCY_LOGIN !== "true") return notFound;
  const expires = Number(request.nextUrl.searchParams.get("expires"));
  const signature = request.nextUrl.searchParams.get("sig") || "";
  if (!Number.isFinite(expires) || expires < Date.now() || expires > Date.now() + 15 * 60_000) return notFound;
  const expected = createHmac("sha256", env.sessionSecret).update(`emergency:${expires}`).digest("hex");
  if (signature.length !== expected.length || !timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) return notFound;

  const sealed = await sealSession(
    { id: "0", username: "Acceso de emergencia", avatar: null, accessToken: "emergency", emergency: true }, 2 * 60 * 60);
  const response = NextResponse.redirect(new URL("/", env.dashboardUrl));
  response.cookies.set(sessionCookie(sealed, 2 * 60 * 60));
  return response;
}
