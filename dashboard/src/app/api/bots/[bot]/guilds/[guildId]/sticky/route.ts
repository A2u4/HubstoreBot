import { stickyCreate } from "@/lib/schemas/content";
import { botFetch, invalidateBot } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { assertGuildChannels } from "@/lib/server/channels";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) =>
  db(bot.id).stickyMessage.findMany({ where: { guildId }, orderBy: { createdAt: "desc" } }));

/** Create or replace the sticky of one or many channels (one sticky per channel), then post it right away. */
export const POST = guildRoute(async (request, { bot, guildId, session }) => {
  const { channelIds, ...data } = await readBody(request, stickyCreate);
  await assertGuildChannels(bot, guildId, channelIds);
  const prisma = db(bot.id);
  const rows = await prisma.$transaction(channelIds.map((channelId) => prisma.stickyMessage.upsert({
    where: { channelId },
    create: { ...data, guildId, channelId, createdBy: session.id },
    update: { ...data, messageId: null },
  })));
  await invalidateBot(bot, guildId);
  await Promise.allSettled(channelIds.map((channelId) => botFetch(bot, "/internal/sticky/resend", { body: { guildId, channelId } })));
  return rows;
});
