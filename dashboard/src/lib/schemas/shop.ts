import { z } from "zod";

export const shopProductCreate = z.object({
  name: z.string().trim().min(1).max(255),
  category: z.string().trim().min(1).max(50).default("General"),
  description: z.string().max(2000).default(""),
  price: z.number().min(0),
  priceLabel: z.string().trim().max(100).nullable().optional(),
  stock: z.number().int().min(0),
  stockLabel: z.string().trim().max(100).nullable().optional(),
  image: z.string().url().nullable().optional(),
  images: z.array(z.string().url()).max(20).optional(),
  active: z.boolean().default(true),
}).strict();
export const shopProductUpdate = shopProductCreate.partial().strict();

const layout = { width: z.number().int().min(320).max(1920).default(960), height: z.number().int().min(180).max(1080).default(540) };
export const mediaEffectSchema = z.object({
  url: z.string().url(),
  effect: z.enum(["normal", "dark", "saturated", "soft", "mono"]),
  ...layout,
  fit: z.enum(["contain", "cover"]).default("cover"),
});
export const mediaPlaylistSchema = z.object({ urls: z.array(z.string().url()).min(2).max(20), ...layout });
