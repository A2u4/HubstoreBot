import { levelRewardCreate } from "@/lib/schemas/community";
import { collectionRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({ model: "levelReward", create: levelRewardCreate, orderBy: { level: "asc" }, notify: "invalidate" });
