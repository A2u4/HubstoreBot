import { z } from "zod";
import { cronExpression, hexColor, optionalUrl, snowflake } from "./common";

export const autoResponseCreate = z.object({
  trigger: z.string().trim().min(1).max(200),
  response: z.string().trim().min(1).max(2000),
  matchType: z.enum(["exact", "contains", "startsWith", "regex"]).default("contains"),
  enabled: z.boolean().default(true),
}).strict().refine((v) => {
  if (v.matchType !== "regex") return true;
  try { new RegExp(v.trigger); return true; } catch { return false; }
}, { message: "Expresión regular inválida", path: ["trigger"] });
export const autoResponseUpdate = z.object({
  trigger: z.string().trim().min(1).max(200).optional(),
  response: z.string().trim().min(1).max(2000).optional(),
  matchType: z.enum(["exact", "contains", "startsWith", "regex"]).optional(),
  enabled: z.boolean().optional(),
}).strict();

export const scheduledCreate = z.object({
  channelId: snowflake,
  message: z.string().trim().min(1).max(2000),
  cron: cronExpression,
  enabled: z.boolean().default(true),
}).strict();
export const scheduledUpdate = scheduledCreate.partial().strict();

export const reactionRoleCreate = z.object({
  channelId: snowflake,
  messageId: snowflake,
  emoji: z.string().trim().min(1).max(100),
  roleId: snowflake,
  type: z.enum(["toggle", "give", "remove"]).default("toggle"),
}).strict();
export const reactionRoleUpdate = reactionRoleCreate.partial().strict();

export const stickyCreate = z.object({
  channelIds: z.array(snowflake).min(1).max(50),
  title: z.string().max(256).nullable().optional(),
  description: z.string().min(1).max(4000),
  color: hexColor.default("#FFFFFF"),
  plainText: z.boolean().default(false),
  enabled: z.boolean().default(true),
}).strict();
export const stickyUpdate = z.object({
  title: z.string().max(256).nullable().optional(),
  description: z.string().min(1).max(4000).optional(),
  color: hexColor.optional(),
  plainText: z.boolean().optional(),
  enabled: z.boolean().optional(),
}).strict();

const commandName = z.string().trim().toLowerCase()
  .regex(/^[-_a-z0-9ñáéíóúü]{1,32}$/, "Nombre inválido: minúsculas, números, - o _ (máx. 32)");

export const textCommandCreate = z.object({
  name: commandName,
  text: z.string().trim().min(1).max(2000),
  embedColor: hexColor.default("#FFFFFF"),
  title: z.string().max(256).nullable().optional(),
  thumbnailUrl: optionalUrl,
  showAuthor: z.boolean().default(true),
  enabled: z.boolean().default(true),
}).strict();
export const textCommandUpdate = z.object({
  name: commandName.optional(),
  text: z.string().trim().min(1).max(2000).optional(),
  embedColor: hexColor.optional(),
  title: z.string().max(256).nullable().optional(),
  thumbnailUrl: optionalUrl,
  showAuthor: z.boolean().optional(),
  enabled: z.boolean().optional(),
}).strict();
