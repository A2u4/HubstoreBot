import "server-only";
import path from "node:path";

function required(name: string, fallback?: string): string {
  const value = process.env[name] || fallback;
  if (!value) throw new Error(`Missing environment variable ${name}`);
  return value;
}

export const env = {
  get dashboardUrl(): string {
    return (process.env.DASHBOARD_URL || "http://localhost:3100").replace(/\/+$/, "");
  },
  /** Encrypts the session cookie. Falls back to API_SECRET so existing installs keep working. */
  get sessionSecret(): string {
    return required("SESSION_SECRET", process.env.API_SECRET);
  },
  /** Shared secret for the bots' internal HTTP API (x-internal-secret). */
  get apiSecret(): string {
    return required("API_SECRET");
  },
  /** Uploaded shop media. v1 kept them in <repo>/uploads, served at /bots/<bot>/api/uploads/<file>. */
  get uploadsDir(): string {
    return path.resolve(process.env.UPLOADS_DIR || path.join(process.cwd(), "..", "uploads"));
  },
  get secure(): boolean {
    return this.dashboardUrl.startsWith("https://");
  },
};
