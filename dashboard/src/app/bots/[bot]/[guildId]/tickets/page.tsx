"use client";

import { Copy, Download, Eye, Pencil, Plus, RefreshCw, Send, Ticket, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { formatDate, relativeTime } from "@/components/ui/format";
import { ColorInput, Field, Input, NumberInput, Select, TagInput, Textarea } from "@/components/ui/form";
import { Member } from "@/components/ui/member";
import { Badge, Empty, Spinner, Stat, Tabs } from "@/components/ui/misc";
import { confirm, Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker } from "@/components/ui/pickers";
import { Pager, Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";
import { useMembers } from "@/lib/client/members";
import { DEFAULT_PANEL, editablePanel, PanelForm, type TicketPanel } from "./panel-form";

interface TicketRow {
  id: string; number: number; status: string; userId: string; channelId: string; claimedBy: string | null; priority: string;
  topic: string | null; rating: number | null; feedback: string | null; formAnswers: Record<string, string> | Array<{ question: string; answer: string }> | null;
  createdAt: string; closedAt: string | null; panel: { id: string; name: string } | null;
  transcripts?: Array<{ id: string; messageCount: number; createdAt: string }>;
}
interface TranscriptRow { id: string; userId: string; closedBy: string | null; messageCount: number; createdAt: string; ticket: { number: number } | null }
interface TranscriptMessage {
  author?: string; authorName?: string; content?: string; timestamp?: string;
  attachments?: Array<string | { url: string; name?: string }>;
}

const PRIORITY: Record<string, string> = { low: "Baja", normal: "Normal", high: "Alta", urgent: "Urgente" };
const pad = (n: number) => String(n).padStart(4, "0");

function Overview() {
  const { api } = useGuild();
  const { data } = useApi<Record<string, number | null>>(`${api}/tickets/stats`);
  const v = (k: string) => (data?.[k] ?? "—").toLocaleString();
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Abiertos" value={v("open")} />
      <Stat label="Esta semana" value={v("thisWeek")} />
      <Stat label="Valoración media" value={data?.avgRating ? `${data.avgRating}/5` : "—"} hint={data?.ratings ? `${data.ratings} valoraciones` : undefined} />
      <Stat label="Primera respuesta" value={data?.medianFirstResponseMinutes != null ? `${data.medianFirstResponseMinutes} min` : "—"} hint="Mediana, últimos 30 días" />
      <Stat label="Cerrados" value={v("closed")} />
      <Stat label="Total" value={v("total")} />
      <Stat label="Paneles" value={v("panels")} />
      <Stat label="Transcripciones" value={v("transcripts")} />
    </div>
  );
}

function TicketDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { api, channelName } = useGuild();
  const ticket = useApi<TicketRow>(`${api}/tickets/${id}`);
  const t = ticket.data;
  const members = useMembers(api, t ? [t.userId, t.claimedBy ?? ""] : []);
  const patch = async (body: Record<string, string>) => {
    try {
      ticket.setData(await apiFetch<TicketRow>(`${api}/tickets/${id}`, { method: "PATCH", body }));
      toast.success("Ticket actualizado");
      onChanged();
    } catch (err) { toast.error(errorMessage(err)); }
  };
  const answers = !t?.formAnswers ? [] : Array.isArray(t.formAnswers)
    ? t.formAnswers.map((a) => [a.question, a.answer] as const) : Object.entries(t.formAnswers);
  return (
    <Modal open wide onClose={onClose} title={t ? `Ticket #${pad(t.number)}` : "Ticket"} description={t?.panel?.name}>
      {!t ? <Spinner /> : (
        <div className="space-y-5">
          <dl className="grid gap-4 text-sm sm:grid-cols-3">
            <div><dt className="label">Creador</dt><dd><Member id={t.userId} info={members[t.userId]} /></dd></div>
            <div><dt className="label">Asignado</dt><dd>{t.claimedBy ? <Member id={t.claimedBy} info={members[t.claimedBy]} /> : <span className="text-faint">—</span>}</dd></div>
            <div><dt className="label">Canal</dt><dd>{t.status === "open" ? channelName(t.channelId) : <span className="text-faint">Eliminado</span>}</dd></div>
            <div><dt className="label">Abierto</dt><dd className="text-fg-2">{formatDate(t.createdAt)}</dd></div>
            <div><dt className="label">Cerrado</dt><dd className="text-fg-2">{formatDate(t.closedAt)}</dd></div>
            <div><dt className="label">Valoración</dt><dd className="text-fg-2">{t.rating ? `${"★".repeat(t.rating)}${"☆".repeat(5 - t.rating)}` : "—"}</dd></div>
          </dl>
          {t.feedback && <p className="border-l-2 border-line-strong pl-3 text-sm text-fg-2">{t.feedback}</p>}
          {answers.length > 0 && (
            <div><p className="label">Formulario</p>
              <dl className="space-y-2 rounded-lg border border-line p-3 text-sm">
                {answers.map(([q, a]) => <div key={q}><dt className="text-xs text-muted">{q}</dt><dd className="whitespace-pre-wrap">{a}</dd></div>)}
              </dl>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
            <Field label="Prioridad"><Select value={t.priority} options={Object.entries(PRIORITY).map(([value, label]) => ({ value, label }))} onChange={(priority) => patch({ priority })} /></Field>
            <Field label="Asunto"><Input defaultValue={t.topic ?? ""} maxLength={256} onBlur={(e) => e.target.value !== (t.topic ?? "") && patch({ topic: e.target.value })} /></Field>
          </div>
          {t.transcripts && t.transcripts.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {t.transcripts.map((tr) => (
                <a key={tr.id} href={`${api}/tickets/transcripts/${tr.id}/html`} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs hover:border-line-strong">
                  <Download size={12} /> Transcripción · {tr.messageCount} mensajes
                </a>
              ))}
            </div>
          )}
          {t.status === "open" && (
            <Button variant="danger" icon={<X size={14} />} onClick={async () => {
              if (await confirm({ title: "Cerrar ticket", message: "El bot generará la transcripción y cerrará el canal.", confirmLabel: "Cerrar ticket", danger: true })) patch({ status: "closed" });
            }}>Cerrar ticket</Button>
          )}
        </div>
      )}
    </Modal>
  );
}

function TicketList({ panels }: { panels: TicketPanel[] }) {
  const { api } = useGuild();
  const [filters, setFilters] = useState({ status: "open", panelId: "", priority: "" });
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const query = new URLSearchParams({ page: String(page), ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) });
  const list = useApi<{ tickets: TicketRow[]; total: number; pages: number }>(`${api}/tickets?${query}`);
  const members = useMembers(api, list.data?.tickets.flatMap((t) => [t.userId, t.claimedBy ?? ""]) ?? []);
  const setFilter = (patch: Partial<typeof filters>) => { setFilters((f) => ({ ...f, ...patch })); setPage(1); };
  return (
    <Card>
      <div className="flex flex-wrap gap-3 border-b border-line p-4">
        <div className="w-40"><Select value={filters.status} placeholder="Todos" options={[{ value: "open", label: "Abiertos" }, { value: "closed", label: "Cerrados" }]} onChange={(status) => setFilter({ status })} /></div>
        <div className="w-48"><Select value={filters.panelId} placeholder="Todos los paneles" options={panels.map((p) => ({ value: p.id, label: p.name }))} onChange={(panelId) => setFilter({ panelId })} /></div>
        <div className="w-44"><Select value={filters.priority} placeholder="Toda prioridad" options={Object.entries(PRIORITY).map(([value, label]) => ({ value, label }))} onChange={(priority) => setFilter({ priority })} /></div>
      </div>
      {list.loading && !list.data ? <Spinner /> : (
        <>
          <Table rows={list.data?.tickets ?? []} rowKey={(t) => t.id} onRowClick={(t) => setOpen(t.id)} empty={<Empty title="Sin tickets" />}
                 columns={[
                   { key: "n", header: "#", className: "w-20 font-mono text-xs", render: (t) => pad(t.number) },
                   { key: "user", header: "Creador", render: (t) => <Member id={t.userId} info={members[t.userId]} /> },
                   { key: "panel", header: "Panel", render: (t) => <span className="text-muted">{t.panel?.name ?? "—"}</span> },
                   { key: "claim", header: "Asignado", render: (t) => t.claimedBy ? <Member id={t.claimedBy} info={members[t.claimedBy]} /> : <span className="text-faint">—</span> },
                   { key: "prio", header: "Prioridad", render: (t) => <Badge tone={t.priority === "urgent" ? "solid" : t.priority === "low" ? "muted" : "default"}>{PRIORITY[t.priority] ?? t.priority}</Badge> },
                   { key: "date", header: "Abierto", render: (t) => <span className="text-xs text-muted" title={formatDate(t.createdAt)}>{relativeTime(t.createdAt)}</span> },
                 ]} />
          <Pager page={page} pages={list.data?.pages ?? 1} onChange={setPage} />
        </>
      )}
      {open && <TicketDetail id={open} onClose={() => setOpen(null)} onChanged={list.reload} />}
    </Card>
  );
}

