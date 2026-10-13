import { z } from "zod";
import { CLONE_SECTIONS } from "@/lib/clone-sections";
import { snowflake } from "@/lib/schemas/common";
import { assertGuildAccess } from "@/lib/server/access";
import { invalidateBot } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { HttpError } from "@/lib/server/errors";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

const schema = z.object({
  targetGuildId: snowflake,
  sections: z.array(z.enum(Object.keys(CLONE_SECTIONS) as [string, ...string[]])).min(1),
});

/** Copy config sections to another server of the same bot; the user must manage the target too. */
export const POST = guildRoute(async (request, { bot, guildId, session }) => {
  const { targetGuildId, sections } = await readBody(request, schema);
  if (targetGuildId === guildId) throw new HttpError(400, "El servidor de origen y el de destino deben ser diferentes");
  await assertGuildAccess(session, targetGuildId);
  const source = await db(bot.id).guildConfig.findUnique({ where: { id: guildId } });
  if (!source) throw new HttpError(404, "Configuración de origen no encontrada");
  const data = Object.fromEntries(sections.flatMap((s) => CLONE_SECTIONS[s].fields).map((f) => [f, (source as Record<string, unknown>)[f]])
    .filter(([, v]) => v !== undefined));
  await db(bot.id).guildConfig.upsert({ where: { id: targetGuildId }, create: { id: targetGuildId, ...data }, update: data });
  await invalidateBot(bot, targetGuildId, true);
  return { success: true, cloned: Object.keys(data).length, targetGuildId };
});
