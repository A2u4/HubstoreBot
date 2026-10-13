import { reactionRoleUpdate } from "@/lib/schemas/content";
import { itemRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { PATCH, DELETE } = itemRoutes({ model: "reactionRole", update: reactionRoleUpdate, channelFields: ["channelId"], notify: "invalidate" });
