"use client";

import { Ban, Dice5, Gift, Send } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { relativeTime } from "@/components/ui/format";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { confirm } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker } from "@/components/ui/pickers";
import { Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Rifa { id: string; prize: string; maxSlots: number; filledCount: number; winnersCount: number; winnerIds: string[]; ended: boolean; cancelled: boolean; endsAt: string | null; createdAt: string }

function PanelDeploy() {
  const { api } = useGuild();
  const [data, setData] = useState({ channelId: "" as string | null, title: "🎟️ Rifas — Soporte", description: "Haz clic en el botón para solicitar tu número de rifa.\nEl staff te atenderá en un canal privado.", buttonLabel: "🎫 Solicitar número de rifa", buttonColor: "3" });
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardHeader title="Panel de solicitudes" description="Publica el botón con el que los miembros piden un número (reemplaza el panel anterior)." />
      <CardBody className="grid gap-4 md:grid-cols-2">
        <Field label="Canal"><ChannelPicker value={data.channelId} onChange={(channelId) => setData({ ...data, channelId })} /></Field>
        <Field label="Color del botón"><Select value={data.buttonColor} onChange={(buttonColor) => setData({ ...data, buttonColor })}
                options={[{ value: "1", label: "Azul" }, { value: "2", label: "Gris" }, { value: "3", label: "Verde" }, { value: "4", label: "Rojo" }]} /></Field>
        <Field label="Título"><Input value={data.title} maxLength={256} onChange={(e) => setData({ ...data, title: e.target.value })} /></Field>
        <Field label="Texto del botón"><Input value={data.buttonLabel} maxLength={80} onChange={(e) => setData({ ...data, buttonLabel: e.target.value })} /></Field>
        <Field label="Descripción" className="md:col-span-2"><Textarea rows={3} value={data.description} maxLength={4000} onChange={(e) => setData({ ...data, description: e.target.value })} /></Field>
        <div><Button variant="primary" icon={<Send size={14} />} loading={busy} disabled={!data.channelId} onClick={async () => {
          setBusy(true);
          try { await apiFetch(`${api}/rifas/panel`, { body: { ...data, buttonColor: Number(data.buttonColor) } }); toast.success("Panel publicado"); }
          catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
        }}>Publicar panel</Button></div>
      </CardBody>
    </Card>
  );
}

export default function RifasPage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<"active" | "ended" | "cancelled" | "panel" | "settings">("active");
  const list = useApi<Rifa[]>(["active", "ended", "cancelled"].includes(tab) ? `${api}/rifas?status=${tab}` : null);
  const members = useMembers(api, list.data?.flatMap((r) => r.winnerIds) ?? []);
  const act = async (rifa: Rifa, action: "draw" | "cancel") => {
    const ok = await confirm(action === "draw"
      ? { title: "Sortear rifa", message: `Se elegirán ${rifa.winnersCount} ganador(es) entre ${rifa.filledCount} participantes y se anunciará en Discord.`, confirmLabel: "Sortear" }
      : { title: "Cancelar rifa", message: "La rifa se marcará como cancelada y se avisará en Discord.", confirmLabel: "Cancelar rifa", danger: true });
    if (!ok) return;
    try { await apiFetch(`${api}/rifas/${rifa.id}/${action}`, { body: {} }); toast.success(action === "draw" ? "Rifa sorteada" : "Rifa cancelada"); list.reload(); }
    catch (err) { toast.error(errorMessage(err)); }
  };
  return (
    <>
      <PageHeader title="Rifas" description="Rifas por números con /rifa; sorteo y cancelación también desde aquí" icon={<Gift size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "active", label: "Activas" }, { id: "ended", label: "Finalizadas" }, { id: "cancelled", label: "Canceladas" },
                                                  { id: "panel", label: "Panel" }, { id: "settings", label: "Ajustes" }]} />
      {tab === "panel" && <PanelDeploy />}
      {tab === "settings" && <ConfigEditor sections={[{ title: "Rifas", fields: [
        { key: "rifaEnabled", type: "toggle", label: "Activar rifas" },
        { key: "rifaCategoryId", type: "channel", kind: "category", label: "Categoría de los canales de solicitud" },
        { key: "rifaLogChannelId", type: "channel", label: "Canal de registro" },
        { key: "rifaStaffRoleIds", type: "roles", label: "Roles del staff de rifas" },
      ] }]} />}
      {["active", "ended", "cancelled"].includes(tab) && (list.loading && !list.data ? <Spinner /> : (
        <Card>
          <Table rows={list.data ?? []} rowKey={(r) => r.id} empty={<Empty title="Sin rifas" />}
                 columns={[
                   { key: "prize", header: "Premio", render: (r) => <span className="font-medium">{r.prize}</span> },
                   { key: "slots", header: "Puestos", render: (r) => (
                     <div className="flex items-center gap-2">
                       <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-3"><div className="h-full bg-fg" style={{ width: `${(r.filledCount / Math.max(1, r.maxSlots)) * 100}%` }} /></div>
                       <span className="text-xs tabular-nums text-muted">{r.filledCount}/{r.maxSlots}</span>
                     </div>) },
                   { key: "winners", header: "Ganadores", render: (r) => r.winnerIds.length
                     ? <div className="flex flex-col gap-1">{r.winnerIds.map((id) => <Member key={id} id={id} info={members[id]} />)}</div>
                     : <Badge tone="muted">{r.winnersCount}</Badge> },
                   { key: "ends", header: "Cierre", render: (r) => <span className="text-xs text-muted">{r.endsAt ? relativeTime(r.endsAt) : "Al llenarse"}</span> },
                   { key: "actions", header: "", className: "w-48 text-right", render: (r) => !r.ended && !r.cancelled ? (
                     <div className="flex justify-end gap-1">
                       <Button size="sm" icon={<Dice5 size={13} />} disabled={!r.filledCount} onClick={() => act(r, "draw")}>Sortear</Button>
                       <Button size="sm" variant="ghost" icon={<Ban size={13} />} onClick={() => act(r, "cancel")}>Cancelar</Button>
                     </div>) : null },
                 ]} />
        </Card>
      ))}
    </>
  );
}
