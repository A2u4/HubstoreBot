import { NextResponse } from "next/server";
import { requireBot, requireSession } from "@/lib/server/access";
import { manageableGuilds } from "@/lib/server/guilds";
import { errorResponse } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Servers the user manages for this bot (used by migration targets). */
export async function GET(_request: Request, { params }: { params: Promise<{ bot: string }> }) {
  try {
    const bot = requireBot((await params).bot);
    return NextResponse.json(await manageableGuilds(bot.id, await requireSession()));
  } catch (error) {
    return errorResponse(error);
  }
}
