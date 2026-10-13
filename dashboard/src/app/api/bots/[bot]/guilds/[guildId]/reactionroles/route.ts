import { reactionRoleCreate } from "@/lib/schemas/content";
import { collectionRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({ model: "reactionRole", create: reactionRoleCreate, orderBy: { messageId: "asc" }, channelFields: ["channelId"], notify: "invalidate" });
