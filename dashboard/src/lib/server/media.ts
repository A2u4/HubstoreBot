import "server-only";
import crypto from "node:crypto";
import dns from "node:dns/promises";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import sharp, { type Sharp } from "sharp";
import { env } from "./env";
import { HttpError } from "./errors";

// ─── Storage ────────────────────────────────────────────────────────────────

/** Files are served at /bots/<bot>/api/uploads/<file> (same URL shape as v1, so stored links keep working). */
export function uploadUrl(botId: string, filename: string): string {
  return `${env.dashboardUrl}/bots/${botId}/api/uploads/${filename}`;
}

export const SAFE_FILENAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$/;

async function writeUpload(filename: string, data: Buffer): Promise<void> {
  await fs.mkdir(env.uploadsDir, { recursive: true });
  await fs.writeFile(path.join(env.uploadsDir, filename), data);
}

async function exists(filename: string): Promise<boolean> {
  return fs.access(path.join(env.uploadsDir, filename)).then(() => true, () => false);
}

function randomName(ext: string): string {
  return `${Date.now()}-${crypto.randomBytes(4).toString("hex")}${ext}`;
}

const IMAGE_TYPES: Record<string, string> = { "image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp" };
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** Store a dashboard upload. Non-GIF images are re-encoded through sharp (drops metadata, rejects non-images). */
export async function saveUpload(file: File, kind: string | null): Promise<string> {
  const ext = IMAGE_TYPES[file.type];
  if (!ext) throw new HttpError(415, "Solo se permiten imágenes GIF, PNG, JPG o WebP");
  if (file.size > MAX_UPLOAD_BYTES) throw new HttpError(413, "El archivo supera 20 MB");
  const buffer = Buffer.from(await file.arrayBuffer());
  const filename = randomName(ext);
  if (ext === ".gif") {
    const signature = buffer.subarray(0, 6).toString("ascii");
    if (signature !== "GIF87a" && signature !== "GIF89a") throw new HttpError(400, "El archivo no es un GIF válido");
    await writeUpload(filename, buffer);
    return filename;
  }
  try {
    let image = sharp(buffer);
    await image.metadata();
    if (kind === "thumbnail") image = image.resize(128, 128, { fit: "cover", position: "centre" });
    else if (kind === "product") image = image.resize(600, 600, { fit: "inside", withoutEnlargement: true });
    await writeUpload(filename, kind === "banner" ? buffer : await image.toBuffer());
    return filename;
  } catch {
    throw new HttpError(400, "El archivo no contiene una imagen válida");
  }
}

// ─── Remote media (SSRF-safe) ───────────────────────────────────────────────

const MAX_REMOTE_BYTES = 20 * 1024 * 1024;
const BLOCKED = new net.BlockList();
for (const [addr, prefix] of [["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8], ["169.254.0.0", 16],
                              ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15],
                              ["224.0.0.0", 4], ["240.0.0.0", 4]] as const) BLOCKED.addSubnet(addr, prefix, "ipv4");
for (const [addr, prefix] of [["::", 128], ["::1", 128], ["fc00::", 7], ["fe80::", 10], ["ff00::", 8]] as const) {
  BLOCKED.addSubnet(addr, prefix, "ipv6");
}

function blockedAddress(address: string): boolean {
  const family = net.isIP(address);
  return family === 0 || BLOCKED.check(address, family === 6 ? "ipv6" : "ipv4");
}

/** Reject non-http(s) URLs and hosts resolving to private/loopback/link-local networks (cloud metadata etc.). */
async function safeUrl(raw: string): Promise<boolean> {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return false;
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (!host || host === "localhost" || host.endsWith(".local") || host.endsWith(".internal")) return false;
  if (net.isIP(host)) return !blockedAddress(host);
  try {
    const records = await dns.lookup(host, { all: true, verbatim: true });
    return records.length > 0 && records.every((r) => !blockedAddress(r.address));
  } catch {
    return false;
  }
}

