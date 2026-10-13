"use client";

import { Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ConfigEditor } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { formatDate } from "@/components/ui/format";
import { Field, Input, NumberInput, Select, Textarea, Toggle } from "@/components/ui/form";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker } from "@/components/ui/pickers";
import { Table } from "@/components/ui/table";
import { useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { useGuild } from "@/lib/client/guild";

interface AutoResponse { id: string; trigger: string; response: string; matchType: string; enabled: boolean }
interface Scheduled { id: string; channelId: string; message: string; cron: string; enabled: boolean; lastRun: string | null }
interface Poll { id: string; question: string; options: string[]; votes: Record<string, unknown>; ended: boolean; endsAt: string | null; createdAt: string }

const MATCH = [
  { value: "contains", label: "Contiene" }, { value: "exact", label: "Exacto" },
  { value: "startsWith", label: "Empieza con" }, { value: "regex", label: "Expresión regular" },
];

function describeSchedule(cron: string): string {
  const every = /^@every:(\d+)$/.exec(cron);
  if (!every) return cron;
  const minutes = Number(every[1]) / 60_000;
  return minutes % 1440 === 0 ? `Cada ${minutes / 1440} día(s)` : minutes % 60 === 0 ? `Cada ${minutes / 60} hora(s)` : `Cada ${minutes} min`;
}

function ResponseForm({ initial, onSubmit, onClose }: {
  initial?: AutoResponse; onSubmit: (data: Omit<AutoResponse, "id">) => Promise<unknown>; onClose: () => void;
}) {
  const [data, setData] = useState({ trigger: initial?.trigger ?? "", response: initial?.response ?? "",
                                     matchType: initial?.matchType ?? "contains", enabled: initial?.enabled ?? true });
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onClose={onClose} title={initial ? "Editar respuesta" : "Nueva respuesta automática"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!data.trigger || !data.response}
                     onClick={async () => { setBusy(true); if (await onSubmit(data)) onClose(); setBusy(false); }}>Guardar</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-[1fr_180px]">
          <Field label="Disparador"><Input value={data.trigger} maxLength={200} onChange={(e) => setData({ ...data, trigger: e.target.value })} /></Field>
          <Field label="Coincidencia"><Select value={data.matchType} options={MATCH} onChange={(matchType) => setData({ ...data, matchType })} /></Field>
        </div>
        <Field label="Respuesta" help="Variables: {user}, {username}, {server}, {channel}">
          <Textarea value={data.response} maxLength={2000} onChange={(e) => setData({ ...data, response: e.target.value })} />
        </Field>
        <Toggle label="Activada" checked={data.enabled} onChange={(enabled) => setData({ ...data, enabled })} />
      </div>
    </Modal>
  );
}

function ScheduleForm({ initial, onSubmit, onClose }: {
  initial?: Scheduled; onSubmit: (data: Omit<Scheduled, "id" | "lastRun">) => Promise<unknown>; onClose: () => void;
}) {
  const isEvery = !initial || initial.cron.startsWith("@every:");
  const [mode, setMode] = useState<"interval" | "cron">(isEvery ? "interval" : "cron");
  const [minutes, setMinutes] = useState(initial && isEvery ? Number(initial.cron.split(":")[1]) / 60_000 : 60);
  const [cron, setCron] = useState(initial && !isEvery ? initial.cron : "0 9 * * *");
  const [data, setData] = useState({ channelId: initial?.channelId ?? "", message: initial?.message ?? "", enabled: initial?.enabled ?? true });
  const [busy, setBusy] = useState(false);
  const expression = mode === "interval" ? `@every:${Math.max(1, minutes) * 60_000}` : cron;
  return (
    <Modal open onClose={onClose} title={initial ? "Editar mensaje programado" : "Nuevo mensaje programado"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!data.channelId || !data.message}
                     onClick={async () => { setBusy(true); if (await onSubmit({ ...data, cron: expression })) onClose(); setBusy(false); }}>Guardar</Button></>}>
      <div className="space-y-4">
        <Field label="Canal"><ChannelPicker value={data.channelId} onChange={(v) => setData({ ...data, channelId: v ?? "" })} /></Field>
        <Field label="Mensaje"><Textarea value={data.message} maxLength={2000} onChange={(e) => setData({ ...data, message: e.target.value })} /></Field>
        <Field label="Programación">
          <Select value={mode} onChange={(v) => setMode(v as "interval" | "cron")}
                  options={[{ value: "interval", label: "Cada cierto tiempo" }, { value: "cron", label: "Expresión cron" }]} />
        </Field>
        {mode === "interval"
          ? <Field label="Intervalo"><NumberInput value={minutes} min={1} max={43_200} suffix="min" onChange={setMinutes} /></Field>
          : <Field label="Cron (UTC)" help={'minuto hora día mes día-semana · "0 9 * * 1-5" = días laborables a las 9:00'}>
              <Input value={cron} className="font-mono" onChange={(e) => setCron(e.target.value)} />
            </Field>}
        <Toggle label="Activado" checked={data.enabled} onChange={(enabled) => setData({ ...data, enabled })} />
      </div>
    </Modal>
  );
}

