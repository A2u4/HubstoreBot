import "server-only";
import { botCall } from "./bot-api";
import type { BotInfo } from "./bots";
import { db } from "./db";
import { HttpError } from "./errors";
import type { Session } from "./session";

/** Custom text commands become guild slash commands: the name can't clash with a built-in or another custom one. */
export async function prepareTextCommand(
  data: Record<string, unknown>,
  ctx: { bot: BotInfo; guildId: string; session: Session },
  existing: { id: string } | null,
): Promise<Record<string, unknown>> {
  const name = data.name as string | undefined;
  if (name) {
    const builtins = await botCall<Array<{ name: string; parent?: string }>>(ctx.bot, `/internal/guilds/${ctx.guildId}/commands`)
      .catch(() => [] as Array<{ name: string; parent?: string }>);
    if (builtins.some((c) => (c.parent ?? c.name) === name)) throw new HttpError(409, `/${name} ya es un comando del bot`);
    const clash = await db(ctx.bot.id).customTextCommand.findFirst({ where: { guildId: ctx.guildId, name, NOT: existing ? { id: existing.id } : undefined } });
    if (clash) throw new HttpError(409, `Ya existe el comando de texto /${name}`);
  }
  if (typeof data.embedColor === "string" && !data.embedColor.startsWith("#")) data.embedColor = `#${data.embedColor}`;
  return existing ? data : { ...data, createdById: ctx.session.id };
}
