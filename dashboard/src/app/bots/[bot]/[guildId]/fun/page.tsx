"use client";

import { Heart, PartyPopper } from "lucide-react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Card, CardHeader } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Member } from "@/components/ui/member";
import { Empty, Spinner } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface FunStats {
  marriages: Array<{ id: string; user1Id: string; user2Id: string; createdAt: string }>;
  topActions: Array<{ id: string; action: string; userId: string; targetId: string; count: number }>;
  totals: Array<{ action: string; count: number }>;
}

export default function FunPage() {
  const { api } = useGuild();
  const { data, loading } = useApi<FunStats>(`${api}/fun`);
  const ids = [...(data?.marriages.flatMap((m) => [m.user1Id, m.user2Id]) ?? []), ...(data?.topActions.flatMap((a) => [a.userId, a.targetId]) ?? [])];
  const members = useMembers(api, ids);
  const max = Math.max(1, ...(data?.totals.map((t) => t.count) ?? [1]));
  return (
    <>
      <PageHeader title="Diversión" description="Roleplay con GIFs de anime, matrimonios y minijuegos (estilo Nekotina)" icon={<PartyPopper size={18} />} />
      <ConfigEditor sections={[{ title: "Módulo", fields: [{ key: "funEnabled", type: "toggle", label: "Activar diversión",
        description: "/accion (abrazar, besar, acariciar... con contador y botón «Devolver»), /reaccion, /matrimonio, /diversion (8ball, ship, dado, moneda, elegir, calificar)." }] }]}>
        {loading ? <Spinner /> : (
          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Acciones más usadas" />
              {data?.totals.length ? (
                <ul className="space-y-2.5 px-5 py-4">
                  {data.totals.map((t) => (
                    <li key={t.action} className="text-sm">
                      <div className="mb-1 flex justify-between"><span>{t.action}</span><span className="tabular-nums text-muted">{t.count.toLocaleString("es")}</span></div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full bg-fg" style={{ width: `${(t.count / max) * 100}%` }} /></div>
                    </li>
                  ))}
                </ul>
              ) : <Empty title="Todavía nadie usó /accion" />}
            </Card>
            <Card>
              <CardHeader title="Parejas" description={`${data?.marriages.length ?? 0} matrimonios`} icon={<Heart size={15} />} />
              {data?.marriages.length ? (
                <ul className="divide-y divide-line">
                  {data.marriages.map((m) => (
                    <li key={m.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                      <span className="flex min-w-0 items-center gap-2"><Member id={m.user1Id} info={members[m.user1Id]} /> <span className="text-faint">&</span> <Member id={m.user2Id} info={members[m.user2Id]} /></span>
                      <span className="shrink-0 text-xs text-muted">{formatDate(m.createdAt, false)}</span>
                    </li>
                  ))}
                </ul>
              ) : <Empty title="Sin matrimonios" />}
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader title="Interacciones destacadas" />
              {data?.topActions.length ? (
                <ul className="divide-y divide-line">
                  {data.topActions.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                      <span className="flex min-w-0 items-center gap-2"><Member id={a.userId} info={members[a.userId]} /><span className="text-muted">{a.action}</span><Member id={a.targetId} info={members[a.targetId]} /></span>
                      <span className="tabular-nums text-muted">{a.count}×</span>
                    </li>
                  ))}
                </ul>
              ) : <Empty title="Sin datos" />}
            </Card>
          </div>
        )}
      </ConfigEditor>
    </>
  );
}
