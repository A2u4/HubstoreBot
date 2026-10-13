"use client";

import { ChevronDown, Pencil, Plus, RefreshCw, RotateCcw, Terminal, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmbedPreview } from "@/components/ui/embed-preview";
import { ColorInput, Field, Input, Textarea, Toggle } from "@/components/ui/form";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { RoleMultiPicker } from "@/components/ui/pickers";
import { Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";
import { MODULES } from "@/lib/modules";

interface CommandRow {
  name: string; parent?: string; module: string; description: string; adminOnlyByDefault: boolean;
  disabled: boolean; roleIds: string[]; configured: boolean; inherited: boolean;
}
interface TextCommand { id: string; name: string; text: string; embedColor: string; title: string | null; thumbnailUrl: string | null; showAuthor: boolean; enabled: boolean }

const moduleLabel = (name: string) => MODULES.find((m) => m.name === name)?.label
  ?? ({ utility: "Utilidades", config: "Configuración", shop: "Tienda" } as Record<string, string>)[name] ?? name;

function PermissionRow({ row, onSave }: { row: CommandRow; onSave: (patch: Partial<CommandRow> & { reset?: boolean }) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const summary = row.disabled ? "Desactivado" : row.roleIds.length ? `${row.roleIds.length} rol(es)` : row.configured || row.inherited ? "Solo administradores" : "Por defecto";
  return (
    <div className="border-b border-line/60 last:border-0">
      <div className="flex items-center gap-3 px-5 py-3">
        <button type="button" onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <ChevronDown size={14} className={`shrink-0 text-muted transition-transform ${open ? "" : "-rotate-90"}`} />
          <div className="min-w-0">
            <code className="text-sm">/{row.name}</code>
            <p className="truncate text-xs text-muted">{row.description}</p>
          </div>
        </button>
        {row.inherited && <Badge tone="muted">hereda /{row.parent}</Badge>}
        <span className="hidden w-36 text-right text-xs text-muted sm:block">{summary}</span>
        <Toggle checked={!row.disabled} onChange={(on) => onSave({ disabled: !on })} />
      </div>
      {open && (
        <div className="space-y-3 border-t border-line/60 bg-surface-2/50 px-5 py-4 pl-12">
          <Field label="Roles permitidos" help="Sin roles + configurado = solo administradores. Sin configurar = permisos por defecto del comando.">
            <RoleMultiPicker value={row.roleIds} onChange={(roleIds) => onSave({ roleIds })} />
          </Field>
          {row.configured && <Button size="sm" variant="ghost" icon={<RotateCcw size={13} />} onClick={() => onSave({ reset: true })}>Restablecer</Button>}
        </div>
      )}
    </div>
  );
}

function TextCommandForm({ initial, onSubmit, onClose }: {
  initial?: TextCommand; onSubmit: (data: Omit<TextCommand, "id">) => Promise<unknown>; onClose: () => void;
}) {
  const { botName, guildName } = useGuild();
  const [data, setData] = useState({ name: initial?.name ?? "", text: initial?.text ?? "", embedColor: initial?.embedColor ?? "#FFFFFF",
                                     title: initial?.title ?? "", thumbnailUrl: initial?.thumbnailUrl ?? "", showAuthor: initial?.showAuthor ?? true,
                                     enabled: initial?.enabled ?? true });
  const [busy, setBusy] = useState(false);
  return (
    <Modal open wide onClose={onClose} title={initial ? `Editar /${initial.name}` : "Nuevo comando de texto"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!data.name || !data.text} onClick={async () => {
               setBusy(true);
               if (await onSubmit({ ...data, title: data.title || null, thumbnailUrl: data.thumbnailUrl || null })) onClose();
               setBusy(false);
             }}>Guardar</Button></>}>
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          <Field label="Nombre" help="Se publica como /nombre en este servidor."><Input value={data.name} maxLength={32} className="font-mono"
                 onChange={(e) => setData({ ...data, name: e.target.value.toLowerCase().replace(/\s+/g, "-") })} /></Field>
          <Field label="Título"><Input value={data.title} maxLength={256} onChange={(e) => setData({ ...data, title: e.target.value })} /></Field>
          <Field label="Texto"><Textarea rows={6} value={data.text} maxLength={2000} onChange={(e) => setData({ ...data, text: e.target.value })} /></Field>
          <Field label="Color"><ColorInput value={data.embedColor} onChange={(embedColor) => setData({ ...data, embedColor })} /></Field>
          <Field label="Miniatura (URL)"><Input value={data.thumbnailUrl} onChange={(e) => setData({ ...data, thumbnailUrl: e.target.value })} /></Field>
          <Toggle label="Mostrar nombre e icono del servidor" checked={data.showAuthor} onChange={(showAuthor) => setData({ ...data, showAuthor })} />
          <Toggle label="Activado" checked={data.enabled} onChange={(enabled) => setData({ ...data, enabled })} />
        </div>
        <div><p className="label">Vista previa</p>
          <EmbedPreview botName={botName} embed={{ title: data.title, description: data.text, color: data.embedColor,
                                                   thumbnailUrl: data.thumbnailUrl, authorName: data.showAuthor ? guildName : null }} /></div>
      </div>
    </Modal>
  );
}

export default function CommandsPage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<"permissions" | "text">("permissions");
  const commands = useApi<{ botOnline: boolean; commands: CommandRow[] }>(`${api}/commands`);
  const text = useCollection<TextCommand>(`${api}/commands/text`);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<TextCommand | "new" | null>(null);
  const [syncing, setSyncing] = useState(false);

  const grouped = useMemo(() => {
    const rows = (commands.data?.commands ?? []).filter((c) => !filter || `${c.name} ${c.description}`.toLowerCase().includes(filter.toLowerCase()));
    return [...new Set(rows.map((r) => r.module))].sort().map((module) => ({ module, rows: rows.filter((r) => r.module === module) }));
  }, [commands.data, filter]);

  const savePermission = async (row: CommandRow, patch: Partial<CommandRow> & { reset?: boolean }) => {
    try {
      await apiFetch(`${api}/commands/permissions`, { method: "PUT", body: {
        command: row.name, ...(patch.reset ? { reset: true } : {}),
        ...(patch.disabled !== undefined ? { disabled: patch.disabled } : {}), ...(patch.roleIds ? { roleIds: patch.roleIds } : {}),
      } });
      await commands.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const result = await apiFetch<{ count: number }>(`${api}/commands/sync`, { body: {} });
      toast.success(`${result.count} comandos sincronizados con Discord`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <>
      <PageHeader title="Comandos" description="Quién puede usar cada comando y comandos de texto personalizados" icon={<Terminal size={18} />}
                  actions={<>
                    <Button icon={<RefreshCw size={14} />} loading={syncing} onClick={sync}>Sincronizar con Discord</Button>
                    {tab === "text" && <Button variant="primary" icon={<Plus size={14} />} onClick={() => setEditing("new")}>Nuevo comando</Button>}
                  </>} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "permissions", label: "Permisos", count: commands.data?.commands.length },
        { id: "text", label: "Comandos de texto", count: text.rows.length },
      ]} />

      {tab === "permissions" && (commands.loading && !commands.data ? <Spinner /> : !commands.data?.botOnline ? (
        <Card><Empty title="El bot no está en línea" description="La lista de comandos se obtiene del bot en ejecución." /></Card>
      ) : (
        <div className="space-y-5">
          <Input placeholder="Buscar comando..." value={filter} onChange={(e) => setFilter(e.target.value)} />
          {grouped.map(({ module, rows }) => (
            <Card key={module}>
              <CardHeader title={moduleLabel(module)} description={`${rows.length} comando(s)`} />
              {rows.map((row) => <PermissionRow key={row.name} row={row} onSave={(patch) => savePermission(row, patch)} />)}
            </Card>
          ))}
        </div>
      ))}

      {tab === "text" && (
        <Card>
          {text.loading ? <Spinner /> : (
            <Table rows={text.rows} rowKey={(r) => r.id} empty={<Empty title="Sin comandos de texto" description="Crea respuestas rápidas como /reglas o /pagos." />}
                   columns={[
                     { key: "name", header: "Comando", render: (r) => <code className="text-sm">/{r.name}</code> },
                     { key: "text", header: "Respuesta", render: (r) => <span className="line-clamp-2 text-fg-2">{r.text}</span> },
                     { key: "on", header: "", className: "w-16", render: (r) => <Toggle checked={r.enabled} onChange={(enabled) => text.update(r.id, { enabled }, null)} /> },
                     { key: "actions", header: "", className: "w-20 text-right", render: (r) => (
                       <div className="flex justify-end gap-1">
                         <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditing(r)}><Pencil size={14} /></Button>
                         <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => text.remove(r.id, `¿Eliminar /${r.name}?`)}><Trash2 size={14} /></Button>
                       </div>) },
                   ]} />
          )}
        </Card>
      )}

      {editing && (
        <TextCommandForm initial={editing === "new" ? undefined : editing} onClose={() => setEditing(null)}
                         onSubmit={(data) => editing === "new" ? text.create(data, `/${data.name} creado`) : text.update(editing.id, data)} />
      )}
    </>
  );
}
