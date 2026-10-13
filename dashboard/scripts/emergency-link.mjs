// Prints a 10-minute emergency login link. Requires DASHBOARD_EMERGENCY_LOGIN=true on the server.
import { createHmac } from "node:crypto";
import path from "node:path";
import nextEnv from "@next/env";

nextEnv.loadEnvConfig(path.resolve(import.meta.dirname, "..", ".."));
const secret = process.env.SESSION_SECRET || process.env.API_SECRET;
if (!secret) throw new Error("SESSION_SECRET (or API_SECRET) is not set");
const expires = Date.now() + 10 * 60_000;
const sig = createHmac("sha256", secret).update(`emergency:${expires}`).digest("hex");
const base = (process.env.DASHBOARD_URL || "http://localhost:3100").replace(/\/+$/, "");
console.log(`${base}/api/auth/emergency?expires=${expires}&sig=${sig}`);
