import "server-only";
import { Prisma } from "@prisma/client";
import { type NextRequest, NextResponse } from "next/server";
import { type z, ZodError, type ZodTypeAny } from "zod";
import { requireGuildAccess } from "./access";
import type { BotInfo } from "./bots";
import { HttpError } from "./errors";
import type { Session } from "./session";

export interface GuildContext<P> {
  bot: BotInfo;
  guildId: string;
  session: Session;
  params: P;
}

type RouteParams = { bot: string; guildId: string };
type Handler<P> = (request: NextRequest, ctx: GuildContext<P>) => Promise<unknown>;

export function errorResponse(error: unknown): NextResponse {
  if (error instanceof HttpError) {
    return NextResponse.json({ error: error.message, details: error.details }, { status: error.status });
  }
  if (error instanceof ZodError) {
    const details = error.issues.map((i) => ({ path: i.path.join("."), message: i.message }));
    return NextResponse.json({ error: "Datos inválidos", details }, { status: 400 });
  }
  if (error instanceof Prisma.PrismaClientKnownRequestError) {
    if (error.code === "P2025") return NextResponse.json({ error: "Registro no encontrado" }, { status: 404 });
    if (error.code === "P2002") return NextResponse.json({ error: "Ya existe un registro con esos datos" }, { status: 409 });
  }
  console.error("[api]", error);
  return NextResponse.json({ error: "Error interno del servidor" }, { status: 500 });
}

/**
 * Wrap a guild-scoped route handler: checks the session and Manage Server
 * access, then turns thrown errors into JSON responses. Returning a plain
 * value sends it as JSON; returning a Response sends it as-is.
 */
export function guildRoute<P extends RouteParams = RouteParams>(handler: Handler<P>) {
  return async (request: NextRequest, { params }: { params: Promise<P> }) => {
    try {
      const resolved = await params;
      const { bot, session } = await requireGuildAccess(resolved.bot, resolved.guildId);
      const result = await handler(request, { bot, guildId: resolved.guildId, session, params: resolved });
      if (result instanceof Response) return result;
      return NextResponse.json(result ?? { success: true });
    } catch (error) {
      return errorResponse(error);
    }
  };
}

export async function readBody<S extends ZodTypeAny>(request: NextRequest, schema: S): Promise<z.output<S>> {
  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    throw new HttpError(400, "El cuerpo de la solicitud no es JSON válido");
  }
  return schema.parse(raw);
}

export function intParam(value: string | null, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : fallback;
}
