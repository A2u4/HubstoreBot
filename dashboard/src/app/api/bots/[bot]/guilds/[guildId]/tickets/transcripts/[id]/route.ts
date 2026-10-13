import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, { bot, guildId, params }) => {
  const transcript = await db(bot.id).ticketTranscript.findFirst({
    where: { id: params.id, guildId },
    select: { id: true, ticketId: true, userId: true, closedBy: true, messageCount: true, messages: true, createdAt: true,
              ticket: { select: { number: true, status: true, userId: true, createdAt: true, closedAt: true } } },
  });
  if (!transcript) throw new HttpError(404, "Transcripción no encontrada");
  return transcript;
});
