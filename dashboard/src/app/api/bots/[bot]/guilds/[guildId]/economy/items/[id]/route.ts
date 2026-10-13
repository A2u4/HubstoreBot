import { economyItemUpdate } from "@/lib/schemas/community";
import { itemRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { PATCH, DELETE } = itemRoutes({ model: "economyItem", update: economyItemUpdate });
