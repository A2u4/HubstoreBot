"use client";

import { Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type EmbedData, EmbedPreview } from "@/components/ui/embed-preview";
import { ColorInput, Field, Input, Textarea, Toggle } from "@/components/ui/form";
import { Tabs } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker } from "@/components/ui/pickers";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";

type Mode = "text" | "embed" | "both";
const EMPTY: EmbedData = { title: "", description: "", color: "#FFFFFF", fields: [], timestamp: false };
const PRESETS = ["#FFFFFF", "#D4D4D4", "#8A8A8A", "#3A3A3A", "#5865F2", "#57F287", "#FEE75C", "#ED4245"];

export default function MessageSenderPage() {
  const { api, botName } = useGuild();
  const [mode, setMode] = useState<Mode>("embed");
  const [channelId, setChannelId] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [embed, setEmbed] = useState<EmbedData>(EMPTY);
  const [sending, setSending] = useState(false);
  const set = (patch: Partial<EmbedData>) => setEmbed((e) => ({ ...e, ...patch }));
  const fields = embed.fields ?? [];

  const send = async () => {
    if (!channelId) return toast.error("Elige un canal");
    setSending(true);
    try {
      await apiFetch(`${api}/messages`, { body: {
        channelId,
        content: mode !== "embed" || content ? content || undefined : undefined,
        embed: mode === "text" ? undefined : { ...embed, titleUrl: embed.url ?? undefined },
      } });
      toast.success("Mensaje enviado");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PageHeader title="Enviar mensaje" description="Publica mensajes o embeds como el bot" icon={<Send size={18} />}
                  actions={<Button variant="primary" icon={<Send size={14} />} loading={sending} onClick={send}>Enviar</Button>} />
      <div className="grid gap-5 lg:grid-cols-[1fr_420px]">
        <div className="space-y-5">
          <Card>
            <CardBody className="space-y-4">
              <Field label="Canal de destino"><ChannelPicker value={channelId} onChange={setChannelId} placeholder="Seleccionar canal..." /></Field>
              <Tabs value={mode} onChange={setMode} tabs={[{ id: "text", label: "Texto" }, { id: "embed", label: "Embed" }, { id: "both", label: "Texto + Embed" }]} />
              {mode !== "embed" && <Field label="Contenido"><Textarea rows={5} maxLength={2000} value={content} onChange={(e) => setContent(e.target.value)} /></Field>}
              {mode === "embed" && <Field label="Texto fuera del embed (opcional)" help="Útil para menciones como @everyone."><Input maxLength={2000} value={content} onChange={(e) => setContent(e.target.value)} /></Field>}
            </CardBody>
          </Card>
          {mode !== "text" && (
            <Card>
              <CardHeader title="Constructor de embed" />
              <CardBody className="grid gap-4 md:grid-cols-2">
                <Field label="Autor"><Input maxLength={256} value={embed.authorName ?? ""} onChange={(e) => set({ authorName: e.target.value })} /></Field>
                <Field label="Icono del autor (URL)"><Input value={embed.authorIconUrl ?? ""} onChange={(e) => set({ authorIconUrl: e.target.value })} /></Field>
                <Field label="Título"><Input maxLength={256} value={embed.title ?? ""} onChange={(e) => set({ title: e.target.value })} /></Field>
                <Field label="Enlace del título"><Input value={embed.url ?? ""} onChange={(e) => set({ url: e.target.value })} /></Field>
                <Field label="Descripción" className="md:col-span-2"><Textarea rows={6} maxLength={4096} value={embed.description ?? ""} onChange={(e) => set({ description: e.target.value })} /></Field>
                <Field label="Color" className="md:col-span-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="w-48"><ColorInput value={embed.color} onChange={(color) => set({ color })} /></div>
                    {PRESETS.map((c) => <button key={c} type="button" aria-label={c} onClick={() => set({ color: c })}
                                                className="size-7 rounded-md border border-line-strong" style={{ background: c }} />)}
                  </div>
                </Field>
                <Field label="Imagen grande (URL)"><Input value={embed.imageUrl ?? ""} onChange={(e) => set({ imageUrl: e.target.value })} /></Field>
                <Field label="Miniatura (URL)"><Input value={embed.thumbnailUrl ?? ""} onChange={(e) => set({ thumbnailUrl: e.target.value })} /></Field>
                <Field label="Pie de página"><Input maxLength={2048} value={embed.footerText ?? ""} onChange={(e) => set({ footerText: e.target.value })} /></Field>
                <Field label="Icono del pie (URL)"><Input value={embed.footerIconUrl ?? ""} onChange={(e) => set({ footerIconUrl: e.target.value })} /></Field>
                <div className="md:col-span-2"><Toggle label="Mostrar fecha y hora" checked={Boolean(embed.timestamp)} onChange={(timestamp) => set({ timestamp })} /></div>
                <div className="space-y-3 md:col-span-2">
                  <p className="label">Campos ({fields.length}/25)</p>
                  {fields.map((f, i) => (
                    <div key={i} className="grid gap-2 rounded-lg border border-line p-3 md:grid-cols-[1fr_1fr_auto_auto]">
                      <Input placeholder="Nombre" maxLength={256} value={f.name} onChange={(e) => set({ fields: fields.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} />
                      <Input placeholder="Valor" maxLength={1024} value={f.value} onChange={(e) => set({ fields: fields.map((x, j) => j === i ? { ...x, value: e.target.value } : x) })} />
                      <Toggle label="En línea" checked={Boolean(f.inline)} onChange={(inline) => set({ fields: fields.map((x, j) => j === i ? { ...x, inline } : x) })} />
                      <Button size="sm" variant="ghost" aria-label="Quitar campo" onClick={() => set({ fields: fields.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button>
                    </div>
                  ))}
                  {fields.length < 25 && <Button size="sm" icon={<Plus size={14} />} onClick={() => set({ fields: [...fields, { name: "", value: "", inline: false }] })}>Añadir campo</Button>}
                </div>
              </CardBody>
            </Card>
          )}
        </div>
        <div className="lg:sticky lg:top-8 lg:self-start">
          <p className="label">Vista previa</p>
          <EmbedPreview botName={botName} content={content} embed={mode === "text" ? null : embed} />
          <Button variant="ghost" size="sm" className="mt-3" onClick={() => { setEmbed(EMPTY); setContent(""); }}>Limpiar</Button>
        </div>
      </div>
    </>
  );
}
