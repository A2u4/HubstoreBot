import fs from "node:fs/promises";
import path from "node:path";
import { env } from "@/lib/server/env";
import { SAFE_FILENAME } from "@/lib/server/media";

const TYPES: Record<string, string> = { ".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

/**
 * Public media used in Discord embeds (same URL as v1: /bots/<bot>/api/uploads/<file>).
 * Filenames are random or content hashes, so they are immutable and safe to cache.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ bot: string; file: string }> }) {
  const { file } = await params;
  const type = TYPES[path.extname(file).toLowerCase()];
  if (!SAFE_FILENAME.test(file) || !type) return new Response("Not found", { status: 404 });
  try {
    const data = await fs.readFile(path.join(env.uploadsDir, file));
    return new Response(new Uint8Array(data), { headers: {
      "content-type": type, "cache-control": "public, max-age=2592000, immutable", "x-content-type-options": "nosniff",
    } });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
