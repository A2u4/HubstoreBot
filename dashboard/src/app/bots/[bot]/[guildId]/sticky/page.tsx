"use client";

import { Pencil, Plus, StickyNote, Trash2 } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmbedPreview } from "@/components/ui/embed-preview";
import { ColorInput, Field, Input, Textarea, Toggle } from "@/components/ui/form";
import { Empty, Spinner, Tabs } from "@/components/ui/misc";
import { confirm, Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelMultiPicker } from "@/components/ui/pickers";
import { Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";

interface Sticky { id: string; channelId: string; title: string | null; description: string; color: string; plainText: boolean; enabled: boolean }

function StickyForm({ initial, onClose, onSaved }: { initial?: Sticky; onClose: () => void; onSaved: () => void }) {
  const { api, botName } = useGuild();
  const [channels, setChannels] = useState<string[]>(initial ? [initial.channelId] : []);
  const [data, setData] = useState({ title: initial?.title ?? "", description: initial?.description ?? "", color: initial?.color ?? "#FFFFFF",
                                     plainText: initial?.plainText ?? false, enabled: initial?.enabled ?? true });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const body = { ...data, title: data.title || null };
      if (initial) await apiFetch(`${api}/sticky/${initial.channelId}`, { method: "PATCH", body });
      else await apiFetch(`${api}/sticky`, { body: { ...body, channelIds: channels } });
      toast.success(initial ? "Mensaje fijo actualizado" : `Mensaje fijo publicado en ${channels.length} canal(es)`);
      onSaved();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open wide onClose={onClose} title={initial ? "Editar mensaje fijo" : "Nuevo mensaje fijo"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!data.description || (!initial && !channels.length)} onClick={save}>Guardar y publicar</Button></>}>
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          {!initial && <Field label="Canales" help="Se crea (o reemplaza) el mensaje fijo de cada canal."><ChannelMultiPicker value={channels} onChange={setChannels} /></Field>}
          <Toggle label="Texto plano" description="Sin embed: se envía como mensaje normal." checked={data.plainText} onChange={(plainText) => setData({ ...data, plainText })} />
          {!data.plainText && <Field label="Título"><Input value={data.title} maxLength={256} onChange={(e) => setData({ ...data, title: e.target.value })} /></Field>}
          <Field label="Contenido"><Textarea rows={6} value={data.description} maxLength={4000} onChange={(e) => setData({ ...data, description: e.target.value })} /></Field>
          {!data.plainText && <Field label="Color"><ColorInput value={data.color} onChange={(color) => setData({ ...data, color })} /></Field>}
          <Toggle label="Activado" checked={data.enabled} onChange={(enabled) => setData({ ...data, enabled })} />
        </div>
        <div><p className="label">Vista previa</p>
          <EmbedPreview botName={botName} plain={data.plainText} embed={{ title: data.title, description: data.description, color: data.color }} /></div>
      </div>
    </Modal>
  );
}

export default function StickyPage() {
  const { api, channelName } = useGuild();
  const [tab, setTab] = useState<"list" | "settings">("list");
  const sticky = useCollection<Sticky>(`${api}/sticky`);
  const [editing, setEditing] = useState<Sticky | "new" | null>(null);
  const removeSticky = async (row: Sticky) => {
    // Sticky routes are keyed by channel, so the endpoint is called directly instead of useCollection.remove.
    if (!(await confirm({ title: "Eliminar", message: `¿Quitar el mensaje fijo de ${channelName(row.channelId)}?`, danger: true, confirmLabel: "Eliminar" }))) return;
    try {
      await apiFetch(`${api}/sticky/${row.channelId}`, { method: "DELETE" });
      sticky.setRows((rows) => rows?.filter((r) => r.id !== row.id));
      toast.success("Mensaje fijo eliminado");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };
  return (
    <>
      <PageHeader title="Mensajes fijos" description="Mensajes que el bot mantiene siempre al final del canal" icon={<StickyNote size={18} />}
                  actions={<Button variant="primary" icon={<Plus size={14} />} onClick={() => setEditing("new")}>Nuevo</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "list", label: "Mensajes", count: sticky.rows.length }, { id: "settings", label: "Ajustes" }]} />
      {tab === "list" ? (
        <Card>
          {sticky.loading ? <Spinner /> : (
            <Table rows={sticky.rows} rowKey={(r) => r.id} empty={<Empty title="Sin mensajes fijos" description="También puedes usar /fijo en Discord." />}
                   columns={[
                     { key: "channel", header: "Canal", render: (r) => channelName(r.channelId) },
                     { key: "content", header: "Contenido", render: (r) => <span className="line-clamp-2 text-fg-2">{r.title ? <strong>{r.title} · </strong> : null}{r.description}</span> },
                     { key: "on", header: "", className: "w-16", render: (r) => <Toggle checked={r.enabled} onChange={async (enabled) => {
                       try {
                         const row = await apiFetch<Sticky>(`${api}/sticky/${r.channelId}`, { method: "PATCH", body: { enabled } });
                         sticky.setRows((rows) => rows?.map((x) => (x.id === r.id ? row : x)));
                       } catch (err) { toast.error(errorMessage(err)); }
                     }} /> },
                     { key: "actions", header: "", className: "w-20 text-right", render: (r) => (
                       <div className="flex justify-end gap-1">
                         <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditing(r)}><Pencil size={14} /></Button>
                         <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => removeSticky(r)}><Trash2 size={14} /></Button>
                       </div>) },
                   ]} />
          )}
        </Card>
      ) : <ConfigEditor sections={[{ title: "Módulo", fields: [{ key: "stickyEnabled", type: "toggle", label: "Activar mensajes fijos" }] }]} />}
      {editing && <StickyForm initial={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={sticky.reload} />}
    </>
  );
}
