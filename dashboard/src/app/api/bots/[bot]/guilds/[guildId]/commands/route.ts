import { botCall } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

interface BotCommand { name: string; parent?: string; subcommand?: string; module: string; description: string; adminOnlyByDefault: boolean }

/** Commands come from the live bot (rows keyed like CommandPermission: "root" or "root leaf"). */
export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const [commands, stored] = await Promise.all([
    botCall<BotCommand[]>(bot, `/internal/guilds/${guildId}/commands`).catch(() => null),
    db(bot.id).commandPermission.findMany({ where: { guildId } }),
  ]);
  const byKey = new Map(stored.map((p) => [p.command, p]));
  return {
    botOnline: commands !== null,
    commands: (commands ?? []).map((c) => {
      const own = byKey.get(c.name);
      const inherited = c.parent ? byKey.get(c.parent) : undefined;
      const perm = own ?? inherited;
      return { ...c, disabled: perm?.disabled ?? false, roleIds: perm?.roleIds ?? [], configured: Boolean(own), inherited: !own && Boolean(inherited) };
    }),
  };
});
