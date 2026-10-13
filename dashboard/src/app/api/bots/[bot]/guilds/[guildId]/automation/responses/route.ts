import { autoResponseCreate } from "@/lib/schemas/content";
import { collectionRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({ model: "autoResponse", create: autoResponseCreate, orderBy: { createdAt: "desc" }, notify: "invalidate" });
