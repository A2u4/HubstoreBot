"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "./api";

export interface MemberInfo { id: string; name: string; displayName: string; avatar: string }

/** Resolve user ids to names/avatars via the bot (missing members just show their id). */
export function useMembers(api: string, ids: string[]): Record<string, MemberInfo> {
  const [members, setMembers] = useState<Record<string, MemberInfo>>({});
  const key = [...new Set(ids)].filter(Boolean).sort().join(",");
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    apiFetch<MemberInfo[]>(`${api}/members?ids=${key}`)
      .then((rows) => !cancelled && setMembers((m) => ({ ...m, ...Object.fromEntries(rows.map((r) => [r.id, r])) })))
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [api, key]);
  return members;
}
