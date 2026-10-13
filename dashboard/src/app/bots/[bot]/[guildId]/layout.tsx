import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/shell/shell";
import { getBot } from "@/lib/server/bots";
import { HttpError } from "@/lib/server/errors";
import { pageGuild, pageSession } from "@/lib/server/guilds";

export const dynamic = "force-dynamic";

export default async function GuildLayout({ params, children }: {
  params: Promise<{ bot: string; guildId: string }>; children: React.ReactNode;
}) {
  const { bot: botId, guildId } = await params;
  const bot = getBot(botId);
  if (!bot?.databaseUrl) notFound();
  const session = await pageSession(bot.id, `/bots/${bot.id}/${guildId}`);
  let guild: { name: string; icon: string | null };
  try {
    guild = await pageGuild(bot.id, guildId, session);
  } catch (error) {
    const message = error instanceof HttpError ? error.message : "No se pudo verificar el acceso";
    return (
      <main className="flex min-h-screen items-center justify-center px-6">
        <div className="card max-w-sm p-8 text-center">
          <h1 className="text-lg font-semibold">Sin acceso</h1>
          <p className="mt-2 text-sm text-muted">{message}</p>
          <Link href={`/bots/${bot.id}`} className="mt-6 inline-block text-sm text-fg underline underline-offset-4">Elegir otro servidor</Link>
        </div>
      </main>
    );
  }
  return (
    <Shell bot={{ id: bot.id, name: bot.name }} guild={{ id: guildId, ...guild }}
           user={{ id: session.id, username: session.username, avatar: session.avatar }}>
      {children}
    </Shell>
  );
}
