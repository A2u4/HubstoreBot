"use client";

import { Shield, Trash2 } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Input, Select } from "@/components/ui/form";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Pager, Table } from "@/components/ui/table";
import { useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Action { id: string; action: string; userId: string; moderatorId: string; reason: string; duration: number | null; active: boolean; syncedFromBot: string | null; createdAt: string }
interface Warning { id: string; userId: string; moderatorId: string; reason: string; syncedFromBot: string | null; createdAt: string }

const ACTIONS = ["ban", "tempban", "unban", "kick", "mute", "tempmute", "unmute", "warn"];
const LABEL: Record<string, string> = { ban: "Ban", tempban: "Ban temporal", unban: "Desban", kick: "Expulsión", mute: "Silencio", tempmute: "Silencio temporal", unmute: "Fin de silencio", warn: "Advertencia" };

export default function ModerationPage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<"actions" | "warnings" | "settings">("actions");
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const query = new URLSearchParams({ page: String(page), ...(action ? { action } : {}), ...(/^\d{17,20}$/.test(userId) ? { userId } : {}) });
  const actions = useApi<{ rows: Action[]; total: number; pages: number }>(tab === "actions" ? `${api}/moderation/actions?${query}` : null);
  const warnings = useCollection<Warning>(`${api}/moderation/warnings`);
  const members = useMembers(api, [...(actions.data?.rows.flatMap((r) => [r.userId, r.moderatorId]) ?? []), ...warnings.rows.flatMap((w) => [w.userId, w.moderatorId])]);
  return (
    <>
      <PageHeader title="Moderación" description="Historial de sanciones y advertencias (incluye las sincronizadas entre bots)" icon={<Shield size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "actions", label: "Sanciones", count: actions.data?.total }, { id: "warnings", label: "Advertencias", count: warnings.rows.length }, { id: "settings", label: "Ajustes" }]} />
      {tab === "settings" && <ConfigEditor sections={[{ title: "Moderación", fields: [
        { key: "moderationEnabled", type: "toggle", label: "Activar moderación", description: "/mod, /ban, /limpiar, /purgar, /modolento, /rol, /hackeado..." },
        { key: "modLogChannelId", type: "channel", label: "Registro de moderación" },
        { key: "warnLogChannelId", type: "channel", label: "Registro de advertencias" },
        { key: "muteRoleId", type: "role", label: "Rol de silencio" },
      ] }]} />}
      {tab === "actions" && (
        <Card>
          <div className="flex flex-wrap gap-3 border-b border-line p-4">
            <div className="w-48"><Select value={action} placeholder="Todas las acciones" options={ACTIONS.map((a) => ({ value: a, label: LABEL[a] }))} onChange={(v) => { setAction(v); setPage(1); }} /></div>
            <div className="w-64"><Input placeholder="Filtrar por ID de usuario" className="font-mono" value={userId} onChange={(e) => { setUserId(e.target.value.trim()); setPage(1); }} /></div>
          </div>
          {actions.loading && !actions.data ? <Spinner /> : (
            <>
              <Table rows={actions.data?.rows ?? []} rowKey={(r) => r.id} empty={<Empty title="Sin sanciones" />}
                     columns={[
                       { key: "action", header: "Acción", render: (r) => <span className="flex items-center gap-2">{LABEL[r.action] ?? r.action}{r.syncedFromBot && <Badge tone="muted">vía {r.syncedFromBot}</Badge>}</span> },
                       { key: "user", header: "Usuario", render: (r) => <Member id={r.userId} info={members[r.userId]} /> },
                       { key: "mod", header: "Moderador", render: (r) => <Member id={r.moderatorId} info={members[r.moderatorId]} /> },
                       { key: "reason", header: "Razón", render: (r) => <span className="line-clamp-2 text-fg-2">{r.reason}</span> },
                       { key: "date", header: "Fecha", render: (r) => <span className="text-xs text-muted">{formatDate(r.createdAt)}</span> },
                     ]} />
              <Pager page={page} pages={actions.data?.pages ?? 1} onChange={setPage} />
            </>
          )}
        </Card>
      )}
      {tab === "warnings" && (
        <Card>
          {warnings.loading ? <Spinner /> : (
            <Table rows={warnings.rows} rowKey={(r) => r.id} empty={<Empty title="Sin advertencias" />}
                   columns={[
                     { key: "user", header: "Usuario", render: (r) => <Member id={r.userId} info={members[r.userId]} /> },
                     { key: "reason", header: "Razón", render: (r) => <span className="text-fg-2">{r.reason}{r.syncedFromBot && <Badge tone="muted" className="ml-2">vía {r.syncedFromBot}</Badge>}</span> },
                     { key: "mod", header: "Moderador", render: (r) => <Member id={r.moderatorId} info={members[r.moderatorId]} /> },
                     { key: "date", header: "Fecha", render: (r) => <span className="text-xs text-muted">{formatDate(r.createdAt)}</span> },
                     { key: "del", header: "", className: "w-12 text-right", render: (r) => (
                       <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => warnings.remove(r.id, "¿Eliminar esta advertencia?")}><Trash2 size={14} /></Button>) },
                   ]} />
          )}
        </Card>
      )}
    </>
  );
}