interface GroupDraft { panelIds: string[]; channelId: string | null; embedTitle: string; embedDescription: string; embedColor: string; embedImages: string[]; embedImageInterval: number; existing?: TicketPanel[] }

function GroupModal({ draft, panels, onClose, onDone }: { draft: GroupDraft; panels: TicketPanel[]; onClose: () => void; onDone: () => void }) {
  const { api } = useGuild();
  const [d, setD] = useState(draft);
  const [busy, setBusy] = useState(false);
  const editing = Boolean(draft.existing);
  const submit = async () => {
    setBusy(true);
    try {
      if (editing) {
        // Update the group embed on every panel of the deployed message, then refresh it once.
        for (const panel of draft.existing!) {
          await apiFetch(`${api}/tickets/panels/${panel.id}`, { method: "PATCH", body: {
            groupEmbedTitle: d.embedTitle, groupEmbedDescription: d.embedDescription, groupEmbedColor: d.embedColor,
            groupEmbedImages: d.embedImages, embedImageInterval: d.embedImageInterval } });
        }
        toast.success("Mensaje actualizado");
      } else {
        await apiFetch(`${api}/tickets/panels/deploy`, { body: { ...d, existing: undefined } });
        toast.success("Panel publicado en Discord");
      }
      onDone();
      onClose();
    } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
  };
  return (
    <Modal open wide onClose={onClose} title={editing ? "Editar mensaje publicado" : "Publicar panel en Discord"}
           description="Hasta 5 paneles comparten un mensaje: un embed y un botón por panel."
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" icon={<Send size={14} />} loading={busy} disabled={!editing && (!d.channelId || !d.panelIds.length)} onClick={submit}>
               {editing ? "Guardar" : "Publicar"}</Button></>}>
      <div className="grid gap-4 md:grid-cols-2">
        {!editing && (
          <>
            <Field label="Paneles (botones)" className="md:col-span-2">
              <div className="flex flex-wrap gap-2">
                {panels.map((p) => {
                  const on = d.panelIds.includes(p.id);
                  return (
                    <button key={p.id} type="button" disabled={!on && d.panelIds.length >= 5}
                            onClick={() => setD({ ...d, panelIds: on ? d.panelIds.filter((x) => x !== p.id) : [...d.panelIds, p.id] })}
                            className={`rounded-md border px-3 py-1.5 text-sm disabled:opacity-40 ${on ? "border-fg bg-fg text-bg" : "border-line hover:border-line-strong"}`}>
                      {p.buttonEmoji} {p.buttonLabel} <span className="opacity-60">· {p.name}</span>
                    </button>
                  );
                })}
              </div>
            </Field>
            <Field label="Canal"><ChannelPicker value={d.channelId} onChange={(channelId) => setD({ ...d, channelId })} /></Field>
          </>
        )}
        <Field label="Color"><ColorInput value={d.embedColor} onChange={(embedColor) => setD({ ...d, embedColor })} /></Field>
        <Field label="Título" className="md:col-span-2"><Input value={d.embedTitle} maxLength={256} onChange={(e) => setD({ ...d, embedTitle: e.target.value })} /></Field>
        <Field label="Descripción" className="md:col-span-2"><Textarea rows={4} value={d.embedDescription} maxLength={4000} onChange={(e) => setD({ ...d, embedDescription: e.target.value })} /></Field>
        <Field label="Imágenes (URLs)" help="Con varias, el bot las rota en el mensaje." className="md:col-span-2">
          <TagInput value={d.embedImages} placeholder="https://... y Enter" max={20} onChange={(embedImages) => setD({ ...d, embedImages })} />
        </Field>
        {d.embedImages.length > 1 && <Field label="Cambiar imagen cada"><NumberInput value={d.embedImageInterval} min={1} max={86_400} suffix="seg" onChange={(embedImageInterval) => setD({ ...d, embedImageInterval })} /></Field>}
      </div>
    </Modal>
  );
}

