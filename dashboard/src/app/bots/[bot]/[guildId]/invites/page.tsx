"use client";

import { UserPlus } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Table } from "@/components/ui/table";
import { useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface InviteData {
  recent: Array<{ id: string; inviterId: string; invitedId: string; code: string; fake: boolean; left: boolean; createdAt: string }>;
  leaderboard: Array<{ inviterId: string; valid: number; fake: number; left: number; total: number }>;
}

export default function InvitesPage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<"ranking" | "recent" | "settings">("ranking");
  const { data, loading } = useApi<InviteData>(`${api}/invites`);
  const members = useMembers(api, [...(data?.leaderboard.map((r) => r.inviterId) ?? []), ...(data?.recent.flatMap((r) => [r.inviterId, r.invitedId]) ?? [])]);
  return (
    <>
      <PageHeader title="Invitaciones" description="Quién invitó a quién. Cuentas con menos de 7 días cuentan como sospechosas." icon={<UserPlus size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "ranking", label: "Ranking" }, { id: "recent", label: "Entradas recientes" }, { id: "settings", label: "Ajustes" }]} />
      {tab === "settings" ? (
        <ConfigEditor sections={[{ title: "Módulo", fields: [{ key: "invitesEnabled", type: "toggle", label: "Activar seguimiento de invitaciones",
          description: "Muestra /invitacion y /invitaciones y registra cada entrada en el canal de invitaciones." }] }]} />
      ) : loading ? <Spinner /> : tab === "ranking" ? (
        <Card>
          <Table rows={data?.leaderboard ?? []} rowKey={(r) => r.inviterId} empty={<Empty title="Sin invitaciones registradas" />}
                 columns={[
                   { key: "pos", header: "#", className: "w-12 tabular-nums text-muted", render: (r) => (data?.leaderboard.indexOf(r) ?? 0) + 1 },
                   { key: "who", header: "Invitador", render: (r) => <Member id={r.inviterId} info={members[r.inviterId]} /> },
                   { key: "valid", header: "Válidas", className: "tabular-nums font-medium", render: (r) => r.valid },
                   { key: "left", header: "Salieron", className: "tabular-nums text-muted", render: (r) => r.left },
                   { key: "fake", header: "Sospechosas", className: "tabular-nums text-muted", render: (r) => r.fake },
                 ]} />
        </Card>
      ) : (
        <Card>
          <Table rows={data?.recent ?? []} rowKey={(r) => r.id} empty={<Empty title="Sin entradas" />}
                 columns={[
                   { key: "invited", header: "Miembro", render: (r) => <Member id={r.invitedId} info={members[r.invitedId]} /> },
                   { key: "inviter", header: "Invitado por", render: (r) => <Member id={r.inviterId} info={members[r.inviterId]} /> },
                   { key: "code", header: "Código", render: (r) => <code className="text-xs text-muted">{r.code}</code> },
                   { key: "status", header: "Estado", render: (r) => r.fake ? <Badge>Sospechosa</Badge> : r.left ? <Badge tone="muted">Salió</Badge> : <Badge tone="solid">Válida</Badge> },
                   { key: "date", header: "Fecha", render: (r) => <span className="text-xs text-muted">{formatDate(r.createdAt)}</span> },
                 ]} />
        </Card>
      )}
    </>
  );
}
