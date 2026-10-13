"use client";

import { Activity, Clock, Gauge, Hash, Shield, Ticket, TrendingUp, UserPlus, Users } from "lucide-react";
import Link from "next/link";
import { Card, CardHeader } from "@/components/ui/card";
import { formatDate, formatNumber } from "@/components/ui/format";
import { Badge, Empty, Spinner, Stat } from "@/components/ui/misc";
import { useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { NAV, navHref } from "@/lib/navigation";

interface Overview {
  live: null | {
    memberCount: number; humans: number; bots: number; online: number; channels: number; roles: number; boosts: number;
    boostTier: number; bot: { name: string; latencyMs: number | null; uptimeSeconds: number; guilds: number };
  };
  counts: Record<string, number>;
  recentModActions: Array<{ id: string; action: string; userId: string; moderatorId: string; reason: string | null; createdAt: string }>;
}

const ACTIONS: Record<string, string> = {
  ban: "Ban", unban: "Desban", kick: "Expulsión", mute: "Silencio", unmute: "Fin de silencio", warn: "Advertencia",
  tempban: "Ban temporal", timeout: "Aislamiento", lock: "Bloqueo", unlock: "Desbloqueo",
};

function uptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

export default function OverviewPage() {
  const { api, bot, guildId, guildName, botName } = useGuild();
  const { data, loading } = useApi<Overview>(`${api}/overview`);
  if (loading && !data) return <Spinner />;
  const live = data?.live;
  const counts = data?.counts ?? {};
  const shortcuts = NAV.filter((n) => ["/tickets", "/shop", "/moderation", "/leveling", "/economy", "/messages"].includes(n.path));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-muted">{botName}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{guildName}</h1>
        </div>
        {live ? <Badge tone="solid"><Activity size={11} /> En línea · {live.bot.latencyMs ?? "?"} ms</Badge>
              : <Badge tone="muted">Bot sin conexión</Badge>}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Miembros" value={formatNumber(live?.memberCount)} hint={live ? `${formatNumber(live.humans)} humanos · ${formatNumber(live.bots)} bots` : undefined} icon={<Users size={15} />} />
        <Stat label="En línea" value={formatNumber(live?.online)} icon={<Activity size={15} />} />
        <Stat label="Canales" value={formatNumber(live?.channels)} hint={live ? `${live.roles} roles` : undefined} icon={<Hash size={15} />} />
        <Stat label="Boosts" value={formatNumber(live?.boosts)} hint={live ? `Nivel ${live.boostTier}` : undefined} icon={<Gauge size={15} />} />
        <Stat label="Tickets abiertos" value={formatNumber(counts.openTickets)} hint={`${formatNumber(counts.ticketsThisWeek)} esta semana`} icon={<Ticket size={15} />} />
        <Stat label="Invitaciones válidas" value={formatNumber(counts.validInvites)} icon={<UserPlus size={15} />} />
        <Stat label="Sanciones" value={formatNumber(counts.modActions)} hint={`${formatNumber(counts.warnings)} advertencias`} icon={<Shield size={15} />} />
        <Stat label="Miembros con XP" value={formatNumber(counts.rankedMembers)} hint={`${formatNumber(counts.economyAccounts)} cuentas de economía`} icon={<TrendingUp size={15} />} />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Actividad de moderación" description="Últimas sanciones registradas" />
          {data?.recentModActions.length ? (
            <ul className="divide-y divide-line">
              {data.recentModActions.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                  <div className="min-w-0">
                    <span className="font-medium">{ACTIONS[a.action] ?? a.action}</span>
                    <span className="text-muted"> · {a.userId}</span>
                    {a.reason && <p className="truncate text-xs text-muted">{a.reason}</p>}
                  </div>
                  <span className="shrink-0 text-xs text-faint">{formatDate(a.createdAt)}</span>
                </li>
              ))}
            </ul>
          ) : <Empty title="Sin sanciones recientes" />}
        </Card>
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <CardHeader title="Accesos rápidos" />
            <div className="grid grid-cols-2 gap-2 p-3">
              {shortcuts.map((item) => (
                <Link key={item.path} href={navHref(bot, guildId, item)}
                      className="flex items-center gap-2 rounded-lg border border-line px-3 py-2.5 text-sm hover:border-line-strong hover:bg-surface-2">
                  <item.icon size={14} className="text-muted" /> {item.label}
                </Link>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="Sistema" />
            <dl className="space-y-2 px-5 py-4 text-sm">
              {[["Bot", live?.bot.name ?? botName], ["Servidores", formatNumber(live?.bot.guilds)],
                ["Tiempo activo", live ? uptime(live.bot.uptimeSeconds) : "—"], ["Respaldos", formatNumber(counts.backups)],
                ["Sugerencias pendientes", formatNumber(counts.pendingSuggestions)], ["Sorteos activos", formatNumber(counts.activeGiveaways)]]
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4"><dt className="text-muted">{k}</dt><dd className="tabular-nums">{v}</dd></div>
                ))}
            </dl>
          </Card>
          <p className="flex items-center gap-1.5 text-xs text-faint"><Clock size={12} /> Datos en vivo del bot y de la base de datos.</p>
        </div>
      </div>
    </div>
  );
}
