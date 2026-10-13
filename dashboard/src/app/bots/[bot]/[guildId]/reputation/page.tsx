"use client";

import { ArrowRightLeft, Plus, Star } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Field, Input, NumberInput } from "@/components/ui/form";
import { Member } from "@/components/ui/member";
import { Empty, Spinner, Tabs } from "@/components/ui/misc";
import { confirm } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface RepData {
  leaderboard: Array<{ userId: string; rep: number }>;
  recent: Array<{ id: string; userId: string; giverId: string; reason: string | null; createdAt: string }>;
}

function Tools({ onDone }: { onDone: () => void }) {
  const { api } = useGuild();
  const [add, setAdd] = useState({ userId: "", cantidad: 1, razon: "" });
  const [move, setMove] = useState({ fromUserId: "", toUserId: "", razon: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (kind: "ingresar" | "migrar") => {
    if (kind === "migrar" && !(await confirm({ title: "Migrar reputación", message: `Se moverá toda la reputación de ${move.fromUserId} a ${move.toUserId}.`, confirmLabel: "Migrar" }))) return;
    setBusy(kind);
    try {
      const result = await apiFetch<{ total: number; moved?: number }>(`${api}/reputation/${kind}`, { body: kind === "ingresar" ? add : { ...move, razon: move.razon || undefined } });
      toast.success(kind === "ingresar" ? `Reputación añadida (total: ${result.total})` : `${result.moved} reps migradas (total: ${result.total})`);
      onDone();
    } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(null); }
  };
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader title="Añadir reputación" description="Registra reps manualmente (p. ej. reps de antes del bot)." />
        <CardBody className="space-y-3">
          <Field label="ID del usuario"><Input className="font-mono" value={add.userId} onChange={(e) => setAdd({ ...add, userId: e.target.value.trim() })} /></Field>
          <Field label="Cantidad"><NumberInput value={add.cantidad} min={1} max={1000} onChange={(cantidad) => setAdd({ ...add, cantidad })} /></Field>
          <Field label="Razón"><Input maxLength={200} value={add.razon} onChange={(e) => setAdd({ ...add, razon: e.target.value })} /></Field>
          <Button variant="primary" icon={<Plus size={14} />} loading={busy === "ingresar"} disabled={!add.userId || !add.razon} onClick={() => run("ingresar")}>Añadir</Button>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Migrar reputación" description="Mueve todas las reps de una cuenta a otra." />
        <CardBody className="space-y-3">
          <Field label="Desde (ID)"><Input className="font-mono" value={move.fromUserId} onChange={(e) => setMove({ ...move, fromUserId: e.target.value.trim() })} /></Field>
          <Field label="Hacia (ID)"><Input className="font-mono" value={move.toUserId} onChange={(e) => setMove({ ...move, toUserId: e.target.value.trim() })} /></Field>
          <Field label="Razón (opcional)"><Input maxLength={200} value={move.razon} onChange={(e) => setMove({ ...move, razon: e.target.value })} /></Field>
          <Button icon={<ArrowRightLeft size={14} />} loading={busy === "migrar"} disabled={!move.fromUserId || !move.toUserId} onClick={() => run("migrar")}>Migrar</Button>
        </CardBody>
      </Card>
    </div>
  );
}

export default function ReputationPage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<"ranking" | "recent" | "tools" | "settings">("ranking");
  const { data, loading, reload } = useApi<RepData>(`${api}/reputation`);
  const members = useMembers(api, [...(data?.leaderboard.map((r) => r.userId) ?? []), ...(data?.recent.flatMap((r) => [r.userId, r.giverId]) ?? [])]);
  return (
    <>
      <PageHeader title="Reputación" description="+rep y /rep: una fila = una reputación" icon={<Star size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "ranking", label: "Ranking" }, { id: "recent", label: "Recientes" }, { id: "tools", label: "Herramientas" }, { id: "settings", label: "Ajustes" }]} />
      {tab === "settings" && <ConfigEditor sections={[{ title: "Reputación", fields: [
        { key: "reputationEnabled", type: "toggle", label: "Activar +rep en el chat",
          description: "/rep funciona siempre (igual que en v1). La misma persona solo puede dar una rep cada 10 segundos al mismo usuario." },
      ] }]} />}
      {tab === "tools" && <Tools onDone={reload} />}
      {(tab === "ranking" || tab === "recent") && (loading && !data ? <Spinner /> : (
        <Card>
          {tab === "ranking" ? (
            <Table rows={data?.leaderboard ?? []} rowKey={(r) => r.userId} empty={<Empty title="Sin reputación" />}
                   columns={[
                     { key: "pos", header: "#", className: "w-12 tabular-nums text-muted", render: (r) => (data?.leaderboard.indexOf(r) ?? 0) + 1 },
                     { key: "user", header: "Miembro", render: (r) => <Member id={r.userId} info={members[r.userId]} /> },
                     { key: "rep", header: "Reputación", className: "tabular-nums font-medium", render: (r) => r.rep.toLocaleString("es") },
                   ]} />
          ) : (
            <Table rows={data?.recent ?? []} rowKey={(r) => r.id} empty={<Empty title="Sin reputación" />}
                   columns={[
                     { key: "to", header: "Recibió", render: (r) => <Member id={r.userId} info={members[r.userId]} /> },
                     { key: "from", header: "Dio", render: (r) => <Member id={r.giverId} info={members[r.giverId]} /> },
                     { key: "reason", header: "Razón", render: (r) => <span className="text-fg-2">{r.reason ?? <span className="text-faint">—</span>}</span> },
                     { key: "date", header: "Fecha", render: (r) => <span className="text-xs text-muted">{formatDate(r.createdAt)}</span> },
                   ]} />
          )}
        </Card>
      ))}
    </>
  );
}