/** Fetch following redirects manually so every hop is re-validated. */
export async function fetchRemote(rawUrl: string): Promise<Response> {
  const signal = AbortSignal.timeout(15_000);
  let url = rawUrl;
  for (let hop = 0; hop <= 5; hop += 1) {
    if (!(await safeUrl(url))) throw new HttpError(400, "La URL no está permitida");
    const response = await fetch(url, { signal, redirect: "manual", cache: "no-store" });
    const location = response.headers.get("location");
    if (response.status >= 300 && response.status < 400 && location) {
      await response.body?.cancel().catch(() => undefined);
      url = new URL(location, url).toString();
      continue;
    }
    return response;
  }
  throw new HttpError(400, "Demasiadas redirecciones");
}

export async function readLimited(response: Response, limit = MAX_REMOTE_BYTES): Promise<Buffer> {
  if (Number(response.headers.get("content-length") || 0) > limit) throw new HttpError(413, "El archivo remoto es demasiado grande");
  if (!response.body) return Buffer.from(await response.arrayBuffer());
  const reader = response.body.getReader();
  const chunks: Buffer[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel();
      throw new HttpError(413, "El archivo remoto es demasiado grande");
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks, total);
}

/** Resolve page links (Tenor, Giphy...) to their og:image and download the media. */
async function downloadMedia(url: string): Promise<{ buffer: Buffer; contentType: string; finalUrl: string }> {
  let response = await fetchRemote(url);
  if (!response.ok) throw new HttpError(400, "No se pudo descargar el archivo");
  let finalUrl = url;
  let contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/html")) {
    const html = (await readLimited(response, 2 * 1024 * 1024)).toString("utf8");
    const match = html.match(/<meta[^>]*property=["']og:image["'][^>]*content=["']([^"']+)["']/i)
      || html.match(/<meta[^>]*content=["']([^"']+)["'][^>]*property=["']og:image["']/i);
    if (!match) throw new HttpError(400, "El enlace no contiene una imagen");
    finalUrl = match[1].replace(/&amp;/g, "&");
    response = await fetchRemote(finalUrl);
    if (!response.ok) throw new HttpError(400, "No se pudo descargar el archivo");
    contentType = response.headers.get("content-type") || "";
  }
  return { buffer: await readLimited(response), contentType, finalUrl: response.url || finalUrl };
}

/**
 * v1 behaviour for shop banners/thumbnails: copy remote images locally (cropped)
 * so they keep working after the source expires. GIFs stay as direct links;
 * on any failure the original URL is kept.
 */
export async function localizeRemoteImage(botId: string, url: string, kind: "banner" | "thumbnail"): Promise<string> {
  if (!url || !/^https?:\/\//.test(url) || url.includes("/api/uploads/")) return url;
  try {
    const media = await downloadMedia(url);
    if (media.contentType.includes("gif") || /\.gif(\?|$)/i.test(media.finalUrl)) return media.finalUrl;
    const [width, height] = kind === "banner" ? [960, 540] : [128, 128];
    const output = await sharp(media.buffer).resize(width, height, { fit: "cover", position: "centre" }).png().toBuffer();
    const filename = randomName(".png");
    await writeUpload(filename, output);
    return uploadUrl(botId, filename);
  } catch {
    return url;
  }
}

// ─── Effects & playlists (ported from v1 mediaEffects.ts) ───────────────────

export type MediaEffect = "normal" | "dark" | "saturated" | "soft" | "mono";
export interface MediaLayout { width: number; height: number; fit: "contain" | "cover" }

const MAX_ANIMATED_PIXELS = 80_000_000;
const FRAME_MS = 150;
const STATIC_MS = 3_000;
const MAX_DURATION_MS = 20_000;
const MAX_FRAMES = MAX_DURATION_MS / FRAME_MS;
const TARGET_BYTES = 8 * 1024 * 1024;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, Math.round(value)));

function applyEffect(pipeline: Sharp, effect: MediaEffect): Sharp {
  switch (effect) {
    case "normal": return pipeline;
    case "mono": return pipeline.grayscale();
    case "dark": return pipeline.modulate({ brightness: 0.58, saturation: 0.9 });
    case "saturated": return pipeline.modulate({ saturation: 1.7, brightness: 1.03 });
    case "soft": return pipeline.modulate({ saturation: 0.78, brightness: 1.04 }).linear(0.86, 18);
  }
}

/** Create a resized, filtered copy; the original upload is never overwritten. Cached by content hash. */
export async function createEffectCopy(sourceUrl: string, effect: MediaEffect, layout: MediaLayout) {
  const { buffer: source } = await downloadMedia(sourceUrl);
  const metadata = await sharp(source, { animated: true, limitInputPixels: MAX_ANIMATED_PIXELS }).metadata();
  const pages = Math.max(1, Number(metadata.pages || 1));
  const width = Math.max(1, Number(metadata.width || 1));
  const pageHeight = Math.max(1, Number(metadata.pageHeight || metadata.height || 1));
  if (pages > 240 || width * pageHeight * pages > MAX_ANIMATED_PIXELS) {
    throw new HttpError(413, "El GIF es demasiado largo o grande para procesarlo de forma segura");
  }
  const outW = clamp(layout.width, 320, 1920);
  const outH = clamp(layout.height, 180, 1080);
  if (outW * outH * pages > MAX_ANIMATED_PIXELS) throw new HttpError(413, "El tamaño elegido es demasiado grande para este GIF");

  const animated = pages > 1;
  const ext = animated || metadata.format === "gif" ? ".gif" : ".webp";
  const hash = crypto.createHash("sha256").update(source).update(effect).update(`${outW}x${outH}-${layout.fit}-hq-v3`)
    .digest("hex").slice(0, 20);
  const filename = `effect-${effect}-${hash}${ext}`;
  if (!(await exists(filename))) {
    const pipeline = applyEffect(sharp(source, { animated, limitInputPixels: MAX_ANIMATED_PIXELS }).resize(outW, outH, {
      fit: layout.fit, position: "centre", background: { r: 10, g: 10, b: 10, alpha: 1 }, kernel: sharp.kernel.lanczos3,
    }), effect);
    const untouched = ext === ".gif" && effect === "normal" && width === outW && pageHeight === outH;
    const output = untouched ? source : ext === ".gif"
      ? await pipeline.gif({ effort: 7, colours: 256, dither: 0, interFrameMaxError: 0, interPaletteMaxError: 0, reuse: false }).toBuffer()
      : await pipeline.webp({ quality: 92, effort: 5 }).toBuffer();
    await writeUpload(filename, output);
  }
  return { filename, animated, frames: pages };
}

function delaysOf(delays: number[] | undefined, pages: number): number[] {
  if (pages <= 1) return [STATIC_MS];
  return Array.from({ length: pages }, (_, i) => {
    const delay = Number(delays?.[i] ?? delays?.at(-1) ?? FRAME_MS);
    return Math.min(10_000, Math.max(20, Math.round(delay / 10) * 10));
  });
}

async function encodePlaylist(sources: Buffer[], width: number, height: number, colours: number) {
  const clips: Array<{ frames: Buffer; frameBytes: number; delays: number[]; duration: number }> = [];
  for (const source of sources) { // sequential: decoding 20 GIFs at once could exhaust RAM
    const image = sharp(source, { animated: true, limitInputPixels: MAX_ANIMATED_PIXELS });
    const meta = await image.metadata();
    const pages = Math.max(1, Number(meta.pages || 1));
    const pageHeight = Math.max(1, Number(meta.pageHeight || meta.height || 1));
    if (pages > MAX_FRAMES || Math.max(1, Number(meta.width || 1)) * pageHeight * pages > MAX_ANIMATED_PIXELS) {
      throw new HttpError(413, "Uno de los GIFs es demasiado largo o grande para procesarlo de forma segura");
    }
    const delays = delaysOf(meta.delay, pages);
    const { data, info } = await image.resize(width, height, { fit: "cover", position: "centre", kernel: sharp.kernel.lanczos3 })
      .ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    clips.push({ frames: data, frameBytes: width * height * info.channels, delays, duration: delays.reduce((a, b) => a + b, 0) });
  }
  if (clips.reduce((t, c) => t + c.duration, 0) > MAX_DURATION_MS) {
    throw new HttpError(413, "La secuencia supera 20 segundos. Reduce la cantidad o duración de los GIFs");
  }
  const frames: Buffer[] = [];
  const delays: number[] = [];
  for (const clip of clips) {
    for (let elapsed = 0; elapsed < clip.duration; elapsed += FRAME_MS) {
      let cursor = 0;
      let index = clip.delays.length - 1;
      for (let i = 0; i < clip.delays.length; i += 1) {
        cursor += clip.delays[i];
        if (elapsed < cursor) { index = i; break; }
      }
      frames.push(clip.frames.subarray(index * clip.frameBytes, (index + 1) * clip.frameBytes));
      delays.push(Math.max(10, Math.round(Math.min(FRAME_MS, clip.duration - elapsed) / 10) * 10));
    }
  }
  if (!frames.length || frames.length > MAX_FRAMES) throw new HttpError(413, "La secuencia contiene demasiados cuadros");
  const buffer = await sharp(Buffer.concat(frames), { raw: { width, height: height * frames.length, pageHeight: height, channels: 4 } })
    .gif({ loop: 0, delay: delays, effort: 7, colours, dither: 0.1, interFrameMaxError: 0, interPaletteMaxError: 0, reuse: false })
    .toBuffer();
  return { buffer, frames: frames.length, durationMs: delays.reduce((a, b) => a + b, 0) };
}

/** Join several GIFs into one animation so Discord shows one stable URL (no periodic message edits). */
export async function createPlaylist(urls: string[], requested: { width: number; height: number }) {
  if (urls.length < 2) throw new HttpError(400, "Agrega por lo menos 2 GIFs para crear la secuencia");
  if (urls.length > 20) throw new HttpError(400, "La secuencia admite hasta 20 GIFs");
  const sources: Buffer[] = [];
  let total = 0;
  for (const url of urls) {
    const { buffer } = await downloadMedia(url);
    total += buffer.length;
    if (total > 60 * 1024 * 1024) throw new HttpError(413, "La secuencia completa es demasiado pesada");
    sources.push(buffer);
  }
  const reqW = clamp(requested.width, 320, 1920);
  const reqH = clamp(requested.height, 180, 1080);
  const longEdge = Math.max(reqW, reqH);
  const candidates = [720, 560, 400, 320]
    .map((edge) => Math.min(1, edge / longEdge))
    .map((scale) => ({ width: Math.max(1, Math.round(reqW * scale)), height: Math.max(1, Math.round(reqH * scale)) }))
    .filter((c, i, all) => all.findIndex((o) => o.width === c.width && o.height === c.height) === i)
    .filter((c) => c.width * c.height * MAX_FRAMES <= MAX_ANIMATED_PIXELS)
    .map((c, i) => ({ ...c, colours: i === 0 ? 160 : 128 }));
  if (!candidates.length) throw new HttpError(413, "El tamaño elegido es demasiado grande para una secuencia");

  const hash = crypto.createHash("sha256");
  sources.forEach((s) => hash.update(s));
  hash.update(`${reqW}x${reqH}-cover-playlist-v2`);
  const filename = `playlist-${hash.digest("hex").slice(0, 20)}.gif`;

  if (await exists(filename)) {
    const filePath = path.join(env.uploadsDir, filename);
    const meta = await sharp(filePath, { animated: true }).metadata();
    const pages = Math.max(1, Number(meta.pages || 1));
    return {
      filename, animated: true, frames: pages, clips: sources.length,
      durationMs: delaysOf(meta.delay, pages).reduce((a, b) => a + b, 0),
      width: Number(meta.width || candidates[0].width), height: Number(meta.pageHeight || meta.height || candidates[0].height),
      sizeBytes: (await fs.stat(filePath)).size,
    };
  }
  let encoded: Awaited<ReturnType<typeof encodePlaylist>> | null = null;
  let output = candidates[0];
  for (const candidate of candidates) {
    output = candidate;
    encoded = await encodePlaylist(sources, candidate.width, candidate.height, candidate.colours);
    if (encoded.buffer.length <= TARGET_BYTES) break;
  }
  if (!encoded || encoded.buffer.length > 25 * 1024 * 1024) {
    throw new HttpError(413, "La secuencia sigue siendo demasiado pesada. Reduce la cantidad o duración de los GIFs");
  }
  await writeUpload(filename, encoded.buffer);
  return {
    filename, animated: true, frames: encoded.frames, clips: sources.length, durationMs: encoded.durationMs,
    width: output.width, height: output.height, sizeBytes: encoded.buffer.length,
  };
}
