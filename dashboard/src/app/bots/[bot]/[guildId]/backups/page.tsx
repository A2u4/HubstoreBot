"use client";

import { Database, Download, Trash2 } from "lucide-react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Member } from "@/components/ui/member";
import { Empty, Spinner } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Backup { id: string; name: string; creatorId: string; size: number; createdAt: string }

function bytes(n: number): string {
  return n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

export default function BackupsPage() {
  const { api } = useGuild();
  const backups = useCollection<Backup>(`${api}/backups`);
  const members = useMembers(api, backups.rows.map((b) => b.creatorId));
  const download = async (backup: Backup) => {
    try {
      const full = await apiFetch<{ data: unknown }>(`${api}/backups/${backup.id}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(full.data, null, 2)], { type: "application/json" }));
      Object.assign(document.createElement("a"), { href: url, download: `${backup.name.replace(/[^\w.-]+/g, "_")}.json` }).click();
      URL.revokeObjectURL(url);
    } catch (err) { toast.error(errorMessage(err)); }
  };
  return (
    <>
      <PageHeader title="Respaldos" description="Copias de roles, canales y permisos. Se crean y restauran con /respaldo en Discord." icon={<Database size={18} />} />
      <ConfigEditor sections={[{ title: "Módulo", fields: [{ key: "backupEnabled", type: "toggle", label: "Activar respaldos" }] }]}>
        <Card>
          <CardHeader title="Copias guardadas" description={`${backups.rows.length} respaldo(s)`} />
          {backups.loading ? <Spinner /> : (
            <Table rows={backups.rows} rowKey={(b) => b.id} empty={<Empty title="Sin respaldos" description="Usa /respaldo crear en Discord." />}
                   columns={[
                     { key: "name", header: "Nombre", render: (b) => <span className="font-medium">{b.name}</span> },
                     { key: "by", header: "Creado por", render: (b) => <Member id={b.creatorId} info={members[b.creatorId]} /> },
                     { key: "size", header: "Tamaño", className: "tabular-nums text-muted", render: (b) => bytes(b.size) },
                     { key: "date", header: "Fecha", render: (b) => <span className="text-xs text-muted">{formatDate(b.createdAt)}</span> },
                     { key: "actions", header: "", className: "w-24 text-right", render: (b) => (
                       <div className="flex justify-end gap-1">
                         <Button size="sm" variant="ghost" aria-label="Descargar" onClick={() => download(b)}><Download size={14} /></Button>
                         <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => backups.remove(b.id, `¿Eliminar el respaldo «${b.name}»?`)}><Trash2 size={14} /></Button>
                       </div>) },
                   ]} />
          )}
        </Card>
      </ConfigEditor>
    </>
  );
}
