"use client";

import { Gift } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Card } from "@/components/ui/card";
import { formatDate, relativeTime } from "@/components/ui/format";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Table } from "@/components/ui/table";
import { useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Giveaway { id: string; prize: string; hostId: string; winners: number; entries: string[]; winnerIds: string[]; endsAt: string; ended: boolean; channelId: string }

export default function GiveawaysPage() {
  const { api, channelName } = useGuild();
  const [status, setStatus] = useState<"active" | "ended" | "settings">("active");
  const list = useApi<Giveaway[]>(status === "settings" ? null : `${api}/giveaways?status=${status}`);
  const members = useMembers(api, list.data?.flatMap((g) => [g.hostId, ...g.winnerIds]) ?? []);
  return (
    <>
      <PageHeader title="Sorteos" description="Se crean con /sorteo en Discord; los ganadores se eligen con un generador criptográfico" icon={<Gift size={18} />} />
      <Tabs value={status} onChange={setStatus} tabs={[{ id: "active", label: "Activos" }, { id: "ended", label: "Finalizados" }, { id: "settings", label: "Ajustes" }]} />
      {status === "settings" ? (
        <ConfigEditor sections={[{ title: "Sorteos", fields: [{ key: "giveawayEnabled", type: "toggle", label: "Activar sorteos" }] }]} />
      ) : list.loading && !list.data ? <Spinner /> : (
        <Card>
          <Table rows={list.data ?? []} rowKey={(g) => g.id} empty={<Empty title="Sin sorteos" />}
                 columns={[
                   { key: "prize", header: "Premio", render: (g) => <span className="font-medium">{g.prize}</span> },
                   { key: "channel", header: "Canal", render: (g) => <span className="text-muted">{channelName(g.channelId)}</span> },
                   { key: "entries", header: "Participantes", className: "tabular-nums", render: (g) => g.entries.length },
                   { key: "winners", header: status === "ended" ? "Ganadores" : "Ganadores", render: (g) => g.ended
                     ? (g.winnerIds.length ? <div className="flex flex-col gap-1">{g.winnerIds.map((id) => <Member key={id} id={id} info={members[id]} />)}</div> : <span className="text-faint">Sin ganadores</span>)
                     : <Badge>{g.winners}</Badge> },
                   { key: "ends", header: status === "ended" ? "Terminó" : "Termina", render: (g) => <span className="text-xs text-muted" title={formatDate(g.endsAt)}>{relativeTime(g.endsAt)}</span> },
                 ]} />
        </Card>
      )}
    </>
  );
}
