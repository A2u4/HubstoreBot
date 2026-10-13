import { itemRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { DELETE } = itemRoutes({ model: "levelReward", notify: "invalidate" });
