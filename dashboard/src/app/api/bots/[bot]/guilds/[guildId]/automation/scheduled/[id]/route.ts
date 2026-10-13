import { scheduledUpdate } from "@/lib/schemas/content";
import { itemRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { PATCH, DELETE } = itemRoutes({ model: "scheduledMessage", update: scheduledUpdate, channelFields: ["channelId"], notify: "invalidate" });
