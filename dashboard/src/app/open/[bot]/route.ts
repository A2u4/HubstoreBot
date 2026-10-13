import { type NextRequest, NextResponse } from "next/server";
import { getBot } from "@/lib/server/bots";
import { env } from "@/lib/server/env";

/** Target of the bot's /dashboard button: goes straight to the guild when one is given. */
export async function GET(request: NextRequest, { params }: { params: Promise<{ bot: string }> }) {
  const bot = getBot((await params).bot);
  if (!bot) return NextResponse.redirect(new URL("/", env.dashboardUrl));
  const guild = request.nextUrl.searchParams.get("guild");
  const path = guild && /^\d{17,20}$/.test(guild) ? `/bots/${bot.id}/${guild}` : `/bots/${bot.id}`;
  return NextResponse.redirect(new URL(path, env.dashboardUrl));
}
