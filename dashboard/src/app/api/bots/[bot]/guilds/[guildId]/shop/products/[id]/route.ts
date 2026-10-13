import { shopProductUpdate } from "@/lib/schemas/shop";
import { itemRoutes } from "@/lib/server/crud";
import { refreshShop } from "@/lib/server/shop";

export const dynamic = "force-dynamic";
export const { PATCH, DELETE } = itemRoutes({ model: "shopProduct", update: shopProductUpdate, after: (ctx) => refreshShop(ctx.bot, ctx.guildId) });
