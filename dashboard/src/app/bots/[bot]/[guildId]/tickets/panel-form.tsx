"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EmbedPreview } from "@/components/ui/embed-preview";
import { ColorInput, Field, Input, NumberInput, Select, Textarea, Toggle } from "@/components/ui/form";
import { Tabs } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { ChannelPicker, RoleMultiPicker } from "@/components/ui/pickers";
import { useGuild } from "@/lib/client/guild";

export interface FormQuestion { label: string; placeholder?: string | null; style?: "short" | "paragraph"; required?: boolean; minLength?: number | null; maxLength?: number | null }

export interface TicketPanel {
  id: string; name: string; channelId: string; messageId: string | null; title: string; description: string; embedColor: string;
  footerText: string | null; embedImages: string[]; embedImageInterval: number; groupEmbedTitle: string | null; groupEmbedDescription: string | null;
  groupEmbedColor: string | null; groupEmbedImages: string[]; buttonLabel: string; buttonEmoji: string | null; buttonColor: string;
  style: string; categoryId: string | null; closedCategoryId: string | null; namingPattern: string; staffRoleIds: string[];
  adminRoleIds: string[]; ticketLimit: number; mentionStaff: boolean; mentionCreator: boolean; welcomeTitle: string | null;
  welcomeMessage: string | null; welcomeColor: string; closeRequestEnabled: boolean; closeRequestMessage: string | null;
  claimEnabled: boolean; claimLockOthers: boolean; transcriptEnabled: boolean; transcriptChannelId: string | null;
  transcriptDMUser: boolean; transcriptDMStaff: boolean; logChannelId: string | null; showCloseButton: boolean;
  showClaimButton: boolean; showTranscriptButton: boolean; formEnabled: boolean; formTitle: string | null;
  formQuestions: FormQuestion[] | null; escalatePanelId: string | null; feedbackEnabled: boolean; feedbackMessage: string | null;
  autoCloseHours: number; panelAutoRepost: boolean; panelAutoRepostCooldown: number; panelAutoRepostIgnoreBots: boolean;
  _count?: { tickets: number; transcripts: number };
}

export const DEFAULT_PANEL: Partial<TicketPanel> = {
  name: "Soporte", title: "Tickets de soporte", description: "Haz clic en el botón de abajo para crear un ticket.", embedColor: "#FFFFFF",
  buttonLabel: "Crear ticket", buttonEmoji: "🎫", buttonColor: "Primary", style: "button", namingPattern: "ticket-{number}",
  staffRoleIds: [], adminRoleIds: [], ticketLimit: 1, mentionStaff: true, mentionCreator: true, welcomeTitle: "Ticket abierto",
  welcomeMessage: "¡Bienvenido {user}! Describe tu consulta.\nUn miembro del staff te ayudará pronto.", welcomeColor: "#FFFFFF",
  closeRequestEnabled: true, closeRequestMessage: "¿Seguro que quieres cerrar este ticket?", claimEnabled: true, claimLockOthers: false,
  transcriptEnabled: true, transcriptDMUser: true, transcriptDMStaff: false, showCloseButton: true, showClaimButton: true,
  showTranscriptButton: true, formEnabled: false, formTitle: "Formulario de ticket", formQuestions: [], feedbackEnabled: false,
  feedbackMessage: "¿Cómo calificarías la atención recibida?", autoCloseHours: 0, panelAutoRepost: false, panelAutoRepostCooldown: 5,
  panelAutoRepostIgnoreBots: true, embedImages: [], embedImageInterval: 10,
};

const BUTTON_COLORS = [
  { value: "Primary", label: "Azul" }, { value: "Secondary", label: "Gris" }, { value: "Success", label: "Verde" }, { value: "Danger", label: "Rojo" },
];

