import { shopProductCreate } from "@/lib/schemas/shop";
import { collectionRoutes } from "@/lib/server/crud";
import { refreshShop } from "@/lib/server/shop";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({
  model: "shopProduct", create: shopProductCreate, orderBy: { createdAt: "desc" }, after: (ctx) => refreshShop(ctx.bot, ctx.guildId),
});
