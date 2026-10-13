"use client";

import { Coins, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, NumberInput, Textarea, Toggle } from "@/components/ui/form";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Stat, Tabs } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { RolePicker } from "@/components/ui/pickers";
import { Pager, Table } from "@/components/ui/table";
import { useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";

interface Item { id: string; name: string; description: string; emoji: string | null; price: number; roleId: string | null; stock: number | null; active: boolean }

const sections: SectionSpec[] = [
  { title: "Economía", fields: [
    { key: "economyEnabled", type: "toggle", label: "Activar economía",
      description: "/saldo, /diario, /semanal, /trabajar, /crimen, /robar, /pagar, /apostar, /tragamonedas, /items y /top-economia." },
    { key: "currencyName", type: "text", label: "Nombre de la moneda", max: 32 },
    { key: "currencySymbol", type: "text", label: "Símbolo o emoji", max: 64 },
    { key: "economyStartBalance", type: "number", label: "Saldo inicial", min: 0, max: 1_000_000_000 },
  ] },
  { title: "Recompensas", fields: [
    { key: "dailyAmount", type: "number", label: "Diario", min: 0, max: 100_000_000, help: "+10% por día de racha (máx. +100%)." },
    { key: "weeklyAmount", type: "number", label: "Semanal", min: 0, max: 100_000_000 },
    { key: "workMin", type: "number", label: "Trabajo: mínimo", min: 0, max: 100_000_000 },
    { key: "workMax", type: "number", label: "Trabajo: máximo", min: 0, max: 100_000_000 },
    { key: "workCooldownSeconds", type: "number", label: "Trabajo: espera", min: 0, max: 604_800, suffix: "seg" },
  ] },
  { title: "Crimen y robos", fields: [
    { key: "crimeMin", type: "number", label: "Crimen: mínimo", min: 0, max: 100_000_000 },
    { key: "crimeMax", type: "number", label: "Crimen: máximo", min: 0, max: 100_000_000 },
    { key: "crimeSuccessRate", type: "number", label: "Probabilidad de éxito", min: 0, max: 100, suffix: "%", help: "Al fallar se paga una multa de la mitad." },
    { key: "crimeCooldownSeconds", type: "number", label: "Crimen: espera", min: 0, max: 604_800, suffix: "seg" },
    { key: "robEnabled", type: "toggle", label: "Permitir robos", description: "40% de éxito, roba hasta el 30% de la cartera. El banco está a salvo." },
    { key: "robCooldownSeconds", type: "number", label: "Robo: espera", min: 0, max: 604_800, suffix: "seg", showIf: (c) => Boolean(c.robEnabled) },
  ] },
];

function ItemForm({ initial, onSubmit, onClose }: { initial?: Item; onSubmit: (data: Omit<Item, "id">) => Promise<unknown>; onClose: () => void }) {
  const [data, setData] = useState<Omit<Item, "id">>({ name: initial?.name ?? "", description: initial?.description ?? "", emoji: initial?.emoji ?? "",
    price: initial?.price ?? 100, roleId: initial?.roleId ?? null, stock: initial?.stock ?? null, active: initial?.active ?? true });
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onClose={onClose} title={initial ? "Editar artículo" : "Nuevo artículo"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!data.name} onClick={async () => {
               setBusy(true); if (await onSubmit({ ...data, emoji: data.emoji || null })) onClose(); setBusy(false);
             }}>Guardar</Button></>}>
      <div className="grid gap-4 sm:grid-cols-[1fr_96px]">
        <Field label="Nombre"><Input value={data.name} maxLength={60} onChange={(e) => setData({ ...data, name: e.target.value })} /></Field>
        <Field label="Emoji"><Input value={data.emoji ?? ""} maxLength={64} onChange={(e) => setData({ ...data, emoji: e.target.value })} /></Field>
        <Field label="Descripción" className="sm:col-span-2"><Textarea rows={2} maxLength={500} value={data.description} onChange={(e) => setData({ ...data, description: e.target.value })} /></Field>
        <Field label="Precio"><NumberInput value={data.price} min={0} max={2_000_000_000} onChange={(price) => setData({ ...data, price })} /></Field>
        <Field label="Stock" help="Vacío = ilimitado">
          <Input type="number" min={0} value={data.stock ?? ""} onChange={(e) => setData({ ...data, stock: e.target.value === "" ? null : Number(e.target.value) })} />
        </Field>
        <Field label="Rol que otorga (opcional)" className="sm:col-span-2"><RolePicker assignableOnly value={data.roleId} onChange={(roleId) => setData({ ...data, roleId })} /></Field>
        <div className="sm:col-span-2"><Toggle label="A la venta" checked={data.active} onChange={(active) => setData({ ...data, active })} /></div>
      </div>
    </Modal>
  );
}

