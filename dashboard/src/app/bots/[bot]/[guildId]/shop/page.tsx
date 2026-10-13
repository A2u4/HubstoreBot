"use client";

import { Eye, EyeOff, Pencil, Plus, Save, Send, ShoppingCart, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ListEditor } from "@/components/config/list-editor";
import { Button } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmbedPreview } from "@/components/ui/embed-preview";
import { ColorInput, Field, Input, NumberInput, Select, Textarea, Toggle } from "@/components/ui/form";
import { Badge, Empty, Spinner, Tabs } from "@/components/ui/misc";
import { confirm, Modal } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker, RoleMultiPicker } from "@/components/ui/pickers";
import { Table } from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useCollection } from "@/lib/client/collection";
import { CONFIG_EVENT } from "@/lib/client/events";
import { useGuild } from "@/lib/client/guild";
import { CategoryMedia } from "./media";
import {
  type CustomButton, type DiscordStyle, newCategory, normalizeCategories, type PaymentOption, SHOP_KEYS, type ShopCategory,
  type ShopConfig, type ShopProduct, STYLES,
} from "./types";

type Step = "products" | "categories" | "buttons" | "publish";
const pick = (config: Record<string, unknown>): ShopConfig => Object.fromEntries(SHOP_KEYS.map((k) => [k, config[k]])) as unknown as ShopConfig;

