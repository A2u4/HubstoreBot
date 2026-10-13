import { mediaPlaylistSchema } from "@/lib/schemas/shop";
import { createPlaylist, uploadUrl } from "@/lib/server/media";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

export const POST = guildRoute(async (request, { bot }) => {
  const { urls, width, height } = await readBody(request, mediaPlaylistSchema);
  const result = await createPlaylist(urls, { width, height });
  return { success: true, ...result, url: uploadUrl(bot.id, result.filename) };
});
