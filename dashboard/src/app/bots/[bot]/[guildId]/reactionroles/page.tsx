"use client";

import { Plus, Tags, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { Badge, Empty, Spinner } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker, RolePicker } from "@/components/ui/pickers";
import { Table } from "@/components/ui/table";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";

interface ReactionRole { id: string; channelId: string; messageId: string; emoji: string; roleId: string; type: string }

const TYPES = [
  { value: "toggle", label: "Alternar (dar y quitar)" }, { value: "give", label: "Solo dar" }, { value: "remove", label: "Solo quitar" },
];

export default function ReactionRolesPage() {
  const { api, channelName, roleName, emojis } = useGuild();
  const roles = useCollection<ReactionRole>(`${api}/reactionroles`);
  const [form, setForm] = useState<Omit<ReactionRole, "id"> | null>(null);
  const [busy, setBusy] = useState(false);
  const emojiLabel = (raw: string) => {
    const custom = /<a?:(\w+):(\d+)>/.exec(raw);
    const found = custom && emojis.find((e) => e.id === custom[2]);
    // eslint-disable-next-line @next/next/no-img-element
    return found ? <img src={found.url} alt={found.name} className="inline size-5" /> : raw;
  };
  return (
    <>
      <PageHeader title="Roles por reacción" description="Reaccionar a un mensaje da o quita un rol. Para paneles con botones usa /rolreaccion en Discord." icon={<Tags size={18} />}
                  actions={<Button variant="primary" icon={<Plus size={14} />} onClick={() => setForm({ channelId: "", messageId: "", emoji: "", roleId: "", type: "toggle" })}>Añadir</Button>} />
      <Card>
        {roles.loading ? <Spinner /> : (
          <Table rows={roles.rows} rowKey={(r) => r.id} empty={<Empty title="Sin roles por reacción" />}
                 columns={[
                   { key: "emoji", header: "Emoji", className: "w-16", render: (r) => <span className="text-lg">{emojiLabel(r.emoji)}</span> },
                   { key: "role", header: "Rol", render: (r) => roleName(r.roleId) },
                   { key: "message", header: "Mensaje", render: (r) => <span className="text-xs text-muted">{channelName(r.channelId)} · {r.messageId}</span> },
                   { key: "type", header: "Tipo", render: (r) => <Badge>{TYPES.find((t) => t.value === r.type)?.label ?? r.type}</Badge> },
                   { key: "actions", header: "", className: "w-12 text-right", render: (r) => (
                     <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => roles.remove(r.id, "¿Eliminar este rol por reacción?")}><Trash2 size={14} /></Button>) },
                 ]} />
        )}
      </Card>
      {form && (
        <Modal open onClose={() => setForm(null)} title="Nuevo rol por reacción"
               footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancelar</Button>
                 <Button variant="primary" loading={busy} disabled={!form.channelId || !form.messageId || !form.emoji || !form.roleId}
                         onClick={async () => { setBusy(true); if (await roles.create(form)) setForm(null); setBusy(false); }}>Guardar</Button></>}>
          <div className="space-y-4">
            <Field label="Canal"><ChannelPicker value={form.channelId} onChange={(v) => setForm({ ...form, channelId: v ?? "" })} /></Field>
            <Field label="ID del mensaje" help="Clic derecho en el mensaje → Copiar ID (requiere modo desarrollador).">
              <Input value={form.messageId} className="font-mono" onChange={(e) => setForm({ ...form, messageId: e.target.value.trim() })} />
            </Field>
            <Field label="Emoji" help="Unicode (⭐) o personalizado (<:nombre:id>)."><Input value={form.emoji} onChange={(e) => setForm({ ...form, emoji: e.target.value.trim() })} /></Field>
            <Field label="Rol"><RolePicker assignableOnly value={form.roleId} onChange={(v) => setForm({ ...form, roleId: v ?? "" })} /></Field>
            <Field label="Comportamiento"><Select value={form.type} options={TYPES} onChange={(type) => setForm({ ...form, type })} /></Field>
          </div>
        </Modal>
      )}
    </>
  );
}
