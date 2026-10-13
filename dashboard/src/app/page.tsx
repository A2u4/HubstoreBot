import { ArrowRight, Bot } from "lucide-react";
import Link from "next/link";
import { listBots } from "@/lib/server/bots";
import { getSession } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [bots, session] = [listBots(), await getSession()];
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <p className="text-xs font-medium uppercase tracking-[0.25em] text-muted">Markets</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight">Panel de administración</h1>
      <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted">
        Elige el bot que quieres administrar. {session ? `Sesión iniciada como ${session.username}.` : "Te pediremos iniciar sesión con Discord."}
      </p>
      <div className="mt-10 grid gap-3 sm:grid-cols-2">
        {bots.map((bot) => (
          <Link key={bot.id} href={`/bots/${bot.id}`}
                className="card group flex items-center gap-4 p-5 transition-colors hover:border-line-strong hover:bg-surface-2">
            <div className="flex size-11 items-center justify-center rounded-xl border border-line bg-surface-3"><Bot size={20} /></div>
            <div className="min-w-0 flex-1">
              <div className="font-medium">{bot.name}</div>
              <div className="text-xs text-muted">{bot.internalUrl ? "Conectado al bot" : "Solo base de datos"}</div>
            </div>
            <ArrowRight size={16} className="text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-fg" />
          </Link>
        ))}
        {!bots.length && (
          <div className="card p-5 text-sm text-muted sm:col-span-2">
            No hay bots configurados. Define <span className="kbd">VAPIANO_DATABASE_URL</span> (y equivalentes) en el archivo <span className="kbd">.env</span>.
          </div>
        )}
      </div>
    </main>
  );
}
