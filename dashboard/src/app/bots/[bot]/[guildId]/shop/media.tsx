"use client";

import { ImagePlus, Link2, Sparkles, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, NumberInput, Select } from "@/components/ui/form";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { MEDIA_EFFECTS, MEDIA_TEMPLATES, type MediaEffect, type ShopCategory } from "./types";

/**
 * Category media: originals stay untouched; Discord shows processed copies
 * (resized + filter). In "sequence" mode all clips are merged into one GIF,
 * so the published message never needs periodic edits.
 */
export function CategoryMedia({ category, apply }: {
  category: ShopCategory;
  /** Save the patch to the config and refresh the published shop. */
  apply: (patch: Partial<ShopCategory>, message: string) => Promise<boolean>;
}) {
  const { api } = useGuild();
  const fileInput = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const images = category.images ?? [];
  const effect = category.effect ?? "normal";
  const width = category.mediaWidth ?? 960;
  const height = category.mediaHeight ?? 540;
  const fit = category.mediaFit ?? "cover";

  /** Produce processed copies (+ playlist) for a list of originals, using the category's current layout/effect. */
  const process = async (originals: string[], overrides: Partial<ShopCategory> = {}): Promise<Partial<ShopCategory>> => {
    const opts = { effect: overrides.effect ?? effect, width: overrides.mediaWidth ?? width, height: overrides.mediaHeight ?? height,
                   fit: overrides.mediaFit ?? fit, mode: overrides.playbackMode ?? category.playbackMode ?? "sequence" };
    const effectImages: string[] = [];
    for (const [i, original] of originals.entries()) {
      setBusy(`Procesando ${i + 1}/${originals.length}...`);
      const result = await apiFetch<{ url: string }>(`${api}/shop/media-effect`, { body: { url: original, effect: opts.effect, width: opts.width, height: opts.height, fit: opts.fit } });
      effectImages.push(result.url);
    }
    let playlist: Partial<ShopCategory> = { playlistImage: null, playlistDuration: 0 };
    if (opts.mode === "sequence" && effectImages.length >= 2) {
      setBusy("Creando secuencia...");
      const result = await apiFetch<{ url: string; durationMs: number }>(`${api}/shop/media-playlist`, { body: { urls: effectImages, width: opts.width, height: opts.height } });
      playlist = { playlistImage: result.url, playlistDuration: result.durationMs };
    }
    return { ...overrides, images: originals, image: originals[0] ?? null, effectImages, ...playlist };
  };

  const run = async (label: string, work: () => Promise<Partial<ShopCategory>>, message: string) => {
    setBusy(label);
    try {
      await apply(await work(), message);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const add = (urls: string[]) => run("Agregando...", () => process([...new Set([...images, ...urls])].slice(0, 20)), `${urls.length} medio(s) agregados a ${category.label}`);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const uploaded: string[] = [];
    setBusy("Subiendo...");
    for (const file of Array.from(files).slice(0, 10)) {
      const form = new FormData();
      form.set("file", file);
      form.set("type", "banner");
      try {
        uploaded.push((await apiFetch<{ url: string }>(`${api}/shop/upload`, { body: form })).url);
      } catch (err) {
        toast.error(`${file.name}: ${errorMessage(err)}`);
      }
    }
    if (fileInput.current) fileInput.current.value = "";
    if (uploaded.length) await add(uploaded);
    else setBusy(null);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {images.map((src, i) => (
          <div key={src} className="group relative overflow-hidden rounded-lg border border-line bg-surface-2" style={{ aspectRatio: `${width} / ${height}` }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={category.effectImages?.[i] ?? src} alt="" className="size-full object-cover" loading="lazy" />
            <button type="button" aria-label="Quitar" disabled={Boolean(busy)}
                    onClick={() => run("Quitando...", () => process(images.filter((x) => x !== src)), "Medio retirado")}
                    className="absolute right-1.5 top-1.5 rounded-md bg-black/80 p-1.5 opacity-0 transition-opacity group-hover:opacity-100"><Trash2 size={13} /></button>
            {i === 0 && <span className="absolute bottom-1.5 left-1.5 rounded bg-black/80 px-1.5 text-[10px]">Principal</span>}
          </div>
        ))}
        <button type="button" disabled={Boolean(busy)} onClick={() => fileInput.current?.click()}
                className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-line-strong text-xs text-muted hover:text-fg"
                style={{ aspectRatio: `${width} / ${height}` }}>
          <ImagePlus size={18} /> Subir GIF / imagen
        </button>
        <input ref={fileInput} type="file" multiple accept="image/gif,image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => upload(e.target.files)} />
      </div>

      <div className="flex gap-2">
        <Input placeholder="https://… (también enlaces de Tenor / Giphy)" value={url} onChange={(e) => setUrl(e.target.value)} />
        <Button icon={<Link2 size={14} />} disabled={!/^https?:\/\//.test(url) || Boolean(busy)} onClick={async () => { await add([url.trim()]); setUrl(""); }}>Agregar</Button>
      </div>

      <div className="grid gap-4 rounded-lg border border-line p-4 md:grid-cols-4">
        <Field label="Formato">
          <Select value={MEDIA_TEMPLATES.find((t) => t.width === width && t.height === height)?.id ?? ""} placeholder="Personalizado"
                  options={MEDIA_TEMPLATES.map((t) => ({ value: t.id, label: t.label }))}
                  onChange={(id) => { const t = MEDIA_TEMPLATES.find((x) => x.id === id); if (t) void run("Aplicando formato...", () => process(images, { mediaWidth: t.width, mediaHeight: t.height }), "Formato aplicado"); }} />
        </Field>
        <Field label="Ajuste">
          <Select value={fit} options={[{ value: "cover", label: "Recortar (llenar)" }, { value: "contain", label: "Completo (bordes)" }]}
                  onChange={(v) => void run("Aplicando...", () => process(images, { mediaFit: v as "cover" | "contain" }), "Ajuste aplicado")} />
        </Field>
        <Field label="Filtro">
          <Select value={effect} options={MEDIA_EFFECTS} onChange={(v) => void run("Aplicando filtro...", () => process(images, { effect: v as MediaEffect }), "Filtro aplicado")} />
        </Field>
        <Field label="Reproducción">
          <Select value={category.playbackMode ?? "sequence"} options={[{ value: "sequence", label: "Secuencia (un GIF)" }, { value: "interval", label: "Rotar cada cierto tiempo" }]}
                  onChange={(v) => void run("Preparando...", () => process(images, { playbackMode: v as "sequence" | "interval" }), "Modo de reproducción actualizado")} />
        </Field>
        {category.playbackMode === "interval" && (
          <Field label="Rotar cada" className="md:col-span-2">
            <NumberInput value={Math.round((category.imageInterval ?? 3600) / 60)} min={1} max={43_200} suffix="min"
                         onChange={(minutes) => void apply({ imageInterval: Math.max(60, minutes * 60) }, "Intervalo guardado")} />
          </Field>
        )}
      </div>
      <div className="flex items-center gap-3 text-xs text-muted">
        <Button size="sm" icon={<Sparkles size={13} />} disabled={!images.length || Boolean(busy)}
                onClick={() => run("Reprocesando...", () => process(images), "Medios reprocesados")}>Reprocesar todo</Button>
        {busy ? <span>{busy}</span> : category.playlistImage ? <span>Secuencia lista · {Math.round((category.playlistDuration ?? 0) / 100) / 10}s</span> : null}
      </div>
    </div>
  );
}
