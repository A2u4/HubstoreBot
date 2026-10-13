import { botCall } from "@/lib/server/bot-api";
import { db } from "@/lib/server/db";
import { guildRoute } from "@/lib/server/route";

export const dynamic = "force-dynamic";

export const GET = guildRoute(async (_request, { bot, guildId }) => {
  const prisma = db(bot.id);
  const where = { guildId };
  const weekAgo = new Date(Date.now() - 7 * 86_400_000);
  const [live, counts, recentModActions] = await Promise.all([
    botCall<Record<string, unknown>>(bot, `/internal/guilds/${guildId}/overview`, { timeoutMs: 5000 }).catch(() => null),
    Promise.all([
      prisma.invite.count({ where: { guildId, fake: false, left: false } }),
      prisma.modAction.count({ where }),
      prisma.warning.count({ where }),
      prisma.ticket.count({ where: { guildId, status: "open" } }),
      prisma.ticket.count({ where: { guildId, createdAt: { gte: weekAgo } } }),
      prisma.reputation.count({ where }),
      prisma.giveaway.count({ where: { guildId, ended: false } }),
      prisma.suggestion.count({ where: { guildId, status: "pending" } }),
      prisma.memberLevel.count({ where: { guildId, xp: { gt: 0 } } }),
      prisma.economyAccount.count({ where }),
      prisma.backup.count({ where }),
    ]),
    prisma.modAction.findMany({ where, orderBy: { createdAt: "desc" }, take: 8 }),
  ]);
  const [validInvites, modActions, warnings, openTickets, ticketsThisWeek, reputation, activeGiveaways, pendingSuggestions,
         rankedMembers, economyAccounts, backups] = counts;
  return {
    live,
    counts: { validInvites, modActions, warnings, openTickets, ticketsThisWeek, reputation, activeGiveaways, pendingSuggestions,
              rankedMembers, economyAccounts, backups },
    recentModActions,
  };
});