/** Fields the API accepts (strips ids, counts and timestamps from a loaded panel). */
const EDITABLE: Array<keyof TicketPanel> = [
  "name", "channelId", "title", "description", "embedColor", "footerText", "embedImages", "embedImageInterval", "buttonLabel", "buttonEmoji",
  "buttonColor", "style", "categoryId", "closedCategoryId", "namingPattern", "staffRoleIds", "adminRoleIds", "ticketLimit", "mentionStaff",
  "mentionCreator", "welcomeTitle", "welcomeMessage", "welcomeColor", "closeRequestEnabled", "closeRequestMessage", "claimEnabled",
  "claimLockOthers", "transcriptEnabled", "transcriptChannelId", "transcriptDMUser", "transcriptDMStaff", "logChannelId",
  "showCloseButton", "showClaimButton", "showTranscriptButton", "formEnabled", "formTitle", "formQuestions", "escalatePanelId",
  "feedbackEnabled", "feedbackMessage", "autoCloseHours", "panelAutoRepost", "panelAutoRepostCooldown", "panelAutoRepostIgnoreBots",
];
export function editablePanel(panel: Partial<TicketPanel>): Partial<TicketPanel> {
  return Object.fromEntries(EDITABLE.filter((k) => panel[k] !== undefined).map((k) => [k, panel[k]])) as Partial<TicketPanel>;
}

type Section = "general" | "access" | "inside" | "closing" | "form" | "advanced";

