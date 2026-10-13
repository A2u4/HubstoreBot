import { ArrowLeft, Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getBot } from "@/lib/server/bots";
import { HttpError } from "@/lib/server/errors";
import { manageableGuilds, pageSession } from "@/lib/server/guilds";
import { UserMenu } from "@/components/shell/user-menu";

export const dynamic = "force-dynamic";

export default async function GuildPicker({ params }: { params: Promise<{ bot: string }> }) {
  const { bot: botId } = await params;
  const bot = getBot(botId);
  if (!bot?.databaseUrl) notFound();
  const session = await pageSession(bot.id, `/bots/${bot.id}`);

  let guilds: Awaited<ReturnType<typeof manageableGuilds>> = [];
  let error: string | null = null;
  try {
    guilds = await manageableGuilds(bot.id, session);
  } catch (err) {
    error = err instanceof HttpError ? err.message : "No se pudieron cargar los servidores";
  }
  const invite = (guildId: string) => bot.clientId
    ? `https://discord.com/oauth2/authorize?client_id=${bot.clientId}&scope=bot%20applications.commands&permissions=8&guild_id=${guildId}`
    : null;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <div className="mb-10 flex items-center justify-between">
        <Link href="/" className="inline-flex items-center gap-2 text-sm text-muted hover:text-fg"><ArrowLeft size={14} /> Bots</Link>
        <UserMenu session={{ username: session.username, id: session.id, avatar: session.avatar }} />
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">{bot.name}</h1>
      <p className="mt-2 text-sm text-muted">Servidores donde tienes permiso de <span className="text-fg-2">Gestionar servidor</span>.</p>
      {error && <div className="card mt-8 p-5 text-sm text-fg-2">{error}</div>}
      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {guilds.map((guild) => {
          const href = guild.botPresent ? `/bots/${bot.id}/${guild.id}` : invite(guild.id);
          const body = (
            <>
              {guild.icon
                // eslint-disable-next-line @next/next/no-img-element
                ? <img src={guild.icon} alt="" className="size-11 rounded-xl grayscale" />
                : <div className="flex size-11 items-center justify-center rounded-xl border border-line bg-surface-3 text-sm font-semibold">
                    {guild.name.slice(0, 2).toUpperCase()}
                  </div>}
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{guild.name}</div>
                <div className="text-xs text-muted">{guild.botPresent ? "Administrar" : "Invitar al bot"}</div>
              </div>
              {!guild.botPresent && <Plus size={16} className="text-faint" />}
            </>
          );
          const className = `card flex items-center gap-4 p-4 transition-colors hover:border-line-strong hover:bg-surface-2 ${guild.botPresent ? "" : "opacity-60"}`;
          if (!href) return <div key={guild.id} className={className}>{body}</div>;
          return guild.botPresent
            ? <Link key={guild.id} href={href} className={className}>{body}</Link>
            : <a key={guild.id} href={href} target="_blank" rel="noreferrer" className={className}>{body}</a>;
        })}
        {!error && !guilds.length && <div className="card p-5 text-sm text-muted sm:col-span-2">No administras ningún servidor.</div>}
      </div>
    </main>
  );
}
