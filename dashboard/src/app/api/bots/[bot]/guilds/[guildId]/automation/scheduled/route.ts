import { scheduledCreate } from "@/lib/schemas/content";
import { collectionRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({ model: "scheduledMessage", create: scheduledCreate, orderBy: { createdAt: "desc" }, channelFields: ["channelId"], notify: "invalidate" });
