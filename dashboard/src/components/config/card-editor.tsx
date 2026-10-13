"use client";

import { Eye, EyeOff, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { ColorInput, Field, Input, NumberInput, Select } from "@/components/ui/form";
import { useGuild } from "@/lib/client/guild";

export interface CardText {
  id: string; text: string; x: number; y: number; fontFamily: string; fontWeight: number; fontSize: number;
  color: string; align: "left" | "center" | "right"; visible: boolean; shadowColor?: string; shadowBlur?: number;
}
export interface CardLayout {
  width?: number; height?: number;
  background: { color: string; imageUrl?: string | null; imageFit?: "cover" | "contain"; overlay?: string };
  avatar: { x: number; y: number; size: number; shape: "circle" | "square"; borderColor: string; borderWidth: number; visible: boolean };
  texts: CardText[];
}

const WIDTH = 900;
const HEIGHT = 350;

/** Mirrors DEFAULT_LAYOUT in the bot's services/welcome_card.py. */
export const DEFAULT_LAYOUT: CardLayout = {
  background: { color: "#0d1117", imageFit: "cover", overlay: "rgba(0,0,0,0.35)" },
  avatar: { x: 175, y: 175, size: 180, shape: "circle", borderColor: "#ffffff", borderWidth: 6, visible: true },
  texts: [
    { id: "title", text: "¡Bienvenido a {server}!", x: 340, y: 90, fontFamily: "Arial", fontWeight: 800, fontSize: 34, color: "#ffffff", align: "left", shadowColor: "rgba(0,0,0,0.6)", shadowBlur: 8, visible: true },
    { id: "username", text: "{user}", x: 340, y: 145, fontFamily: "Arial", fontWeight: 700, fontSize: 46, color: "#ffffff", align: "left", visible: true },
    { id: "member", text: "Sos el miembro #{memberCount}", x: 340, y: 220, fontFamily: "Arial", fontWeight: 500, fontSize: 20, color: "rgba(255,255,255,0.8)", align: "left", visible: true },
    { id: "inviter", text: "Invitado por {inviter}", x: 340, y: 260, fontFamily: "Arial", fontWeight: 500, fontSize: 18, color: "rgba(255,255,255,0.55)", align: "left", visible: true },
  ],
};

function normalize(value: unknown): CardLayout {
  const layout = (value && typeof value === "object" ? value : {}) as Partial<CardLayout>;
  return {
    background: { ...DEFAULT_LAYOUT.background, ...(layout.background ?? {}) },
    avatar: { ...DEFAULT_LAYOUT.avatar, ...(layout.avatar ?? {}) },
    texts: Array.isArray(layout.texts) && layout.texts.length ? layout.texts : DEFAULT_LAYOUT.texts,
  };
}

const FONTS = ["Arial", "DejaVuSans", "Liberation Sans", "Inter", "Roboto", "Montserrat", "Poppins"].map((f) => ({ value: f, label: f }));
const WEIGHTS = [400, 500, 600, 700, 800, 900].map((w) => ({ value: String(w), label: String(w) }));
const VARS = ["{user}", "{username}", "{server}", "{memberCount}", "{inviter}"];

/** Visual editor for welcome/farewell card layouts. Click the preview to move the selected element. */
export function CardEditor({ value, onChange, inviterLabel = "Invitador" }: {
  value: unknown; onChange: (layout: CardLayout) => void; inviterLabel?: string;
}) {
  const { api } = useGuild();
  const layout = normalize(value);
  const [selected, setSelected] = useState<string>("avatar");
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const serialized = JSON.stringify(layout);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`${api}/welcome/preview`, {
          method: "POST", headers: { "content-type": "application/json" }, signal: controller.signal,
          body: JSON.stringify({ layout: JSON.parse(serialized), inviterName: inviterLabel }),
        });
        if (!response.ok) throw new Error((await response.json().catch(() => null))?.error ?? "No se pudo generar la vista previa");
        const url = URL.createObjectURL(await response.blob());
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = url;
        setPreview(url);
        setPreviewError(null);
      } catch (err) {
        if (!controller.signal.aborted) setPreviewError(err instanceof Error ? err.message : "Error");
      }
    }, 500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [api, serialized, inviterLabel]);

  const update = (patch: (l: CardLayout) => CardLayout) => onChange(patch(normalize(JSON.parse(serialized))));
  const setText = (id: string, patch: Partial<CardText>) => update((l) => ({ ...l, texts: l.texts.map((t) => (t.id === id ? { ...t, ...patch } : t)) }));
  const text = layout.texts.find((t) => t.id === selected);

  const place = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.round(((event.clientX - rect.left) / rect.width) * WIDTH);
    const y = Math.round(((event.clientY - rect.top) / rect.height) * HEIGHT);
    if (selected === "avatar") update((l) => ({ ...l, avatar: { ...l.avatar, x, y } }));
    else if (text) setText(text.id, { x, y });
  };

  return (
    <div className="space-y-4">
      <div className="relative cursor-crosshair overflow-hidden rounded-lg border border-line bg-surface-2" style={{ aspectRatio: `${WIDTH} / ${HEIGHT}` }}
           onClick={place} title="Haz clic para mover el elemento seleccionado">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {preview && <img src={preview} alt="Vista previa de la tarjeta" className="absolute inset-0 size-full" draggable={false} />}
        {!preview && <div className="absolute inset-0 flex items-center justify-center text-xs text-muted">{previewError ?? "Generando vista previa..."}</div>}
        {preview && previewError && <div className="absolute bottom-2 left-2 rounded bg-black/80 px-2 py-1 text-[11px]">{previewError}</div>}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {[{ id: "background", label: "Fondo" }, { id: "avatar", label: "Avatar" }, ...layout.texts.map((t) => ({ id: t.id, label: t.text.slice(0, 18) || t.id }))].map((item) => (
          <button key={item.id} type="button" onClick={() => setSelected(item.id)}
                  className={cn("rounded-md border px-2.5 py-1 text-xs", selected === item.id ? "border-fg bg-fg text-bg" : "border-line text-fg-2 hover:border-line-strong")}>
            {item.label}
          </button>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus size={13} />} onClick={() => {
          const id = `text-${Date.now()}`;
          update((l) => ({ ...l, texts: [...l.texts, { ...DEFAULT_LAYOUT.texts[2], id, text: "Nuevo texto", y: 300 }] }));
          setSelected(id);
        }}>Texto</Button>
        <Button size="sm" variant="ghost" icon={<RotateCcw size={13} />} onClick={() => onChange(DEFAULT_LAYOUT)}>Restablecer</Button>
      </div>

      <div className="grid gap-4 rounded-lg border border-line p-4 md:grid-cols-3">
        {selected === "background" && (
          <>
            <Field label="Color de fondo"><ColorInput value={layout.background.color} onChange={(color) => update((l) => ({ ...l, background: { ...l.background, color } }))} /></Field>
            <Field label="Imagen de fondo (URL)" className="md:col-span-2">
              <Input value={layout.background.imageUrl ?? ""} placeholder="https://..." onChange={(e) => update((l) => ({ ...l, background: { ...l.background, imageUrl: e.target.value || null } }))} />
            </Field>
            <Field label="Ajuste"><Select value={layout.background.imageFit ?? "cover"} options={[{ value: "cover", label: "Cubrir" }, { value: "contain", label: "Contener" }]}
                                         onChange={(v) => update((l) => ({ ...l, background: { ...l.background, imageFit: v as "cover" | "contain" } }))} /></Field>
            <Field label="Capa oscura" help="rgba(0,0,0,0.35)" className="md:col-span-2">
              <Input value={layout.background.overlay ?? ""} className="font-mono" onChange={(e) => update((l) => ({ ...l, background: { ...l.background, overlay: e.target.value } }))} />
            </Field>
          </>
        )}
        {selected === "avatar" && (
          <>
            <Field label="Tamaño"><NumberInput value={layout.avatar.size} min={40} max={340} suffix="px" onChange={(size) => update((l) => ({ ...l, avatar: { ...l.avatar, size } }))} /></Field>
            <Field label="Forma"><Select value={layout.avatar.shape} options={[{ value: "circle", label: "Círculo" }, { value: "square", label: "Cuadrado" }]}
                                        onChange={(v) => update((l) => ({ ...l, avatar: { ...l.avatar, shape: v as "circle" | "square" } }))} /></Field>
            <Field label="Visible"><Button size="sm" icon={layout.avatar.visible ? <Eye size={13} /> : <EyeOff size={13} />}
                                           onClick={() => update((l) => ({ ...l, avatar: { ...l.avatar, visible: !l.avatar.visible } }))}>
              {layout.avatar.visible ? "Visible" : "Oculto"}</Button></Field>
            <Field label="Borde"><ColorInput value={layout.avatar.borderColor} onChange={(borderColor) => update((l) => ({ ...l, avatar: { ...l.avatar, borderColor } }))} /></Field>
            <Field label="Grosor del borde"><NumberInput value={layout.avatar.borderWidth} min={0} max={20} suffix="px" onChange={(borderWidth) => update((l) => ({ ...l, avatar: { ...l.avatar, borderWidth } }))} /></Field>
            <Field label="Posición (centro)"><span className="text-sm tabular-nums text-muted">x {layout.avatar.x} · y {layout.avatar.y}</span></Field>
          </>
        )}
        {text && (
          <>
            <Field label="Texto" className="md:col-span-3" help={<span className="flex flex-wrap gap-1">{VARS.map((v) => (
              <button key={v} type="button" className="kbd" onClick={() => setText(text.id, { text: `${text.text}${v}` })}>{v}</button>))}</span>}>
              <Input value={text.text} maxLength={120} onChange={(e) => setText(text.id, { text: e.target.value })} />
            </Field>
            <Field label="Fuente"><Select value={text.fontFamily} options={FONTS} onChange={(fontFamily) => setText(text.id, { fontFamily })} /></Field>
            <Field label="Grosor"><Select value={String(text.fontWeight)} options={WEIGHTS} onChange={(w) => setText(text.id, { fontWeight: Number(w) })} /></Field>
            <Field label="Tamaño"><NumberInput value={text.fontSize} min={8} max={120} suffix="px" onChange={(fontSize) => setText(text.id, { fontSize })} /></Field>
            <Field label="Color"><ColorInput value={text.color} onChange={(color) => setText(text.id, { color })} /></Field>
            <Field label="Alineación"><Select value={text.align} options={[{ value: "left", label: "Izquierda" }, { value: "center", label: "Centro" }, { value: "right", label: "Derecha" }]}
                                             onChange={(align) => setText(text.id, { align: align as CardText["align"] })} /></Field>
            <Field label="Acciones">
              <div className="flex gap-2">
                <Button size="sm" icon={text.visible ? <Eye size={13} /> : <EyeOff size={13} />} onClick={() => setText(text.id, { visible: !text.visible })}>
                  {text.visible ? "Visible" : "Oculto"}</Button>
                <Button size="sm" variant="ghost" aria-label="Eliminar texto" onClick={() => {
                  update((l) => ({ ...l, texts: l.texts.filter((t) => t.id !== text.id) }));
                  setSelected("avatar");
                }}><Trash2 size={13} /></Button>
              </div>
            </Field>
          </>
        )}
      </div>
    </div>
  );
}
