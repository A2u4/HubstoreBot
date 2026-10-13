import { economyItemCreate } from "@/lib/schemas/community";
import { collectionRoutes } from "@/lib/server/crud";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({ model: "economyItem", create: economyItemCreate, orderBy: [{ price: "asc" }, { name: "asc" }] });