export function PanelForm({ initial, panels, onSubmit, onClose }: {
  initial: Partial<TicketPanel>; panels: TicketPanel[]; onSubmit: (data: Partial<TicketPanel>) => Promise<unknown>; onClose: () => void;
}) {
  const { botName } = useGuild();
  const [p, setP] = useState<Partial<TicketPanel>>({ ...DEFAULT_PANEL, ...initial });
  const [section, setSection] = useState<Section>("general");
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<TicketPanel>) => setP((x) => ({ ...x, ...patch }));
  const questions = p.formQuestions ?? [];
  const setQuestion = (i: number, patch: Partial<FormQuestion>) => set({ formQuestions: questions.map((q, j) => (j === i ? { ...q, ...patch } : q)) });

  return (
    <Modal open wide onClose={onClose} title={initial.id ? `Editar panel «${initial.name}»` : "Nuevo panel de tickets"}
           footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!p.name || !p.channelId || !p.buttonLabel} onClick={async () => {
               setBusy(true);
               if (await onSubmit(editablePanel(p))) onClose();
               setBusy(false);
             }}>Guardar</Button></>}>
      <Tabs value={section} onChange={setSection} tabs={[
        { id: "general", label: "Panel" }, { id: "access", label: "Canales y staff" }, { id: "inside", label: "Dentro del ticket" },
        { id: "closing", label: "Cierre" }, { id: "form", label: "Formulario" }, { id: "advanced", label: "Avanzado" },
      ]} />
      {section === "general" && (
        <div className="grid gap-5 md:grid-cols-2">
          <div className="space-y-4">
            <Field label="Nombre interno"><Input value={p.name ?? ""} maxLength={100} onChange={(e) => set({ name: e.target.value })} /></Field>
            <Field label="Canal donde se publica"><ChannelPicker value={p.channelId} onChange={(channelId) => set({ channelId: channelId ?? "" })} /></Field>
            <Field label="Título"><Input value={p.title ?? ""} maxLength={256} onChange={(e) => set({ title: e.target.value })} /></Field>
            <Field label="Descripción"><Textarea rows={4} value={p.description ?? ""} maxLength={4000} onChange={(e) => set({ description: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Color"><ColorInput value={p.embedColor} onChange={(embedColor) => set({ embedColor })} /></Field>
              <Field label="Pie"><Input value={p.footerText ?? ""} maxLength={256} onChange={(e) => set({ footerText: e.target.value || null })} /></Field>
            </div>
            <div className="grid grid-cols-[1fr_80px_1fr] gap-3">
              <Field label="Botón"><Input value={p.buttonLabel ?? ""} maxLength={80} onChange={(e) => set({ buttonLabel: e.target.value })} /></Field>
              <Field label="Emoji"><Input value={p.buttonEmoji ?? ""} maxLength={100} onChange={(e) => set({ buttonEmoji: e.target.value || null })} /></Field>
              <Field label="Color"><Select value={p.buttonColor ?? "Primary"} options={BUTTON_COLORS} onChange={(buttonColor) => set({ buttonColor })} /></Field>
            </div>
          </div>
          <div>
            <p className="label">Vista previa</p>
            <EmbedPreview botName={botName} embed={{ title: p.title, description: p.description, color: p.embedColor, footerText: p.footerText }} />
            <div className="mt-2 pl-12"><span className="inline-flex h-8 items-center gap-1.5 rounded-md bg-surface-3 px-3 text-sm">{p.buttonEmoji} {p.buttonLabel}</span></div>
          </div>
        </div>
      )}
      {section === "access" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Categoría de tickets abiertos"><ChannelPicker kind="category" value={p.categoryId} onChange={(categoryId) => set({ categoryId })} placeholder="Usar la global" /></Field>
          <Field label="Categoría de tickets cerrados"><ChannelPicker kind="category" value={p.closedCategoryId} onChange={(closedCategoryId) => set({ closedCategoryId })} placeholder="Ninguna" /></Field>
          <Field label="Nombre del canal" help="{number}, {username}, {displayname}, {userid}"><Input value={p.namingPattern ?? ""} maxLength={100} className="font-mono" onChange={(e) => set({ namingPattern: e.target.value })} /></Field>
          <Field label="Tickets abiertos por usuario"><NumberInput value={p.ticketLimit} min={1} max={9999} onChange={(ticketLimit) => set({ ticketLimit })} /></Field>
          <Field label="Roles del staff"><RoleMultiPicker value={p.staffRoleIds ?? []} onChange={(staffRoleIds) => set({ staffRoleIds })} /></Field>
          <Field label="Roles administradores"><RoleMultiPicker value={p.adminRoleIds ?? []} onChange={(adminRoleIds) => set({ adminRoleIds })} /></Field>
          <Toggle label="Mencionar al staff al abrir" checked={Boolean(p.mentionStaff)} onChange={(mentionStaff) => set({ mentionStaff })} />
          <Toggle label="Mencionar al creador" checked={Boolean(p.mentionCreator)} onChange={(mentionCreator) => set({ mentionCreator })} />
          <Field label="Canal de registro"><ChannelPicker value={p.logChannelId} onChange={(logChannelId) => set({ logChannelId })} placeholder="Usar el global" /></Field>
        </div>
      )}
      {section === "inside" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Título de bienvenida"><Input value={p.welcomeTitle ?? ""} maxLength={256} onChange={(e) => set({ welcomeTitle: e.target.value || null })} /></Field>
          <Field label="Color"><ColorInput value={p.welcomeColor} onChange={(welcomeColor) => set({ welcomeColor })} /></Field>
          <Field label="Mensaje de bienvenida" help="{user}, {number}, {panel}" className="md:col-span-2">
            <Textarea rows={4} value={p.welcomeMessage ?? ""} maxLength={2000} onChange={(e) => set({ welcomeMessage: e.target.value || null })} />
          </Field>
          <Toggle label="Botón cerrar" checked={Boolean(p.showCloseButton)} onChange={(showCloseButton) => set({ showCloseButton })} />
          <Toggle label="Botón asignar" checked={Boolean(p.showClaimButton)} onChange={(showClaimButton) => set({ showClaimButton })} />
          <Toggle label="Botón transcripción" checked={Boolean(p.showTranscriptButton)} onChange={(showTranscriptButton) => set({ showTranscriptButton })} />
          <Toggle label="Permitir asignar (claim)" checked={Boolean(p.claimEnabled)} onChange={(claimEnabled) => set({ claimEnabled })} />
          {p.claimEnabled && <Toggle label="Solo el staff asignado puede responder" checked={Boolean(p.claimLockOthers)} onChange={(claimLockOthers) => set({ claimLockOthers })} />}
        </div>
      )}
      {section === "closing" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Toggle label="Confirmar antes de cerrar" checked={Boolean(p.closeRequestEnabled)} onChange={(closeRequestEnabled) => set({ closeRequestEnabled })} />
          {p.closeRequestEnabled && <Field label="Mensaje de confirmación"><Input value={p.closeRequestMessage ?? ""} maxLength={1000} onChange={(e) => set({ closeRequestMessage: e.target.value || null })} /></Field>}
          <Toggle label="Generar transcripción" checked={Boolean(p.transcriptEnabled)} onChange={(transcriptEnabled) => set({ transcriptEnabled })} />
          {p.transcriptEnabled && <>
            <Field label="Canal de transcripciones"><ChannelPicker value={p.transcriptChannelId} onChange={(transcriptChannelId) => set({ transcriptChannelId })} placeholder="Usar el global" /></Field>
            <Toggle label="Enviar por DM al usuario" checked={Boolean(p.transcriptDMUser)} onChange={(transcriptDMUser) => set({ transcriptDMUser })} />
            <Toggle label="Enviar por DM al staff asignado" checked={Boolean(p.transcriptDMStaff)} onChange={(transcriptDMStaff) => set({ transcriptDMStaff })} />
          </>}
          <Toggle label="Pedir valoración (1-5 ⭐)" checked={Boolean(p.feedbackEnabled)} onChange={(feedbackEnabled) => set({ feedbackEnabled })} />
          {p.feedbackEnabled && <Field label="Mensaje de valoración"><Input value={p.feedbackMessage ?? ""} maxLength={1000} onChange={(e) => set({ feedbackMessage: e.target.value || null })} /></Field>}
          <Field label="Cierre automático por inactividad" help="0 = desactivado"><NumberInput value={p.autoCloseHours} min={0} max={720} suffix="horas" onChange={(autoCloseHours) => set({ autoCloseHours })} /></Field>
        </div>
      )}
      {section === "form" && (
        <div className="space-y-4">
          <Toggle label="Mostrar un formulario al abrir el ticket" description="Hasta 5 preguntas; las respuestas aparecen en el ticket." checked={Boolean(p.formEnabled)} onChange={(formEnabled) => set({ formEnabled })} />
          {p.formEnabled && <>
            <Field label="Título del formulario" help="Máximo 45 caracteres (límite de Discord)."><Input value={p.formTitle ?? ""} maxLength={45} onChange={(e) => set({ formTitle: e.target.value || null })} /></Field>
            {questions.map((q, i) => (
              <div key={i} className="grid gap-3 rounded-lg border border-line p-3 md:grid-cols-[1fr_1fr_140px_auto]">
                <Input placeholder="Pregunta" maxLength={45} value={q.label} onChange={(e) => setQuestion(i, { label: e.target.value })} />
                <Input placeholder="Texto de ayuda" maxLength={100} value={q.placeholder ?? ""} onChange={(e) => setQuestion(i, { placeholder: e.target.value })} />
                <Select value={q.style ?? "short"} options={[{ value: "short", label: "Corta" }, { value: "paragraph", label: "Párrafo" }]} onChange={(style) => setQuestion(i, { style: style as FormQuestion["style"] })} />
                <div className="flex items-center gap-2">
                  <Toggle label="Obligatoria" checked={q.required !== false} onChange={(required) => setQuestion(i, { required })} />
                  <Button size="sm" variant="ghost" aria-label="Quitar" onClick={() => set({ formQuestions: questions.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button>
                </div>
              </div>
            ))}
            {questions.length < 5 && <Button size="sm" icon={<Plus size={14} />} onClick={() => set({ formQuestions: [...questions, { label: "", style: "short", required: true }] })}>Añadir pregunta</Button>}
          </>}
        </div>
      )}
      {section === "advanced" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Toggle label="Panel siempre al final (re-publicar)" description="Si alguien escribe en el canal del panel, el bot lo vuelve a publicar abajo."
                  checked={Boolean(p.panelAutoRepost)} onChange={(panelAutoRepost) => set({ panelAutoRepost })} />
          {p.panelAutoRepost && <>
            <Field label="Espera entre re-publicaciones"><NumberInput value={p.panelAutoRepostCooldown} min={1} max={300} suffix="seg" onChange={(panelAutoRepostCooldown) => set({ panelAutoRepostCooldown })} /></Field>
            <Toggle label="Ignorar mensajes de bots" checked={Boolean(p.panelAutoRepostIgnoreBots)} onChange={(panelAutoRepostIgnoreBots) => set({ panelAutoRepostIgnoreBots })} />
          </>}
          <Field label="Escalar a otro panel" help="/ticket escalar mueve el ticket a este panel.">
            <Select value={p.escalatePanelId ?? ""} placeholder="Ninguno" options={panels.filter((x) => x.id !== initial.id).map((x) => ({ value: x.id, label: x.name }))}
                    onChange={(v) => set({ escalatePanelId: v || null })} />
          </Field>
        </div>
      )}
    </Modal>
  );
}
