import { HttpError } from "@/lib/server/errors";
import { saveUpload, uploadUrl } from "@/lib/server/media";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Multipart upload (field "file", optional "type": banner | thumbnail | product). */
export const POST = guildRoute(async (request, { bot }) => {
  const form = await request.formData().catch(() => null);
  const file = form?.get("file");
  if (!(file instanceof File)) throw new HttpError(400, "No se ha subido ningún archivo");
  const filename = await saveUpload(file, typeof form?.get("type") === "string" ? (form!.get("type") as string) : null);
  return { success: true, filename, url: uploadUrl(bot.id, filename) };
});