function ProductForm({ initial, categories, onSubmit, onClose }: {
  initial: Partial<ShopProduct>; categories: ShopCategory[]; onSubmit: (data: Partial<ShopProduct>) => Promise<unknown>; onClose: () => void;
}) {
  const [p, setP] = useState<Partial<ShopProduct>>(initial);
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onClose={onClose} title={initial.id ? "Editar producto" : "Nuevo producto"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!p.name} onClick={async () => {
               setBusy(true);
               const { id: _id, ...data } = p;
               if (await onSubmit({ ...data, priceLabel: p.priceLabel || null, stockLabel: p.stockLabel || null, image: p.image || null })) onClose();
               setBusy(false);
             }}>Guardar</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nombre" className="sm:col-span-2"><Input value={p.name ?? ""} maxLength={255} onChange={(e) => setP({ ...p, name: e.target.value })} /></Field>
        <Field label="Categoría"><Select value={p.category ?? ""} options={[...categories.map((c) => ({ value: c.label, label: c.label })), { value: "General", label: "General" }]}
                                        onChange={(category) => setP({ ...p, category })} /></Field>
        <Toggle label="Visible" checked={p.active !== false} onChange={(active) => setP({ ...p, active })} />
        <Field label="Precio"><NumberInput value={p.price ?? 0} min={0} step={0.01} onChange={(price) => setP({ ...p, price })} /></Field>
        <Field label="Texto del precio" help="Opcional, p. ej. «250K IC»"><Input value={p.priceLabel ?? ""} maxLength={100} onChange={(e) => setP({ ...p, priceLabel: e.target.value })} /></Field>
        <Field label="Stock"><NumberInput value={p.stock ?? 0} min={0} onChange={(stock) => setP({ ...p, stock })} /></Field>
        <Field label="Texto del stock"><Input value={p.stockLabel ?? ""} maxLength={100} onChange={(e) => setP({ ...p, stockLabel: e.target.value })} /></Field>
        <Field label="Descripción" className="sm:col-span-2"><Textarea rows={3} maxLength={2000} value={p.description ?? ""} onChange={(e) => setP({ ...p, description: e.target.value })} /></Field>
        <Field label="Imagen (URL)" className="sm:col-span-2"><Input value={p.image ?? ""} onChange={(e) => setP({ ...p, image: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}

function PaymentOptions({ value, onChange }: { value: PaymentOption[]; onChange: (v: PaymentOption[]) => void }) {
  return (
    <ListEditor<PaymentOption> value={value} onChange={onChange} max={25} addLabel="Añadir país o método" empty="Sin precios por país."
      create={() => ({ id: `payment-${Date.now().toString(36)}`, emoji: "🌎", country: "", price: "", methods: "", stock: "", hidden: false })}
      renderItem={(o, update) => (
        <div className="grid gap-2 md:grid-cols-[64px_1fr_1fr_1fr_1fr_auto]">
          <Input aria-label="Emoji" value={o.emoji ?? ""} maxLength={20} onChange={(e) => update({ emoji: e.target.value })} />
          <Input placeholder="País" value={o.country} maxLength={60} onChange={(e) => update({ country: e.target.value })} />
          <Input placeholder="Precio" value={o.price} maxLength={100} onChange={(e) => update({ price: e.target.value })} />
          <Input placeholder="Métodos" value={o.methods ?? ""} maxLength={150} onChange={(e) => update({ methods: e.target.value })} />
          <Input placeholder="Stock" value={o.stock ?? ""} maxLength={60} onChange={(e) => update({ stock: e.target.value })} />
          <Button size="sm" variant="ghost" aria-label={o.hidden ? "Mostrar" : "Ocultar"} onClick={() => update({ hidden: !o.hidden })}>
            {o.hidden ? <EyeOff size={14} /> : <Eye size={14} />}
          </Button>
        </div>
      )} />
  );
}

export default function ShopPage() {
  const { api, botName, channelName } = useGuild();
  const configApi = useApi<Record<string, unknown>>(`${api}/config`);
  const products = useCollection<ShopProduct>(`${api}/shop/products`);
  const panels = useApi<Array<{ id: string; name: string }>>(`${api}/tickets/panels`);
  const [draft, setDraft] = useState<ShopConfig | null>(null);
  const [step, setStep] = useState<Step>("products");
  const [selected, setSelected] = useState<string>("");
  const [editingProduct, setEditingProduct] = useState<Partial<ShopProduct> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (configApi.data) {
      const config = pick(configApi.data);
      if (!config.shopCategories?.length) config.shopCategories = [newCategory(1)];
      setDraft(config);
      setSelected((s) => s || config.shopCategories[0]?.id || "");
    }
  }, [configApi.data]);

  const categories = useMemo(() => draft?.shopCategories ?? [], [draft]);
  const category = categories.find((c) => c.id === selected) ?? categories[0];
  const dirty = Boolean(draft && configApi.data && JSON.stringify(draft) !== JSON.stringify(pick(configApi.data)));
  const set = (patch: Partial<ShopConfig>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const setCategory = (patch: Partial<ShopCategory>) => set({ shopCategories: categories.map((c) => (c.id === category?.id ? { ...c, ...patch } : c)) });

  /** Save the shop fields; optionally refresh the published message right away. */
  const save = async (next: ShopConfig | null = draft, { refresh = true, message = "Cambios guardados" } = {}): Promise<boolean> => {
    if (!next) return false;
    setBusy("save");
    try {
      const body = { ...next, shopCategories: normalizeCategories(next.shopCategories) };
      const updated = await apiFetch<Record<string, unknown>>(`${api}/config`, { method: "PATCH", body });
      configApi.setData(updated);
      window.dispatchEvent(new CustomEvent(CONFIG_EVENT, { detail: updated }));
      if (refresh && updated.shopMessageId) {
        await apiFetch(`${api}/shop/refresh`, { body: {} }).catch(() => toast.error("Guardado, pero no se pudo actualizar el mensaje publicado."));
      }
      toast.success(message);
      return true;
    } catch (err) {
      toast.error(errorMessage(err));
      return false;
    } finally {
      setBusy(null);
    }
  };

  /** Media changes are saved immediately (they create files on the server). */
  const applyCategoryMedia = async (patch: Partial<ShopCategory>, message: string) => {
    if (!draft || !category) return false;
    const next = { ...draft, shopCategories: categories.map((c) => (c.id === category.id ? { ...c, ...patch } : c)) };
    setDraft(next);
    return save(next, { message });
  };

  const publish = async () => {
    if (!draft?.shopChannelId) return toast.error("Elige el canal donde publicar la tienda");
    if (dirty && !(await save(draft, { refresh: false, message: "Configuración guardada" }))) return;
    setBusy("publish");
    try {
      await apiFetch(`${api}/shop/publish`, { body: { channelId: draft.shopChannelId } });
      toast.success("Tienda publicada en Discord");
      configApi.reload();
    } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(null); }
  };

  const publishCategory = async () => {
    if (!category?.channelId) return toast.error("Elige el canal de esta sección");
    if (dirty && !(await save(draft, { refresh: false, message: "Configuración guardada" }))) return;
    setBusy("category");
    try {
      await apiFetch(`${api}/shop/publish-category`, { body: { categoryId: category.id, channelId: category.channelId } });
      toast.success(`${category.label} publicada como mensaje propio`);
      configApi.reload();
    } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(null); }
  };

  if (!draft) return <Spinner />;
  const categoryProducts = products.rows.filter((p) => p.category.toLowerCase() === (category?.label ?? "").toLowerCase());

  return (
    <>
      <PageHeader title="Tienda" description="Catálogo, precios por país, GIFs y publicación en Discord" icon={<ShoppingCart size={18} />}
                  actions={<>
                    <Button icon={<Save size={14} />} loading={busy === "save"} disabled={!dirty} onClick={() => save()}>Guardar y aplicar</Button>
                    <Button variant="primary" icon={<Send size={14} />} loading={busy === "publish"} onClick={publish}>Publicar</Button>
                  </>} />
      <Tabs value={step} onChange={setStep} tabs={[
        { id: "products", label: "1 · Productos", count: products.rows.length }, { id: "categories", label: "2 · Categorías y GIFs", count: categories.length },
        { id: "buttons", label: "3 · Tickets y botones" }, { id: "publish", label: "4 · Publicar" },
      ]} />

      {(step === "products" || step === "categories") && (
        <div className="mb-5 flex flex-wrap items-center gap-2">
          {categories.map((c) => (
            <button key={c.id} type="button" onClick={() => setSelected(c.id)}
                    className={cn("rounded-md border px-3 py-1.5 text-sm", c.id === category?.id ? "border-fg bg-fg text-bg" : "border-line hover:border-line-strong")}>
              {c.emoji} {c.label}
            </button>
          ))}
          {step === "categories" && categories.length < 10 && (
            <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={() => {
              const created = newCategory(categories.length + 1);
              set({ shopCategories: [...categories, created] });
              setSelected(created.id);
            }}>Sección</Button>
          )}
        </div>
      )}

      {step === "products" && category && (
        <Card>
          <CardHeader title={`Productos de ${category.label}`} actions={<Button size="sm" variant="primary" icon={<Plus size={14} />}
                      onClick={() => setEditingProduct({ name: "", category: category.label, description: "", price: 0, stock: 0, active: true })}>Producto</Button>} />
          {products.loading ? <Spinner /> : (
            <Table rows={categoryProducts} rowKey={(p) => p.id} empty={<Empty title="Sin productos en esta categoría" />}
                   columns={[
                     { key: "name", header: "Producto", render: (p) => <span>{p.name}{!p.active && <Badge tone="muted" className="ml-2">oculto</Badge>}</span> },
                     { key: "price", header: "Precio", className: "tabular-nums", render: (p) => p.priceLabel || p.price.toLocaleString("es") },
                     { key: "stock", header: "Stock", className: "tabular-nums", render: (p) => p.stockLabel || p.stock },
                     { key: "actions", header: "", className: "w-20 text-right", render: (p) => (
                       <div className="flex justify-end gap-1">
                         <Button size="sm" variant="ghost" aria-label="Editar" onClick={() => setEditingProduct(p)}><Pencil size={14} /></Button>
                         <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => products.remove(p.id, `¿Eliminar ${p.name}?`)}><Trash2 size={14} /></Button>
                       </div>) },
                   ]} />
          )}
        </Card>
      )}

      {step === "categories" && category && (
        <div className="space-y-5">
          <Card>
            <CardHeader title={`Sección: ${category.label}`} actions={categories.length > 1 && (
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={async () => {
                if (categoryProducts.length) return toast.error("Mueve o elimina los productos de esta sección antes de borrarla");
                if (!(await confirm({ title: "Eliminar sección", message: `¿Eliminar «${category.label}»?`, danger: true, confirmLabel: "Eliminar" }))) return;
                const rest = categories.filter((c) => c.id !== category.id);
                set({ shopCategories: rest });
                setSelected(rest[0]?.id ?? "");
              }}>Eliminar</Button>)} />
            <CardBody className="grid gap-4 md:grid-cols-3">
              <Field label="Nombre"><Input value={category.label} maxLength={50} onChange={(e) => setCategory({ label: e.target.value })} /></Field>
              <Field label="Emoji"><Input value={category.emoji ?? ""} maxLength={100} onChange={(e) => setCategory({ emoji: e.target.value })} /></Field>
              <Field label="Color del botón"><Select value={category.style ?? "Primary"} options={STYLES} onChange={(v) => setCategory({ style: v as DiscordStyle })} /></Field>
              <Field label="Descripción" className="md:col-span-3"><Textarea rows={2} maxLength={500} value={category.description ?? ""} onChange={(e) => setCategory({ description: e.target.value })} /></Field>
              <Field label="Stock (cantidad)" help="Vacío = usar texto libre"><Input type="number" min={0} value={category.stockAmount ?? ""}
                     onChange={(e) => setCategory({ stockAmount: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) })} /></Field>
              <Field label="Unidad"><Input value={category.stockUnit ?? ""} maxLength={80} placeholder="unidades disponibles" onChange={(e) => setCategory({ stockUnit: e.target.value })} /></Field>
              <Field label="Disponibilidad (texto libre)"><Input value={category.availabilityText ?? ""} maxLength={100} disabled={category.stockAmount != null} onChange={(e) => setCategory({ availabilityText: e.target.value })} /></Field>
              <Field label="Pie del catálogo" className="md:col-span-3"><Textarea rows={3} maxLength={1000} value={category.footerText ?? ""} onChange={(e) => setCategory({ footerText: e.target.value })} /></Field>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Precios y métodos por país" description="Úsalo cuando el mismo producto tenga monedas o medios de pago distintos. El stock por país también se edita desde /tienda." />
            <CardBody><PaymentOptions value={category.paymentOptions ?? []} onChange={(paymentOptions) => setCategory({ paymentOptions })} /></CardBody>
          </Card>
          <Card>
            <CardHeader title="GIFs e imágenes" description="Los cambios de medios se guardan y aplican al momento." />
            <CardBody><CategoryMedia category={category} apply={applyCategoryMedia} /></CardBody>
          </Card>
          <Card>
            <CardHeader title="Botones de la sección" description="Acciones extra (hasta 5), p. ej. «Hacer un encargo»." />
            <CardBody>
              <ListEditor value={(category.actionButtons ?? []).map((a) => ({ ...a }))} max={5} addLabel="Añadir botón" empty="Sin botones extra."
                onChange={(actionButtons) => setCategory({ actionButtons })}
                create={() => ({ id: `action_${Date.now().toString(36)}`, label: "Hacer un encargo", emoji: "📝", style: "Secondary" as DiscordStyle })}
                renderItem={(a, update) => (
                  <div className="grid gap-2 md:grid-cols-[1fr_80px_160px]">
                    <Input value={a.label} maxLength={80} onChange={(e) => update({ label: e.target.value })} />
                    <Input value={a.emoji ?? ""} maxLength={100} onChange={(e) => update({ emoji: e.target.value })} />
                    <Select value={a.style ?? "Primary"} options={STYLES} onChange={(v) => update({ style: v as DiscordStyle })} />
                  </div>
                )} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Mensaje propio" description="Publica esta sección como un mensaje independiente que se mantiene sincronizado." />
            <CardBody className="flex flex-wrap items-end gap-3">
              <Field label="Canal" className="min-w-64 flex-1"><ChannelPicker value={category.channelId} onChange={(channelId) => setCategory({ channelId })} /></Field>
              <Button loading={busy === "category"} icon={<Send size={14} />} onClick={publishCategory}>Publicar sección</Button>
              {category.messageId && <span className="text-xs text-muted">Publicada en {channelName(category.channelId)}</span>}
            </CardBody>
          </Card>
        </div>
      )}

      {step === "buttons" && (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Botón principal de compra" />
            <CardBody className="grid gap-4 md:grid-cols-4">
              <Field label="Texto"><Input value={draft.shopBuyButtonLabel ?? ""} maxLength={80} onChange={(e) => set({ shopBuyButtonLabel: e.target.value })} /></Field>
              <Field label="Emoji"><Input value={draft.shopBuyButtonEmoji ?? ""} maxLength={100} onChange={(e) => set({ shopBuyButtonEmoji: e.target.value })} /></Field>
              <Field label="Color"><Select value={draft.shopBuyButtonStyle ?? "Primary"} options={STYLES} onChange={(v) => set({ shopBuyButtonStyle: v as DiscordStyle })} /></Field>
              <Field label="Panel de tickets"><Select value={draft.shopPanelId ?? ""} placeholder="Ninguno" options={(panels.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
                                                     onChange={(v) => set({ shopPanelId: v || null })} /></Field>
              <Field label="Botones de categorías" className="md:col-span-2">
                <Select value={draft.shopButtonStyle ?? "multiple"} onChange={(v) => set({ shopButtonStyle: v as "multiple" | "single" })}
                        options={[{ value: "multiple", label: "Un botón por categoría" }, { value: "single", label: "Un solo botón (menú)" }]} />
              </Field>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Acciones adicionales" description="Cada botón abre un ticket con su propio panel, categoría y staff." />
            <CardBody>
              <ListEditor<CustomButton> value={draft.shopCustomButtons ?? []} max={20} addLabel="Añadir acción" empty="Sin acciones adicionales."
                onChange={(shopCustomButtons) => set({ shopCustomButtons })}
                create={() => ({ id: `btn_${Date.now()}`, label: "Vender artículos", emoji: "💰", style: "Secondary", panelId: null, categoryId: null,
                                 staffRoleIds: [], namingPattern: "ticket-{number}", welcomeMessage: "", stockBehavior: "keep_enabled", ticketTopic: "" })}
                renderItem={(b, update) => (
                  <div className="grid gap-3 md:grid-cols-3">
                    <Field label="Texto"><Input value={b.label} maxLength={80} onChange={(e) => update({ label: e.target.value })} /></Field>
                    <Field label="Emoji"><Input value={b.emoji ?? ""} maxLength={100} onChange={(e) => update({ emoji: e.target.value })} /></Field>
                    <Field label="Color"><Select value={b.style} options={STYLES} onChange={(v) => update({ style: v as DiscordStyle })} /></Field>
                    <Field label="Panel de tickets"><Select value={b.panelId ?? ""} placeholder="Ninguno" options={(panels.data ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(v) => update({ panelId: v || null })} /></Field>
                    <Field label="Categoría de Discord"><ChannelPicker kind="category" value={b.categoryId} onChange={(categoryId) => update({ categoryId })} placeholder="La del panel" /></Field>
                    <Field label="Nombre del canal"><Input value={b.namingPattern ?? ""} maxLength={100} className="font-mono" onChange={(e) => update({ namingPattern: e.target.value })} /></Field>
                    <Field label="Staff"><RoleMultiPicker value={b.staffRoleIds ?? []} onChange={(staffRoleIds) => update({ staffRoleIds })} /></Field>
                    <Field label="Sin stock">
                      <Select value={b.stockBehavior ?? "keep_enabled"} onChange={(v) => update({ stockBehavior: v as CustomButton["stockBehavior"] })}
                              options={[{ value: "keep_enabled", label: "Mantener activo" }, { value: "disable_when_empty", label: "Desactivar" }, { value: "hide_when_empty", label: "Ocultar" }]} />
                    </Field>
                    <Field label="Asunto del ticket"><Input value={b.ticketTopic ?? ""} maxLength={200} onChange={(e) => update({ ticketTopic: e.target.value })} /></Field>
                    <Field label="Mensaje de bienvenida" className="md:col-span-3"><Textarea rows={2} maxLength={2000} value={b.welcomeMessage ?? ""} onChange={(e) => update({ welcomeMessage: e.target.value })} /></Field>
                  </div>
                )} />
            </CardBody>
          </Card>
        </div>
      )}

      {step === "publish" && (
        <div className="grid gap-5 lg:grid-cols-[1fr_400px]">
          <div className="space-y-5">
            <Card>
              <CardHeader title="Mensaje principal" />
              <CardBody className="grid gap-4 md:grid-cols-2">
                <Field label="Canal de la tienda"><ChannelPicker value={draft.shopChannelId} onChange={(shopChannelId) => set({ shopChannelId })} /></Field>
                <Field label="Color"><ColorInput value={draft.shopColor} onChange={(shopColor) => set({ shopColor })} /></Field>
                <Field label="Título" className="md:col-span-2"><Input value={draft.shopTitle ?? ""} maxLength={256} onChange={(e) => set({ shopTitle: e.target.value })} /></Field>
                <Field label="Descripción" className="md:col-span-2"><Textarea rows={4} maxLength={4000} value={draft.shopDescription ?? ""} onChange={(e) => set({ shopDescription: e.target.value })} /></Field>
                <Field label="Miniatura (URL)" className="md:col-span-2" help="Se copia al servidor para que no caduque."><Input value={draft.shopThumbnail ?? ""} onChange={(e) => set({ shopThumbnail: e.target.value })} /></Field>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Aviso periódico" description="El bot vuelve a anunciar la tienda cada cierto tiempo." />
              <CardBody className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2"><Toggle label="Activar aviso" checked={draft.shopAnnouncementEnabled} onChange={(shopAnnouncementEnabled) => set({ shopAnnouncementEnabled })} /></div>
                <Field label="Canal"><ChannelPicker value={draft.shopAnnouncementChannelId} onChange={(shopAnnouncementChannelId) => set({ shopAnnouncementChannelId })} /></Field>
                <Field label="Cada"><NumberInput value={Math.round(draft.shopAnnouncementInterval / 60)} min={5} max={10_080} suffix="min" onChange={(m) => set({ shopAnnouncementInterval: m * 60 })} /></Field>
                <Field label="Mensaje" className="md:col-span-2"><Textarea rows={2} maxLength={2000} value={draft.shopAnnouncementMessage ?? ""} onChange={(e) => set({ shopAnnouncementMessage: e.target.value })} /></Field>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Mantener catálogo abajo" description="Cuando alguien escribe en el canal, el bot vuelve a publicar la tienda al final." />
              <CardBody className="grid gap-4 md:grid-cols-2">
                <Toggle label="Activar" checked={draft.shopStickyEnabled} onChange={(shopStickyEnabled) => set({ shopStickyEnabled })} />
                <Field label="Espera mínima"><NumberInput value={draft.shopStickyCooldown} min={5} max={3600} suffix="seg" onChange={(shopStickyCooldown) => set({ shopStickyCooldown })} /></Field>
              </CardBody>
            </Card>
          </div>
          <div className="lg:sticky lg:top-8 lg:self-start">
            <p className="label">Vista previa</p>
            <EmbedPreview botName={botName} embed={{ title: draft.shopTitle, description: draft.shopDescription, color: draft.shopColor, thumbnailUrl: draft.shopThumbnail,
                                                     imageUrl: categories[0]?.playlistImage || categories[0]?.effectImages?.[0] || categories[0]?.images?.[0] }} />
            <div className="mt-2 flex flex-wrap gap-1.5 pl-12">
              {(draft.shopButtonStyle === "single" ? [{ id: "x", emoji: draft.shopBuyButtonEmoji, label: draft.shopBuyButtonLabel }] : categories)
                .map((c) => <span key={c.id} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-surface-3 px-3 text-sm">{c.emoji} {c.label}</span>)}
            </div>
          </div>
        </div>
      )}

      {editingProduct && (
        <ProductForm initial={editingProduct} categories={categories} onClose={() => setEditingProduct(null)}
                     onSubmit={(data) => editingProduct.id ? products.update(editingProduct.id, data) : products.create(data, "Producto creado")} />
      )}
    </>
  );
}
