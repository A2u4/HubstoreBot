import { ticketPanelCreate } from "@/lib/schemas/tickets";
import { collectionRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({
  model: "ticketPanel", create: ticketPanelCreate, orderBy: { createdAt: "asc" },
  include: { _count: { select: { tickets: true, transcripts: true } } },
  channelFields: ["channelId", "transcriptChannelId", "logChannelId"], notify: "invalidate",
});
