"use client";

import { ChevronsUpDown, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/components/ui/cn";
import { useApi } from "@/lib/client/api";
import { CONFIG_EVENT } from "@/lib/client/events";
import { GuildProvider } from "@/lib/client/guild";
import { NAV, navHref } from "@/lib/navigation";
import { UserMenu } from "./user-menu";


export function Shell({ bot, guild, user, children }: {
  bot: { id: string; name: string };
  guild: { id: string; name: string; icon: string | null };
  user: { id: string; username: string; avatar: string | null };
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const api = `/api/bots/${bot.id}/guilds/${guild.id}`;
  const { data: config, setData } = useApi<Record<string, unknown>>(`${api}/config`);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onUpdate = (event: Event) => setData((event as CustomEvent<Record<string, unknown>>).detail);
    window.addEventListener(CONFIG_EVENT, onUpdate);
    return () => window.removeEventListener(CONFIG_EVENT, onUpdate);
  }, [setData]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const items = NAV.filter((n) => !q || `${n.label} ${n.description}`.toLowerCase().includes(q));
    return [...new Set(items.map((n) => n.group))].map((group) => ({ group, items: items.filter((n) => n.group === group) }));
  }, [query]);
  const base = `/bots/${bot.id}/${guild.id}`;

  const sidebar = (
    <nav className="flex h-full flex-col">
      <Link href={`/bots/${bot.id}`} className="mx-3 mt-3 flex items-center gap-3 rounded-lg border border-line bg-surface-2 p-2.5 hover:border-line-strong">
        {guild.icon
          // eslint-disable-next-line @next/next/no-img-element
          ? <img src={guild.icon} alt="" className="size-8 rounded-lg grayscale" />
          : <div className="flex size-8 items-center justify-center rounded-lg bg-surface-3 text-xs font-semibold">{guild.name.slice(0, 2).toUpperCase()}</div>}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{guild.name}</div>
          <div className="truncate text-[11px] text-muted">{bot.name}</div>
        </div>
        <ChevronsUpDown size={14} className="text-faint" />
      </Link>
      <div className="px-3 pt-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar módulo..." className="input h-8 text-xs" />
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {groups.map(({ group, items }) => (
          <div key={group} className="mb-4">
            <div className="px-2 pb-1 text-[10px] font-medium uppercase tracking-[0.18em] text-faint">{group}</div>
            {items.map((item) => {
              const href = navHref(bot.id, guild.id, item);
              const active = item.path ? pathname.startsWith(href) : pathname === base;
              const enabled = item.toggle && config ? Boolean(config[item.toggle]) : null;
              return (
                <Link key={item.path} href={href}
                      className={cn("group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                                    active ? "bg-fg text-bg" : "text-fg-2 hover:bg-surface-3 hover:text-fg")}>
                  <item.icon size={15} className={active ? "" : "text-muted group-hover:text-fg"} />
                  <span className="flex-1 truncate">{item.label}</span>
                  {item.isNew && !active && <span className="rounded border border-line-strong px-1 text-[9px] uppercase tracking-wider text-muted">nuevo</span>}
                  {enabled !== null && (
                    <span title={enabled ? "Activado" : "Desactivado"}
                          className={cn("size-1.5 rounded-full", enabled ? (active ? "bg-bg" : "bg-fg") : "border border-faint")} />
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </div>
      <div className="border-t border-line p-3"><UserMenu session={user} /></div>
    </nav>
  );

  return (
    <GuildProvider bot={bot.id} botName={bot.name} guildId={guild.id} guildName={guild.name}>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line bg-surface lg:block">{sidebar}</aside>
      {open && <div className="fixed inset-0 z-40 bg-black/70 lg:hidden" onClick={() => setOpen(false)} />}
      <aside className={cn("fixed inset-y-0 left-0 z-50 w-72 border-r border-line bg-surface transition-transform lg:hidden",
                           open ? "translate-x-0" : "-translate-x-full")}>
        <button type="button" onClick={() => setOpen(false)} aria-label="Cerrar menú" className="absolute right-3 top-4 text-muted"><X size={18} /></button>
        {sidebar}
      </aside>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b border-line bg-bg/90 px-4 backdrop-blur lg:hidden">
          <button type="button" onClick={() => setOpen(true)} aria-label="Abrir menú"><Menu size={18} /></button>
          <span className="truncate text-sm font-medium">{guild.name}</span>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">{children}</main>
      </div>
    </GuildProvider>
  );
}
