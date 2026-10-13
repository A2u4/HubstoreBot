import { z } from "zod";
import { snowflake } from "@/lib/schemas/common";
import { botCall } from "@/lib/server/bot-api";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

const url = z.string().url().max(2000).or(z.literal("")).optional();
const sendSchema = z.object({
  channelId: snowflake,
  content: z.string().max(2000).optional(),
  embed: z.object({
    title: z.string().max(256).optional(), description: z.string().max(4096).optional(), color: z.string().max(7).optional(),
    titleUrl: url, authorName: z.string().max(256).optional(), authorIconUrl: url, footerText: z.string().max(2048).optional(),
    footerIconUrl: url, imageUrl: url, thumbnailUrl: url, timestamp: z.boolean().optional(),
    fields: z.array(z.object({ name: z.string().min(1).max(256), value: z.string().min(1).max(1024), inline: z.boolean().optional() })).max(25).optional(),
  }).optional(),
}).refine((v) => v.content || v.embed, "Escribe un texto o un embed");

/** The bot validates that the channel belongs to this guild before sending. */
export const POST = guildRoute(async (request, { bot, guildId }) =>
  botCall(bot, `/internal/guilds/${guildId}/messages/send`, { body: await readBody(request, sendSchema) }));
