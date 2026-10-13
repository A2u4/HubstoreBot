import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Downloaded as a file (never rendered inline on the dashboard origin: it contains user content). */
export const GET = guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, { bot, guildId, params }) => {
  const transcript = await db(bot.id).ticketTranscript.findFirst({
    where: { id: params.id, guildId }, select: { htmlContent: true, ticket: { select: { number: true } } },
  });
  if (!transcript?.htmlContent) throw new HttpError(404, "La transcripción HTML no está disponible");
  return new Response(transcript.htmlContent, { headers: {
    "content-type": "text/html; charset=utf-8",
    "content-disposition": `attachment; filename="ticket-${transcript.ticket?.number ?? "desconocido"}-transcripcion.html"`,
    "content-security-policy": "sandbox", "x-content-type-options": "nosniff",
  } });
});