function Items() {
  const { api, roleName } = useGuild();
  const items = useCollection<Item>(`${api}/economy/items`);
  const [editing, setEditing] = useState<Item | "new" | null>(null);
  return (
    <Card>
      <CardHeader title="Tienda de artículos" description="Se compran con /items comprar. Los artículos con rol lo entregan al comprarlos."
                  actions={<Button size="sm" variant="primary" icon={<Plus size={14} />} onClick={() => setEditing("new")}>Nuevo</Button>} />
      {items.loading ? <Spinner /> : (
        <Table rows={items.rows} rowKey={(r) => r.id} empty={<Empty title="Sin artículos" />}
               columns={[
                 { key: "name", header: "Artículo", render: (r) => <span>{r.emoji} {r.name}{!r.active && <Badge tone="muted" className="ml-2">oculto</Badge>}</span> },
                 { key: "price", header: "Precio", className: "tabular-nums", render: (r) => r.price.toLocaleString("es") },
                 { key: "stock", header: "Stock", className: "tabular-nums", render: (r) => r.stock ?? "∞" },
                 { key: "role", header: "Rol", render: (r) => r.roleId ? roleName(r.roleId) : <span className="text-faint">—</span> },
                 { key: "actions", header: "", className: "w-20 text-right", render: (r) => (
                   <div className="flex justify-end gap-1">
                     <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditing(r)}><Pencil size={14} /></Button>
                     <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => items.remove(r.id, `¿Eliminar «${r.name}»? Se quitará de los inventarios.`)}><Trash2 size={14} /></Button>
                   </div>) },
               ]} />
      )}
      {editing && <ItemForm initial={editing === "new" ? undefined : editing} onClose={() => setEditing(null)}
                            onSubmit={(data) => editing === "new" ? items.create(data) : items.update(editing.id, data)} />}
    </Card>
  );
}

function Leaderboard() {
  const { api } = useGuild();
  const [page, setPage] = useState(1);
  const board = useApi<{ rows: Array<{ userId: string; wallet: number; bank: number }>; pages: number; accounts: number; circulation: number }>(`${api}/economy/leaderboard?page=${page}`);
  const members = useMembers(api, board.data?.rows.map((r) => r.userId) ?? []);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Cuentas" value={board.data?.accounts.toLocaleString("es") ?? "—"} />
        <Stat label="Dinero en circulación" value={board.data?.circulation.toLocaleString("es") ?? "—"} />
      </div>
      <Card>
        {board.loading && !board.data ? <Spinner /> : (
          <>
            <Table rows={board.data?.rows ?? []} rowKey={(r) => r.userId} empty={<Empty title="Nadie tiene dinero todavía" />}
                   columns={[
                     { key: "pos", header: "#", className: "w-12 tabular-nums text-muted", render: (r) => (page - 1) * 25 + (board.data?.rows.indexOf(r) ?? 0) + 1 },
                     { key: "member", header: "Miembro", render: (r) => <Member id={r.userId} info={members[r.userId]} /> },
                     { key: "wallet", header: "Cartera", className: "tabular-nums text-muted", render: (r) => r.wallet.toLocaleString("es") },
                     { key: "bank", header: "Banco", className: "tabular-nums text-muted", render: (r) => r.bank.toLocaleString("es") },
                     { key: "total", header: "Total", className: "tabular-nums font-medium", render: (r) => (r.wallet + r.bank).toLocaleString("es") },
                   ]} />
            <Pager page={page} pages={board.data?.pages ?? 1} onChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}

export default function EconomyPage() {
  const [tab, setTab] = useState<"settings" | "items" | "ranking">("settings");
  return (
    <>
      <PageHeader title="Economía" description="Moneda del servidor, trabajos, apuestas y tienda de artículos" icon={<Coins size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "settings", label: "Ajustes" }, { id: "items", label: "Artículos" }, { id: "ranking", label: "Ranking" }]} />
      {tab === "settings" && <ConfigEditor sections={sections} />}
      {tab === "items" && <Items />}
      {tab === "ranking" && <Leaderboard />}
    </>
  );
}
