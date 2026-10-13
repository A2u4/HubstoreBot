import "server-only";
import type { PrismaClient } from "@prisma/client";
import type { NextRequest } from "next/server";
import type { ZodTypeAny } from "zod";
import { invalidateBot } from "./bot-api";
import { assertGuildChannels } from "./channels";
import { db } from "./db";
import { HttpError } from "./errors";
import { type GuildContext, guildRoute, readBody } from "./route";

type Row = Record<string, unknown> & { id: string };

/** The subset of a Prisma model delegate the generic routes need. */
interface Delegate {
  findMany(args: object): Promise<Row[]>;
  findFirst(args: object): Promise<Row | null>;
  count(args: object): Promise<number>;
  create(args: object): Promise<Row>;
  updateMany(args: object): Promise<{ count: number }>;
  deleteMany(args: object): Promise<{ count: number }>;
}

export type ModelName =
  | "autoResponse" | "scheduledMessage" | "reactionRole" | "stickyMessage" | "customTextCommand" | "levelReward"
  | "economyItem" | "ticketPanel" | "shopProduct";

function delegate(prisma: PrismaClient, model: ModelName): Delegate {
  return prisma[model] as unknown as Delegate;
}

type Ctx = GuildContext<{ bot: string; guildId: string; id?: string }>;

interface CrudOptions {
  model: ModelName;
  create?: ZodTypeAny;
  update?: ZodTypeAny;
  orderBy?: Record<string, "asc" | "desc"> | Array<Record<string, "asc" | "desc">>;
  include?: Record<string, unknown>;
  limit?: number;
  /** Adjust validated data before writing (defaults, uniqueness checks...). */
  prepare?: (data: Record<string, unknown>, ctx: Ctx, existing: Row | null) => Promise<Record<string, unknown>> | Record<string, unknown>;
  /** Fields holding channel ids the bot will post in; each must belong to the guild. */
  channelFields?: string[];
  /** What the bot must do after a write: drop caches, or also redeploy slash commands. */
  notify?: "invalidate" | "resync";
  /** Extra side effect after any write (e.g. refresh the published shop message). */
  after?: (ctx: Ctx) => Promise<unknown>;
}

async function checkChannels(options: CrudOptions, ctx: Ctx, data: Record<string, unknown>): Promise<void> {
  if (options.channelFields?.length) {
    await assertGuildChannels(ctx.bot, ctx.guildId, options.channelFields.map((f) => data[f] as string | undefined));
  }
}

async function notify(options: CrudOptions, ctx: Ctx): Promise<void> {
  if (options.notify) await invalidateBot(ctx.bot, ctx.guildId, options.notify === "resync");
  if (options.after) await options.after(ctx).catch(() => undefined);
}

/** GET (list) and POST (create) for /<collection>. Every query is scoped to the guild. */
export function collectionRoutes(options: CrudOptions) {
  return {
    GET: guildRoute(async (_request: NextRequest, ctx) => delegate(db(ctx.bot.id), options.model).findMany({
      where: { guildId: ctx.guildId }, orderBy: options.orderBy ?? { id: "asc" }, include: options.include,
      take: options.limit ?? 500,
    })),
    POST: guildRoute(async (request: NextRequest, ctx) => {
      if (!options.create) throw new HttpError(405, "Método no permitido");
      let data: Record<string, unknown> = await readBody(request, options.create);
      if (options.prepare) data = await options.prepare(data, ctx, null);
      await checkChannels(options, ctx, data);
      const row = await delegate(db(ctx.bot.id), options.model).create({ data: { ...data, guildId: ctx.guildId } });
      await notify(options, ctx);
      return row;
    }),
  };
}

/** GET, PATCH and DELETE for /<collection>/[id]. */
export function itemRoutes(options: CrudOptions) {
  const find = async (ctx: Ctx) => {
    const row = await delegate(db(ctx.bot.id), options.model).findFirst({
      where: { id: ctx.params.id, guildId: ctx.guildId }, include: options.include,
    });
    if (!row) throw new HttpError(404, "Registro no encontrado");
    return row;
  };
  return {
    GET: guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, ctx) => find(ctx)),
    PATCH: guildRoute<{ bot: string; guildId: string; id: string }>(async (request, ctx) => {
      if (!options.update) throw new HttpError(405, "Método no permitido");
      const existing = await find(ctx);
      let data: Record<string, unknown> = await readBody(request, options.update);
      if (options.prepare) data = await options.prepare(data, ctx, existing);
      await checkChannels(options, ctx, data);
      await delegate(db(ctx.bot.id), options.model).updateMany({ where: { id: existing.id, guildId: ctx.guildId }, data });
      await notify(options, ctx);
      return find(ctx);
    }),
    DELETE: guildRoute<{ bot: string; guildId: string; id: string }>(async (_request, ctx) => {
      const { count } = await delegate(db(ctx.bot.id), options.model).deleteMany({ where: { id: ctx.params.id, guildId: ctx.guildId } });
      if (!count) throw new HttpError(404, "Registro no encontrado");
      await notify(options, ctx);
      return { success: true };
    }),
  };
}
