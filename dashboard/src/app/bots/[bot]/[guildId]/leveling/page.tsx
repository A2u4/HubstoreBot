"use client";

import { Plus, RotateCcw, Trash2, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, NumberInput, Select } from "@/components/ui/form";
import { Member } from "@/components/ui/member";
import { Empty, Spinner, Tabs } from "@/components/ui/misc";
import { confirm } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { RolePicker } from "@/components/ui/pickers";
import { Pager, Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { CHANNEL, useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";
import { levelFromXp } from "@/lib/leveling";

interface Reward { id: string; level: number; roleId: string }
interface Ranked { id: string; userId: string; xp: number; messages: number }

/** Text channels plus "off" (the bot's sentinel for no announcements); empty = same channel as the message. */
function LevelUpChannelPicker({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const { channels } = useGuild();
  const options = useMemo(() => [
    { value: "off", label: "No anunciar" },
    ...channels.filter((c) => c.type === CHANNEL.text || c.type === CHANNEL.news).map((c) => ({ value: c.id, label: `# ${c.name}` })),
  ], [channels]);
  return <Select value={value ?? ""} placeholder="El mismo canal del mensaje" options={options} onChange={(v) => onChange(v || null)} />;
}

const sections: SectionSpec[] = [
  { title: "Sistema de niveles", fields: [
    { key: "levelingEnabled", type: "toggle", label: "Activar niveles", description: "Los miembros ganan XP al escribir. /nivel muestra su tarjeta y /top-niveles el ranking." },
    { key: "xpPerMessageMin", type: "number", label: "XP mínima por mensaje", min: 1, max: 500 },
    { key: "xpPerMessageMax", type: "number", label: "XP máxima por mensaje", min: 1, max: 500 },
    { key: "xpCooldownSeconds", type: "number", label: "Espera entre mensajes con XP", min: 0, max: 3600, suffix: "seg", help: "Evita farmear XP con spam." },
  ] },
  { title: "Anuncio de subida de nivel", fields: [
    { key: "levelUpChannelId", type: "custom", label: "Dónde anunciar", render: (value, set) => <LevelUpChannelPicker value={value as string | null} onChange={set} /> },
    { key: "levelUpMessage", type: "textarea", label: "Mensaje", rows: 2, max: 1000, vars: ["{user}", "{username}", "{level}", "{server}"] },
  ] },
  { title: "Exclusiones", fields: [
    { key: "levelingIgnoredChannelIds", type: "channels", label: "Canales sin XP" },
    { key: "levelingIgnoredRoleIds", type: "roles", label: "Roles sin XP" },
  ] },
  { title: "Recompensas", fields: [
    { key: "levelRewardsStack", type: "toggle", label: "Acumular recompensas", description: "Apagado: al llegar a una recompensa nueva se quitan las anteriores." },
  ] },
];

function Rewards() {
  const { api, roleName } = useGuild();
  const rewards = useCollection<Reward>(`${api}/leveling/rewards`);
  const [level, setLevel] = useState(5);
  const [roleId, setRoleId] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader title="Roles por nivel" description="El bot da el rol al alcanzar el nivel (también con /niveles recompensa-agregar)." />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Nivel" className="w-28"><NumberInput value={level} min={1} max={500} onChange={setLevel} /></Field>
          <Field label="Rol" className="min-w-56 flex-1"><RolePicker assignableOnly value={roleId} onChange={setRoleId} placeholder="Elegir rol..." /></Field>
          <Button variant="primary" icon={<Plus size={14} />} disabled={!roleId}
                  onClick={async () => { if (await rewards.create({ level, roleId }, "Recompensa añadida")) setRoleId(null); }}>Añadir</Button>
        </div>
        {rewards.loading ? <Spinner /> : rewards.rows.length === 0 ? <p className="text-sm text-muted">Sin recompensas.</p> : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {[...rewards.rows].sort((a, b) => a.level - b.level).map((r) => (
              <li key={r.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <span><span className="tabular-nums text-muted">Nivel {r.level}</span> → {roleName(r.roleId)}</span>
                <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => rewards.remove(r.id)}><Trash2 size={14} /></Button>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function Leaderboard() {
  const { api } = useGuild();
  const [page, setPage] = useState(1);
  const board = useApi<{ rows: Ranked[]; total: number; pages: number }>(`${api}/leveling/leaderboard?page=${page}`);
  const members = useMembers(api, board.data?.rows.map((r) => r.userId) ?? []);
  const reset = async () => {
    if (!(await confirm({ title: "Reiniciar XP", message: "Se borrará el XP de TODOS los miembros. Los roles ya entregados se mantienen.", danger: true, confirmLabel: "Reiniciar todo" }))) return;
    try {
      const result = await apiFetch<{ count: number }>(`${api}/leveling/reset`, { body: {} });
      toast.success(`${result.count} miembros reiniciados`);
      board.reload();
    } catch (err) { toast.error(errorMessage(err)); }
  };
  return (
    <Card>
      <CardHeader title="Ranking" description={`${board.data?.total ?? 0} miembros con XP`}
                  actions={<Button size="sm" variant="danger" icon={<RotateCcw size={13} />} onClick={reset}>Reiniciar todo</Button>} />
      {board.loading && !board.data ? <Spinner /> : (
        <>
          <Table rows={board.data?.rows ?? []} rowKey={(r) => r.id} empty={<Empty title="Nadie tiene XP todavía" />}
                 columns={[
                   { key: "pos", header: "#", className: "w-12 tabular-nums text-muted", render: (r) => (page - 1) * 25 + (board.data?.rows.indexOf(r) ?? 0) + 1 },
                   { key: "member", header: "Miembro", render: (r) => <Member id={r.userId} info={members[r.userId]} /> },
                   { key: "level", header: "Nivel", render: (r) => {
                     const p = levelFromXp(r.xp);
                     return (
                       <div className="flex items-center gap-3">
                         <span className="w-8 tabular-nums font-medium">{p.level}</span>
                         <div className="h-1.5 w-28 overflow-hidden rounded-full bg-surface-3"><div className="h-full bg-fg" style={{ width: `${(p.current / p.needed) * 100}%` }} /></div>
                       </div>
                     );
                   } },
                   { key: "xp", header: "XP", className: "tabular-nums", render: (r) => r.xp.toLocaleString("es") },
                   { key: "msgs", header: "Mensajes", className: "tabular-nums text-muted", render: (r) => r.messages.toLocaleString("es") },
                 ]} />
          <Pager page={page} pages={board.data?.pages ?? 1} onChange={setPage} />
        </>
      )}
    </Card>
  );
}

export default function LevelingPage() {
  const [tab, setTab] = useState<"settings" | "rewards" | "ranking">("settings");
  return (
    <>
      <PageHeader title="Niveles" description="XP por actividad, tarjetas de rango y roles por nivel" icon={<TrendingUp size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "settings", label: "Ajustes" }, { id: "rewards", label: "Recompensas" }, { id: "ranking", label: "Ranking" }]} />
      {tab === "settings" && <ConfigEditor sections={sections} />}
      {tab === "rewards" && <Rewards />}
      {tab === "ranking" && <Leaderboard />}
    </>
  );
}
