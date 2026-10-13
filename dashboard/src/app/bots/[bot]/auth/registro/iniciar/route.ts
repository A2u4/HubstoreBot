import { type NextRequest, NextResponse } from "next/server";
import { botCall } from "@/lib/server/bot-api";
import { getBot } from "@/lib/server/bots";
import { env } from "@/lib/server/env";
import { clientIp, rateLimit } from "@/lib/server/rate-limit";

export const dynamic = "force-dynamic";

/**
 * Consent form target. The bot claims the one-time session token, hashes the
 * client IP with its secret (the raw IP is never stored) and assigns the role.
 */
export async function POST(request: NextRequest, { params }: { params: Promise<{ bot: string }> }) {
  const bot = getBot((await params).bot);
  const page = new URL(`/bots/${bot?.id ?? ""}/auth/registro`, env.dashboardUrl);
  const finish = (status: string) => {
    page.searchParams.set("estado", status);
    return NextResponse.redirect(page, 303);
  };
  if (!bot || !rateLimit(request, "registro", 10)) return finish("error");
  const proto = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  if (proto !== "https" || !env.secure) return finish("error");

  const form = await request.formData().catch(() => null);
  if (form?.get("consentimiento") !== "acepto") return finish("error");
  const token = String(form.get("sesion") ?? "");
  if (!/^[A-Za-z0-9_-]{40,100}$/.test(token)) return finish("error");

  // The network hash needs the real client address; without the proxy header every member would share one hash.
  const ip = clientIp(request);
  if (ip === "unknown") {
    console.error("[registro] missing X-Real-IP / X-Forwarded-For: configure the reverse proxy to send the client IP");
    return finish("error");
  }
  const result = await botCall<{ status: string }>(bot, "/internal/market/register", { body: { token, ip }, timeoutMs: 30_000 })
    .catch(() => ({ status: "error" }));
  return finish(result.status || "error");
}