function Panels({ panels }: { panels: ReturnType<typeof useCollection<TicketPanel>> }) {
  const { api, channelName } = useGuild();
  const [editing, setEditing] = useState<Partial<TicketPanel> | null>(null);
  const [group, setGroup] = useState<GroupDraft | null>(null);
  const groups = useMemo(() => {
    const byMessage = new Map<string, TicketPanel[]>();
    for (const p of panels.rows) if (p.messageId) byMessage.set(p.messageId, [...(byMessage.get(p.messageId) ?? []), p]);
    return [...byMessage.values()];
  }, [panels.rows]);
  const sync = async (panel: TicketPanel) => {
    try { await apiFetch(`${api}/tickets/panels/${panel.id}/sync`, { body: {} }); toast.success("Mensaje actualizado en Discord"); }
    catch (err) { toast.error(errorMessage(err)); }
  };
  const save = async (data: Partial<TicketPanel>) => {
    if (editing?.id) {
      const row = await panels.update(editing.id, data, null);
      if (row) toast.success((row as TicketPanel & { synced?: boolean }).synced ? "Panel guardado y actualizado en Discord" : "Panel guardado");
      return row;
    }
    return panels.create(data, "Panel creado");
  };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" icon={<Plus size={14} />} onClick={() => setEditing({ ...DEFAULT_PANEL })}>Nuevo panel</Button>
        <Button icon={<Send size={14} />} disabled={!panels.rows.length} onClick={() => setGroup({
          panelIds: [], channelId: null, embedTitle: "Sistema de Tickets", embedDescription: "Elige una opción para abrir un ticket.", embedColor: "#FFFFFF",
          embedImages: [], embedImageInterval: 10 })}>Publicar en Discord</Button>
      </div>
      <Card>
        <CardHeader title="Paneles" description="Cada panel define un tipo de ticket (botón)." />
        {panels.loading ? <Spinner /> : (
          <Table rows={panels.rows} rowKey={(p) => p.id} empty={<Empty title="Sin paneles" description="Crea uno o usa /ticket preset en Discord." />}
                 columns={[
                   { key: "name", header: "Panel", render: (p) => <div><div className="font-medium">{p.buttonEmoji} {p.name}</div><div className="text-xs text-muted">{p.buttonLabel}</div></div> },
                   { key: "where", header: "Publicado en", render: (p) => p.messageId ? channelName(p.channelId) : <Badge tone="muted">Sin publicar</Badge> },
                   { key: "count", header: "Tickets", className: "tabular-nums text-muted", render: (p) => p._count?.tickets ?? 0 },
                   { key: "actions", header: "", className: "w-36 text-right", render: (p) => (
                     <div className="flex justify-end gap-1">
                       <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditing(p)}><Pencil size={14} /></Button>
                       <Button size="sm" variant="ghost" aria-label="Duplicar" onClick={() => setEditing({ ...editablePanel(p), name: `${p.name} (copia)` })}><Copy size={14} /></Button>
                       {p.messageId && <Button size="sm" variant="ghost" aria-label="Actualizar en Discord" onClick={() => sync(p)}><RefreshCw size={14} /></Button>}
                       <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => panels.remove(p.id, `¿Eliminar el panel «${p.name}»? Los tickets existentes se conservan.`)}><Trash2 size={14} /></Button>
                     </div>) },
                 ]} />
        )}
      </Card>
      {groups.length > 0 && (
        <Card>
          <CardHeader title="Mensajes publicados" />
          <ul className="divide-y divide-line">
            {groups.map((g) => (
              <li key={g[0].messageId} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-medium">{g[0].groupEmbedTitle || g[0].title}</div>
                  <div className="truncate text-xs text-muted">{channelName(g[0].channelId)} · {g.map((p) => p.buttonLabel).join(", ")}</div>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" icon={<Pencil size={13} />} onClick={() => setGroup({
                    panelIds: g.map((p) => p.id), channelId: g[0].channelId, embedTitle: g[0].groupEmbedTitle || g[0].title,
                    embedDescription: g[0].groupEmbedDescription ?? "", embedColor: g[0].groupEmbedColor || g[0].embedColor,
                    embedImages: g[0].groupEmbedImages ?? [], embedImageInterval: g[0].embedImageInterval, existing: g })}>Editar</Button>
                  <Button size="sm" variant="ghost" icon={<RefreshCw size={13} />} onClick={() => sync(g[0])}>Actualizar</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {editing && <PanelForm initial={editing} panels={panels.rows} onClose={() => setEditing(null)} onSubmit={save} />}
      {group && <GroupModal draft={group} panels={panels.rows} onClose={() => setGroup(null)} onDone={panels.reload} />}
    </div>
  );
}

