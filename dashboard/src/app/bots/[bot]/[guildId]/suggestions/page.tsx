"use client";

import { Lightbulb, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Suggestion { id: string; userId: string; content: string; status: string; upvotes: string[]; downvotes: string[]; staffNote: string | null; createdAt: string }
const STATUS: Record<string, string> = { pending: "Pendiente", approved: "Aprobada", denied: "Rechazada", implemented: "Implementada" };

export default function SuggestionsPage() {
  const { api } = useGuild();
  const [status, setStatus] = useState<"all" | "pending" | "approved" | "denied" | "implemented" | "settings">("pending");
  const list = useApi<Suggestion[]>(status === "settings" ? null : `${api}/suggestions?status=${status}`);
  const members = useMembers(api, list.data?.map((s) => s.userId) ?? []);
  return (
    <>
      <PageHeader title="Sugerencias" description="Se crean con /sugerencia y se votan en Discord" icon={<Lightbulb size={18} />} />
      <Tabs value={status} onChange={setStatus} tabs={[...(["pending", "approved", "denied", "implemented", "all"] as const).map((id) => ({ id, label: STATUS[id] ?? "Todas" })), { id: "settings" as const, label: "Ajustes" }]} />
      {status === "settings" ? (
        <ConfigEditor sections={[{ title: "Sugerencias", fields: [
          { key: "suggestionsEnabled", type: "toggle", label: "Activar sugerencias" },
          { key: "suggestionsChannelId", type: "channel", label: "Canal de sugerencias" },
          { key: "suggestionsLogChannelId", type: "channel", label: "Canal de registro", help: "Aprobaciones y rechazos del staff." },
        ] }]} />
      ) : list.loading && !list.data ? <Spinner /> : !list.data?.length ? <Card><Empty title="Sin sugerencias" /></Card> : (
        <div className="space-y-3">
          {list.data.map((s) => (
            <Card key={s.id} className="p-4">
              <div className="flex items-start justify-between gap-4">
                <Member id={s.userId} info={members[s.userId]} />
                <Badge tone={s.status === "pending" ? "default" : "muted"}>{STATUS[s.status] ?? s.status}</Badge>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm text-fg-2">{s.content}</p>
              {s.staffNote && <p className="mt-2 border-l-2 border-line-strong pl-3 text-xs text-muted">Staff: {s.staffNote}</p>}
              <div className="mt-3 flex items-center gap-4 text-xs text-muted">
                <span className="flex items-center gap-1"><ThumbsUp size={12} /> {s.upvotes.length}</span>
                <span className="flex items-center gap-1"><ThumbsDown size={12} /> {s.downvotes.length}</span>
                <span className="ml-auto">{formatDate(s.createdAt)}</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