export default function AutomationPage() {
  const { api, channelName } = useGuild();
  const [tab, setTab] = useState<"responses" | "scheduled" | "polls" | "settings">("responses");
  const responses = useCollection<AutoResponse>(`${api}/automation/responses`);
  const scheduled = useCollection<Scheduled>(`${api}/automation/scheduled`);
  const polls = useApi<Poll[]>(tab === "polls" ? `${api}/automation/polls` : null);
  const [editing, setEditing] = useState<{ kind: "response" | "scheduled"; row?: AutoResponse | Scheduled } | null>(null);

  return (
    <>
      <PageHeader title="Automatización" description="Respuestas automáticas, mensajes programados y encuestas" icon={<Bot size={18} />}
                  actions={tab === "responses" || tab === "scheduled"
                    ? <Button variant="primary" icon={<Plus size={14} />} onClick={() => setEditing({ kind: tab === "responses" ? "response" : "scheduled" })}>
                        {tab === "responses" ? "Nueva respuesta" : "Nuevo programado"}</Button> : undefined} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "responses", label: "Respuestas", count: responses.rows.length },
        { id: "scheduled", label: "Programados", count: scheduled.rows.length },
        { id: "polls", label: "Encuestas" }, { id: "settings", label: "Ajustes" },
      ]} />

      {tab === "responses" && (
        <Card>
          {responses.loading ? <Spinner /> : (
            <Table rows={responses.rows} rowKey={(r) => r.id}
                   empty={<Empty title="Sin respuestas automáticas" description="El bot responde cuando un mensaje coincide con el disparador." />}
                   columns={[
                     { key: "trigger", header: "Disparador", render: (r) => <code className="text-xs">{r.trigger}</code> },
                     { key: "match", header: "Modo", render: (r) => <Badge>{MATCH.find((m) => m.value === r.matchType)?.label}</Badge> },
                     { key: "response", header: "Respuesta", render: (r) => <span className="line-clamp-2 text-fg-2">{r.response}</span> },
                     { key: "on", header: "", className: "w-16", render: (r) => <Toggle checked={r.enabled} onChange={(enabled) => responses.update(r.id, { enabled }, null)} /> },
                     { key: "actions", header: "", className: "w-20 text-right", render: (r) => (
                       <div className="flex justify-end gap-1">
                         <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditing({ kind: "response", row: r })}><Pencil size={14} /></Button>
                         <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => responses.remove(r.id, `¿Eliminar la respuesta «${r.trigger}»?`)}><Trash2 size={14} /></Button>
                       </div>) },
                   ]} />
          )}
        </Card>
      )}

      {tab === "scheduled" && (
        <Card>
          {scheduled.loading ? <Spinner /> : (
            <Table rows={scheduled.rows} rowKey={(r) => r.id} empty={<Empty title="Sin mensajes programados" />}
                   columns={[
                     { key: "when", header: "Programación", render: (r) => <code className="text-xs">{describeSchedule(r.cron)}</code> },
                     { key: "channel", header: "Canal", render: (r) => channelName(r.channelId) },
                     { key: "message", header: "Mensaje", render: (r) => <span className="line-clamp-2 text-fg-2">{r.message}</span> },
                     { key: "last", header: "Último envío", render: (r) => <span className="text-xs text-muted">{formatDate(r.lastRun)}</span> },
                     { key: "on", header: "", className: "w-16", render: (r) => <Toggle checked={r.enabled} onChange={(enabled) => scheduled.update(r.id, { enabled }, null)} /> },
                     { key: "actions", header: "", className: "w-20 text-right", render: (r) => (
                       <div className="flex justify-end gap-1">
                         <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditing({ kind: "scheduled", row: r })}><Pencil size={14} /></Button>
                         <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => scheduled.remove(r.id, "¿Eliminar este mensaje programado?")}><Trash2 size={14} /></Button>
                       </div>) },
                   ]} />
          )}
        </Card>
      )}

      {tab === "polls" && (
        <Card>
          <CardHeader title="Encuestas" description="Se crean con /encuesta crear en Discord." />
          {polls.loading ? <Spinner /> : (
            <Table rows={polls.data ?? []} rowKey={(p) => p.id} empty={<Empty title="Sin encuestas" />}
                   columns={[
                     { key: "q", header: "Pregunta", render: (p) => p.question },
                     { key: "votes", header: "Votos", render: (p) => Object.values(p.votes ?? {}).reduce<number>((n, v) => n + (Array.isArray(v) ? v.length : 0), 0) },
                     { key: "status", header: "Estado", render: (p) => p.ended ? <Badge tone="muted">Finalizada</Badge> : <Badge tone="solid">Activa</Badge> },
                     { key: "date", header: "Creada", render: (p) => <span className="text-xs text-muted">{formatDate(p.createdAt)}</span> },
                   ]} />
          )}
        </Card>
      )}

      {tab === "settings" && <ConfigEditor sections={[{ title: "Módulo", fields: [
        { key: "automationEnabled", type: "toggle", label: "Activar automatización", description: "Respuestas automáticas, mensajes programados y /encuesta." },
      ] }]} />}

      {editing?.kind === "response" && (
        <ResponseForm initial={editing.row as AutoResponse | undefined} onClose={() => setEditing(null)}
                      onSubmit={(data) => editing.row ? responses.update(editing.row.id, data) : responses.create(data)} />
      )}
      {editing?.kind === "scheduled" && (
        <ScheduleForm initial={editing.row as Scheduled | undefined} onClose={() => setEditing(null)}
                      onSubmit={(data) => editing.row ? scheduled.update(editing.row.id, data) : scheduled.create(data)} />
      )}
    </>
  );
}
