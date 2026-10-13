import { mediaEffectSchema } from "@/lib/schemas/shop";
import { createEffectCopy, uploadUrl } from "@/lib/server/media";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export const POST = guildRoute(async (request, { bot }) => {
  const { url, effect, width, height, fit } = await readBody(request, mediaEffectSchema);
  const result = await createEffectCopy(url, effect, { width, height, fit });
  return { success: true, ...result, url: uploadUrl(bot.id, result.filename) };
});
