import { z } from "zod";

export const snowflake = z.string().regex(/^\d{17,20}$/, "Debe ser un ID válido de Discord");
/** Optional channel/role id: "" and null both clear it. */
export const optionalSnowflake = z.union([snowflake, z.literal(""), z.null()]).optional()
  .transform((v) => (v === "" ? null : v));
export const snowflakes = z.array(snowflake).max(250);
export const hexColor = z.string().regex(/^#?[0-9a-fA-F]{6}$/, "Color hex inválido (#RRGGBB)");
export const optionalUrl = z.union([z.string().url().max(2000), z.literal(""), z.null()]).optional()
  .transform((v) => (v === "" ? null : v));
export const buttonStyle = z.enum(["Primary", "Secondary", "Success", "Danger"]);

/** 5/6-field cron (node-cron style) or the dashboard's fixed-interval form "@every:<ms>". */
const cronField = /^(\*|\?|[0-9A-Za-z]+(-[0-9A-Za-z]+)?)(\/\d+)?(,(\*|[0-9A-Za-z]+(-[0-9A-Za-z]+)?)(\/\d+)?)*$/;
export const cronExpression = z.string().trim().min(1).max(100).refine((value) => {
  const every = /^@every:(\d+)$/.exec(value);
  if (every) return Number(every[1]) >= 60_000;
  const fields = value.split(/\s+/);
  return (fields.length === 5 || fields.length === 6) && fields.every((f) => cronField.test(f));
}, "La expresión de programación no es válida");
