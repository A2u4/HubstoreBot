"use client";

import { Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Member } from "@/components/ui/member";
import { Empty, Spinner, Tabs } from "@/components/ui/misc";
import { confirm } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { Pager } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Entry { id: string; authorId: string; stars: number; content: string | null; attachmentUrl: string | null; originalChId: string; createdAt: string }

export default function StarboardPage() {
  const { api, channelName } = useGuild();
  const [tab, setTab] = useState<"entries" | "settings">("entries");
  const [page, setPage] = useState(1);
  const list = useApi<{ rows: Entry[]; total: number; pages: number }>(tab === "entries" ? `${api}/starboard?page=${page}` : null);
  const members = useMembers(api, list.data?.rows.map((r) => r.authorId) ?? []);
  const remove = async (entry: Entry) => {
    if (!(await confirm({ title: "Quitar destacado", message: "Se borra el registro (el mensaje del canal de destacados no se elimina).", danger: true, confirmLabel: "Quitar" }))) return;
    try { await apiFetch(`${api}/starboard/${entry.id}`, { method: "DELETE" }); list.reload(); toast.success("Eliminado"); }
    catch (err) { toast.error(errorMessage(err)); }
  };
  return (
    <>
      <PageHeader title="Destacados" description="Mensajes que alcanzan suficientes reacciones se copian al canal de destacados" icon={<Sparkles size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "entries", label: "Mensajes", count: list.data?.total }, { id: "settings", label: "Ajustes" }]} />
      {tab === "settings" ? (
        <ConfigEditor sections={[{ title: "Destacados", fields: [
          { key: "starboardEnabled", type: "toggle", label: "Activar destacados" },
          { key: "starboardChannelId", type: "channel", label: "Canal de destacados" },
          { key: "starboardEmoji", type: "text", label: "Emoji", max: 50 },
          { key: "starboardThreshold", type: "number", label: "Reacciones necesarias", min: 1, max: 100 },
        ] }]} />
      ) : list.loading && !list.data ? <Spinner /> : !list.data?.rows.length ? <Card><Empty title="Aún no hay mensajes destacados" /></Card> : (
        <Card>
          <ul className="divide-y divide-line">
            {list.data.rows.map((e) => (
              <li key={e.id} className="flex gap-4 px-5 py-4">
                <div className="w-12 shrink-0 text-center"><div className="text-lg font-semibold tabular-nums">{e.stars}</div><div className="text-[10px] uppercase text-muted">⭐</div></div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs text-muted"><Member id={e.authorId} info={members[e.authorId]} /> · {channelName(e.originalChId)} · {formatDate(e.createdAt)}</div>
                  {e.content && <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm text-fg-2">{e.content}</p>}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {e.attachmentUrl && <img src={e.attachmentUrl} alt="" className="mt-2 max-h-40 rounded" />}
                </div>
                <Button size="sm" variant="ghost" aria-label="Quitar" onClick={() => remove(e)}><Trash2 size={14} /></Button>
              </li>
            ))}
          </ul>
          <Pager page={page} pages={list.data.pages} onChange={setPage} />
        </Card>
      )}
    </>
  );
}
