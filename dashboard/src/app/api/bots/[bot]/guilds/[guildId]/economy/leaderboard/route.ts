import { db } from "@/lib/server/db";
import { guildRoute, intParam } from "@/lib/server/route";

export const dynamic = "force-dynamic";

/** Richest members by wallet + bank (raw SQL: Prisma can't order by a sum of columns). */
export const GET = guildRoute(async (request, { bot, guildId }) => {
  const page = intParam(request.nextUrl.searchParams.get("page"), 1, 1, 1000);
  const take = 25;
  const prisma = db(bot.id);
  const [rows, totals] = await Promise.all([
    prisma.$queryRaw<Array<{ userId: string; wallet: number; bank: number }>>`
      SELECT "userId", wallet, bank FROM economy_accounts
      WHERE "guildId" = ${guildId} AND wallet + bank > 0
      ORDER BY wallet + bank DESC LIMIT ${take} OFFSET ${(page - 1) * take}`,
    prisma.economyAccount.aggregate({ where: { guildId }, _count: true, _sum: { wallet: true, bank: true } }),
  ]);
  return {
    rows, page, pages: Math.max(1, Math.ceil(totals._count / take)), accounts: totals._count,
    circulation: (totals._sum.wallet ?? 0) + (totals._sum.bank ?? 0),
  };
});
