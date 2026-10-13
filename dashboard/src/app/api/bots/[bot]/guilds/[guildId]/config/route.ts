import { configUpdateSchema, RESYNC_FIELDS } from "@/lib/schemas/config";
import { invalidateBot } from "@/lib/server/bot-api";
import { db, ensureGuildConfig } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { localizeRemoteImage } from "@/lib/server/media";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) => ensureGuildConfig(bot.id, guildId));

type Category = { id?: string; paymentOptions?: Array<Record<string, unknown>> };

/** Per-country stock/hidden are also edited from Discord (/tienda): keep them if a save omits those fields. */
function preserveCountryExtras(incoming: Category[], stored: unknown): Category[] {
  const previous = Array.isArray(stored) ? (stored as Category[]) : [];
  return incoming.map((category) => {
    const old = previous.find((c) => c?.id === category.id);
    if (!old || !Array.isArray(category.paymentOptions)) return category;
    return {
      ...category,
      paymentOptions: category.paymentOptions.map((option) => {
        const before = old.paymentOptions?.find((o) => o?.id === option.id);
        if (!before) return option;
        return {
          ...option,
          ...(option.stock === undefined && before.stock ? { stock: before.stock } : {}),
          ...(option.hidden === undefined && before.hidden === true ? { hidden: true } : {}),
        };
      }),
    };
  });
}

export const PATCH = guildRoute(async (request, { bot, guildId }) => {
  const data: Record<string, unknown> = await readBody(request, configUpdateSchema);
  if (!Object.keys(data).length) throw new HttpError(400, "No se proporcionaron campos válidos");

  const current = await ensureGuildConfig(bot.id, guildId);
  const merged = { ...current, ...data } as unknown as Record<string, number>;
  for (const [low, high, label] of [["xpPerMessageMin", "xpPerMessageMax", "XP por mensaje"], ["workMin", "workMax", "Trabajo"],
                                    ["crimeMin", "crimeMax", "Crimen"]] as const) {
    if (merged[low] > merged[high]) throw new HttpError(400, `${label}: el mínimo no puede ser mayor que el máximo`);
  }

  // v1 behaviour: shop banner/thumbnail links are copied to local storage so they never expire.
  if (typeof data.shopImage === "string") data.shopImage = await localizeRemoteImage(bot.id, data.shopImage, "banner");
  if (typeof data.shopThumbnail === "string") data.shopThumbnail = await localizeRemoteImage(bot.id, data.shopThumbnail, "thumbnail");
  if (Array.isArray(data.shopImages)) {
    data.shopImages = await Promise.all((data.shopImages as string[]).map((url) => localizeRemoteImage(bot.id, url, "banner")));
  }
  if (Array.isArray(data.shopCategories)) {
    data.shopCategories = preserveCountryExtras(data.shopCategories as Category[], current.shopCategories);
  }

  const updated = await db(bot.id).guildConfig.update({ where: { id: guildId }, data });
  await invalidateBot(bot, guildId, Object.keys(data).some((k) => RESYNC_FIELDS.has(k)));
  return updated;
});
