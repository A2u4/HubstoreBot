import { botCall } from "@/lib/server/bot-api";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const POST = guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, { bot, guildId, params, session }) =>
  botCall(bot, "/internal/rifas/cancel", { body: { guildId, rifaId: params.id, by: session.id, reason: "Cancelada desde el dashboard" } }));