function Transcripts() {
  const { api } = useGuild();
  const [page, setPage] = useState(1);
  const list = useApi<{ transcripts: TranscriptRow[]; pages: number }>(`${api}/tickets/transcripts?page=${page}`);
  const members = useMembers(api, list.data?.transcripts.flatMap((t) => [t.userId, t.closedBy ?? ""]) ?? []);
  const [viewing, setViewing] = useState<string | null>(null);
  const transcript = useApi<{ messages: TranscriptMessage[]; ticket: { number: number } | null }>(viewing ? `${api}/tickets/transcripts/${viewing}` : null);
  return (
    <Card>
      {list.loading && !list.data ? <Spinner /> : (
        <>
          <Table rows={list.data?.transcripts ?? []} rowKey={(t) => t.id} empty={<Empty title="Sin transcripciones" />}
                 columns={[
                   { key: "n", header: "Ticket", className: "font-mono text-xs", render: (t) => t.ticket ? `#${pad(t.ticket.number)}` : "—" },
                   { key: "user", header: "Usuario", render: (t) => <Member id={t.userId} info={members[t.userId]} /> },
                   { key: "by", header: "Cerrado por", render: (t) => t.closedBy && /^\d+$/.test(t.closedBy) ? <Member id={t.closedBy} info={members[t.closedBy]} /> : <span className="text-muted">{t.closedBy ?? "—"}</span> },
                   { key: "msgs", header: "Mensajes", className: "tabular-nums text-muted", render: (t) => t.messageCount },
                   { key: "date", header: "Fecha", render: (t) => <span className="text-xs text-muted">{formatDate(t.createdAt)}</span> },
                   { key: "actions", header: "", className: "w-24 text-right", render: (t) => (
                     <div className="flex justify-end gap-1">
                       <Button size="sm" variant="ghost" aria-label="Ver" onClick={() => setViewing(t.id)}><Eye size={14} /></Button>
                       <a href={`${api}/tickets/transcripts/${t.id}/html`} aria-label="Descargar HTML" className="inline-flex h-8 items-center rounded-lg px-3 text-fg-2 hover:bg-surface-3"><Download size={14} /></a>
                     </div>) },
                 ]} />
          <Pager page={page} pages={list.data?.pages ?? 1} onChange={setPage} />
        </>
      )}
      {viewing && (
        <Modal open wide onClose={() => setViewing(null)} title={transcript.data?.ticket ? `Transcripción #${pad(transcript.data.ticket.number)}` : "Transcripción"}>
          {transcript.loading ? <Spinner /> : (
            <ul className="space-y-3">
              {(transcript.data?.messages ?? []).map((m, i) => (
                <li key={i} className="text-sm">
                  <div className="flex items-baseline gap-2"><span className="font-medium">{m.authorName ?? m.author ?? "?"}</span>
                    <span className="text-[11px] text-faint">{m.timestamp ? formatDate(m.timestamp) : ""}</span></div>
                  {m.content && <p className="whitespace-pre-wrap text-fg-2">{m.content}</p>}
                  {m.attachments?.map((a) => {
                    const { url, name } = typeof a === "string" ? { url: a, name: a } : { url: a.url, name: a.name ?? a.url };
                    return <a key={url} href={url} target="_blank" rel="noreferrer" className="block truncate text-xs text-muted underline">{name}</a>;
                  })}
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </Card>
  );
}

export default function TicketsPage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<"overview" | "tickets" | "panels" | "transcripts" | "settings">("overview");
  const panels = useCollection<TicketPanel>(`${api}/tickets/panels`);
  return (
    <>
      <PageHeader title="Tickets" description="Soporte y compras con paneles, formularios, asignación, valoraciones y transcripciones" icon={<Ticket size={18} />} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Resumen" }, { id: "tickets", label: "Tickets" }, { id: "panels", label: "Paneles", count: panels.rows.length },
        { id: "transcripts", label: "Transcripciones" }, { id: "settings", label: "Ajustes" },
      ]} />
      {tab === "overview" && <Overview />}
      {tab === "tickets" && <TicketList panels={panels.rows} />}
      {tab === "panels" && <Panels panels={panels} />}
      {tab === "transcripts" && <Transcripts />}
      {tab === "settings" && <ConfigEditor sections={[{ title: "Ajustes globales", description: "Cada panel puede sobrescribir categoría, registro y transcripciones.", fields: [
        { key: "ticketsEnabled", type: "toggle", label: "Activar tickets" },
        { key: "ticketCategoryId", type: "channel", kind: "category", label: "Categoría por defecto" },
        { key: "ticketLogChannelId", type: "channel", label: "Canal de registro" },
        { key: "ticketTranscriptChannelId", type: "channel", label: "Canal de transcripciones" },
        { key: "ticketStaffRoleIds", type: "roles", label: "Roles del staff (todos los paneles)" },
        { key: "ticketCloseConfirmation", type: "toggle", label: "Confirmar antes de cerrar" },
        { key: "ticketDMTranscript", type: "toggle", label: "Enviar transcripción por DM" },
      ] }]} />}
    </>
  );
}
