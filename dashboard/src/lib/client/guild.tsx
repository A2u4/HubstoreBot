"use client";

import { createContext, useCallback, useContext, useMemo } from "react";
import { useApi } from "./api";

export interface ChannelInfo { id: string; name: string; type: number; position: number; parentId: string | null }
export interface RoleInfo { id: string; name: string; color: number; position: number; managed: boolean; assignable: boolean }
export interface EmojiInfo { id: string; name: string; animated: boolean; url: string }
export interface PeerBot { id: string; name: string; guildId: string | null; online: boolean }

interface GuildMeta { channels: ChannelInfo[]; roles: RoleInfo[]; emojis: EmojiInfo[]; botOnline: boolean; peers: PeerBot[] }

interface GuildContextValue extends GuildMeta {
  bot: string;
  botName: string;
  guildId: string;
  guildName: string;
  /** Base URL of this guild's JSON API. */
  api: string;
  metaLoading: boolean;
  reloadMeta: () => void;
  channelName: (id: string | null | undefined) => string;
  roleName: (id: string | null | undefined) => string;
}

const GuildContext = createContext<GuildContextValue | null>(null);

export const CHANNEL = { text: 0, voice: 2, category: 4, news: 5, stage: 13, forum: 15 } as const;

export function GuildProvider({ bot, botName, guildId, guildName, children }: {
  bot: string; botName: string; guildId: string; guildName: string; children: React.ReactNode;
}) {
  const api = `/api/bots/${bot}/guilds/${guildId}`;
  const { data, loading, reload } = useApi<GuildMeta>(`${api}/meta`);
  const channels = useMemo(() => data?.channels ?? [], [data]);
  const roles = useMemo(() => data?.roles ?? [], [data]);

  const channelName = useCallback((id: string | null | undefined) => {
    if (!id) return "—";
    const channel = channels.find((c) => c.id === id);
    return channel ? `#${channel.name}` : `#${id}`;
  }, [channels]);
  const roleName = useCallback((id: string | null | undefined) => {
    if (!id) return "—";
    return `@${roles.find((r) => r.id === id)?.name ?? id}`;
  }, [roles]);

  const value = useMemo<GuildContextValue>(() => ({
    bot, botName, guildId, guildName, api, channels, roles, emojis: data?.emojis ?? [], botOnline: data?.botOnline ?? false,
    peers: data?.peers ?? [], metaLoading: loading, reloadMeta: () => void reload(), channelName, roleName,
  }), [bot, botName, guildId, guildName, api, channels, roles, data, loading, reload, channelName, roleName]);

  return <GuildContext.Provider value={value}>{children}</GuildContext.Provider>;
}

export function useGuild(): GuildContextValue {
  const context = useContext(GuildContext);
  if (!context) throw new Error("useGuild must be used inside GuildProvider");
  return context;
}
