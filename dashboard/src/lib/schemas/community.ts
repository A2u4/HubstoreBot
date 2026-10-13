import { z } from "zod";
import { snowflake } from "./common";

export const levelRewardCreate = z.object({ level: z.number().int().min(1).max(500), roleId: snowflake }).strict();

export const economyItemCreate = z.object({
  name: z.string().trim().min(1).max(60),
  description: z.string().trim().max(500).default(""),
  emoji: z.string().trim().max(64).nullable().optional(),
  price: z.number().int().min(0).max(2_000_000_000),
  roleId: snowflake.nullable().optional(),
  stock: z.number().int().min(0).max(1_000_000).nullable().optional(),
  active: z.boolean().default(true),
}).strict();
export const economyItemUpdate = z.object({
  name: z.string().trim().min(1).max(60).optional(),
  description: z.string().trim().max(500).optional(),
  emoji: z.string().trim().max(64).nullable().optional(),
  price: z.number().int().min(0).max(2_000_000_000).optional(),
  roleId: snowflake.nullable().optional(),
  stock: z.number().int().min(0).max(1_000_000).nullable().optional(),
  active: z.boolean().optional(),
}).strict();
