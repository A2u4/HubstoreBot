import { z } from "zod";
import { snowflakes } from "@/lib/schemas/common";
import { invalidateBot } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { guildRoute, readBody } from "@/lib/server/route";

export const dynamic = "force-dynamic";

const schema = z.object({
  command: z.string().trim().min(1).max(70).regex(/^[-_\p{L}\p{N}]+( [-_\p{L}\p{N}]+)?$/u),
  disabled: z.boolean().optional(),
  roleIds: snowflakes.max(100).optional(),
  reset: z.boolean().optional(),
}).strict();

/** Upsert a command's dashboard permission, or delete it with ``reset`` (back to the defaults). */
export const PUT = guildRoute(async (request, { bot, guildId }) => {
  const { command, reset, ...data } = await readBody(request, schema);
  const prisma = db(bot.id);
  if (reset) {
    await prisma.commandPermission.deleteMany({ where: { guildId, command } });
  } else {
    await prisma.commandPermission.upsert({
      where: { guildId_command: { guildId, command } },
      create: { guildId, command, disabled: data.disabled ?? false, roleIds: data.roleIds ?? [] },
      update: data,
    });
  }
  await invalidateBot(bot, guildId);
  return { success: true };
});
