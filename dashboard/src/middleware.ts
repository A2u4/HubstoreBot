import { type NextRequest, NextResponse } from "next/server";

/**
 * CSRF guard: state-changing requests must come from the dashboard's own origin
 * (same rule as v1's Express API). Session cookies are SameSite=Lax as a second layer.
 */
export function middleware(request: NextRequest) {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return NextResponse.next();
  const origin = request.headers.get("origin");
  if (!origin) return NextResponse.next();
  const allowed = new Set([request.nextUrl.origin]);
  if (process.env.DASHBOARD_URL) {
    try {
      allowed.add(new URL(process.env.DASHBOARD_URL).origin);
    } catch {
      /* invalid DASHBOARD_URL: only the request origin is accepted */
    }
  }
  if (!allowed.has(origin)) {
    return NextResponse.json({ error: "Origen no permitido" }, { status: 403 });
  }
  return NextResponse.next();
}

export const config = { matcher: ["/api/:path*", "/bots/:bot/auth/:path*"] };
