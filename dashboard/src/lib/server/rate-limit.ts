import "server-only";
import type { NextRequest } from "next/server";
import { TtlCache } from "./ttl-cache";

const buckets = new TtlCache<{ count: number; reset: number }>(60_000, 10_000);

export function clientIp(request: NextRequest): string {
  // nginx sets X-Real-IP; otherwise the last X-Forwarded-For hop is the one our proxy appended.
  const real = request.headers.get("x-real-ip");
  if (real) return real.trim();
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",").map((s) => s.trim()).filter(Boolean).at(-1) || "unknown";
  return "unknown";
}

/** Fixed-window limiter: ``limit`` requests per minute per IP and bucket. Returns false when exceeded. */
export function rateLimit(request: NextRequest, bucket: string, limit: number): boolean {
  const key = `${bucket}:${clientIp(request)}`;
  const now = Date.now();
  const entry = buckets.get(key);
  if (!entry || entry.reset < now) {
    buckets.set(key, { count: 1, reset: now + 60_000 });
    return true;
  }
  entry.count += 1;
  return entry.count <= limit;
}
